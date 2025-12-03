import asyncio
import time
from typing import Any, Dict, Optional

from src.chat.utils.utils import parse_platform_accounts
from src.common.logger import get_logger
from src.config.config import global_config

recall_logger = get_logger("pic_auto_recall")


def _get_bot_account_for_platform(platform: str) -> str:
    """根据平台获取机器人自身账号"""
    platform_key = (platform or "").strip().lower()
    bot_config = getattr(global_config, "bot", None)
    if not bot_config:
        return ""

    account_map_raw = parse_platform_accounts(getattr(bot_config, "platforms", []) or [])
    account_map = {
        k.strip().lower(): str(v).strip()
        for k, v in account_map_raw.items()
        if v
    }

    qq_account = str(getattr(bot_config, "qq_account", "") or "").strip()
    if qq_account:
        account_map.setdefault("qq", qq_account)

    telegram_account = str(getattr(bot_config, "telegram_account", "") or "").strip()
    if telegram_account:
        account_map.setdefault("telegram", telegram_account)
        account_map.setdefault("tg", telegram_account)

    if platform_key in account_map:
        return account_map[platform_key]

    return qq_account


def _extract_message_field(msg: Any, field: str):
    """兼容 DatabaseMessages 与 dict 的字段访问"""
    if isinstance(msg, dict):
        return msg.get(field)
    return getattr(msg, field, None)


def _is_image_message(msg: Any) -> bool:
    """判断消息是否为bot发送的图片"""
    try:
        if isinstance(msg, dict):
            if msg.get("is_picid"):
                return True
            seg = msg.get("message_segment")
            if isinstance(seg, dict):
                seg_type = seg.get("type")
                if seg_type in {"image", "imageurl"}:
                    return True
                if seg_type == "seglist":
                    for child in seg.get("data") or []:
                        if isinstance(child, dict) and child.get("type") in {"image", "imageurl"}:
                            return True
            for key in ("processed_plain_text", "display_message", "raw_message"):
                text_val = msg.get(key)
                if isinstance(text_val, str) and any(
                    tag in text_val
                    for tag in ("[图片", "[image", "[imageurl", "[picid", "picid:")
                ):
                    return True
            return False

        if getattr(msg, "is_picid", False):
            return True
        text_candidates = [
            getattr(msg, "processed_plain_text", None),
            getattr(msg, "display_message", None),
            getattr(msg, "raw_message", None),
        ]
        for text in text_candidates:
            if isinstance(text, str) and any(
                tag in text for tag in ("[图片", "[image", "[imageurl", "[picid", "picid:")
            ):
                return True
        return False
    except Exception:
        return False


class AutoRecallMixin:
    """提供自动撤回相关的通用方法"""

    def _get_recall_context(self) -> Dict[str, Any]:
        """获取自动撤回所需的上下文信息"""
        # Command组件
        message = getattr(self, "message", None)
        if message and getattr(message, "message_info", None):
            message_info = message.message_info
            return {
                "platform": getattr(message_info, "platform", "") or "",
                "group_info": getattr(message_info, "group_info", None),
                "user_info": getattr(message_info, "user_info", None),
                "chat_stream": getattr(message, "chat_stream", None),
            }

        # Action组件
        action_message = getattr(self, "action_message", None)
        if action_message:
            chat_info = getattr(action_message, "chat_info", None)
            platform = getattr(chat_info, "platform", None) if chat_info else getattr(self, "platform", None)
            group_info = None
            user_info = None

            if chat_info:
                group_info = getattr(chat_info, "group_info", None)
                user_info = getattr(chat_info, "user_info", None)

            if group_info is None:
                group_info = getattr(action_message, "group_info", None)
            if user_info is None:
                user_info = getattr(action_message, "user_info", None)

            return {
                "platform": platform or "",
                "group_info": group_info,
                "user_info": user_info,
                "chat_stream": getattr(self, "chat_stream", None),
            }

        # 兜底
        return {
            "platform": getattr(self, "platform", "") or "",
            "group_info": None,
            "user_info": None,
            "chat_stream": getattr(self, "chat_stream", None),
        }

    async def _schedule_auto_recall(self, placeholder_message_id: Optional[str] = None):
        """计划自动撤回任务"""
        try:
            context = self._get_recall_context()
            platform = context.get("platform") or ""
            group_info = context.get("group_info")
            user_info = context.get("user_info")

            if group_info and getattr(group_info, "group_id", None):
                chat_id = str(getattr(group_info, "group_id"))
            elif user_info and getattr(user_info, "user_id", None):
                chat_id = str(getattr(user_info, "user_id"))
            else:
                recall_logger.debug(f"{self.log_prefix} 无法识别聊天类型，跳过自动撤回")
                return

            if not self._is_auto_recall_enabled(platform, chat_id):
                recall_logger.debug(f"{self.log_prefix} 会话未启用自动撤回")
                return

            delay_seconds = self.get_config("auto_recall.delay_seconds", 5)
            id_wait_seconds = max(0, self.get_config("auto_recall.id_wait_seconds", 15))
            poll_interval = min(1.0, max(0.2, id_wait_seconds / 10)) if id_wait_seconds else 0

            await asyncio.sleep(1.0)

            message_id = await self._get_last_message_id()
            if not message_id and placeholder_message_id:
                recall_logger.debug(f"{self.log_prefix} 使用占位消息ID作为兜底: {placeholder_message_id}")
                message_id = placeholder_message_id
            if not message_id:
                recall_logger.warning(f"{self.log_prefix} 未能获取消息ID，无法自动撤回")
                return

            recall_logger.info(f"{self.log_prefix} 计划在 {delay_seconds} 秒后撤回消息: {message_id}")
            initial_message_id = message_id

            async def _resolve_message_id(initial_id: Optional[str]) -> Optional[str]:
                candidate = initial_id or placeholder_message_id
                if not candidate:
                    return None
                if not candidate.startswith("send_api_"):
                    return candidate
                if id_wait_seconds <= 0:
                    return candidate
                deadline = time.monotonic() + id_wait_seconds
                while time.monotonic() < deadline:
                    refreshed_id = await self._get_last_message_id()
                    if refreshed_id and not refreshed_id.startswith("send_api_"):
                        recall_logger.debug(f"{self.log_prefix} 占位ID替换为正式ID: {refreshed_id}")
                        return refreshed_id
                    await asyncio.sleep(poll_interval or 0.5)
                recall_logger.debug(f"{self.log_prefix} 在限定时间内未获取正式ID，继续使用占位ID")
                return candidate

            async def _delayed_recall():
                await asyncio.sleep(delay_seconds)
                target_message_id = await _resolve_message_id(initial_message_id)
                if not target_message_id:
                    recall_logger.warning(f"{self.log_prefix} 撤回失败：缺少消息ID")
                    return
                try:
                    success = await self._try_recall_message(target_message_id)
                    if success:
                        recall_logger.info(f"{self.log_prefix} 消息 {target_message_id} 已成功撤回")
                    else:
                        recall_logger.warning(f"{self.log_prefix} 消息 {target_message_id} 撤回失败")
                except Exception as exc:
                    recall_logger.error(f"{self.log_prefix} 撤回消息时出错: {exc!r}")

            task = asyncio.create_task(_delayed_recall())
            if hasattr(self, "plugin") and hasattr(self.plugin, "_track_task"):
                self.plugin._track_task(task)
        except Exception as exc:
            recall_logger.error(f"{self.log_prefix} 计划自动撤回失败: {exc!r}")

    def _is_auto_recall_enabled(self, platform: str, chat_id: str) -> bool:
        """由子类实现，用于判断当前会话是否启用了自动撤回"""
        raise NotImplementedError

    async def _get_last_message_id(self) -> Optional[str]:
        """获取最后发送的消息ID"""
        try:
            recall_logger.info(f"{self.log_prefix} 【调试】开始获取消息ID")

            context = self._get_recall_context()
            chat_stream = context.get("chat_stream")
            stream_id = getattr(chat_stream, "stream_id", None) if chat_stream else None
            if not stream_id:
                recall_logger.info(f"{self.log_prefix} 【调试】无法获取stream_id")
                return None

            platform = context.get("platform", "") or ""
            bot_account = _get_bot_account_for_platform(platform)
            send_timestamp = getattr(self, "_last_send_timestamp", None)
            timestamp_tolerance = 0.2

            from src.plugin_system import message_api

            max_attempts = 5
            placeholder_id: Optional[str] = None

            for attempt in range(max_attempts):
                msgs = message_api.get_recent_messages(
                    chat_id=str(stream_id),
                    hours=0.05,
                    limit=5,
                    limit_mode="latest",
                    filter_mai=False
                ) or []
                recall_logger.debug(f"{self.log_prefix} 【调试】尝试{attempt + 1}/{max_attempts}，获取到 {len(msgs)} 条消息")

                for msg in reversed(msgs):
                    if not _is_image_message(msg):
                        continue

                    message_id = _extract_message_field(msg, "message_id")
                    if not message_id:
                        continue
                    message_id = str(message_id)

                    msg_user_id = str(_extract_message_field(msg, "user_id") or "")
                    msg_time = _extract_message_field(msg, "time")
                    try:
                        msg_time_val = float(msg_time) if msg_time is not None else None
                    except (TypeError, ValueError):
                        msg_time_val = None

                    if send_timestamp and msg_time_val is not None:
                        if msg_time_val + timestamp_tolerance < send_timestamp:
                            continue

                    if bot_account and msg_user_id and msg_user_id != bot_account:
                        continue

                    if not message_id.startswith("send_api_"):
                        recall_logger.info(f"{self.log_prefix} 【调试】命中消息ID: {message_id}")
                        return message_id

                    placeholder_id = message_id

                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.4)

            if placeholder_id:
                recall_logger.warning(f"{self.log_prefix} 未获取到正式ID，使用占位ID: {placeholder_id}")
                return placeholder_id

            recall_logger.warning(f"{self.log_prefix} 所有方法都未能获取消息ID")
            return None
        except Exception as exc:
            recall_logger.error(f"{self.log_prefix} 获取消息ID失败: {exc!r}")
            return None

    async def _try_recall_message(self, message_id: str) -> bool:
        """尝试撤回消息"""
        try:
            delete_commands = ["DELETE_MSG", "delete_msg", "RECALL_MSG", "recall_msg"]
            for cmd in delete_commands:
                try:
                    result = await self.send_command(
                        cmd,
                        {"message_id": str(message_id)},
                        display_message="",
                        storage_message=False
                    )
                    if isinstance(result, bool) and result:
                        return True
                    if isinstance(result, dict):
                        status = str(result.get("status", "")).lower()
                        if status in ("ok", "success") or result.get("retcode") == 0:
                            return True
                except Exception as exc:
                    recall_logger.debug(f"{self.log_prefix} 尝试命令 {cmd} 失败: {exc!r}")
                    continue
            return False
        except Exception as exc:
            recall_logger.error(f"{self.log_prefix} 撤回消息异常: {exc!r}")
            return False

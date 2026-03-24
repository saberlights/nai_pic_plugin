# -*- coding: utf-8 -*-
"""
/nai 撤回 命令：手动撤回 bot 发送的图片。

- 引用回复指定图片 → 撤回该图片
- 不引用回复 → 自动撤回 bot 最近发送的图片
"""
import asyncio
import time
from typing import Optional, Tuple

from src.common.logger import get_logger
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system import message_api

from ..mixins.auto_recall_mixin import AutoRecallMixin, _extract_message_field, _is_nai_pic_plugin_image_message
from ..utils.tagger_utils import find_reply_message_id

logger = get_logger("nai_pic_plugin")


class NaiManualRecallCommand(BaseCommand, AutoRecallMixin):
    """发送 /nai 撤回，手动撤回 bot 发送的图片"""

    command_name = "nai_manual_recall_command"
    command_description = "手动撤回图片：/nai 撤回"
    command_pattern = r"(?:.*?)(?:/nai\s+撤回)\s*$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        logger.info(f"{self.log_prefix} [手动撤回] 收到 /nai 撤回")

        # 优先：引用回复 → 撤回指定消息
        reply_message_id = self._extract_reply_message_id()
        try:
            current_id = str(getattr(getattr(self.message, "message_info", None), "message_id", "") or "")
        except Exception:
            current_id = ""
        if reply_message_id and current_id and reply_message_id == current_id:
            # 防止误把“本条命令消息ID”当成引用目标
            reply_message_id = None

        if reply_message_id:
            ok, resolved_id, reason = await self._validate_reply_target(reply_message_id)
            if not ok or not resolved_id:
                await self.send_text(
                    f"❌ 只能撤回本插件生成的图片（{reason}）",
                    storage_message=False,
                )
                return False, reason, True
            return await self._do_recall(resolved_id, "引用")

        # 兜底：没有引用回复 → 撤回 bot 最近发送的图片
        last_message_id = await self._get_last_message_id(require_marker=True, hours=24.0, limit=300)
        if last_message_id:
            resolved_id = await self._resolve_latest_message_id(last_message_id)
            return await self._do_recall(resolved_id, "最近图片")

        await self.send_text(
            "❌ 找不到可撤回的图片（可以引用回复指定图片，或直接发送撤回最近一张）",
            storage_message=False,
        )
        return False, "找不到可撤回的消息", True

    async def _do_recall(self, message_id: str, source: str) -> Tuple[bool, Optional[str], bool]:
        """执行撤回并返回结果"""
        success = await self._try_recall_message(message_id)
        if success:
            logger.info(f"{self.log_prefix} [手动撤回] 消息 {message_id} 已撤回（{source}）")
            await self.send_text("✅ 已撤回", storage_message=False)
            return True, "手动撤回成功", True
        else:
            logger.warning(f"{self.log_prefix} [手动撤回] 消息 {message_id} 撤回失败（{source}）")
            await self.send_text(
                "❌ 撤回失败（可能消息已被删除、超过撤回时限、或 bot 无权撤回）",
                storage_message=False,
            )
            return False, "撤回失败", True

    # ---- 引用消息 ID 提取 ----

    def _extract_reply_message_id(self) -> Optional[str]:
        """从多种来源提取被引用消息的 message_id"""

        def _clean(v) -> Optional[str]:
            if isinstance(v, int):
                v = str(v)
            if isinstance(v, str):
                s = v.strip()
                return s or None
            return None

        # 1) message.reply
        rep = getattr(self.message, "reply", None)
        rep_info = getattr(rep, "message_info", None) if rep else None
        mid = _clean(getattr(rep_info, "message_id", None)) if rep_info else None
        if mid:
            return mid

        # 2) message.message_info
        mi = getattr(self.message, "message_info", None)
        if mi:
            for attr in (
                "reply_to",
                "reply_to_message_id",
                "reply_message_id",
                "quote_message_id",
                "reply_id",
            ):
                mid = _clean(getattr(mi, attr, None))
                if mid:
                    return mid

            add_cfg = getattr(mi, "additional_config", None)
            if isinstance(add_cfg, dict):
                for k in (
                    "reply_to",
                    "reply_to_message_id",
                    "reply_message_id",
                    "quote_message_id",
                    "reply_id",
                ):
                    mid = _clean(add_cfg.get(k))
                    if mid:
                        return mid

            if hasattr(mi, "to_dict"):
                try:
                    d = mi.to_dict()
                    mid = _clean(self._deep_find_first(d, keys={
                        "reply_to",
                        "reply_to_message_id",
                        "reply_message_id",
                        "quote_message_id",
                        "reply_id",
                    }))
                    if mid:
                        return mid
                except Exception:
                    pass

        # 3) raw_message
        raw = getattr(self.message, "raw_message", None)
        if isinstance(raw, dict):
            mid = _clean(self._deep_find_first(raw, keys={
                "reply_to",
                "reply_to_message_id",
                "reply_message_id",
                "quote_message_id",
                "reply_id",
            }))
            if mid:
                return mid

        # 4) message_segment
        return find_reply_message_id(getattr(self.message, "message_segment", None))

    def _deep_find_first(self, obj, keys: set):
        """在 dict/list 结构中递归查找给定 keys 的第一个值"""
        try:
            if isinstance(obj, dict):
                for k in keys:
                    if k in obj:
                        v = obj.get(k)
                        if v not in (None, ""):
                            return v
                for v in obj.values():
                    hit = self._deep_find_first(v, keys)
                    if hit not in (None, ""):
                        return hit
                return None
            if isinstance(obj, list):
                for it in obj:
                    hit = self._deep_find_first(it, keys)
                    if hit not in (None, ""):
                        return hit
                return None
            return None
        except Exception:
            return None

    async def _validate_reply_target(self, message_id: str) -> Tuple[bool, Optional[str], str]:
        """
        校验“引用撤回”的目标：必须是本插件发送的图片。

        Returns:
            (ok, resolved_message_id, reason)
        """
        target_id = (message_id or "").strip()
        if not target_id:
            return False, None, "未获取到引用消息ID"

        # 快路径：若上游已经把被引用消息内容挂在 message.reply 上，直接校验，
        # 避免再走历史扫描，减少引用图片时的等待。
        reply_msg = getattr(self.message, "reply", None)
        if reply_msg:
            reply_mid = _extract_message_field(getattr(reply_msg, "message_info", None), "message_id")
            if reply_mid is not None and str(reply_mid).strip() == target_id:
                if _is_nai_pic_plugin_image_message(reply_msg):
                    return True, target_id, "ok"
                return False, None, "该消息不是本插件生成的图片"

        chat_stream = getattr(self.message, "chat_stream", None)
        stream_id = getattr(chat_stream, "stream_id", None) if chat_stream else None
        if not stream_id:
            return False, None, "无法获取会话ID"

        def _scan_once() -> Tuple[bool, bool, Optional[str]]:
            # 由于 message_api 没有按 message_id 精确查询接口，这里只在“近期窗口”内查找
            search_windows = [
                (1.0, 500),    # 近1小时（更常见）
                (24.0, 2000),  # 近24小时（兜底）
            ]
            found = False
            for hours, limit in search_windows:
                msgs = message_api.get_recent_messages(
                    chat_id=str(stream_id),
                    hours=hours,
                    limit=limit,
                    limit_mode="latest",
                    filter_mai=False,
                ) or []
                for msg in msgs:
                    mid = _extract_message_field(msg, "message_id")
                    if not mid:
                        continue
                    if str(mid) != target_id:
                        continue
                    found = True
                    if not _is_nai_pic_plugin_image_message(msg):
                        return True, False, None
                    return True, True, str(mid)
            return found, False, None

        # 先扫一遍
        found, is_plugin, resolved_id = _scan_once()
        if found:
            if not is_plugin:
                return False, None, "该消息不是本插件生成的图片"
            return True, resolved_id, "ok"

        # 可能在 echo 回写前：消息在数据库里还是 send_api_*，此时引用拿到的是平台正式ID，会短暂“查不到”
        id_wait_seconds = max(0, self.get_config("auto_recall.id_wait_seconds", 15))
        poll_interval = min(1.0, max(0.2, id_wait_seconds / 10)) if id_wait_seconds else 0.5
        deadline = time.monotonic() + min(id_wait_seconds, 15)
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)
            found, is_plugin, resolved_id = _scan_once()
            if found:
                if not is_plugin:
                    return False, None, "该消息不是本插件生成的图片"
                return True, resolved_id, "ok"

        return False, None, "未在近期记录中找到该消息（可能太久远或未入库）"

    async def _resolve_latest_message_id(self, message_id: str) -> str:
        """
        处理“撤回最近图片”场景下的临时 message_id（send_api_*）问题。

        message_id 可能是 send_api_*（发送时的临时ID），真实平台ID会通过 echo 异步回写。
        这里在限定时间内轮询，等待其变为正式ID。
        """
        candidate = (message_id or "").strip()
        if not candidate.startswith("send_api_"):
            return candidate

        id_wait_seconds = max(0, self.get_config("auto_recall.id_wait_seconds", 15))
        if id_wait_seconds <= 0:
            return candidate

        poll_interval = min(1.0, max(0.2, id_wait_seconds / 10))
        deadline = time.monotonic() + id_wait_seconds
        while time.monotonic() < deadline:
            refreshed = await self._get_last_message_id(require_marker=True, hours=24.0, limit=300)
            if refreshed and not refreshed.startswith("send_api_"):
                return refreshed
            await asyncio.sleep(poll_interval)
        return candidate

    # ---- AutoRecallMixin 要求的抽象方法 ----

    def _is_auto_recall_enabled(self, platform: str, chat_id: str) -> bool:
        return False

from typing import Tuple, Optional

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger

logger = get_logger("nai_recall_command")


class NaiRecallControlCommand(BaseCommand):
    """NovelAI 图片生成自动撤回控制命令"""

    # 类级别的配置覆盖
    _recall_status_overrides = {}

    # Command基本信息
    command_name = "nai_recall_control_command"
    command_description = "NAI自动撤回控制命令：/nai <on|off>"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+(?P<action>on|off)$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行自动撤回控制命令"""
        logger.info(f"{self.log_prefix} 执行NAI自动撤回控制命令")

        # 获取匹配的参数
        action = self.matched_groups.get("action", "").strip()

        # 获取当前会话信息
        if not self.message or not getattr(self.message, "message_info", None):
            await self.send_text("❌ 无法获取会话信息", storage_message=False)
            return False, "无法获取会话信息", True

        message_info = self.message.message_info
        platform = getattr(message_info, "platform", "")
        group_info = getattr(message_info, "group_info", None)
        user_info = getattr(message_info, "user_info", None)

        if not user_info:
            await self.send_text("❌ 无法获取用户信息", storage_message=False)
            return False, "无法获取用户信息", True

        if group_info and getattr(group_info, "group_id", None):
            chat_id = group_info.group_id
            chat_type = "群聊"
        else:
            chat_id = user_info.user_id
            chat_type = "私聊"

        user_id = user_info.user_id

        # 权限检查：如果管理员模式开启，则需要管理员权限
        from .nai_admin_command import NaiAdminControlCommand
        admin_mode_enabled = NaiAdminControlCommand.is_admin_mode_enabled(platform, chat_id, self.get_config)

        if admin_mode_enabled:
            is_admin = self._check_admin_permission()
            if not is_admin:
                await self.send_text("❌ 当前会话已开启管理员模式，仅管理员可使用此命令", storage_message=False)
                return False, "没有权限", True

        # 检查会话权限（支持群聊和私聊）
        has_permission, permission_error = self._check_chat_permission()
        if not has_permission:
            await self.send_text(f"❌ {permission_error}")
            return False, permission_error, True

        current_chat_key = f"{platform}:{chat_id}"

        if action == "on":
            # 开启自动撤回
            self._recall_status_overrides[current_chat_key] = True
            delay_seconds = self.get_config("auto_recall.delay_seconds", 5)
            await self.send_text(
                f"✅ 已在{chat_type}中开启NAI图片自动撤回功能\n"
                f"📝 图片将在发送后 {delay_seconds} 秒自动撤回\n"
                f"💡 使用 /nai off 可关闭此功能"
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已开启自动撤回")
            return True, "自动撤回已开启", True

        elif action == "off":
            # 关闭自动撤回
            self._recall_status_overrides[current_chat_key] = False
            await self.send_text(
                f"✅ 已在{chat_type}中关闭NAI图片自动撤回功能\n"
                f"💡 使用 /nai on 可重新开启"
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已关闭自动撤回")
            return True, "自动撤回已关闭", True

        else:
            await self.send_text(
                "使用方法：\n"
                "/nai on - 开启NAI图片自动撤回\n"
                "/nai off - 关闭NAI图片自动撤回"
            )
            return False, "无效的操作参数", True

    def _check_chat_permission(self) -> Tuple[bool, Optional[str]]:
        """检查当前会话（群聊/私聊）是否有自动撤回权限"""
        if not self.message or not getattr(self.message, "message_info", None):
            return False, "无法获取消息信息"

        message_info = self.message.message_info
        platform = getattr(message_info, "platform", "")
        group_info = getattr(message_info, "group_info", None)
        user_info = getattr(message_info, "user_info", None)

        # 判断是群聊还是私聊
        if group_info and getattr(group_info, "group_id", None):
            # 群聊模式
            chat_id = group_info.group_id
            chat_type = "group"
        elif user_info and getattr(user_info, "user_id", None):
            # 私聊模式
            chat_id = user_info.user_id
            chat_type = "private"
        else:
            return False, "无法识别聊天类型"

        current_chat_key = f"{platform}:{chat_id}"

        # 检查白名单配置
        allowed_groups = self.get_config("auto_recall.allowed_groups", [])
        if not allowed_groups:
            logger.info(f"{self.log_prefix} 未配置白名单，允许所有会话���用自动撤回")
            return True, None

        if current_chat_key in allowed_groups:
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 有自动撤回权限")
            return True, None

        logger.warning(f"{self.log_prefix} {chat_type} {current_chat_key} 没有自动撤回权限")
        return False, "当前会话没有使用自动撤回功能的权限"

    def _check_admin_permission(self) -> bool:
        """检查当前用户是否是管理员"""
        try:
            admin_users = self.get_config("admin.admin_users", [])
            if not admin_users:
                # 如果未配置管理员列表，默认允许所有人管理
                logger.warning(f"{self.log_prefix} 未配置管理员列表，允许所有人使用管理命令")
                return True

            if not self.message or not getattr(self.message, "message_info", None):
                logger.warning(f"{self.log_prefix} 无法获取消息信息")
                return False

            message_info = self.message.message_info
            user_info = getattr(message_info, "user_info", None)
            user_id = str(getattr(user_info, "user_id", "")) if user_info else None
            is_admin = user_id in admin_users

            logger.debug(f"{self.log_prefix} 用户 {user_id} 管理员检查结果: {is_admin}")
            return is_admin
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查管理员权限时出错: {e}", exc_info=True)
            return False

    @classmethod
    def is_recall_enabled(cls, platform: str, chat_id: str, get_config_func) -> bool:
        """
        静态方法：检查指定会话（群聊/私聊）是否启用了自动撤回

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）
            get_config_func: 获取配置的函数

        Returns:
            bool: 是否启用自动撤回
        """
        current_chat_key = f"{platform}:{chat_id}"

        # 检查运行时覆盖
        if current_chat_key in cls._recall_status_overrides:
            return cls._recall_status_overrides[current_chat_key]

        # 检查默认配置
        return get_config_func("auto_recall.enabled", False)

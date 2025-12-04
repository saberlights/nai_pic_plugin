# -*- coding: utf-8 -*-
"""
NAI 管理员权限控制命令
"""
from typing import Tuple, Optional

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger

logger = get_logger("nai_admin_command")


class NaiAdminControlCommand(BaseCommand):
    """NAI 管理员模式控制命令"""

    # 类级别的管理员模式状态
    _admin_mode_enabled = {}

    # Command基本信息
    command_name = "nai_admin_control_command"
    command_description = "NAI管理员模式控制命令：/nai <st|sp>"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+(?P<action>st|sp)$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行管理员模式控制命令"""
        logger.info(f"{self.log_prefix} 执行NAI管理员模式控制命令")

        # 获取匹配的参数
        action = self.matched_groups.get("action", "").strip()

        # 检查是否是管理员
        is_admin = self._check_admin_permission()
        if not is_admin:
            await self.send_text("❌ 你没有权限使用此命令", storage_message=False)
            return False, "没有管理员权限", True

        # 获取当前会话的key（支持群聊和私聊）
        platform = self.message.message_info.platform
        group_info = self.message.message_info.group_info
        user_info = self.message.message_info.user_info

        if group_info and group_info.group_id:
            chat_id = group_info.group_id
            chat_type = "群聊"
        else:
            chat_id = user_info.user_id
            chat_type = "私聊"

        current_chat_key = f"{platform}:{chat_id}"

        if action == "st":
            # 开启管理员模式
            self._admin_mode_enabled[current_chat_key] = True
            await self.send_text(
                f"✅ 已在{chat_type}中开启NAI管理员模式\n"
                f"🔒 现在仅管理员可使用 /nai 生图命令\n"
                f"💡 使用 /nai sp 可关闭此模式"
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已开启管理员模式")
            return True, "管理员模式已开启", True

        elif action == "sp":
            # 关闭管理员模式
            self._admin_mode_enabled[current_chat_key] = False
            await self.send_text(
                f"✅ 已在{chat_type}中关闭NAI管理员模式\n"
                f"🔓 现在所有人都可使用 /nai 生图命令\n"
                f"💡 使用 /nai st 可重新开启"
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已关闭管理员模式")
            return True, "管理员模式已关闭", True

        else:
            await self.send_text(
                "使用方法：\n"
                "/nai st - 开启管理员模式（仅管理员可生图）\n"
                "/nai sp - 关闭管理员模式（所有人可生图）"
            )
            return False, "无效的操作参数", True

    def _check_admin_permission(self) -> bool:
        """检查当前用户是否是管理员"""
        try:
            admin_users = self.get_config("admin.admin_users", [])
            if not admin_users:
                # 如果未配置管理员列表，默认允许所有人管理
                logger.warning(f"{self.log_prefix} 未配置管理员列表，允许所有人使用管理命令")
                return True

            user_id = str(self.message.message_info.user_info.user_id) if self.message and self.message.message_info and self.message.message_info.user_info else None
            is_admin = user_id in admin_users

            logger.debug(f"{self.log_prefix} 用户 {user_id} 管理员检查结果: {is_admin}")
            return is_admin
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查管理员权限时出错: {e}", exc_info=True)
            return False

    @classmethod
    def is_admin_mode_enabled(cls, platform: str, chat_id: str, get_config_func) -> bool:
        """
        静态方法：检查指定会话是否启用了管理员模式

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）
            get_config_func: 获取配置的函数

        Returns:
            bool: 是否启用管理员模式
        """
        current_chat_key = f"{platform}:{chat_id}"

        # 检查运行时覆盖
        if current_chat_key in cls._admin_mode_enabled:
            return cls._admin_mode_enabled[current_chat_key]

        # 检查默认配置
        return get_config_func("admin.default_admin_mode", False)

    @classmethod
    def check_user_permission(cls, platform: str, chat_id: str, user_id: str, get_config_func) -> bool:
        """
        静态方法：检查用户是否有权限使用生图命令

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）
            user_id: 用户ID
            get_config_func: 获取配置的函数

        Returns:
            bool: 是否有权限
        """
        # 如果管理员模式未开启，所有人都有权限
        if not cls.is_admin_mode_enabled(platform, chat_id, get_config_func):
            return True

        # 管理员模式已开启，检查是否是管理员
        admin_users = get_config_func("admin.admin_users", [])
        return str(user_id) in admin_users

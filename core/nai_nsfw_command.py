# -*- coding: utf-8 -*-
"""
/nai nsfw 命令：NSFW内容过滤开关控制
"""
from typing import Tuple, Optional

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger

logger = get_logger("nai_nsfw_command")


class NaiNsfwControlCommand(BaseCommand):
    """NovelAI NSFW内容过滤控制命令"""

    # 类级别的状态覆盖（运行时状态）
    _nsfw_filter_overrides = {}

    command_name = "nai_nsfw_control_command"
    command_description = "NSFW内容过滤控制命令：/nai nsfw <on|off>"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+nsfw(?:\s+(?P<action>on|off))?$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行NSFW过滤控制命令"""
        logger.info(f"{self.log_prefix} 执行NSFW过滤控制命令")

        # 获取匹配的参数
        action = (self.matched_groups.get("action") or "").strip().lower()

        # 获取当前会话信息
        if not self.message or not getattr(self.message, "message_info", None):
            await self.send_text("❌ 无法获取会话信息", storage_message=False)
            return False, "无法获取会话信息", True

        message_info = self.message.message_info
        platform = getattr(message_info, "platform", "")
        group_info = getattr(message_info, "group_info", None)
        user_info = getattr(message_info, "user_info", None)

        if group_info and getattr(group_info, "group_id", None):
            chat_id = group_info.group_id
            chat_type = "群聊"
        elif user_info and getattr(user_info, "user_id", None):
            chat_id = user_info.user_id
            chat_type = "私聊"
        else:
            await self.send_text("❌ 无法识别聊天类型", storage_message=False)
            return False, "无法识别聊天类型", True

        current_chat_key = f"{platform}:{chat_id}"

        # 如果没有参数，显示当前状态
        if not action:
            current_state = self.is_nsfw_filter_enabled(platform, chat_id, self.get_config)
            state_text = "已开启" if current_state else "已关闭"
            await self.send_text(
                f"当前NSFW过滤状态: {state_text}\n\n"
                "使用方法:\n"
                "/nai nsfw on - 开启NSFW内容过滤（禁止生成NSFW）\n"
                "/nai nsfw off - 关闭NSFW内容过滤（允许生成NSFW）",
                storage_message=False
            )
            return True, "显示NSFW过滤状态", True

        if action == "on":
            # 开启NSFW过滤
            self._nsfw_filter_overrides[current_chat_key] = True
            await self.send_text(
                f"✅ 已在{chat_type}中开启NSFW内容过滤\n"
                f"🔒 生成的图片将避免包含成人内容\n"
                f"💡 使用 /nai nsfw off 可关闭过滤",
                storage_message=False
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已开启NSFW过滤")
            return True, "NSFW过滤已开启", True

        elif action == "off":
            # 关闭NSFW过滤
            self._nsfw_filter_overrides[current_chat_key] = False
            await self.send_text(
                f"✅ 已在{chat_type}中关闭NSFW内容过滤\n"
                f"🔓 生成的图片将不受NSFW限制\n"
                f"💡 使用 /nai nsfw on 可重新开启",
                storage_message=False
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已关闭NSFW过滤")
            return True, "NSFW过滤已关闭", True

        else:
            await self.send_text(
                "使用方法:\n"
                "/nai nsfw on - 开启NSFW内容过滤\n"
                "/nai nsfw off - 关闭NSFW内容过滤",
                storage_message=False
            )
            return False, "无效的操作参数", True

    @classmethod
    def is_nsfw_filter_enabled(cls, platform: str, chat_id: str, get_config_func) -> bool:
        """
        检查指定会话是否启用了NSFW过滤

        Args:
            platform: 平台标识
            chat_id: 会话ID
            get_config_func: 获取配置的函数

        Returns:
            bool: 是否启用NSFW过滤
        """
        current_chat_key = f"{platform}:{chat_id}"

        # 检查运行时覆盖
        if current_chat_key in cls._nsfw_filter_overrides:
            return cls._nsfw_filter_overrides[current_chat_key]

        # 检查默认配置
        return get_config_func("nsfw_filter.enabled", False)

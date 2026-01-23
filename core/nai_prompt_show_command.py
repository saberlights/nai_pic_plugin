# -*- coding: utf-8 -*-
"""
/nai pt 命令：控制是否输出生成的提示词
"""
from typing import Tuple, Optional

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger

logger = get_logger("nai_prompt_show_command")


class NaiPromptShowCommand(BaseCommand):
    """NovelAI 提示词显示控制命令"""

    # 类级别的配置覆盖
    _prompt_show_overrides = {}

    # Command基本信息
    command_name = "nai_prompt_show_command"
    command_description = "NAI提示词显示控制命令：/nai pt <on|off>"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+pt\s+(?P<action>on|off)$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行提示词显示控制命令"""
        logger.info(f"{self.log_prefix} 执行NAI提示词显示控制命令")

        action = self.matched_groups.get("action", "").strip()

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

        current_chat_key = f"{platform}:{chat_id}"

        if action == "on":
            self._prompt_show_overrides[current_chat_key] = True
            await self.send_text(f"✅ 已开启提示词显示")
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已开启提示词显示")
            return True, "提示词显示已开启", True

        elif action == "off":
            self._prompt_show_overrides[current_chat_key] = False
            await self.send_text(f"✅ 已关闭提示词显示")
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已关闭提示词显示")
            return True, "提示词显示已关闭", True

        else:
            await self.send_text("/nai pt on|off - 开启/关闭提示词显示")
            return False, "无效的操作参数", True

    @classmethod
    def is_prompt_show_enabled(cls, platform: str, chat_id: str, get_config_func) -> bool:
        """检查指定会话是否启用了提示词显示"""
        current_chat_key = f"{platform}:{chat_id}"

        if current_chat_key in cls._prompt_show_overrides:
            return cls._prompt_show_overrides[current_chat_key]

        return get_config_func("prompt_show.enabled", False)

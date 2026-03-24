# -*- coding: utf-8 -*-
"""
/nai 撤回 命令：手动撤回 bot 发送的图片。

- 仅支持直接发送 /nai 撤回
- 每次按顺序撤回 bot 最近发送的一张图片
"""
import time
from typing import Optional, Tuple

from src.common.logger import get_logger
from src.plugin_system.base.base_command import BaseCommand

from ..mixins.auto_recall_mixin import AutoRecallMixin

logger = get_logger("nai_pic_plugin")


class NaiManualRecallCommand(BaseCommand, AutoRecallMixin):
    """发送 /nai 撤回，手动撤回 bot 发送的图片"""

    command_name = "nai_manual_recall_command"
    command_description = "手动撤回图片：/nai 撤回"
    command_pattern = r"(?:.*?)(?:/nai\s+撤回)(?:\s+.*)?$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        logger.info(f"{self.log_prefix} [手动撤回] 收到 /nai 撤回")

        last_message_id = await self._get_last_message_id(require_marker=True, hours=24.0, limit=300)
        if last_message_id:
            resolved_id = await self._resolve_latest_message_id(last_message_id)
            return await self._do_recall(resolved_id, "最近图片")

        await self.send_text(
            "❌ 找不到可撤回的图片（直接发送 /nai 撤回 即可按顺序撤回最近一张）",
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

# -*- coding: utf-8 -*-
"""
提示词记忆（仅用于 Action 生图）

需求目标：
- 每次 action 生图时，将上一轮 LLM 生成的正向提示词注入到本轮模板中
- 重启后也能从 ActionRecords 中恢复上一轮提示词

注意：
- 这里只记录 LLM 生成的正向提示词（不包含自拍补充、画师串、负面提示词等）
"""

from __future__ import annotations

from typing import Optional

try:
    from src.common.logger import get_logger  # type: ignore

    logger = get_logger("nai_pic_plugin")
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("nai_pic_plugin")


LAST_PROMPT_RECORD_PREFIX = "NAI_LAST_PROMPT:"


def render_previous_prompt_block(last_prompt: Optional[str]) -> str:
    """Generate the replacement content for the <<PREVIOUS_PROMPT>> placeholder.

    Returns an XML block with inheritance rules when last_prompt is present,
    or an empty string when there is no previous prompt.
    """
    previous = (last_prompt or "").strip()
    if not previous:
        return ""

    return (
        "<previous_prompt_context>\n"
        + "\u3010\u4e0a\u4e00\u8f6e LLM \u751f\u6210\u7684\u63d0\u793a\u8bcd"
        + "\uff08\u7cfb\u7edf\u6ce8\u5165\uff0c\u975e\u7528\u6237\u8f93\u5165\u7684\u82f1\u6587tag\uff09\u3011\n"
        + previous + "\n\n"
        + "\u3010\u7ee7\u627f\u89c4\u5219\uff08\u5fc5\u987b\u9075\u5b88\uff09\u3011\n"
        + "- \u5224\u65ad\u672c\u6b21\u7528\u6237\u8bf7\u6c42\u662f\u5426\u4e3a\u540c\u4e00\u4e3b\u9898\u7684\u5fae\u8c03\uff0c\u8fd8\u662f\u5b8c\u5168\u4e0d\u540c\u7684\u65b0\u4e3b\u9898\n"
        + "- \u540c\u4e00\u4e3b\u9898/\u5fae\u8c03\uff1a\u4ee5\u4e0a\u65b9\u63d0\u793a\u8bcd\u4e3a\u5e95\u7a3f\uff0c\u4ec5\u4fee\u6539\u7528\u6237\u8981\u6c42\u53d8\u66f4\u7684\u90e8\u5206\uff0c\u4fdd\u7559\u5176\u4f59\u6807\u7b7e\n"
        + "- \u65b0\u4e3b\u9898/\u5927\u53d8\u52a8\uff1a\u5b8c\u5168\u5ffd\u7565\u4e0a\u65b9\u63d0\u793a\u8bcd\uff0c\u6309\u7528\u6237\u8bf7\u6c42\u91cd\u65b0\u751f\u6210\n"
        + "</previous_prompt_context>"
    )


def extract_last_prompt_from_record_display(action_prompt_display: str) -> Optional[str]:
    """Extract last_prompt from ActionRecords.action_prompt_display."""
    text = action_prompt_display if isinstance(action_prompt_display, str) else ""
    if not text:
        return None
    if not text.startswith(LAST_PROMPT_RECORD_PREFIX):
        return None
    prompt = text[len(LAST_PROMPT_RECORD_PREFIX):].lstrip("\n").strip()
    return prompt or None


def load_last_prompt_from_action_records(chat_stream_id: str, action_name: str, limit: int = 50) -> Optional[str]:
    """Read last prompt from ActionRecords (synchronous, returns None on failure)."""
    if not chat_stream_id or not action_name:
        return None

    try:
        from src.common.database.database_model import ActionRecords
    except Exception as e:
        logger.debug(f"[prompt_memory] ActionRecords import failed: {e}")
        return None

    try:
        records = (
            ActionRecords.select(ActionRecords.action_prompt_display)
            .where((ActionRecords.chat_id == chat_stream_id) & (ActionRecords.action_name == action_name))
            .order_by(ActionRecords.time.desc())
            .limit(max(1, int(limit)))
        )
        for r in records:
            display = getattr(r, "action_prompt_display", "") or ""
            prompt = extract_last_prompt_from_record_display(display)
            if prompt:
                return prompt
        return None
    except Exception as e:
        logger.warning(f"[prompt_memory] Failed to read ActionRecords: {e}")
        return None

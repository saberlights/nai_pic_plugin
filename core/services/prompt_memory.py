# -*- coding: utf-8 -*-
"""
提示词记忆（仅用于 Action 生图）

需求目标：
- 每次 action 生图时，将“上一轮 LLM 生成的正向提示词”注入到本轮提示词生成请求中
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
    # 单元测试/脱离宿主环境运行时，可能不存在 src 或 structlog，降级为标准日志
    import logging

    logger = logging.getLogger("nai_pic_plugin")


LAST_PROMPT_RECORD_PREFIX = "NAI_LAST_PROMPT:"


def compose_prompt_generator_request(user_request: str, last_prompt: Optional[str]) -> str:
    """将上一轮提示词注入到本轮用户请求中，供 LLM 判断是否继承/大改。"""
    request = (user_request or "").strip()
    previous = (last_prompt or "").strip()
    if not request:
        return ""
    if not previous:
        return request

    # 关键点：避免与 prompt_rules 里的“用户提供英文tag必须保留”冲突
    # 因此明确声明：previous_prompt 是系统历史记录，不属于用户输入，可被丢弃或大幅修改
    return (
        "【系统历史提示词】（上一次由 LLM 生成的正向提示词，仅供参考，不属于用户输入的英文tag，可被修改/替换/丢弃）\n"
        "<previous_prompt>\n"
        f"{previous}\n"
        "</previous_prompt>\n\n"
        "【本次用户要求】\n"
        f"{request}\n\n"
        "【继承规则】\n"
        "- 你必须判断：本次是否与上次同一主题/小改动，还是新主题/大变动。\n"
        "- 若新主题/大变动：忽略 previous_prompt，完全按本次用户要求重新生成一份完整提示词。\n"
        "- 若同一主题/小改动：以 previous_prompt 为底稿做最小必要修改，输出一份新的完整提示词。\n"
    ).strip()


def extract_last_prompt_from_record_display(action_prompt_display: str) -> Optional[str]:
    """从 ActionRecords.action_prompt_display 中提取 last_prompt。"""
    text = action_prompt_display if isinstance(action_prompt_display, str) else ""
    if not text:
        return None
    if not text.startswith(LAST_PROMPT_RECORD_PREFIX):
        return None
    prompt = text[len(LAST_PROMPT_RECORD_PREFIX) :].lstrip("\n").strip()
    return prompt or None


def load_last_prompt_from_action_records(chat_stream_id: str, action_name: str, limit: int = 50) -> Optional[str]:
    """从数据库 ActionRecords 中读取上一轮提示词（同步读取，失败则返回 None）。"""
    if not chat_stream_id or not action_name:
        return None

    try:
        from src.common.database.database_model import ActionRecords
    except Exception as e:
        logger.debug(f"[prompt_memory] ActionRecords 导入失败: {e}")
        return None

    try:
        # 不依赖 startswith SQL（兼容性更好），直接取最近 N 条再在 Python 里筛
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
        logger.warning(f"[prompt_memory] 读取 ActionRecords 失败: {e}")
        return None

# -*- coding: utf-8 -*-
"""
随机场景中文描述清洗工具

将 LLM 返回的随机中文短语标准化为更贴近 Danbooru 中文对照表的表达，
提升后续 tag 检索命中率。
"""

from __future__ import annotations

import re


_DIRECT_REPLACEMENTS = {
    "POV": "第一人称视角",
    "pov": "第一人称视角",
    "第一视角": "第一人称视角",
    "天台": "屋顶",
    "教室里": "教室",
    "房间里": "室内",
    "床上": "在床上",
    "俯视": "俯视镜头",
}


def _normalize_count_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""

    pair = re.fullmatch(r"(\d+)男(\d+)女", token)
    if pair:
        male_count, female_count = pair.groups()
        return f"{male_count}个男性 {female_count}个女性"

    female_only = re.fullmatch(r"(\d+)女", token)
    if female_only:
        return f"{female_only.group(1)}个女性"

    male_only = re.fullmatch(r"(\d+)男", token)
    if male_only:
        return f"{male_only.group(1)}个男性"

    return token


def normalize_random_scene_description(text: str) -> str:
    """标准化随机场景中文短语。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    cleaned = cleaned.replace("\n", " ")
    cleaned = re.sub(r"[，,、|/]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    normalized_tokens: list[str] = []
    for token in cleaned.split(" "):
        token = _normalize_count_token(token)
        token = _DIRECT_REPLACEMENTS.get(token, token)
        token = token.strip()
        if not token:
            continue
        normalized_tokens.extend(part for part in token.split() if part)

    return " ".join(normalized_tokens).strip()

# -*- coding: utf-8 -*-
"""NAI 图片生成插件 - 规则层"""

from .prompt_rules import PROMPT_GENERATOR_TEMPLATE
from .artist_rules import (
    EXTRACT_TAGS_TEMPLATE,
    EXTRACT_FEEDBACK_TAGS_TEMPLATE,
    ARTIST_FROM_POOL_TEMPLATE,
    ARTIST_FIX_FROM_POOL_TEMPLATE,
    format_candidate_pool,
)

__all__ = [
    "PROMPT_GENERATOR_TEMPLATE",
    "EXTRACT_TAGS_TEMPLATE",
    "EXTRACT_FEEDBACK_TAGS_TEMPLATE",
    "ARTIST_FROM_POOL_TEMPLATE",
    "ARTIST_FIX_FROM_POOL_TEMPLATE",
    "format_candidate_pool",
]

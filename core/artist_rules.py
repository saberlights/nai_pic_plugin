# -*- coding: utf-8 -*-
"""
画师串生成规则 - 用于 LLM 生成 NovelAI 画师组合
"""

# ==================== 新流程：预筛选画师池 ====================

# 步骤1: 理解需求，提取英文标签
EXTRACT_TAGS_TEMPLATE = """
你是 Danbooru 标签专家。根据用户的画风需求，提取用于搜索画师的标签。

用户需求：<<USER_REQUEST>>

请输出 3-6 个最相关的 Danbooru 标签（英文，下划线格式）。
这些标签将用于搜索擅长该风格的画师。

【常用 Danbooru 标签参考】
人物特征：loli, shota, mature_female, school_uniform, maid, chibi, 1girl, 1boy
身体特征：small_breasts, large_breasts, flat_chest, thick_thighs, muscular
画风技法：lineart, sketch, monochrome, greyscale, flat_color, gradient, cel_shading
色彩风格：pale_color, pastel_colors, colorful, dark, high_contrast, limited_palette
构图元素：simple_background, white_background, detailed_background, portrait
题材风格：moe, cute, dark, horror, fantasy, science_fiction, cyberpunk

参考示例：
- "清纯可爱小萝莉" → loli cute flat_chest school_uniform
- "暗黑哥特风" → dark gothic pale_skin black_dress
- "性感御姐" → mature_female large_breasts
- "厚涂油画感" → detailed impasto
- "赛博朋克" → cyberpunk science_fiction neon_lights
- "简约扁平风" → flat_color simple_background lineart
- "Q版可爱" → chibi cute moe

只输出标签，用空格分隔，不要解释。优先使用上面参考列表中的标签。
""".strip()

# 步骤2: 从候选池组合画师串
ARTIST_FROM_POOL_TEMPLATE = """
<role>
你是专业的 NovelAI 画师串配方专家。
**重要：只能使用下方候选池中的画师，不要编造其他画师名。**
</role>

<syntax>
### 画师名格式
- **必须使用 `artist:` 前缀**
- 画师名必须与候选池中的完全一致

### 数值权重
- 格式：`权重值::artist:画师名::`
- 高权重(1.2-1.5)主导风格，中等(0.8-1.0)强化，低权重(0.5-0.7)点缀

### 括号权重
- 强化：`{artist:画师名}`, `{{artist:画师名}}`

### 辅助标签
- 年份：`year_2024`, `year_2025`
- 风格：`flat_color`, `pale_color`, `colorful`
</syntax>

<strategy>
1. **同向叠加**：线条感画师叠加线条感画师，同类特征互相增强
2. **权重分层**：主导画师(1.2-1.5)放最前，点缀画师(0.5-0.7)放后面
3. **多画师打包**：风格相近的画师打包：`1.5::artist:A, artist:B::`
4. **数量控制**：通常 3-5 个主力画师 + 2-3 个点缀画师效果最佳
</strategy>

<user_request>
用户需求：<<USER_REQUEST>>
模型版本：<<MODEL_VERSION>>
</user_request>

<candidate_pool>
【候选画师池】以下画师已验证存在，按相关度排序：
<<CANDIDATE_ARTISTS>>
</candidate_pool>

<output>
从候选池中选择 5-10 个画师进行组合，直接输出画师串。
不要解释，不要输出质量词。所有画师必须带 `artist:` 前缀。
<<EXTRA_HINT>>
</output>
""".strip()


def format_candidate_pool(artists: list) -> str:
    """
    格式化候选画师池为 LLM 可读的文本

    Args:
        artists: 画师列表，每个元素为 {"name": str, "post_count": int, "style_tags": list}

    Returns:
        格式化的候选池文本
    """
    if not artists:
        return "（无候选画师）"

    from .danbooru_api import get_artist_quality_score

    lines = []
    for artist in artists:
        name = artist.get("name", "")
        post_count = artist.get("post_count", 0)
        style_tags = artist.get("style_tags", [])

        grade = get_artist_quality_score(artist)

        if style_tags:
            style_str = ", ".join(style_tags[:5])
            lines.append(f"• {name} [{grade}] ({post_count:,}) - {style_str}")
        else:
            lines.append(f"• {name} [{grade}] ({post_count:,})")

    return "\n".join(lines)


# artfix 步骤1: 从用户反馈提取搜索标签
EXTRACT_FEEDBACK_TAGS_TEMPLATE = """
你是 Danbooru 标签专家。用户对一组画师串的效果提出了反馈，请提取用于搜索补充画师的标签。

用户反馈：<<USER_FEEDBACK>>

请输出 2-4 个最能代表用户想要调整方向的 Danbooru 标签（英文，下划线格式）。
这些标签将用于搜索擅长该特征的画师作为候选补充。

【常用 Danbooru 标签参考】
画风技法：lineart, sketch, cel_shading, flat_color, monochrome, watercolor_(medium)
色彩风格：pale_color, pastel_colors, colorful, dark, high_contrast, limited_palette
人物风格：chibi, moe, cute, mature_female, realistic
构图：portrait, close-up, full_body, simple_background, detailed_background

参考示例：
- "线条太粗" → lineart detailed
- "颜色太淡，想要更鲜艳" → colorful high_contrast
- "风格不够萌" → cute chibi moe
- "太写实了" → flat_color cel_shading
- "细节太多" → simple_background flat_color
- "颜色太暗" → colorful pastel_colors pale_color

只输出标签，用空格分隔，不要解释。优先使用上面参考列表中的标签。
""".strip()

# artfix 步骤2: 从扩展池重新组合
ARTIST_FIX_FROM_POOL_TEMPLATE = """
<role>
你是专业的 NovelAI 画师串配方专家，根据用户反馈优化画师串。
**重要：只能使用下方扩展候选池中的画师，不要编造其他画师名。**
</role>

<syntax>
- 画师必须带 `artist:` 前缀，如 `artist:画师名`
- 画师名必须与候选池中的完全一致
- 数值权重：`权重值::artist:画师名::` 高权重(1.2-1.5)强化，低权重(0.5-0.7)点缀
- 括号权重：`{{artist:画师名}}` 强化
</syntax>

<strategy>
- 某特征太强 → 降低相关画师权重或替换为池中风格更合适的画师
- 某特征太弱 → 提高相关画师权重，或从池中补充同类画师
- 不想要某特征 → 移除该画师，从池中选替代画师
- 缺少某特征 → 从池中选擅长该特征的画师加入
- 权重分层：主导画师(1.2-1.5)放最前，点缀画师(0.5-0.7)放后面
- 多个相近画师可打包：`1.5::artist:A, artist:B::`
</strategy>

<context>
原画师串：<<ORIGINAL_PROMPT>>
用户反馈：<<USER_FEEDBACK>>
模型版本：<<MODEL_VERSION>>
</context>

<candidate_pool>
【扩展候选池】包含原画师和根据反馈方向搜索的新画师，均已验证存在：
<<CANDIDATE_ARTISTS>>
</candidate_pool>

<output>
根据用户反馈，从扩展池中重新组合画师串。直接输出优化后的画师串。
不要解释，不要输出质量词。所有画师必须带 `artist:` 前缀。
</output>
""".strip()

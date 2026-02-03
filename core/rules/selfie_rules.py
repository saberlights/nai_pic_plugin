# -*- coding: utf-8 -*-
"""
自拍提示词生成规则模块
提供自拍场景检测和提示词建议，让 LLM 自主选择合适的自拍类型
"""

import re
from typing import Tuple, List


# ==================== 触发关键词（仅用于检测是否自拍）====================

SELFIE_TRIGGER_KEYWORDS = [
    # 直接自拍
    "自拍", "selfie", "self-shot", "自己拍", "给自己拍", "自拍照",
    # 镜子相关
    "镜子", "mirror", "照镜子", "镜中", "镜面", "浴室镜", "全身镜", "穿衣镜",
    # 手机拍照
    "手机拍", "前置", "前置摄像头", "front camera", "举手机",
    # 自拍杆
    "自拍杆", "自拍棒", "selfie stick",
    # 合照自拍
    "合照", "合影", "一起拍", "group selfie",
]


# ==================== 完整的自拍提示（让 LLM 自己选择类型）====================

SELFIE_HINT_FOR_LLM = """
【自拍模式】用户正在请求自拍风格的图片。

【硬规则（最高优先级）】
- 除非用户明确要求外貌（发色/发型/瞳色等），否则禁止输出任何外貌描述类标签（hair/eyes/发型/瞳色等）
- 你可以且应该补充：自拍类型、镜头构图、动作姿势、背景环境、光影氛围（这些是本插件希望你补充的重点）

## 自拍类型选择规则（按优先级执行）

1. **根据用户描述匹配**：分析用户描述中的场景、角度、方式等细节，匹配最合适的类型
   - 场景线索：浴室/卧室/穿衣镜前 → 镜子自拍，户外/景点 → 自拍杆自拍
   - 角度线索：从上往下/显脸小 → 高角度俯拍，从下往上/显腿长 → 低角度仰拍
   - 人数线索：和朋友/两个人/合影 → 合照自拍
   - 构图线索：全身/看衣服/看穿搭 → 镜子自拍或自拍杆自拍
   - **展示线索：黑丝/腿部/鞋子/裙子/全身穿搭等需要展示下半身的内容 → 必须选择能看到全身的类型（镜子自拍/自拍杆自拍/低角度仰拍），禁止选高角度俯拍**
2. **根据上下文推断**：如果用户只说"自拍"，但对话上下文有线索（如之前提到在洗澡→镜子自拍），根据上下文选择
3. **随机选择**：如果用户只说"自拍"且描述和上下文都无参考信息，从以下类型中随机选择一种，增加多样性

## 自拍类型及对应标签

**【重要】只有"必须标签"是固定的，其他所有标签请根据场景自由发挥，不要重复使用相同组合**

### 1. 手机前置自拍
- **必须标签**：selfie, pov, looking at viewer
- **方向**：手机在画面外看不到，通常是近景或半身，自由搭配表情、光线、氛围

### 2. 镜子自拍
- **必须标签**：mirror selfie, holding phone, looking at viewer
- **方向**：通过镜子反射拍摄，可以是全身或半身，自由搭配场景（浴室、卧室、试衣间等）

### 3. 高角度俯拍自拍
- **必须标签**：selfie, from above, pov, looking up
- **方向**：从上往下拍，显脸小大眼效果，手机在画面外，自由搭配可爱/甜美方向的元素

### 4. 低角度仰拍自拍
- **必须标签**：selfie, from below, pov, looking down
- **方向**：从下往上拍，显腿长气场强，手机在画面外，自由搭配自信/酷飒方向的元素

### 5. 合照自拍
- **必须标签**：group selfie, pov, looking at viewer
- **方向**：多人合照，手机在画面外，自由搭配人物互动姿态和亲密感

### 6. 自拍杆自拍
- **必须标签**：selfie stick, wide angle, pov
- **方向**：广角效果，通常是全身或环境人像，自由搭配户外场景和背景元素

## 通用规则
- **必须**：looking at viewer（直视镜头）
- **必须**：pov（第一人称视角，镜子自拍除外）
- 表情、手势、光线、氛围等：根据用户描述和场景自由发挥，追求多样性

## 重要提醒
- 前置自拍时手机在画面外，不要添加 holding phone、smartphone 等标签
- 只有镜子自拍才能看到手机（通过镜子反射）
- 不要使用 arm up（向上举手），自拍手臂是向前伸
- **禁止生成角色外貌描述**（发色、瞳色、发型等），角色特征由系统自动添加
- 不要重复表达相同概念（如 mirror selfie 已经表达镜子，不需要再加 mirror, reflection）
"""


def detect_selfie_mode(description: str) -> bool:
    """
    检测是否为自拍模式（简化版，只检测是否触发）

    Args:
        description: 用户输入的描述

    Returns:
        bool: 是否为自拍模式
    """
    description_lower = description.lower()

    for keyword in SELFIE_TRIGGER_KEYWORDS:
        if keyword.lower() in description_lower:
            return True

    return False


def get_selfie_hint() -> str:
    """
    获取自拍模式的 LLM 提示（包含所有类型，让 LLM 自己选择）

    Returns:
        str: 完整的自拍提示文本
    """
    return SELFIE_HINT_FOR_LLM


def merge_selfie_prompt(generated_prompt: str, selfie_prompt_add: str) -> str:
    """
    智能合并自拍提示词，配置中的角色特征优先

    Args:
        generated_prompt: LLM 生成的提示词
        selfie_prompt_add: 配置文件中的角色特征

    Returns:
        str: 合并后的提示词
    """
    if not selfie_prompt_add:
        return generated_prompt

    # 解析要添加的角色特征标签
    add_tags = [
        tag.strip()
        for tag in selfie_prompt_add.split(",")
        if tag.strip()
    ]

    if not add_tags:
        return generated_prompt

    # 冲突类别关键词
    conflict_keywords = {
        "hair_color": ["hair", "haired"],
        "eye_color": ["eyes", "eyed"],
        "hair_style": ["twintails", "ponytail", "braid", "bun", "bob", "hime cut"],
    }

    # 检测配置中的角色特征属于哪些类别
    config_categories = set()
    for tag in add_tags:
        tag_lower = tag.lower()
        for category, keywords in conflict_keywords.items():
            if any(kw in tag_lower for kw in keywords):
                config_categories.add(category)

    # 解析 LLM 生成的标签，移除与配置冲突的标签
    generated_tags = [
        tag.strip()
        for tag in generated_prompt.replace("\n", ",").split(",")
        if tag.strip()
    ]

    filtered_tags = []
    for tag in generated_tags:
        tag_lower = tag.lower()
        is_conflict = False

        for category in config_categories:
            keywords = conflict_keywords[category]
            if any(kw in tag_lower for kw in keywords):
                is_conflict = True
                break

        if not is_conflict:
            filtered_tags.append(tag)

    # 组合：在人数标签后插入角色特征
    if len(filtered_tags) >= 2:
        prefix = ", ".join(filtered_tags[:2])
        suffix = ", ".join(filtered_tags[2:]) if len(filtered_tags) > 2 else ""
        if suffix:
            merged = f"{prefix}, {', '.join(add_tags)}, {suffix}"
        else:
            merged = f"{prefix}, {', '.join(add_tags)}"
    else:
        merged = f"{', '.join(add_tags)}, {', '.join(filtered_tags)}"

    return merged.strip(", ")

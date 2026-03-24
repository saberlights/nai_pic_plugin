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
    # 合照自拍
    "合照", "合影", "一起拍", "group selfie",
]


# ==================== 完整的自拍提示（让 LLM 自己选择类型）====================

SELFIE_HINT_FOR_LLM = """
【自拍模式判定与规则】

## 自拍意图判定（必须执行）
请根据用户请求判断是否存在自拍/自画像意图。以下情况应判定为自拍：
- 直接提到自拍相关词：自拍、selfie、镜子、前置摄像头等
- 向 bot 索要照片/展示：看你的、给我看、秀一下、拍给我看、发张照片、show me 等
- 明确用第二人称指向 bot 本人出镜：「你穿黑丝」「你的腿」「你今天穿了什么」等
- 提到拍照动作：拍一张、照一张、合照、合影等
- 展示/观看请求 + 服饰/身体部位：「看看黑丝」「来张JK」「白丝给我看看」等——用户想看 bot 穿着/展示的样子，属于自拍

**【关键】区分自拍与普通画图的核心标准：用户是想让 bot 展示自己（自拍），还是想让 bot 画一幅与 bot 无关的画（普通画图）？**
- 明确画图请求（如"画一个穿黑丝的女孩"、"画黑丝少女"）→ 普通画图，不是自拍
- 展示/观看请求（如"看看黑丝"、"来张黑丝照"、"穿JK给我看"）→ 自拍（用户想看 bot 穿）
- 明确指向 bot（如"你穿黑丝"、"你的腿"）→ 自拍
- 纯讨论（如"黑丝好看吗"）→ 不触发生图

**如果判定不是自拍意图，忽略下方所有自拍规则，按正常模式生成。**
**如果判定为自拍意图，必须应用以下全部规则：**

## 自拍硬规则（最高优先级）
- 除非用户明确要求外貌（发色/发型/瞳色等），否则禁止输出任何外貌描述类标签（hair/eyes/发型/瞳色等）
- 除非用户明确要求某个角色、某部作品或 cosplay，否则禁止输出任何角色名、作品名、版权来源标签
- 尤其禁止输出 `人物名(作品名)`、`character_name_(series)`、角色别名、作品缩写、版权名、系列名这类会把自拍误导成二创角色图的标签
- 自拍默认是 bot 本人出镜，不是现成作品角色；因此默认不要补充 character / copyright / source 相关信息
- 如果用户明确要求 cosplay，则允许输出角色相关标签，但应优先使用 `角色tag (cosplay)` 这种 cosplay 标记形式，而不是直接把 bot 当成该角色本体
- 你可以且应该补充：自拍类型、镜头构图、动作姿势、背景环境、光影氛围（这些是本插件希望你补充的重点）

## 自拍类型选择规则（按优先级执行）

1. **根据用户描述匹配**：分析用户描述中的场景、角度、方式等细节，匹配最合适的类型
   - 场景线索：浴室/卧室/穿衣镜前 → 镜子自拍，户外/景点 → 选择自然的手持自拍或其他合理自拍构图
   - 角度线索：从上往下/显脸小 → 高角度俯拍，从下往上/显腿长 → 低角度仰拍
   - 人数线索：和朋友/两个人/合影 → 合照自拍
   - 构图线索：全身/看衣服/看穿搭 → 镜子自拍或低角度仰拍等能看清全身的构图
   - **展示线索：黑丝/腿部/鞋子/裙子/全身穿搭等需要展示下半身的内容 → 必须选择能看到全身的类型（镜子自拍/低角度仰拍等），禁止选高角度俯拍**
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

## 通用规则
- **必须**：looking at viewer（直视镜头）
- **必须**：pov（第一人称视角，镜子自拍除外）
- 表情、手势、光线、氛围等：根据用户描述和场景自由发挥，追求多样性

## 重要提醒
- 前置自拍时手机在画面外，不要添加 holding phone、smartphone 等标签
- 只有镜子自拍才能看到手机（通过镜子反射）
- 不要使用 arm up（向上举手），自拍手臂是向前伸
- 不要使用 selfie stick、holding selfie stick
- **禁止生成角色外貌描述**（发色、瞳色、发型等），角色特征由系统自动添加
- **禁止生成角色/作品标签**（如 `人物(作品)`、角色名、作品名、版权名、系列名）；除非用户明确要求角色自拍或 cosplay
- **如果用户明确要求 cosplay**，角色标签请优先写成 `角色tag (cosplay)`，不要直接写成角色本体标签
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


# LLM 输出中的自拍标签（用于从生成结果判断是否为自拍）
_SELFIE_OUTPUT_TAGS = [
    "selfie", "mirror selfie", "group selfie",
    "self-shot", "self shot",
]


def detect_selfie_from_output(prompt: str) -> bool:
    """从 LLM 生成的提示词中检测是否包含自拍标签。

    用于在 LLM 自行判定自拍意图后，从输出结果决定是否执行后处理
    （合并角色特征、移除外貌标签等）。
    """
    prompt_lower = prompt.lower()
    return any(tag in prompt_lower for tag in _SELFIE_OUTPUT_TAGS)


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

    def normalize_tag(tag: str) -> str:
        """移除常见权重包装，便于判断外貌冲突。"""
        tag = tag.strip()
        tag = re.sub(r"^[+-]?\d+(?:\.\d+)?::", "", tag).strip()
        tag = re.sub(r"::\s*$", "", tag).strip()
        tag = tag.strip("{}[]() ")
        return re.sub(r"\s+", " ", tag.lower()).strip()

    def is_hair_related(tag: str) -> bool:
        core = normalize_tag(tag)
        hair_keywords = [
            " hair", "haired", "twintails", "twin tails", "ponytail", "side ponytail",
            "braid", "pigtails", "bun", "bob cut", "hime cut", "bangs", "forelock",
            "ahoge", "side lock", "side locks", "hairclip", "hair clip", "barrette",
            "hair ornament", "hair ribbon", "hair bow", "hairband", "headband",
            "scrunchie", "wavy ends", "loose hair strands", "pixie cut", "cropped hair",
            "short bob", "bob haircut", "shoulder-length hair", "chin-length hair",
        ]
        return any(keyword in core for keyword in hair_keywords)

    def is_eye_related(tag: str) -> bool:
        core = normalize_tag(tag)
        eye_colors = {
            "black", "brown", "blue", "red", "green", "purple", "orange",
            "gray", "grey", "golden", "yellow", "pink", "aqua", "cyan",
        }
        if core in {"eyelashes", "long eyelashes", "heterochromia"}:
            return True
        match = re.search(r"\b([a-z]+)\s+eyes\b", core)
        if match and match.group(1) in eye_colors:
            return True
        return bool(re.search(r"\b[a-z]+-eyed\b", core))

    has_hair_anchor = any(is_hair_related(tag) for tag in add_tags)
    has_eye_anchor = any(is_eye_related(tag) for tag in add_tags)

    # 解析 LLM 生成的标签，移除与配置冲突的标签
    generated_tags = [
        tag.strip()
        for tag in generated_prompt.replace("\n", ",").split(",")
        if tag.strip()
    ]

    filtered_tags = []
    for tag in generated_tags:
        if has_hair_anchor and is_hair_related(tag):
            continue
        if has_eye_anchor and is_eye_related(tag):
            continue
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

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
【自拍模式规则】

1. 先判断用户是不是在索要 bot 本人出镜的照片。
以下情况通常判定为自拍：
- 明确提到 自拍、selfie、镜子、前置、合照
- 索要 bot 的照片、展示照、穿搭照，如“发张照片”“给我看看你今天穿什么”
- 明确要求 bot 本人展示穿搭或身体部位，如“你穿黑丝”“给我看鞋子”“来张全身照”

以下情况通常不是自拍：
- “画一个穿黑丝的女孩”这类与 bot 无关的普通画图
- 纯讨论，不是在索要图片

如果不是自拍，忽略下面全部规则，按普通画图处理。

2. 自拍时按以下优先级决策：
- 用户明确要求
- 已提供的连续性上下文 / 上一轮自拍锚点
- 当前时间与光线
- 少量合理补充

3. 自拍硬规则：
- 除非用户明确要求外貌，否则不要输出发色、发型、瞳色等外貌标签；这些由系统自拍锚点负责
- 重点补自拍类型、构图、镜头、动作、背景、光线、时间氛围
- 如果用户没有明确要求变化，默认延续上一轮自拍的场景和穿搭
- 系统自拍锚点里已经固定的发长、刘海和发夹位置视为硬约束；不要擅自改成 short hair、bob cut，也不要把发夹换到另一侧
- 如果用户只说宽泛服装类别，如睡衣、裙子、外套、鞋子、袜子、制服、泳装、家居服，不要停留在大类；必须收敛成一个单一具体款式
- 细化服装时优先确定：主款式、长度、材质、剪裁、覆盖度、颜色；只补必要项，不要把一件衣服写成多个分支
- 在没有明确性感指令时，宽泛服装默认按自然、日常、非情趣化款式处理；不要把“睡衣”自动发散成低胸性感睡裙或情趣内衣
- 如果上一轮自拍已经有明确服装锚点，而用户这轮没有说要换款式，就继续沿用，不要只因同属一个大类就换成另一种完全不同的衣服
- 如果用户这轮只改主衣物、主衣物颜色或材质，默认保留上一轮的袜子、鞋子和未提到的配饰
- 如果用户这轮只改袜子或鞋子，默认保留上一轮的主衣物
- 如果用户这轮只是说“再来一张”“继续”“另一张”，没有明确说换衣服、换袜子、换鞋子，就默认整套穿搭强继承，不要自行删掉上一轮已经存在的袜类或鞋类
- 袜类请优先按以下标准 tag 处理：短袜=ankle socks，普通袜=socks，小腿袜/及膝袜=knee socks，过膝袜/大腿袜=thighhighs，裤袜/连裤袜=pantyhose
- 黑丝/白丝优先理解成 black pantyhose / white pantyhose；不要误写成 over knee socks
- 如果用户或上文出现 `over knee socks`，归一理解为 `thighhighs`，不要原样输出
- `stockings` 只有在用户明确说“丝袜”但无法进一步判断具体长度时才作为兜底；能具体时优先 `pantyhose` 或 `thighhighs`
- 如果用户明确指定黑丝、白丝、过膝袜、鞋子、腿部、全身穿搭等是本轮观看重点，这些元素就是自拍主视觉元素，优先级高于慵懒感、日常感、室内感、光线氛围
- 主视觉元素优先放在提示词前部；必要时允许对 1-3 个核心元素使用中高权重，不要把所有 tag 都加权
- 不要让 sleepy, soft lighting, indoors, living room 这类氛围词压过 black pantyhose, thighhighs, loafers 等明确指定的展示目标

4. 自拍类型选择：
- 只有明确提到镜子、镜前、浴室镜、穿衣镜、全身镜，或上下文强烈限定在镜前时，才选择镜子自拍
- 需要展示全身、穿搭、腿部、袜子、鞋子时，优先选择能清楚展示下半身的构图，不要选高角度俯拍
- 用户只说“自拍”“来一张”“再来一张”“看看”时，在合理候选里选择一种，不要长期固定成单一类型
- 不要使用自拍杆自拍
- 如果当前镜头会遮挡用户明确要看的元素，必须优先改构图去展示该元素，而不是保留更有气氛但看不清重点的自拍角度

5. 自拍类型与必须标签：
- 手机前置自拍：selfie, pov, looking at viewer
- 镜子自拍：mirror selfie, holding phone, looking at viewer
- 高角度俯拍自拍：selfie, from above, pov, looking up
- 低角度仰拍自拍：selfie, from below, pov, looking down
- 合照自拍：group selfie, pov, looking at viewer

6. 通用提醒：
- 非镜子自拍时，手机应在画面外，不要添加 holding phone、smartphone
- 只有镜子自拍才能自然看到手机
- 非镜子自拍通常带 pov；镜子自拍通常不带 pov
- 不要生成 selfie stick、holding selfie stick、arm up
- 不要重复表达同一个概念，如 mirror selfie 后又加 mirror、reflection
- 对同一套穿搭，只保留一个明确主款式，不要同时混入彼此冲突的服装分支
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

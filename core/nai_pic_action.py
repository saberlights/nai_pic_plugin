# -*- coding: utf-8 -*-
import traceback
import time
from typing import Tuple, Optional, Dict, Any

from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.component_types import ActionActivationType, ChatMode
from src.common.logger import get_logger
from src.plugin_system import llm_api

from .nai_web_client import NaiWebClient
from .auto_recall_mixin import AutoRecallMixin
from .image_url_helper import save_base64_image_to_file

logger = get_logger("nai_pic_plugin")

_PROMPT_RULES_TEXT = """
# 角色指令：你是一位专业的AI绘画提示词转换专家，专门为 NovelAI 模型生成高质量的提示词。
# 你的核心任务是：严格按照用户的描述，将其转换成简短有效的英文提示词，优先使用简洁的自然语言描述。

---
### **处理要求 1: 提示词风格 (简洁自然语言)**
*   优先使用简短的英文短语和精炼的自然语言描述，避免冗长句子。
*   仅在描述角色名称和作品名称时使用关键词格式（如：rem (re zero)）。
*   对于场景、动作、表情、服装等描述，使用简洁有效的英文短语。

### **处理要求 2: 严格按用户描述转换**
*   **严格翻译,不添加不删减**：将用户的中文描述准确翻译成英文,不添加用户未提到的内容,不删减、不修改、不"净化"用户原意（即便包含NSFW等内容）。
*   **【重要】完整保留用户的英文tag**：如果用户已经提供了英文单词、英文短语或英文tag（如 "masterpiece", "1girl", "solo", "best quality" 等），**必须原封不动地保留这些英文内容**，不得删除、修改、替换或"优化"。
*   **【重要】识别强调词并加权**：当用户使用"必须"、"一定"、"重点"、"务必"、"非常"、"特别"等强调词时，对相应的描述内容使用`{}`进行加权。例如"必须是红色头发"→`{red hair}`，"一定要微笑"→`{smiling}`。

### **处理要求 3: 角色处理规则**
*   **角色名称格式**: 当用户提到特定角色时，转换为标准格式：角色罗马音名称 (作品英文名)，如：rem (re zero)。
*   **用户描述优先**: 严格按用户描述转换，不添加角色的默认特征（除非用户明确提到）。

### **处理要求 4: 构图控制**
*   除非用户明确要求多人场景,否则在涉及人物的描述中在**最前面**添加`{{{{{{{{{{solo}}}}}}}}}}`, `1girl`标签确保单人构图。
*   如果用户没有要求绘制人物,则不添加任何人物相关标签。
*   多人场景在最前面使用`2girls`、`3girls`等标签(不使用solo)。

### **处理要求 5: 简洁有效原则**
*   使用最精炼的词汇表达完整含义。
*   避免重复和冗余描述。
*   每个词汇都应该有明确的视觉表现作用。

### **处理要求 6: 严格禁止**
*   **禁止输出非提示词内容**: 只输出纯粹的英文提示词。
*   **禁止添加质量词**: 不自动添加 masterpiece, best quality, 8k 等质量标签。
*   **禁止自主发挥**: 严格按照用户描述转换，不添加任何个人理解或补充。

---
### **# 示例**

#### **示例 1: 简单场景描述**
*   **用户输入**: "画一个女孩在雨中哭泣"
*   **输出**: `{{{{{{{{{{solo}}}}}}}}}}, 1girl, girl crying in rain`

#### **示例 2: 角色 + 用户具体描述**
*   **用户输入**: "画雷姆穿着白色连衣裙站在花园里"
*   **输出**: `{{{{{{{{{{solo}}}}}}}}}}, 1girl, rem (re zero) in white dress, standing in garden`

#### **示例 3: 角色但无额外描述**
*   **用户输入**: "画初音未来"
*   **输出**: `{{{{{{{{{{solo}}}}}}}}}}, 1girl, hatsune miku (vocaloid)`

#### **示例 4: 非人物场景**
*   **用户输入**: "画一个美丽的日落海滩"
*   **输出**: `beautiful sunset beach, golden light on waves`

#### **示例 5: 用户提供英文tag**
*   **用户输入**: "masterpiece, best quality, 1girl, 蕾姆穿着白色连衣裙"
*   **输出**: `masterpiece, best quality, 1girl, {{{{{{{{{{solo}}}}}}}}}}, rem (re zero) in white dress`

#### **示例 6: 混合中英文描述**
*   **用户输入**: "画一个女孩在雨中, crying, wet clothes"
*   **输出**: `{{{{{{{{{{solo}}}}}}}}}}, 1girl, girl in rain, crying, wet clothes`

#### **示例 7: 用户提供完整英文提示词**
*   **用户输入**: "solo, 1girl, long hair, blue eyes, standing in garden"
*   **输出**: `solo, 1girl, long hair, blue eyes, standing in garden`

#### **示例 8: 用户使用强调词**
*   **用户输入**: "画蕾姆,必须是蓝色头发,一定要微笑"
*   **输出**: `{{{{{{{{{{solo}}}}}}}}}}, 1girl, rem (re zero), {blue hair}, {smiling}`

#### **示例 9: 英文tag + 强调词组合**
*   **用户输入**: "masterpiece, 1girl, 画一个女孩,重点突出红色眼睛"
*   **输出**: `masterpiece, 1girl, {{{{{{{{{{solo}}}}}}}}}}, girl, {red eyes}`

#### **示例 10: 多人场景**
*   **用户输入**: "画蕾姆和拉姆两个人站在一起"
*   **输出**: `2girls, rem (re zero), ram (re zero), standing together`
""".strip()

_PROMPT_GENERATOR_TEMPLATE = f"""
{_PROMPT_RULES_TEXT}

【用户描述】
<<USER_REQUEST>>
<<SELFIE_HINT>>
""".strip()

class NaiPicAction(AutoRecallMixin, BaseAction):
    """NovelAI Web 图片生成动作"""

    # 激活设置
    activation_type = ActionActivationType.LLM_JUDGE
    focus_activation_type = ActionActivationType.LLM_JUDGE
    normal_activation_type = ActionActivationType.KEYWORD
    mode_enable = ChatMode.ALL
    parallel_action = True

    # 动作基本信息
    action_name = "nai_web_draw"
    action_description = (
        "使用 NovelAI Web API 生成图片（仅支持文生图）。"
        "适用于 std.loliyc.com 等 NovelAI 网页代理接口。"
    )

    # 关键词设置
    activation_keywords = [
        "画", "绘制", "生成图片", "画图", "draw", "paint", "图片生成", "创作",
        "nai画", "nai生成", "novelai画"
    ]

    # LLM判定提示词
    llm_judge_prompt = """
判定是否需要使用 NovelAI Web 图片生成动作的条件：

**使用场景：**
1. 用户要求画图、生成图片或创作图像
2. 用户描述了想要看到的画面或场景
3. 用户想要创意图片或艺术作品

**不要使用的情况：**
1. 纯文字聊天和问答
2. 只是提到"图片"、"画"等词但不是要求生成
3. 谈论已存在的图片或照片
4. 用户明确表示不需要图片时
5. 涉及图生图的需求（本插件仅支持文生图）
"""

    keyword_case_sensitive = False

    # 动作参数定义
    default_action_parameters = {
        "description": "用户绘图请求的原始描述（保持用户原话，不要翻译或排序）",
        "size": "图片尺寸 512x512(默认从配置中获取，如果配置中含有多个大小，则可以从中选取一个)",
        "selfie_mode": "是否生成自拍模式的图片，设置为true时会自动添加自拍相关提示词，默认为false",
    }

    # 动作使用场景
    action_require = [
    "用户明确要求画图、生成图片或创作图像时使用",
    "用户要求生成自拍照片时，设置selfie_mode为true",
    "只有在以下情况才执行：1) 用户直接要求画图 2) 用户在延续同一绘图主题进行修改",
    "禁止在纯聊天、问答或技术讨论中自动触发画图功能",
    "若用户未明确要求'重新画'，'再来一张'等等，则禁止重复输出相同提示词",
    "必须强制执行久远的所有画图要求"
    ]
    associated_types = ["text"]

    action_parameters = default_action_parameters

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_client = NaiWebClient(self)

    async def execute(self) -> Tuple[bool, Optional[str]]:
        """执行 NovelAI Web 图片生成"""
        logger.info(f"{self.log_prefix} 执行 NovelAI Web 图片生成动作")

        # 获取参数
        description = (self.action_data.get("description") or "").strip()
        size = (self.action_data.get("size") or "").strip()
        selfie_mode_raw = self.action_data.get("selfie_mode", False)
        selfie_mode = self._normalize_bool(selfie_mode_raw)

        # 始终使用LLM生成提示词
        generated_prompt = await self._generate_prompt_with_llm(selfie_mode, description)
        if generated_prompt:
            description = generated_prompt.strip()
            logger.info(f"{self.log_prefix} 已通过LLM自动生成提示词: {description}")
        elif description:
            logger.info(f"{self.log_prefix} 使用Planner提供的提示词（LLM提示词生成被禁用或失败）")
        else:
            logger.warning(f"{self.log_prefix} 无法生成提示词，描述为空")
            await self.send_text("提示词生成器开小差了，请直接告诉我想画什么，或者稍后再试一次~")
            return False, "图片描述为空"

        # 处理自拍模式
        if selfie_mode:
            description = self._process_selfie_prompt(description)
            logger.debug(f"{self.log_prefix} 自拍模式已启用")

        # 清��和验证描述
        if len(description) > 1000:
            description = description[:1000]
            logger.debug(f"{self.log_prefix} 提示词已截断至1000字符")

        # 获取模型配置
        model_config = self._get_model_config()
        if not model_config:
            error_msg = "抱歉，NovelAI Web 图片生成功能配置无效，无法提供服务。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} 模型配置获取失败")
            return False, "模型配置无效"

        # 配置验证
        if not model_config.get("base_url"):
            error_msg = "抱歉，NovelAI Web API 地址未配置，无法提供服务。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} base_url 未配置")
            return False, "base_url 未配置"

        # 获取尺寸配置
        image_size = size or model_config.get("nai_size") or model_config.get("default_size", "")

        # 显示处理信息
        enable_debug = self.get_config("components.enable_debug_info", False)
        if enable_debug:
            await self.send_text(f"收到！正在使用 NovelAI Web 生成图片，请稍候...")

        try:
            # 调用API客户端生成图片
            success, result = self.api_client.generate_image(
                prompt=description,
                model_config=model_config,
                size=image_size
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 请求执行失败: {e!r}", exc_info=True)
            traceback.print_exc()
            success = False
            result = f"图片生成服务遇到意外问题: {str(e)[:100]}"

        if success:
            final_image_data = self._process_api_response(result)

            if final_image_data:
                if final_image_data.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):  # Base64
                    temp_message_id = f"send_api_{int(time.time() * 1000)}"
                    send_time = time.time()
                    image_path = save_base64_image_to_file(final_image_data)
                    image_content = f"file://{image_path}" if image_path else None
                    if image_content:
                        send_success = await self.send_custom("imageurl", image_content)
                    else:
                        logger.warning(f"{self.log_prefix} 图片保存失败，回退为Base64发送")
                        send_success = await self.send_image(final_image_data)

                    if send_success:
                        self._last_send_timestamp = send_time
                        if enable_debug:
                            await self.send_text("图片生成完成！")
                        await self._schedule_auto_recall(temp_message_id)
                        return True, "图片已成功生成并发送"
                    else:
                        await self.send_text("图片已处理完成，但发送失败了")
                        return False, "图片发送失败"
                elif final_image_data.startswith(("http://", "https://")):
                    send_time = time.time()
                    try:
                        send_success = await self.send_custom("imageurl", final_image_data)
                        if send_success:
                            self._last_send_timestamp = send_time
                            if enable_debug:
                                await self.send_text("图片生成完成！")
                            await self._schedule_auto_recall()
                            return True, "图片已成功生成并发送"
                        await self.send_text("图片已生成，但发送失败了")
                        return False, "图片发送失败"
                    except Exception as e:
                        logger.error(f"{self.log_prefix} 图片URL发送失败: {e!r}")
                        await self.send_text("图片生成完成但发送时出错")
                        return False, "图片发送失败"
                else:
                    await self.send_text("图片生成API返回了无法处理的数据格式")
                    return False, "API返回数据格式错误"
            else:
                await self.send_text("图片生成API返回了无法处理的数据格式")
                return False, "API返回数据格式错误"
        else:
            await self.send_text(f"哎呀，生成图片时遇到问题：{result}")
            return False, f"生成失败: {result}"

    def _get_model_config(self) -> Dict[str, Any]:
        """获取模型配置，根据模型名称自动合并对应版本的配置"""
        base_config = self.get_config("model", {})
        if not base_config:
            logger.error(f"{self.log_prefix} 模型配置读取失败")
            return {}

        # 获取模型名称
        model_name = base_config.get("model", "")

        # 根据模型名称确定使用哪个版本的配置
        version_config = {}
        if model_name:
            if "nai-diffusion-3" in model_name:
                # NAI V3 模型
                version_config = self.get_config("model_nai3", {})
                logger.info(f"{self.log_prefix} 检测到 NAI V3 模型，使用 model_nai3 配置")
            elif "nai-diffusion-4-5" in model_name:
                # NAI V4.5 模型（优先级高于 V4）
                version_config = self.get_config("model_nai4_5", {})
                logger.info(f"{self.log_prefix} 检测到 NAI V4.5 模型，使用 model_nai4_5 配置")
            elif "nai-diffusion-4" in model_name:
                # NAI V4 模型
                version_config = self.get_config("model_nai4", {})
                logger.info(f"{self.log_prefix} 检测到 NAI V4 模型，使用 model_nai4 配置")

        # 合并配置：base_config 作为基础，version_config 覆盖
        merged_config = base_config.copy()
        if version_config:
            # 合并所有配置项，version_config 中的值优先
            for key, value in version_config.items():
                if key == "nai_extra_params":
                    # 特殊处理 nai_extra_params，合并而不是覆盖
                    base_extra = merged_config.get("nai_extra_params", {})
                    version_extra = value or {}
                    merged_extra = base_extra.copy()
                    merged_extra.update(version_extra)
                    merged_config["nai_extra_params"] = merged_extra
                else:
                    # 其他配置项直接覆盖
                    merged_config[key] = value

        return merged_config

    def _process_api_response(self, result: str) -> Optional[str]:
        """处理API响应，返回base64或URL"""
        if not result:
            return None

        # 如果是URL
        if result.startswith("http://") or result.startswith("https://"):
            return result

        # 如果已经是base64
        if result.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):
            return result

        # 尝试移除可能的data URI前缀
        if "," in result and result.startswith("data:image"):
            return result.split(",", 1)[1]

        return result

    def _process_selfie_prompt(self, description: str) -> str:
        """处理自拍模式的提示词，添加selfie_prompt_add配置"""
        model_config = self._get_model_config()
        selfie_prompt_add = model_config.get("selfie_prompt_add", "") if model_config else ""

        if selfie_prompt_add:
            return f"{selfie_prompt_add}, {description}"
        return description

    def _is_auto_recall_enabled(self, platform: str, chat_id: str) -> bool:
        """供自动撤回Mixin调用"""
        from .nai_recall_command import NaiRecallControlCommand
        return NaiRecallControlCommand.is_recall_enabled(platform, chat_id, self.get_config)

    def _normalize_bool(self, value: Any) -> bool:
        """将可能的配置值转为布尔类型"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            return lowered in {"true", "1", "yes", "y", "on"}
        if isinstance(value, (int, float)):
            return bool(value)
        return False

    async def _generate_prompt_with_llm(self, selfie_mode: bool, request_text: Optional[str] = None) -> Optional[str]:
        """使用LLM生成英文提示词"""
        generator_config = self._get_prompt_generator_config()

        raw_request = (request_text or "").strip()
        if not raw_request:
            raw_request = self._extract_user_request_text()
        if not raw_request:
            logger.warning(f"{self.log_prefix} 无法提取原始用户请求，提示词生成终止")
            return None

        prompt_template = generator_config.get("prompt_template") or _PROMPT_GENERATOR_TEMPLATE
        prompt = self._render_generator_prompt(prompt_template, raw_request, selfie_mode)

        model_config = self._resolve_llm_model_config(generator_config.get("model_name", ""))
        if not model_config:
            logger.error(f"{self.log_prefix} 未找到可用的LLM模型，提示词生成失败")
            return None

        temperature = generator_config.get("temperature", 0.2)
        max_tokens = generator_config.get("max_tokens", 200)

        try:
            success, response, reasoning, model_name = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="nai_pic_plugin.prompt_generator",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 调用LLM生成提示词失败: {e}", exc_info=True)
            return None

        if not success or not response:
            logger.error(
                f"{self.log_prefix} 提示词生成失败，模型={model_name or 'unknown'}，响应={response or '无'}"
            )
            return None

        cleaned = self._cleanup_llm_prompt(response)
        return cleaned if cleaned else None

    def _extract_user_request_text(self) -> str:
        """尝试从当前消息与reasoning中提取用户描述"""
        candidates = []

        if self.action_message:
            for attr in ("processed_plain_text", "display_message"):
                value = getattr(self.action_message, attr, None)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())

        for extra in (
            getattr(self, "reasoning", "") or "",
            self.action_reasoning or "",
            self.action_data.get("reason", ""),
        ):
            if isinstance(extra, str) and extra.strip():
                candidates.append(extra.strip())

        return candidates[0] if candidates else ""

    def _render_generator_prompt(self, template: str, original_request: str, selfie_mode: bool) -> str:
        """将占位符替换为实际内容"""
        selfie_hint = ""
        if selfie_mode:
            selfie_hint = (
                "\n\n【自拍模式】请确保提示词体现前置相机、近距离取景等自拍视角，同时严格遵守上述规则。"
            )

        prompt = template.replace("<<SELFIE_HINT>>", selfie_hint).strip()
        prompt = prompt.replace("<<USER_REQUEST>>", original_request.strip() or "N/A")
        return prompt

    def _resolve_llm_model_config(self, preferred_name: str):
        """根据配置选择可用LLM模型"""
        models = llm_api.get_available_models()
        if not models:
            return None

        candidate_names = []
        if preferred_name:
            candidate_names.append(preferred_name)
        candidate_names.extend(["planner", "replyer"])

        for name in candidate_names:
            config = models.get(name)
            if config:
                if name == preferred_name:
                    logger.info(f"{self.log_prefix} 提示词生成使用自定义模型: {name}")
                else:
                    logger.info(f"{self.log_prefix} 提示词生成使用默认模型: {name}")
                return config

        fallback_name, fallback_config = next(iter(models.items()))
        logger.info(f"{self.log_prefix} 提示词生成使用系统模型: {fallback_name}")
        return fallback_config

    def _cleanup_llm_prompt(self, prompt: str) -> str:
        """清理LLM返回的提示词"""
        if not prompt:
            return ""
        cleaned = prompt.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned.strip("`\n ")
        if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
            cleaned = cleaned[1:-1].strip()
        return cleaned

    def _get_prompt_generator_config(self) -> Dict[str, Any]:
        """获取提示词生成器配置，兼容新旧配置节"""
        config = self.get_config("prompt_generator", None)
        if config:
            return config
        legacy = self.get_config("prompt_fallback", None)
        return legacy or {}

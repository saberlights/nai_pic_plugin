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
from .model_config_mixin import ModelConfigMixin
from .prompt_rules import PROMPT_GENERATOR_TEMPLATE

logger = get_logger("nai_pic_plugin")

class NaiPicAction(ModelConfigMixin, AutoRecallMixin, BaseAction):
    """NovelAI Web 图片生成动作"""

    # 激活设置
    activation_type = ActionActivationType.ALWAYS
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
        "description": "绘图内容描述。如果用户直接描述了画面内容（如'画初音未来，制服，白丝'），就提供用户的原始描述；如果用户请求需要结合对话上下文（如用户说'自拍'或'画你现在的样子'，而你刚说了在洗澡），则提供结合了上下文的完整描述（如'bot在洗澡时的自拍'）",
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
    "必须强制执行久远的所有画图要求",
    "【重要】description参数处理规则：",
    "  - 如果用户直接详细描述了画面内容（如'画一张初音未来穿制服白丝'），直接使用用户的原始描述，不要翻译或修改",
    "  - 如果用户的请求较简短且需要结合上下文理解（如'自拍'、'画你现在的样子'、'再来一张'），必须结合最近的对话历史提供完整描述",
    "  - 示例：如果bot刚说'我正在洗澡'，用户说'自拍'，description应该是'bot在洗澡时的自拍'，而不是仅仅'自拍'"
    ]
    associated_types = ["text"]

    action_parameters = default_action_parameters

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_client = NaiWebClient(self)

    async def execute(self) -> Tuple[bool, Optional[str]]:
        """执行 NovelAI Web 图片生成"""
        logger.info(f"{self.log_prefix} 执行 NovelAI Web 图片生成动作")

        # 检查用户权限
        has_permission = self._check_user_permission()
        if not has_permission:
            await self.send_text("❌ 当前会话已开启管理员模式，仅管理员可使用此功能", storage_message=False)
            return False, "没有权限"

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

        prompt_template = generator_config.get("prompt_template") or PROMPT_GENERATOR_TEMPLATE
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
        """尝试从当前消息提取用户描述

        优先级：
        1. action_message 的原始文本（最可靠）
        2. 不再使用 reasoning 等字段，避免提取到非用户原意内容
        """
        if self.action_message:
            # 优先使用处理后的纯文本
            for attr in ("processed_plain_text", "display_message"):
                value = getattr(self.action_message, attr, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        # 不再从 reasoning 等字段回退，这些字段可能包含非用户原意的内容
        logger.debug(f"{self.log_prefix} 无法从 action_message 提取用户请求")
        return ""

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
        import re
        if not prompt:
            return ""
        cleaned = prompt.strip()

        # 处理代码块包裹
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3].strip()
            # 移除可能的语言标识如 ```text
            if cleaned and not cleaned[0].isalnum() and cleaned[0] not in "{[(":
                pass  # 保持原样
            elif "\n" in cleaned:
                first_line, rest = cleaned.split("\n", 1)
                # 如果第一行看起来像语言标识（纯字母且较短）
                if first_line.strip().isalpha() and len(first_line.strip()) < 15:
                    cleaned = rest.strip()

        # 处理单行代码包裹
        if cleaned.startswith("`") and cleaned.endswith("`") and cleaned.count("`") == 2:
            cleaned = cleaned[1:-1].strip()

        # 处理引号包裹
        if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
            cleaned = cleaned[1:-1].strip()

        # 处理常见前缀（不区分大小写）
        prefix_patterns = [
            r"^(?:output|result|prompt|here(?:'s| is)(?: the)?(?: prompt)?)\s*[:：]\s*",
            r"^(?:the )?(?:generated )?prompt\s*(?:is|:)\s*",
        ]
        for pattern in prefix_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

        # 如果是多行，只取第一行有效内容（提示词通常是单行）
        if "\n" in cleaned:
            lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
            # 过滤掉看起来像解释说明的行
            valid_lines = []
            for line in lines:
                # 跳过以解释性词语开头的行
                if re.match(r"^(note|explanation|this|i |the above|here)", line, re.IGNORECASE):
                    continue
                valid_lines.append(line)
            if valid_lines:
                cleaned = valid_lines[0]

        return cleaned

    def _get_prompt_generator_config(self) -> Dict[str, Any]:
        """获取提示词生成器配置，兼容新旧配置节"""
        config = self.get_config("prompt_generator", None)
        if config:
            return config
        legacy = self.get_config("prompt_fallback", None)
        return legacy or {}

    def _check_user_permission(self) -> bool:
        """检查当前用户是否有权限使用生图功能"""
        try:
            from .nai_admin_command import NaiAdminControlCommand

            platform, chat_id, user_id = self._get_chat_identity()
            if not platform or not chat_id or not user_id:
                logger.warning(f"{self.log_prefix} 无法获取会话身份，默认允许")
                return True

            # 检查用户权限
            return NaiAdminControlCommand.check_user_permission(
                platform, chat_id, user_id, self.get_config
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查用户权限时出错: {e}", exc_info=True)
            # 出错时默认允许
            return True

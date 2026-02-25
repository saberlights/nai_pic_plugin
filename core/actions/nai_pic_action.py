# -*- coding: utf-8 -*-
import traceback
import time
from typing import Tuple, Optional, Dict, Any

from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.component_types import ActionActivationType, ChatMode
from src.common.logger import get_logger
from src.plugin_system import llm_api
from src.plugin_system.apis import send_api

from ..clients.nai_web_client import NaiWebClient
from ..mixins.auto_recall_mixin import AutoRecallMixin
from ..constants import NAI_PIC_IMAGE_DISPLAY_MARKER
from ..utils.image_url_helper import save_base64_image_to_file
from ..mixins.model_config_mixin import ModelConfigMixin
from ..rules.prompt_rules import PROMPT_GENERATOR_TEMPLATE, SFW_PROMPT_GENERATOR_TEMPLATE
from ..rules.selfie_rules import (
    detect_selfie_from_output,
    get_selfie_hint,
    merge_selfie_prompt,
)
from ..services.session_state import session_state
from ..services.prompt_memory import (
    render_previous_prompt_block,
    load_last_prompt_from_action_records,
    LAST_PROMPT_RECORD_PREFIX,
)
from ..utils.prompt_output_parser import parse_prompt_from_structured_output
from ..utils.prompt_postprocessor import (
    normalize_prompt_order,
    remove_selfie_appearance_tags,
    user_mentions_appearance,
)

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
        logger.info(f"{self.log_prefix} [LLM触发] 执行 /nai 动作")

        # 检查用户权限
        has_permission = self._check_user_permission()
        if not has_permission:
            return False, "没有权限"

        # 获取参数
        description = (self.action_data.get("description") or "").strip()
        raw_description = description
        size = (self.action_data.get("size") or "").strip()

        # 始终使用LLM生成提示词（自拍意图由 LLM 自行判断）
        generated_prompt = await self._generate_prompt_with_llm(description)
        if generated_prompt:
            description = generated_prompt.strip()
            logger.debug(f"{self.log_prefix} [LLM触发] 原始提示词: {description}")
        elif description:
            logger.info(f"{self.log_prefix} [LLM触发] 使用Planner提供的提示词（LLM提示词生成被禁用或失败）")
        else:
            logger.warning(f"{self.log_prefix} [LLM触发] 无法生成提示词，描述为空")
            await self.send_text("提示词生成器开小差了，请直接告诉我想画什么，或者稍后再试一次~")
            return False, "图片描述为空"

        # 从 LLM 输出检测是否为自拍（LLM 自行判定后会在输出中包含 selfie 标签）
        is_selfie = detect_selfie_from_output(description)

        # 处理自拍模式（添加角色特征）
        selfie_base_prompt = description
        if is_selfie:
            # 实际生图提示词（可能包含配置文件中的自拍补充提示词）
            description = self._process_selfie_prompt(
                selfie_base_prompt,
                raw_description,
                include_selfie_prompt_add=True,
                log_changes=True,
            )
            logger.debug(f"{self.log_prefix} [LLM触发] 自拍模式已启用")

        # 轻量排序（可配置关闭）
        if self.get_config("prompt_generator.enforce_tag_order", False):
            description = normalize_prompt_order(description)

        logger.info(f"{self.log_prefix} [LLM触发] 最终提示词: {description}")

        # 检查是否需要显示提示词（展示最终提示词，避免与实际生图不一致）
        if self._is_prompt_show_enabled():
            show_prompt = description
            header = "📝 提示词:"
            if is_selfie and self.get_config("prompt_show.hide_selfie_prompt_add", False):
                show_prompt = self._process_selfie_prompt(
                    selfie_base_prompt,
                    raw_description,
                    include_selfie_prompt_add=False,
                    log_changes=False,
                )
                header = "📝 提示词(已隐藏自拍补充):"
            await self.send_text(f"{header}\n{show_prompt}", storage_message=False)

        # 不再默认截断提示词：多人 | 分段与权重语法很容易被截断破坏

        # 获取模型配置
        model_config = self._get_model_config()
        if not model_config:
            error_msg = "抱歉，NovelAI Web 图片生成功能配置无效，无法提供服务。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} [LLM触发] 模型配置获取失败")
            return False, "模型配置无效"

        # 配置验证
        if not model_config.get("base_url"):
            error_msg = "抱歉，NovelAI Web API 地址未配置，无法提供服务。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} [LLM触发] base_url 未配置")
            return False, "base_url 未配置"

        # 获取尺寸配置
        image_size = size or model_config.get("nai_size") or model_config.get("default_size", "")

        # 显示处理信息
        enable_debug = self.get_config("components.enable_debug_info", False)
        if enable_debug:
            await self.send_text(f"收到！正在使用 NovelAI Web 生成图片，请稍候...")

        try:
            # 调用API客户端生成图片（异步，不阻塞事件循环）
            success, result = await self.api_client.generate_image(
                prompt=description,
                model_config=model_config,
                size=image_size
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [LLM触发] 请求执行失败: {e!r}", exc_info=True)
            traceback.print_exc()
            success = False
            result = f"图片生成服务遇到意外问题: {str(e)[:100]}"

        if success:
            final_image_data = self._process_api_response(result)

            if final_image_data:
                if final_image_data.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):  # Base64
                    send_time = time.time()
                    image_path = save_base64_image_to_file(final_image_data)
                    image_content = f"file://{image_path}" if image_path else None
                    if image_content:
                        send_success = await send_api.custom_to_stream(
                            message_type="imageurl",
                            content=image_content,
                            stream_id=self.chat_id,
                            display_message=NAI_PIC_IMAGE_DISPLAY_MARKER,
                        )
                    else:
                        logger.warning(f"{self.log_prefix} [LLM触发] 图片保存失败，回退为Base64发送")
                        send_success = await send_api.custom_to_stream(
                            message_type="image",
                            content=final_image_data,
                            stream_id=self.chat_id,
                            display_message=NAI_PIC_IMAGE_DISPLAY_MARKER,
                        )

                    if send_success:
                        self._last_send_timestamp = send_time
                        if enable_debug:
                            await self.send_text("图片生成完成！")
                        await self._schedule_auto_recall()
                        return True, "图片已成功生成并发送"
                    else:
                        await self.send_text("图片已处理完成，但发送失败了")
                        return False, "图片发送失败"
                elif final_image_data.startswith(("http://", "https://")):
                    send_time = time.time()
                    try:
                        send_success = await send_api.custom_to_stream(
                            message_type="imageurl",
                            content=final_image_data,
                            stream_id=self.chat_id,
                            display_message=NAI_PIC_IMAGE_DISPLAY_MARKER,
                        )
                        if send_success:
                            self._last_send_timestamp = send_time
                            if enable_debug:
                                await self.send_text("图片生成完成！")
                            await self._schedule_auto_recall()
                            return True, "图片已成功生成并发送"
                        await self.send_text("图片已生成，但发送失败了")
                        return False, "图片发送失败"
                    except Exception as e:
                        logger.error(f"{self.log_prefix} [LLM触发] 图片URL发送失败: {e!r}")
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

    def _process_selfie_prompt(
        self,
        description: str,
        raw_request: str = "",
        include_selfie_prompt_add: bool = True,
        log_changes: bool = True,
    ) -> str:
        """处理自拍模式的提示词：可选移除随机外貌 + （可选）合并配置中的自拍特征"""
        model_config = self._get_model_config()
        selfie_prompt_add = model_config.get("selfie_prompt_add", "") if model_config else ""

        policy = (self.get_config("prompt_generator.selfie_appearance_policy", "auto") or "auto").strip().lower()
        user_specified = user_mentions_appearance(raw_request)

        original = description

        # auto: 合并前先移除 LLM 随机外貌（保留配置中的自拍特征）
        if policy in {"auto", "never"} and not user_specified and policy == "auto":
            description = remove_selfie_appearance_tags(description)

        if include_selfie_prompt_add and selfie_prompt_add:
            description = merge_selfie_prompt(description, selfie_prompt_add)

        # never: 合并后再移除一次（连配置外貌也移除），但用户明确指定时不移除
        if policy in {"auto", "never"} and not user_specified and policy == "never":
            description = remove_selfie_appearance_tags(description)

        if log_changes and description != original:
            logger.debug(f"{self.log_prefix} [LLM触发] 自拍提示词后处理已生效：policy={policy}, user_specified={user_specified}")

        return description

    def _is_auto_recall_enabled(self, platform: str, chat_id: str) -> bool:
        """供自动撤回Mixin调用"""
        return session_state.is_recall_enabled(platform, chat_id, self.get_config)

    def _is_prompt_show_enabled(self) -> bool:
        """检查是否启用提示词显示"""
        try:
            platform, chat_id, _ = self._get_chat_identity()
            if not platform or not chat_id:
                return False

            return session_state.is_prompt_show_enabled(platform, chat_id, self.get_config)
        except Exception as e:
            logger.error(f"{self.log_prefix} [LLM触发] 检查提示词显示状态时出错: {e}")
            return False

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

    async def _generate_prompt_with_llm(
        self,
        request_text: Optional[str] = None
    ) -> Optional[str]:
        """使用LLM生成英文提示词（自拍意图由 LLM 自行判断）"""
        generator_config = self._get_prompt_generator_config()

        raw_request = (request_text or "").strip()
        if not raw_request:
            raw_request = self._extract_user_request_text()
        if not raw_request:
            logger.warning(f"{self.log_prefix} [LLM触发] 无法提取原始用户请求，提示词生成终止")
            return None

        # 加载上一轮提示词（全群共享：按 chat_stream.stream_id 存取）
        chat_stream_id = getattr(self, "chat_id", "") or ""
        last_prompt = session_state.get_last_nai_prompt(chat_stream_id)
        if not last_prompt and chat_stream_id:
            last_prompt = load_last_prompt_from_action_records(chat_stream_id, self.action_name)
            if last_prompt:
                session_state.set_last_nai_prompt(chat_stream_id, last_prompt)

        # 检查是否启用 NSFW 过滤，选择对应模板
        try:
            platform, chat_id, _ = self._get_chat_identity()
            nsfw_filter_enabled = False
            if platform and chat_id:
                nsfw_filter_enabled = session_state.is_nsfw_filter_enabled(platform, chat_id, self.get_config)
        except Exception:
            nsfw_filter_enabled = False

        # 根据过滤状态与输出格式选择模板
        output_format = (generator_config.get("output_format") or "text").strip().lower()
        if nsfw_filter_enabled:
            if output_format == "json":
                from ..rules.prompt_rules import SFW_PROMPT_GENERATOR_JSON_TEMPLATE
                default_template = SFW_PROMPT_GENERATOR_JSON_TEMPLATE
            else:
                default_template = SFW_PROMPT_GENERATOR_TEMPLATE
        else:
            if output_format == "json":
                from ..rules.prompt_rules import PROMPT_GENERATOR_JSON_TEMPLATE
                default_template = PROMPT_GENERATOR_JSON_TEMPLATE
            else:
                default_template = PROMPT_GENERATOR_TEMPLATE

        prompt_template = generator_config.get("prompt_template") or default_template
        prompt = self._render_generator_prompt(prompt_template, raw_request, last_prompt)

        model_config = self._resolve_llm_model_config(generator_config.get("model_name", ""))
        if not model_config:
            logger.error(f"{self.log_prefix} [LLM触发] 未找到可用的LLM模型，提示词生成失败")
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
            logger.error(f"{self.log_prefix} [LLM触发] 调用LLM生成提示词失败: {e}", exc_info=True)
            return None

        if not success or not response:
            logger.error(
                f"{self.log_prefix} [LLM触发] 提示词生成失败，模型={model_name or 'unknown'}，响应={response or '无'}"
            )
            return None

        cleaned = self._cleanup_llm_prompt(response)
        if not cleaned:
            return None

        # 写入本轮 LLM 生成的提示词（内存 + 持久化）
        if chat_stream_id:
            session_state.set_last_nai_prompt(chat_stream_id, cleaned)
            await self._persist_last_prompt_record(cleaned)

        return cleaned

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
        logger.debug(f"{self.log_prefix} [LLM触发] 无法从 action_message 提取用户请求")
        return ""

    def _render_generator_prompt(
        self,
        template: str,
        original_request: str,
        last_prompt: Optional[str] = None,
    ) -> str:
        """将占位符替换为实际内容"""
        # 自定义系统提示词
        custom_system_prompt = self.get_config("custom_prompt.system_prompt", "") or ""
        if custom_system_prompt:
            custom_system_prompt = custom_system_prompt.strip() + "\n\n"

        # 永远注入自拍提示，由 LLM 自行判断是否为自拍意图
        selfie_hint = get_selfie_hint()

        # 上一轮提示词 block
        previous_block = render_previous_prompt_block(last_prompt)

        prompt = template.replace("<<CUSTOM_SYSTEM_PROMPT>>", custom_system_prompt).strip()
        prompt = prompt.replace("<<PREVIOUS_PROMPT>>", previous_block).strip()
        prompt = prompt.replace("<<SELFIE_HINT>>", selfie_hint).strip()
        prompt = prompt.replace("<<USER_REQUEST>>", original_request.strip() or "N/A")
        return prompt

    async def _persist_last_prompt_record(self, prompt: str) -> None:
        """将上一轮提示词写入 ActionRecords，便于重启后恢复。"""
        text = (prompt or "").strip()
        if not text:
            return
        try:
            await self.store_action_info(
                action_build_into_prompt=False,
                action_prompt_display=f"{LAST_PROMPT_RECORD_PREFIX}\n{text}",
                action_done=True,
            )
        except Exception as e:
            logger.debug(f"{self.log_prefix} [LLM触发] last_prompt 持久化失败: {e}")

    def _resolve_llm_model_config(self, preferred_name: str):
        """根据配置选择可用LLM模型"""
        # 首先检查是否有自定义模型配置
        generator_config = self._get_prompt_generator_config()
        custom_model = generator_config.get("custom_model")

        if custom_model and isinstance(custom_model, dict):
            model_list = custom_model.get("model_list", [])
            if model_list:
                # 使用自定义模型配置创建 TaskConfig
                from src.config.api_ada_configs import TaskConfig
                try:
                    custom_task_config = TaskConfig(
                        model_list=model_list if isinstance(model_list, list) else [model_list],
                        max_tokens=custom_model.get("max_tokens", 1024),
                        temperature=custom_model.get("temperature", 0.3),
                        slow_threshold=custom_model.get("slow_threshold", 30.0),
                        selection_strategy="random"  # 固定使用随机选择
                    )
                    logger.info(f"{self.log_prefix} [LLM触发] 提示词生成使用自定义模型配置: {model_list}")
                    return custom_task_config
                except Exception as e:
                    logger.warning(f"{self.log_prefix} [LLM触发] 自定义模型配置创建失败: {e}，回退到系统模型")

        # 回退到系统模型
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
                    logger.info(f"{self.log_prefix} [LLM触发] 提示词生成使用自定义模型: {name}")
                else:
                    logger.info(f"{self.log_prefix} [LLM触发] 提示词生成使用默认模型: {name}")
                return config

        fallback_name, fallback_config = next(iter(models.items()))
        logger.info(f"{self.log_prefix} [LLM触发] 提示词生成使用系统模型: {fallback_name}")
        return fallback_config

    def _cleanup_llm_prompt(self, prompt: str) -> str:
        """清理LLM返回的提示词"""
        import re
        if not prompt:
            return ""

        parsed = parse_prompt_from_structured_output(prompt)
        if parsed:
            logger.debug(f"{self.log_prefix} [LLM触发] 结构化提示词解析命中（JSON->prompt），将跳过文本清洗")
            return parsed

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

        # 处理多行内容
        if "\n" in cleaned:
            lines = [line.strip() for line in cleaned.split("\n") if line.strip()]

            # 检测是否为多人场景分段格式（包含 | 分隔符）
            has_multi_person_format = any(line.startswith("|") for line in lines)

            if has_multi_person_format:
                # 多人场景：保留所有有效行，用换行符连接
                valid_lines = []
                for line in lines:
                    # 跳过以解释性词语开头的行
                    if re.match(r"^(note|explanation|this|i |the above|here)", line, re.IGNORECASE):
                        continue
                    valid_lines.append(line)
                if valid_lines:
                    cleaned = "\n".join(valid_lines)
            else:
                # 单人场景：只取第一行有效内容
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
        """获取提示词生成器配置"""
        return self.get_config("prompt_generator", None) or {}

    def _check_user_permission(self) -> bool:
        """检查当前用户是否有权限使用生图功能"""
        try:
            platform, chat_id, user_id = self._get_chat_identity()
            if not platform or not chat_id or not user_id:
                logger.warning(f"{self.log_prefix} [LLM触发] 无法获取会话身份，默认允许")
                return True

            # 检查用户权限
            return session_state.check_user_permission(
                platform, chat_id, user_id, self.get_config
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [LLM触发] 检查用户权限时出错: {e}", exc_info=True)
            # 出错时默认允许
            return True

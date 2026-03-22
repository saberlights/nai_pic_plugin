# -*- coding: utf-8 -*-
import re
import traceback
import time
from datetime import datetime
from typing import Tuple, Optional, Dict, Any, List

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
    detect_selfie_mode,
    get_selfie_hint,
    merge_selfie_prompt,
)
from ..services.session_state import session_state
from ..services.tag_retriever import get_tag_retriever
from ..services.prompt_memory import (
    render_previous_prompt_block,
    load_last_context_from_action_records,
    LAST_PROMPT_RECORD_PREFIX,
    _REQ_LINE_PREFIX,
    _REQ_SEPARATOR,
)
from ..utils.prompt_output_parser import (
    parse_prompt_from_structured_output,
    parse_structured_prompt_payload,
)
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
        "生成图片、自拍、照片。"
        "用于画图、自拍、拍照、发照片等一切需要生成图像的场景。"
    )

    # 动作参数定义
    default_action_parameters = {
        "description": (
            "画面内容的关键词列表，用空格分隔，只输出有视觉意义的核心词。"
            "例如：用户说'穿着黑丝制服在卧室被大叔后入'→'黑丝 制服 卧室 大叔 后入'；"
            "用户说'初音未来穿泳装在海边'→'初音未来 泳装 海边'；"
            "用户请求依赖上下文时（如'自拍'、'再来一张'），"
            "结合对话上下文补全关键词（如你刚说在洗澡→'浴室 洗澡 自拍'）；"
            "当用户想看你的样子（如'看看黑丝'），加上'自拍'关键词（如'黑丝 自拍'）。"
            "禁止输出完整句子，禁止输出'正在'、'非常'、'一个'等虚词"
        ),
        "size": "图片尺寸（默认从配置获取）",
    }

    # 动作使用场景（触发条件）
    action_require = [
        "满足以下任一条件时触发：",
        "1. 用户要求画图、生成图片、创作图像",
        "2. 用户要求自拍、拍照、发照片、发图，或明显是在向你索要一张图（如'自拍一张'、'发张照片'、'拍给我看'）",
        "3. 用户在延续绘图话题（如'再来一张'、'换个姿势'、'重新画'）",
        "4. 当前对话的重心已经明显变成想看你的样子、穿搭、状态或某个视觉重点，这时发图比继续文字描述更自然",
        "不触发的情况：无关的知识问答、技术讨论、只是提到'图片'但不是要求生成、普通暧昧聊天、口嗨、夸赞、试探或玩笑，但还没有明显进入'想看画面'的阶段",
        "非用户主动要求重画时，不要重复生成相同内容",
    ]
    associated_types = ["text"]

    action_parameters = default_action_parameters

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_client = NaiWebClient(self)
        self._last_structured_prompt_payload: Optional[Dict[str, Any]] = None

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

        structured_payload = self._last_structured_prompt_payload or {}
        structured_intent = str(structured_payload.get("intent", "") or "").strip().lower()
        is_selfie = structured_intent == "selfie" or detect_selfie_from_output(description)

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
            anchor_data = self._extract_selfie_anchor_data(description)
            scene_summary = self._format_selfie_anchor_summary(anchor_data)
            if self.chat_id:
                session_state.set_last_selfie_context(
                    self.chat_id,
                    description,
                    raw_description,
                    scene_summary,
                    anchor_data,
                )

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
        inherit_ttl = float(self.get_config("prompt_generator.inherit_ttl", 0) or 0)
        last_prompt, last_request = session_state.get_last_nai_context(
            chat_stream_id, ttl=inherit_ttl
        )
        last_selfie_prompt, last_selfie_request, last_selfie_scene, last_selfie_anchor = session_state.get_last_selfie_context(
            chat_stream_id, ttl=inherit_ttl
        )
        if not last_prompt and chat_stream_id:
            last_prompt, last_request = load_last_context_from_action_records(
                chat_stream_id, self.action_name, ttl=inherit_ttl
            )
            if last_prompt:
                session_state.set_last_nai_context(
                    chat_stream_id, last_prompt, last_request or ""
                )
                if detect_selfie_from_output(last_prompt):
                    last_selfie_anchor = self._extract_selfie_anchor_data(last_prompt)
                    last_selfie_scene = self._format_selfie_anchor_summary(last_selfie_anchor)
                    session_state.set_last_selfie_context(
                        chat_stream_id,
                        last_prompt,
                        last_request or "",
                        last_selfie_scene,
                        last_selfie_anchor,
                    )
                    last_selfie_prompt = last_prompt
                    last_selfie_request = last_request

        # 检查是否启用 NSFW 过滤，选择对应模板
        try:
            platform, chat_id, _ = self._get_chat_identity()
            nsfw_filter_enabled = False
            if platform and chat_id:
                nsfw_filter_enabled = session_state.is_nsfw_filter_enabled(platform, chat_id, self.get_config)
        except Exception:
            nsfw_filter_enabled = False

        # 根据过滤状态与输出格式选择模板
        output_format = (generator_config.get("output_format") or "json").strip().lower()
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
        prompt = self._render_generator_prompt(
            prompt_template,
            raw_request,
            last_prompt,
            last_request,
            last_selfie_prompt=last_selfie_prompt,
            last_selfie_request=last_selfie_request,
            last_selfie_scene=last_selfie_scene,
            last_selfie_anchor=last_selfie_anchor,
        )

        # Tag 检索增强
        tag_candidates_text = await self._retrieve_tag_candidates(raw_request)
        prompt = prompt.replace("<<TAG_CANDIDATES>>", tag_candidates_text).strip()

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
            session_state.set_last_nai_context(chat_stream_id, cleaned, raw_request)
            await self._persist_last_prompt_record(cleaned, raw_request)

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
        last_request: Optional[str] = None,
        last_selfie_prompt: Optional[str] = None,
        last_selfie_request: Optional[str] = None,
        last_selfie_scene: Optional[str] = None,
        last_selfie_anchor: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """将占位符替换为实际内容"""
        # 自定义系统提示词
        custom_system_prompt = self.get_config("custom_prompt.system_prompt", "") or ""
        if custom_system_prompt:
            custom_system_prompt = custom_system_prompt.strip() + "\n\n"

        # 永远注入自拍提示，由 LLM 自行判断是否为自拍意图
        selfie_hint = get_selfie_hint()
        current_time_context = self._build_current_time_context()
        selfie_scene_context = self._build_selfie_scene_context(
            original_request,
            last_selfie_prompt=last_selfie_prompt,
            last_selfie_request=last_selfie_request,
            last_selfie_scene=last_selfie_scene,
            last_selfie_anchor=last_selfie_anchor,
        )

        # 上一轮提示词 block
        previous_block = render_previous_prompt_block(last_prompt, last_request)

        prompt = template.replace("<<CUSTOM_SYSTEM_PROMPT>>", custom_system_prompt).strip()
        prompt = prompt.replace("<<PREVIOUS_PROMPT>>", previous_block).strip()
        prompt = prompt.replace("<<USER_REQUEST>>", original_request.strip() or "N/A")
        prompt = prompt.replace("<<CURRENT_TIME_CONTEXT>>", current_time_context).strip()
        prompt = prompt.replace("<<SELFIE_HINT>>", selfie_hint).strip()
        prompt = prompt.replace("<<SELFIE_SCENE_CONTEXT>>", selfie_scene_context).strip()
        return prompt

    async def _retrieve_tag_candidates(self, request_text: str) -> str:
        """检索候选 danbooru tag"""
        try:
            retriever_config = self.get_config("tag_retriever", None) or {}
            if not retriever_config.get("enabled", False):
                return ""
            retriever = get_tag_retriever(
                enabled=True,
                top_k=retriever_config.get("top_k", 20),
                min_score=retriever_config.get("min_score", 0.3),
            )
            if not retriever:
                return ""
            results = await retriever.retrieve(
                query=request_text,
                top_k=retriever_config.get("top_k", 20),
                min_score=retriever_config.get("min_score", 0.3),
            )
            if results:
                tag_list = ", ".join(f"{r['cn']}→{r['tag']}({r['score']})" for r in results)
                logger.info(f"{self.log_prefix} Tag 检索增强：找到 {len(results)} 个候选 tag: {tag_list}")
                return retriever.format_candidates(results)
        except Exception as e:
            logger.warning(f"{self.log_prefix} Tag 检索失败，跳过: {e}")
        return ""

    def _build_current_time_context(self) -> str:
        """构建当前时间段提示，帮助 LLM 在未指定时补全光线与时间氛围。"""
        now = datetime.now()
        hour = now.hour

        if 5 <= hour < 8:
            period = "清晨"
            lighting_hint = "如果用户未明确指定时间或光线，优先考虑 dawn, early morning, sunrise, soft morning light。"
        elif 8 <= hour < 11:
            period = "上午"
            lighting_hint = "如果用户未明确指定时间或光线，优先考虑 morning, daylight, bright natural light。"
        elif 11 <= hour < 14:
            period = "中午"
            lighting_hint = "如果用户未明确指定时间或光线，优先考虑 noon, midday, bright sunlight。"
        elif 14 <= hour < 17:
            period = "下午"
            lighting_hint = "如果用户未明确指定时间或光线，优先考虑 afternoon, warm daylight, sunlit。"
        elif 17 <= hour < 19:
            period = "傍晚"
            lighting_hint = "如果用户未明确指定时间或光线，优先考虑 dusk, sunset, golden hour, evening glow。"
        elif 19 <= hour < 23:
            period = "夜晚"
            lighting_hint = "如果用户未明确指定时间或光线，优先考虑 night, moonlight, night sky, city lights, warm indoor light。"
        else:
            period = "深夜"
            lighting_hint = "如果用户未明确指定时间或光线，优先考虑 late night, midnight, moonlight, dim light, warm indoor light。"

        return (
            "<current_time_context>\n"
            f"当前本地时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（{period}）。\n"
            "这条信息只用于在用户未指定时补全时间、背景光线与氛围，不是硬性主题。\n"
            "如果用户明确指定了白天、夜晚、清晨、黄昏、室内灯光、天气或其他时间氛围，以用户要求为准。\n"
            f"{lighting_hint}\n"
            "</current_time_context>"
        )

    def _build_selfie_scene_context(
        self,
        original_request: str,
        last_selfie_prompt: Optional[str] = None,
        last_selfie_request: Optional[str] = None,
        last_selfie_scene: Optional[str] = None,
        last_selfie_anchor: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """为自拍/展示照请求构建连续性提示，尽量把判断交给 LLM。"""
        request_text = (original_request or "").strip()
        prompt_text = (last_selfie_prompt or "").strip()
        if not self._is_likely_selfie_request(request_text, prompt_text):
            return ""

        anchor_data = dict(last_selfie_anchor or {})
        scene_summary = (last_selfie_scene or "").strip()
        if not anchor_data and prompt_text:
            anchor_data = self._extract_selfie_anchor_data(prompt_text)
        if not scene_summary and anchor_data:
            scene_summary = self._format_selfie_anchor_summary(anchor_data)

        lines = [
            "<selfie_scene_context>",
            "这轮请求很可能属于 bot 本人自拍/展示照 的连续发图。",
            "若用户没有明确要求切换场景、换穿搭或改光线，默认延续上一轮的背景、穿搭、时间氛围与构图重点。",
            "如果用户明确指定了本轮想看的重点（如黑丝、鞋子、腿部、全身穿搭、背景），优先保留该重点，并选择能看清它的构图。",
        ]
        if last_selfie_request:
            lines.append(f"上一轮用户请求：{last_selfie_request.strip()}")
        if scene_summary:
            lines.append("上一轮自拍锚点：")
            lines.append(scene_summary)
        if prompt_text:
            lines.append(f"上一轮自拍提示词：{prompt_text}")
        lines.append("</selfie_scene_context>")
        return "\n".join(lines)

    def _is_likely_selfie_request(self, request_text: str, last_selfie_prompt: str = "") -> bool:
        """粗略判断当前请求是否属于自拍/展示照连续请求。"""
        text = (request_text or "").strip()
        if not text:
            return False
        if detect_selfie_mode(text):
            return True

        direct_phrases = [
            "看看你", "看你", "发张照片", "发张图", "拍给我看", "给我看", "来张照片", "来张图",
            "你穿", "你的腿", "你的脚", "你的照片", "你今天穿了什么", "看看黑丝", "看看白丝",
        ]
        if any(phrase in text for phrase in direct_phrases):
            return True

        if last_selfie_prompt and detect_selfie_from_output(last_selfie_prompt):
            continuation_patterns = [
                r"再来一张", r"再来个", r"继续", r"换个姿势", r"换个角度", r"来点不一样",
                r"还是.*", r"再拍", r"另一张", r"来一张", r"再发一张", r"换成.+", r"改成.+",
                r"换背景", r"换场景", r"换地方", r"同一个场景", r"同样背景", r"这身", r"这套",
            ]
            return any(re.search(pattern, text) for pattern in continuation_patterns)

        return False

    def _extract_selfie_anchor_data(self, prompt: str) -> Dict[str, List[str]]:
        """从自拍提示词中提取结构化锚点，供下一轮 LLM 参考。"""
        if not prompt or not detect_selfie_from_output(prompt):
            return {}

        normalized_tags = self._normalize_prompt_tags(prompt)

        def pick_labels(label_map: List[Tuple[str, str]], limit: int = 3) -> List[str]:
            selected: List[str] = []
            for keyword, label in label_map:
                if any(keyword in tag for tag in normalized_tags):
                    if label not in selected:
                        selected.append(label)
                if len(selected) >= limit:
                    break
            return selected

        anchor_data: Dict[str, List[str]] = {}
        mapping = {
            "scene_type": pick_labels([
                ("mirror selfie", "镜子自拍"),
                ("group selfie", "合照自拍"),
                ("from above", "高角度自拍"),
                ("from below", "低角度自拍"),
                ("selfie", "前置自拍"),
            ], limit=1),
            "location": pick_labels([
                ("bedroom", "卧室"),
                ("bathroom", "浴室"),
                ("dressing room", "更衣镜前"),
                ("living room", "客厅"),
                ("window", "窗边"),
                ("balcony", "阳台"),
                ("bed", "床边"),
                ("couch", "沙发边"),
                ("desk", "书桌边"),
                ("outdoors", "户外"),
                ("street", "街景"),
                ("city", "城市夜景"),
                ("cafe", "咖啡店"),
                ("park", "公园"),
                ("mirror", "镜前"),
            ]),
            "outfit": pick_labels([
                ("school uniform", "制服"),
                ("serafuku", "水手服"),
                ("blazer", "西装外套"),
                ("pleated skirt", "百褶裙"),
                ("dress", "连衣裙"),
                ("hoodie", "卫衣"),
                ("sweater", "毛衣"),
                ("cardigan", "开衫"),
                ("coat", "外套"),
                ("jacket", "夹克"),
                ("pajamas", "睡衣"),
                ("nightgown", "睡裙"),
                ("lingerie", "内衣"),
                ("bikini", "比基尼"),
                ("swimsuit", "泳装"),
                ("shirt", "衬衫"),
                ("skirt", "裙装"),
            ]),
            "legwear": pick_labels([
                ("black pantyhose", "黑丝"),
                ("white pantyhose", "白丝"),
                ("pantyhose", "连裤袜"),
                ("black thighhighs", "黑色过膝袜"),
                ("white thighhighs", "白色过膝袜"),
                ("thighhighs", "过膝袜"),
                ("ankle socks", "短袜"),
                ("knee socks", "及膝袜"),
                ("socks", "袜子"),
                ("stockings", "丝袜"),
            ]),
            "footwear": pick_labels([
                ("high heels", "高跟鞋"),
                ("loafers", "乐福鞋"),
                ("sneakers", "运动鞋"),
                ("boots", "靴子"),
                ("ankle boots", "短靴"),
                ("sandals", "凉鞋"),
                ("slippers", "拖鞋"),
                ("mary janes", "玛丽珍鞋"),
                ("barefoot", "赤脚"),
                ("no shoes", "没穿鞋"),
                ("shoes removed", "脱鞋"),
            ]),
            "lighting": pick_labels([
                ("soft morning light", "清晨柔光"),
                ("natural light", "自然光"),
                ("daylight", "白天自然光"),
                ("sunlight", "阳光"),
                ("golden hour", "黄昏金光"),
                ("sunset", "傍晚余晖"),
                ("warm indoor light", "暖色室内灯光"),
                ("moonlight", "月光"),
                ("city lights", "城市灯光"),
                ("dim light", "昏暗光线"),
            ]),
            "time_of_day": pick_labels([
                ("sunrise", "清晨"),
                ("morning", "上午"),
                ("noon", "中午"),
                ("midday", "中午"),
                ("afternoon", "下午"),
                ("golden hour", "傍晚"),
                ("sunset", "傍晚"),
                ("evening", "夜晚"),
                ("night", "夜晚"),
                ("late night", "深夜"),
                ("midnight", "深夜"),
            ], limit=1),
            "framing": pick_labels([
                ("full body", "全身构图"),
                ("lower body", "下半身构图"),
                ("upper body", "上半身构图"),
                ("close-up", "近景"),
                ("portrait", "肖像近景"),
                ("wide angle", "广角取景"),
                ("pov", "第一人称视角"),
            ]),
        }

        for key, values in mapping.items():
            if values:
                anchor_data[key] = values

        return anchor_data

    def _format_selfie_anchor_summary(self, anchor_data: Dict[str, List[str]]) -> str:
        """将结构化自拍锚点格式化为摘要文本。"""
        if not anchor_data:
            return ""

        lines: List[str] = []
        label_map = [
            ("scene_type", "自拍类型"),
            ("location", "场景/背景"),
            ("outfit", "服装/穿搭"),
            ("legwear", "袜类/腿部穿搭"),
            ("footwear", "鞋子/足部状态"),
            ("lighting", "光线"),
            ("time_of_day", "时间氛围"),
            ("framing", "构图"),
        ]
        for key, label in label_map:
            values = anchor_data.get(key, [])
            if values:
                lines.append(f"- {label}：{'、'.join(values)}")
        return "\n".join(lines)

    def _normalize_prompt_tags(self, prompt: str) -> List[str]:
        """将提示词切分并清洗为可分析的标准标签列表。"""
        raw_tags = [segment.strip() for segment in prompt.replace("\n", ",").split(",") if segment.strip()]
        normalized_tags: List[str] = []
        for tag in raw_tags:
            cleaned = re.sub(r"^-?\d+(?:\.\d+)?::", "", tag.strip())
            cleaned = cleaned.replace("::", "")
            cleaned = cleaned.strip("{}[]() ")
            if cleaned:
                normalized_tags.append(cleaned.lower())
        return normalized_tags

    async def _persist_last_prompt_record(self, prompt: str, request: str = "") -> None:
        """将上一轮提示词写入 ActionRecords，便于重启后恢复。"""
        text = (prompt or "").strip()
        if not text:
            return
        req = (request or "").strip()
        if req:
            display = f"{LAST_PROMPT_RECORD_PREFIX}\n{_REQ_LINE_PREFIX}{req}\n{_REQ_SEPARATOR}\n{text}"
        else:
            display = f"{LAST_PROMPT_RECORD_PREFIX}\n{text}"
        try:
            await self.store_action_info(
                action_build_into_prompt=False,
                action_prompt_display=display,
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
        if not prompt:
            return ""

        self._last_structured_prompt_payload = parse_structured_prompt_payload(prompt)

        parsed = parse_prompt_from_structured_output(prompt)
        if parsed:
            logger.debug(f"{self.log_prefix} [LLM触发] 结构化提示词解析命中（JSON->prompt），将跳过文本清洗")
            return parsed

        self._last_structured_prompt_payload = None

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

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
        "用户明确索要图像、自拍、照片、展示照、看某个部位/穿搭时触发。"
        "纯聊天、提问偏好、讨论穿搭审美时不触发。"
    )

    # 动作参数定义
    default_action_parameters = {
        "description": (
            "画面内容描述，只写最终要画的内容，不写系统说明或解释。\n"
            "规则：\n"
            "1. 用户直接描述画面→保留原始描述；依赖上下文→结合对话补全（如你刚说在洗澡，用户说'自拍'→'在浴室洗澡时的自拍'）\n"
            "2. 用户想看你本人→必须体现自拍/本人出镜（如'看看腿'→'自拍，展示腿部'；'穿JK给我看'→'你穿JK的自拍'）\n"
            "3. 续图（'再来一张'、'继续'、'换个姿势'）→以上一轮为底稿，只改用户要求变化的部分；用户未提及的主体、场景、整套穿搭（主衣物+袜类+鞋类+配饰）默认沿用\n"
            "4. 局部修改（'换成白丝'、'表情害羞一点'、'改成黑色'）→只改指定项，其余继承；改颜色/材质/长度等属性时是在同一件单品上微调，不换成另一种款式；改主衣物不删袜鞋，改袜类不删主衣物\n"
            "5. 宽泛服装类别（睡衣、裙子、袜子等）→收敛成一个具体款式，不写大类名，不写多个互斥分支\n"
            "6. 用户指定的关键要素（服装、部位、视角、氛围、时间）必须保留，不要泛化成普通自拍"
        ),
        "size": "图片尺寸（默认从配置获取）",
    }

    # 动作使用场景（触发条件）
    action_require = [
        "触发条件（满足任一即触发）：",
        "1. 用户明确要求画图、生成图片、创作图像",
        "2. 用户明确要求自拍、拍照、发照片、看你本人出镜（如'自拍一张'、'发张照片'、'看看你'、'拍给我看'）",
        "3. 用户明确要求看你的某个部位、穿搭或展示照（如'看看腿'、'给我看黑丝'、'秀一下'、'穿JK给我看'、'看看你今天穿什么'）",
        "4. 用户正在延续上一张图的话题（如'再来一张'、'换个姿势'、'继续'），语义上是在上一张图基础上变化",
        "5. 对话已进入看图型互动，用户表达的是明确的视觉索求",
        "",
        "不触发条件：",
        "- 纯聊天、知识问答、技术讨论",
        "- 偏好提问（'你最喜欢的衣服是什么'、'你喜欢JK还是连衣裙'、'你觉得黑丝怎么样'）",
        "- 模糊的夸赞、调情、闲聊，没有明确索要视觉展示",
        "- 文字回复已足够完成互动时，不额外触发生图",
        "- 非用户主动要求重画时，不重复生成相同内容",
        "- 无法明确判断是在要图时，优先文字回复",
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

        previous_selfie_anchor: Dict[str, List[str]] = {}
        if self.chat_id:
            inherit_ttl = float(self.get_config("prompt_generator.inherit_ttl", 0) or 0)
            _, _, _, previous_selfie_anchor = session_state.get_last_selfie_context(
                self.chat_id,
                ttl=inherit_ttl,
            )

        # 优先信任结构化输出中的意图字段，避免再由代码反向猜测
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
                session_state.set_last_nai_context(self.chat_id, description, raw_description)

        if self.get_config("prompt_generator.enable_programmatic_fallbacks", False):
            if is_selfie:
                description = self._inherit_selfie_clothing_from_anchor(
                    description,
                    raw_description,
                    previous_selfie_anchor,
                )
            description = self._enforce_explicit_request_tags(description, raw_description)

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
            await self.send_text(f"哎呀，生成图片时遇到问题：{result[:150]}")
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

    def _inherit_selfie_clothing_from_anchor(
        self,
        description: str,
        raw_request: str,
        previous_anchor: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """在自拍续图时，将上一轮稳定的穿搭锚点程序化回写到本轮提示词。"""
        anchor_data = dict(previous_anchor or {})
        if not anchor_data:
            return description

        change_profile = self._analyze_selfie_change_request(raw_request)
        inherit_keys: List[str] = []

        if change_profile.get("change_main_outfit_only"):
            inherit_keys.extend(["legwear", "footwear"])
        elif change_profile.get("change_legwear_only"):
            inherit_keys.extend(["outfit", "footwear"])
        elif change_profile.get("change_footwear_only"):
            inherit_keys.extend(["outfit", "legwear"])
        elif (
            change_profile.get("implicit_keep_followup")
            or change_profile.get("explicit_keep")
            or change_profile.get("soft_variation")
            or (not change_profile.get("change_outfit") and not change_profile.get("change_scene"))
        ):
            inherit_keys.extend(["outfit", "legwear", "footwear"])

        if not inherit_keys:
            return description

        label_to_tags = {
            "outfit": {
                "制服": ["school uniform"],
                "水手服": ["serafuku"],
                "JK外套": ["blazer"],
                "百褶裙": ["pleated skirt"],
                "连衣裙": ["dress"],
                "卫衣": ["hoodie"],
                "毛衣": ["sweater"],
                "开衫": ["cardigan"],
                "外套": ["coat"],
                "夹克": ["jacket"],
                "睡衣": ["pajamas"],
                "睡裙": ["nightgown"],
                "内衣风": ["lingerie"],
                "比基尼": ["bikini"],
                "泳装": ["swimsuit"],
                "衬衫": ["shirt"],
                "裙装": ["skirt"],
            },
            "legwear": {
                "黑丝": ["black pantyhose"],
                "白丝": ["white pantyhose"],
                "连裤袜": ["pantyhose"],
                "黑色过膝袜": ["black thighhighs"],
                "白色过膝袜": ["white thighhighs"],
                "过膝袜": ["thighhighs"],
                "袜子": ["socks"],
                "短袜": ["ankle socks"],
                "及膝袜": ["knee socks"],
                "丝袜": ["stockings"],
                "吊袜带": ["garter straps"],
            },
            "footwear": {
                "高跟鞋": ["high heels"],
                "乐福鞋": ["loafers"],
                "运动鞋": ["sneakers"],
                "靴子": ["boots"],
                "短靴": ["ankle boots"],
                "凉鞋": ["sandals"],
                "拖鞋": ["slippers"],
                "玛丽珍鞋": ["mary janes"],
                "赤脚": ["barefoot"],
                "没穿鞋": ["no shoes"],
                "脱鞋": ["shoes removed"],
            },
        }
        category_markers = {
            "outfit": [
                "school uniform", "serafuku", "blazer", "pleated skirt", "dress", "hoodie",
                "sweater", "cardigan", "coat", "jacket", "pajamas", "nightgown",
                "lingerie", "bikini", "swimsuit", "shirt", "skirt",
            ],
            "legwear": [
                "black pantyhose", "white pantyhose", "pantyhose", "black thighhighs",
                "white thighhighs", "thighhighs", "socks", "ankle socks", "knee socks",
                "stockings", "garter straps", "garter belt",
            ],
            "footwear": [
                "high heels", "heels", "pumps", "loafers", "sneakers", "boots",
                "ankle boots", "sandals", "slippers", "mary janes", "barefoot",
                "no shoes", "bare feet", "shoes removed",
            ],
        }

        existing_tags = [tag.strip() for tag in description.replace("\n", ",").split(",") if tag.strip()]
        normalized_existing = self._normalize_prompt_tags(description)
        tags_to_add: List[str] = []

        for key in inherit_keys:
            if any(marker in tag for marker in category_markers.get(key, []) for tag in normalized_existing):
                continue
            for label in anchor_data.get(key, []):
                for tag in label_to_tags.get(key, {}).get(label, []):
                    if tag not in tags_to_add and tag not in existing_tags:
                        tags_to_add.append(tag)

        if not tags_to_add:
            return description

        if len(existing_tags) >= 2:
            prefix = ", ".join(existing_tags[:2])
            suffix = ", ".join(existing_tags[2:]) if len(existing_tags) > 2 else ""
            merged = f"{prefix}, {', '.join(tags_to_add)}"
            if suffix:
                merged = f"{merged}, {suffix}"
        else:
            merged = ", ".join(tags_to_add + existing_tags)

        logger.debug(
            f"{self.log_prefix} [LLM触发] 自拍穿搭继承已生效：inherit_keys={inherit_keys}, added={tags_to_add}"
        )
        return merged.strip(", ")

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
        prompt = prompt.replace("<<CURRENT_TIME_CONTEXT>>", current_time_context).strip()
        prompt = prompt.replace("<<SELFIE_HINT>>", selfie_hint).strip()
        prompt = prompt.replace("<<USER_REQUEST>>", original_request.strip() or "N/A")
        if "<<CURRENT_TIME_CONTEXT>>" in prompt:
            prompt = prompt.replace("<<CURRENT_TIME_CONTEXT>>", current_time_context)
        elif "</user_request>" in prompt:
            prompt = prompt.replace("</user_request>", f"{current_time_context}\n</user_request>", 1)
        else:
            prompt = f"{prompt}\n\n{current_time_context}".strip()
        if selfie_scene_context:
            if "<<SELFIE_SCENE_CONTEXT>>" in prompt:
                prompt = prompt.replace("<<SELFIE_SCENE_CONTEXT>>", selfie_scene_context)
            elif "</user_request>" in prompt:
                prompt = prompt.replace("</user_request>", f"{selfie_scene_context}\n</user_request>", 1)
            else:
                prompt = f"{prompt}\n\n{selfie_scene_context}".strip()
        return prompt

    def _build_current_time_context(self) -> str:
        """构建当前时间段提示，帮助 LLM 在未指定时补对光线与场景时间。"""
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
            "这条时间信息用于补全场景时间与光线，不是硬性主题。\n"
            "如果用户明确指定了白天、夜晚、清晨、黄昏、室内灯光、天气或其他时间氛围，以用户要求为准，不要覆盖。\n"
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
        """为 bot 自拍/展示照构建场景连续性提示。"""
        request_text = (original_request or "").strip()
        prompt_text = (last_selfie_prompt or "").strip()
        scene_summary = (last_selfie_scene or "").strip()
        anchor_data = dict(last_selfie_anchor or {})

        if not anchor_data and prompt_text:
            anchor_data = self._extract_selfie_anchor_data(prompt_text)
        if not scene_summary and anchor_data:
            scene_summary = self._format_selfie_anchor_summary(anchor_data)
        elif not scene_summary and prompt_text:
            scene_summary = self._extract_selfie_scene_summary(prompt_text)

        likely_selfie = self._is_likely_selfie_request(request_text, prompt_text)
        if not likely_selfie:
            return ""

        default_scene_hint = self._build_default_selfie_scene_hint()
        prompt_reference = self._build_selfie_prompt_reference(prompt_text)
        lines: List[str] = [
            "<selfie_scene_context>",
            "你正在处理 bot 本人自拍/展示照 的连续发图请求。",
            "代码侧会在最终生图前固定合并 selfie_prompt_add，它是角色身份/外貌硬锚点；你不需要改写、解释或覆盖这部分硬锚点。",
            "请根据当前用户请求、上一轮自拍提示词和下面的锚点信息，自行判断 continuity 应该是 new / keep / adjust / switch。",
            "判断原则：用户明确要求优先；未明确要求变化的场景、构图、光线、穿搭可以延续；只有用户明确要求更换，或旧锚点与本轮要求冲突时才切换。",
        ]

        if scene_summary:
            lines.append("上一轮可延续的自拍锚点：")
            lines.append(scene_summary)
            if last_selfie_request:
                lines.append(f"上一轮用户请求：{last_selfie_request.strip()}")
            if prompt_reference:
                lines.append("上一轮自拍提示词参考：")
                lines.append(prompt_reference)
        else:
            lines.append("当前没有可延续的自拍锚点。除非用户明确指定地点或穿搭，否则不要随机跳到景点、街拍、海边等大场景，也不要无理由突然换成完全不同的衣服主题。")
            if prompt_reference:
                lines.append("如果上一轮自拍提示词里已经包含清晰的场景、服装、自拍方式，可将其作为连续参考，而不是完全重开。")
                lines.append("上一轮自拍提示词参考：")
                lines.append(prompt_reference)

        lines.append(f"默认自拍场景兜底：{default_scene_hint}")
        lines.append("参考上一轮提示词时，优先继承其中稳定的场景、服装、视角和光线锚点；不要机械照抄，用户明确要求变化的部分必须改。")
        lines.append("你只需要在最终 JSON/tag 结果里体现判断结果，不要输出解释过程。")
        lines.append("</selfie_scene_context>")
        return "\n".join(lines)

    def _build_default_selfie_scene_hint(self) -> str:
        """给自拍第一张图一个稳定但不僵硬的默认场景。"""
        hour = datetime.now().hour
        if 6 <= hour < 18:
            return "白天优先室内日常自拍场景，如卧室窗边、卧室镜前、居家角落，使用自然光；不要无理由直接跳到户外景点。"
        return "夜晚优先室内日常自拍场景，如卧室、镜前、床边、居家角落，使用暖色室内灯光；不要无理由直接跳到白天户外。"

    def _build_selfie_prompt_reference(self, prompt_text: str, max_tags: int = 48, max_chars: int = 700) -> str:
        """从上一轮自拍提示词中裁出一段稳定参考，避免上下文过长。"""
        text = (prompt_text or "").strip()
        if not text:
            return ""

        raw_tags = [segment.strip() for segment in text.replace("\n", ",").split(",") if segment.strip()]
        if not raw_tags:
            return text[:max_chars].strip()

        selected_tags: List[str] = []
        current_length = 0
        for tag in raw_tags:
            next_length = current_length + len(tag) + (2 if selected_tags else 0)
            if len(selected_tags) >= max_tags or next_length > max_chars:
                break
            selected_tags.append(tag)
            current_length = next_length

        excerpt = ", ".join(selected_tags).strip()
        if not excerpt:
            excerpt = text[:max_chars].strip()
        if excerpt != text.strip():
            excerpt = f"{excerpt}, ..."
        return excerpt

    def _analyze_selfie_change_request(self, request_text: str) -> Dict[str, bool]:
        """分析本轮自拍请求更像保留、轻改还是切换哪些锚点。"""
        text = (request_text or "").strip().lower()
        if not text:
            return {
                "change_scene": False,
                "change_outfit": False,
                "change_scene_only": False,
                "change_outfit_only": False,
                "soft_variation": False,
                "explicit_keep": False,
                "change_main_outfit": False,
                "change_legwear": False,
                "change_footwear": False,
                "change_accessory": False,
                "change_main_outfit_only": False,
                "change_legwear_only": False,
                "change_footwear_only": False,
                "implicit_keep_followup": False,
            }

        scene_keywords = [
            "背景", "场景", "地点", "地方", "镜前", "卧室", "浴室", "客厅", "窗边",
            "床边", "床上", "沙发", "书桌", "阳台", "户外", "街景", "夜景", "公园",
            "咖啡店", "海边", "教室", "办公室", "灯光", "光线", "自拍", "角度", "构图",
        ]
        main_outfit_keywords = [
            "制服", "jk", "水手服", "百褶裙", "裙", "连衣裙", "毛衣", "开衫", "外套",
            "夹克", "睡衣", "睡裙", "泳装", "比基尼", "内衣", "衣服", "上衣", "衬衫",
            "裤子", "短裤", "长裤", "牛仔裤", "家居服",
        ]
        legwear_keywords = [
            "黑丝", "白丝", "裤袜", "连裤袜", "过膝袜", "丝袜", "袜子",
        ]
        footwear_keywords = [
            "鞋子", "高跟", "高跟鞋", "运动鞋", "小皮鞋", "乐福鞋", "靴子", "凉鞋", "拖鞋", "赤脚", "光脚", "没穿鞋", "不穿鞋",
        ]
        accessory_keywords = [
            "配饰", "发夹", "头饰", "项链", "耳环", "手链", "choker", "蝴蝶结",
        ]
        generic_outfit_keywords = [
            "穿搭", "这身", "这套",
        ]
        color_keywords = [
            "黑色", "白色", "灰色", "棕色", "米色", "奶白", "藏青", "蓝色", "粉色", "红色", "绿色",
        ]
        change_keywords = ["换", "改", "变", "切", "换成", "改成", "换到", "切到"]
        keep_keywords = ["还是", "保留", "保持", "别换", "不要换", "同一个", "同样", "这身", "这套", "原来"]
        soft_variation_keywords = [
            "来点不一样", "换个姿势", "换个角度", "换个表情", "换个动作", "表情", "动作",
            "姿势", "角度", "构图", "镜头", "近一点", "远一点", "侧一点", "自然一点",
        ]
        followup_keep_keywords = [
            "再来一张", "再来个", "继续", "再拍一张", "再发一张", "另一张", "来一张",
            "还是这身", "还是这套", "同一套", "同样穿搭",
        ]

        mentions_scene = any(keyword in text for keyword in scene_keywords)
        mentions_main_outfit = any(keyword in text for keyword in main_outfit_keywords)
        mentions_legwear = any(keyword in text for keyword in legwear_keywords)
        mentions_footwear = any(keyword in text for keyword in footwear_keywords)
        mentions_accessory = any(keyword in text for keyword in accessory_keywords)
        mentions_generic_outfit = any(keyword in text for keyword in generic_outfit_keywords)
        mentions_color = any(keyword in text for keyword in color_keywords)
        mentions_outfit = any([
            mentions_main_outfit,
            mentions_legwear,
            mentions_footwear,
            mentions_accessory,
            mentions_generic_outfit,
        ])
        wants_change = any(keyword in text for keyword in change_keywords)
        explicit_keep = any(keyword in text for keyword in keep_keywords)
        soft_variation = any(keyword in text for keyword in soft_variation_keywords)
        implicit_keep_followup = any(keyword in text for keyword in followup_keep_keywords)

        change_scene = mentions_scene and (wants_change or "去" in text or "到" in text)
        change_outfit = mentions_outfit and (wants_change or "穿" in text or "这身" in text or "这套" in text)
        change_main_outfit = (mentions_main_outfit or (mentions_generic_outfit and mentions_color)) and change_outfit
        change_legwear = mentions_legwear and change_outfit
        change_footwear = mentions_footwear and change_outfit
        change_accessory = mentions_accessory and change_outfit

        return {
            "change_scene": change_scene,
            "change_outfit": change_outfit,
            "change_scene_only": change_scene and not change_outfit,
            "change_outfit_only": change_outfit and not change_scene,
            "soft_variation": soft_variation and not change_scene and not change_outfit,
            "explicit_keep": explicit_keep and not change_scene and not change_outfit,
            "change_main_outfit": change_main_outfit,
            "change_legwear": change_legwear,
            "change_footwear": change_footwear,
            "change_accessory": change_accessory,
            "change_main_outfit_only": change_main_outfit and not change_legwear and not change_footwear and not change_accessory,
            "change_legwear_only": change_legwear and not change_main_outfit and not change_footwear and not change_accessory,
            "change_footwear_only": change_footwear and not change_main_outfit and not change_legwear and not change_accessory,
            "implicit_keep_followup": implicit_keep_followup and not change_scene and not change_outfit,
        }

    def _is_likely_selfie_request(self, request_text: str, last_selfie_prompt: str = "") -> bool:
        """粗略判断当前请求是否属于 bot 自拍/展示照，用于注入连续性提示。"""
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
                r"还是.*", r"再拍", r"另一张", r"来一张", r"再发一张",
                r"换成.+", r"改成.+", r"换套.+", r"换身.+", r"换衣服", r"换穿搭",
                r"换背景", r"换场景", r"换地方", r"换到.+", r"改背景", r"改场景",
                r"同一个场景", r"同样背景", r"这个背景", r"这身", r"这套", r"同一套",
            ]
            if any(re.search(pattern, text) for pattern in continuation_patterns):
                return True

            outfit_keywords = [
                "黑丝", "白丝", "裤袜", "连裤袜", "过膝袜", "丝袜", "袜子", "鞋子", "高跟",
                "高跟鞋", "运动鞋", "小皮鞋", "乐福鞋", "靴子", "凉鞋", "拖鞋", "赤脚", "光脚", "没穿鞋", "不穿鞋",
                "制服", "jk", "水手服", "百褶裙", "裙", "连衣裙", "毛衣", "开衫", "外套",
                "夹克", "睡衣", "睡裙", "泳装", "比基尼", "内衣", "配饰",
                "黑色", "白色", "灰色", "棕色", "米色", "奶白", "藏青", "蓝色", "粉色", "红色", "绿色",
            ]
            scene_keywords = [
                "背景", "场景", "地点", "地方", "镜前", "卧室", "浴室", "客厅", "窗边",
                "床边", "床上", "沙发", "书桌", "阳台", "户外", "街景", "夜景", "公园",
                "咖啡店", "灯光", "光线", "自拍", "角度", "构图",
            ]
            intent_keywords = [
                "换", "改", "变", "保留", "继续", "还是", "同一个", "同样", "这身", "这套",
                "不要换", "别换", "保持",
            ]

            mentions_anchor = any(keyword in text for keyword in outfit_keywords + scene_keywords)
            has_followup_intent = any(keyword in text for keyword in intent_keywords)
            if mentions_anchor and has_followup_intent:
                return True

        return False

    def _extract_selfie_scene_summary(self, prompt: str) -> str:
        """从自拍提示词中提取可延续的场景锚点摘要。"""
        anchor_data = self._extract_selfie_anchor_data(prompt)
        return self._format_selfie_anchor_summary(anchor_data)

    def _extract_selfie_anchor_data(self, prompt: str) -> Dict[str, List[str]]:
        """从自拍提示词中提取结构化锚点。"""
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

        scene_type = pick_labels([
            ("mirror selfie", "镜子自拍"),
            ("group selfie", "合照自拍"),
            ("from above", "高角度自拍"),
            ("from below", "低角度自拍"),
            ("selfie", "前置自拍"),
        ], limit=1)
        location = pick_labels([
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
        ])
        outfit = pick_labels([
            ("school uniform", "制服"),
            ("serafuku", "水手服"),
            ("blazer", "JK外套"),
            ("pleated skirt", "百褶裙"),
            ("dress", "连衣裙"),
            ("hoodie", "卫衣"),
            ("sweater", "毛衣"),
            ("cardigan", "开衫"),
            ("coat", "外套"),
            ("jacket", "夹克"),
            ("pajamas", "睡衣"),
            ("nightgown", "睡裙"),
            ("lingerie", "内衣风"),
            ("bikini", "比基尼"),
            ("swimsuit", "泳装"),
            ("shirt", "衬衫"),
            ("skirt", "裙装"),
        ])
        legwear = pick_labels([
            ("black pantyhose", "黑丝"),
            ("white pantyhose", "白丝"),
            ("pantyhose", "连裤袜"),
            ("black thighhighs", "黑色过膝袜"),
            ("white thighhighs", "白色过膝袜"),
            ("thighhighs", "过膝袜"),
            ("socks", "袜子"),
            ("ankle socks", "短袜"),
            ("knee socks", "及膝袜"),
            ("stockings", "丝袜"),
            ("garter straps", "吊袜带"),
            ("garter belt", "吊袜带"),
        ])
        footwear = pick_labels([
            ("high heels", "高跟鞋"),
            ("heels", "高跟鞋"),
            ("pumps", "高跟鞋"),
            ("loafers", "乐福鞋"),
            ("sneakers", "运动鞋"),
            ("boots", "靴子"),
            ("ankle boots", "短靴"),
            ("sandals", "凉鞋"),
            ("slippers", "拖鞋"),
            ("mary janes", "玛丽珍鞋"),
            ("barefoot", "赤脚"),
            ("no shoes", "没穿鞋"),
            ("bare feet", "赤脚"),
            ("shoes removed", "脱鞋"),
        ])
        outfit_color = pick_labels([
            ("black skirt", "黑色"),
            ("black dress", "黑色"),
            ("black cardigan", "黑色"),
            ("black sweater", "黑色"),
            ("black hoodie", "黑色"),
            ("black coat", "黑色"),
            ("black jacket", "黑色"),
            ("black shirt", "黑色"),
            ("black pajamas", "黑色"),
            ("black nightgown", "黑色"),
            ("white skirt", "白色"),
            ("white dress", "白色"),
            ("white cardigan", "白色"),
            ("white sweater", "白色"),
            ("white hoodie", "白色"),
            ("white shirt", "白色"),
            ("white pajamas", "白色"),
            ("white nightgown", "白色"),
            ("gray pajamas", "灰色"),
            ("gray nightgown", "灰色"),
            ("gray skirt", "灰色"),
            ("gray dress", "灰色"),
            ("gray cardigan", "灰色"),
            ("gray sweater", "灰色"),
            ("grey pajamas", "灰色"),
            ("grey nightgown", "灰色"),
            ("grey skirt", "灰色"),
            ("grey dress", "灰色"),
            ("grey cardigan", "灰色"),
            ("grey sweater", "灰色"),
            ("brown pajamas", "棕色"),
            ("brown nightgown", "棕色"),
            ("brown skirt", "棕色"),
            ("brown dress", "棕色"),
            ("brown cardigan", "棕色"),
            ("brown sweater", "棕色"),
            ("beige pajamas", "米色"),
            ("beige nightgown", "米色"),
            ("beige skirt", "米色"),
            ("beige dress", "米色"),
            ("beige cardigan", "米色"),
            ("beige sweater", "米色"),
            ("cream pajamas", "奶白色"),
            ("cream nightgown", "奶白色"),
            ("cream skirt", "奶白色"),
            ("cream dress", "奶白色"),
            ("cream cardigan", "奶白色"),
            ("navy pajamas", "藏青色"),
            ("navy nightgown", "藏青色"),
            ("navy skirt", "藏青色"),
            ("navy dress", "藏青色"),
            ("navy blazer", "藏青色"),
            ("blue pajamas", "蓝色"),
            ("blue nightgown", "蓝色"),
            ("blue skirt", "蓝色"),
            ("blue dress", "蓝色"),
            ("blue cardigan", "蓝色"),
            ("blue sweater", "蓝色"),
            ("pink pajamas", "粉色"),
            ("pink nightgown", "粉色"),
            ("pink skirt", "粉色"),
            ("pink dress", "粉色"),
            ("pink cardigan", "粉色"),
            ("pink sweater", "粉色"),
            ("red pajamas", "红色"),
            ("red nightgown", "红色"),
            ("red skirt", "红色"),
            ("red dress", "红色"),
            ("red cardigan", "红色"),
            ("green pajamas", "绿色"),
            ("green nightgown", "绿色"),
            ("green skirt", "绿色"),
            ("green dress", "绿色"),
            ("green cardigan", "绿色"),
        ])
        lighting = pick_labels([
            ("warm indoor light", "暖色室内灯光"),
            ("natural light", "自然光"),
            ("daylight", "白天自然光"),
            ("sunlight", "阳光"),
            ("golden hour", "黄昏金光"),
            ("sunset", "傍晚余晖"),
            ("moonlight", "月光"),
            ("night", "夜晚光线"),
            ("city lights", "城市灯光"),
            ("dim light", "昏暗光线"),
            ("soft morning light", "清晨柔光"),
        ])
        time_of_day = pick_labels([
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
        ], limit=1)
        framing = pick_labels([
            ("full body", "全身构图"),
            ("cowboy shot", "大腿以上构图"),
            ("upper body", "上半身构图"),
            ("close-up", "近景"),
            ("portrait", "肖像近景"),
            ("wide angle", "广角取景"),
            ("pov", "第一人称视角"),
        ])

        if scene_type:
            anchor_data["scene_type"] = scene_type
        if location:
            anchor_data["location"] = location
        if outfit:
            anchor_data["outfit"] = outfit
        if legwear:
            anchor_data["legwear"] = legwear
        if footwear:
            anchor_data["footwear"] = footwear
        if outfit_color:
            anchor_data["outfit_color"] = outfit_color
        if lighting:
            anchor_data["lighting"] = lighting
        if time_of_day:
            anchor_data["time_of_day"] = time_of_day
        if framing:
            anchor_data["framing"] = framing

        return anchor_data

    def _format_selfie_anchor_summary(self, anchor_data: Dict[str, List[str]]) -> str:
        """将结构化自拍锚点格式化为摘要文本。"""
        if not anchor_data:
            return ""

        lines: List[str] = []
        label_map = [
            ("scene_type", "自拍类型"),
            ("location", "场景/背景"),
            ("outfit_color", "服装颜色"),
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

    def _normalize_single_prompt_tag(self, tag: str) -> str:
        """将单个提示词清洗为可比较的标准形式。"""
        cleaned = re.sub(r"^-?\d+(?:\.\d+)?::", "", tag.strip())
        cleaned = cleaned.replace("::", "")
        cleaned = cleaned.strip("{}[]() ")
        return cleaned.lower()

    def _condense_request_text(self, text: str) -> str:
        """压缩请求文本，便于匹配被空格打散的中英文关键词。"""
        if not text:
            return ""
        condensed = re.sub(r"\s+", "", text)
        return condensed.lower()

    def _enforce_explicit_request_tags(self, description: str, raw_request: str) -> str:
        """将用户/Planner 明确写出的关键元素程序化前置并加权。"""
        if not description or not raw_request:
            return description

        condensed_request = self._condense_request_text(raw_request)
        if not condensed_request:
            return description

        existing_tags = [tag.strip() for tag in description.replace("\n", ",").split(",") if tag.strip()]
        normalized_existing = self._normalize_prompt_tags(description)
        priority_tags: List[tuple[str, str]] = []

        def has_any_tag(candidates: List[str]) -> bool:
            return any(candidate in tag for candidate in candidates for tag in normalized_existing)

        def add_priority_tag(base_tag: str, weighted_tag: str) -> None:
            if base_tag not in [item[0] for item in priority_tags]:
                priority_tags.append((base_tag, weighted_tag))

        legwear_requested = False

        # 袜类是用户显式指定且最容易被 LLM 漏掉的关键信息，优先前置并加权。
        if ("黑丝" in condensed_request) or ("黑色连裤袜" in condensed_request):
            add_priority_tag("black pantyhose", "{{black pantyhose}}")
            legwear_requested = True
        elif ("白丝" in condensed_request) or ("白色连裤袜" in condensed_request):
            add_priority_tag("white pantyhose", "{{white pantyhose}}")
            legwear_requested = True
        elif ("连裤袜" in condensed_request) or ("裤袜" in condensed_request):
            add_priority_tag("pantyhose", "{{pantyhose}}")
            legwear_requested = True

        if ("黑色过膝袜" in condensed_request) or ("黑色大腿袜" in condensed_request):
            add_priority_tag("black thighhighs", "{{black thighhighs}}")
            legwear_requested = True
        elif ("白色过膝袜" in condensed_request) or ("白色大腿袜" in condensed_request):
            add_priority_tag("white thighhighs", "{{white thighhighs}}")
            legwear_requested = True
        elif ("过膝袜" in condensed_request) or ("大腿袜" in condensed_request) or ("膝上袜" in condensed_request):
            add_priority_tag("thighhighs", "{{thighhighs}}")
            legwear_requested = True

        # 用户明确想看袜类/腿部穿搭时，优先补能看到下半身的构图。
        if legwear_requested and not has_any_tag(["full body", "lower body"]):
            add_priority_tag("full body", "full body")

        if not priority_tags:
            return description

        selected_priority_tags: List[str] = []
        priority_bases = {base for base, _ in priority_tags}

        for base_tag, weighted_tag in priority_tags:
            existing_match = next(
                (tag for tag in existing_tags if self._normalize_single_prompt_tag(tag) == base_tag),
                None,
            )
            if existing_match and ("{{" in existing_match or "::" in existing_match):
                selected_priority_tags.append(existing_match)
            else:
                selected_priority_tags.append(weighted_tag)

        remaining_tags = [
            tag for tag in existing_tags if self._normalize_single_prompt_tag(tag) not in priority_bases
        ]
        merged_tags = selected_priority_tags + remaining_tags
        logger.debug(
            f"{self.log_prefix} [LLM触发] 根据显式请求前置关键标签：raw_request={raw_request!r}, added={selected_priority_tags}"
        )
        return ", ".join(merged_tags)

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
        import re
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

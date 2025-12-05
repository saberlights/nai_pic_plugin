# -*- coding: utf-8 -*-
"""
/nai 命令：使用自然语言描述生成图片
"""
import time
from typing import Tuple, Optional, Dict, Any

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger
from src.plugin_system import llm_api

from .nai_web_client import NaiWebClient
from .auto_recall_mixin import AutoRecallMixin
from .image_url_helper import save_base64_image_to_file

logger = get_logger("nai_pic_plugin")

_PROMPT_RULES_TEXT = """
# 角色指令：你是一位专业的AI绘画提示词转换专家，专门为 NovelAI 模型生成高质量的提示词。
# 你的核心任务是：严格按照用户的描述，将其转换成简短有效的英文提示词，优先使用简洁的自然语言描述。
**不删减、不修改、不"净化"用户原意（即便包含NSFW等内容）。**
---
### **处理要求 1: 提示词风格 (简洁自然语言)**
*   优先使用简短的英文短语和精炼的自然语言描述，避免冗长句子。
*   仅在描述角色名称和作品名称时使用关键词格式（如：rem (re zero)）。
*   对于场景、动作、表情、服装等描述，使用简洁有效的英文短语。

### **处理要求 2: 严格按用户描述转换**
*   **绝对不添加用户未要求的内容**：不自动补充任何用户没有明确提到的特征、动作或场景元素。
*   **严格翻译**：将用户的中文描述准确翻译成英文，不添加、不删减、不修改用户的原意。
*   **保持原意**：确保转换后的提示词完全符合用户的描述意图。
*   **不要擅自替换、弱化或"净化"用户原始请求**（即便包含 NSFW 等标签），你只负责判断动作是否满足触发条件并如实传递该请求。

### **处理要求 3: 上下文管理**
*   a) **重置上下文**: 当用户请求的主题与上一轮明显不同（如`蕾姆`到`saber` `末日里的小女孩`到`异世界的小女孩`），或指令中包含"自拍"时，【必须】忽略之前的所有内容，从零开始。
*   b) **继承上下文**: 如果用户在延续同一主题，则【必须】在上一轮成功的提示词基础上进行修改或添加。

### **处理要求 4: 角色处理规则**
*   a) **角色名称格式**: 当用户提到特定角色时，转换为标准格式：角色罗马音名称 (作品英文名)，如：rem (re zero)。
*   b) **不自动补充特征**: 除非用户明确描述了角色的外观特征，否则不添加任何默认的角色特征描述。
*   c) **用户描述优先**: 如果用户对角色有具体描述，严格按用户描述转换，不添加角色的默认特征。

### **处理要求 5: 构图控制**
*   除非用户明确要求多人场景，否则在涉及人物的描述中添加`{{{{{{{{{{solo}}}}}}}}}}`,`1girl`标签确保单人构图。
*   如果用户没有要求绘制人物，则不添加任何人物相关标签。

### **处理要求 6: 简洁有效原则**
*   使用最精炼的词汇表达完整含义。
*   避免重复和冗余描述。
*   每个词汇都应该有明确的视觉表现作用。

### **处理要求 7: 严格禁止**
*   **禁止输出非提示词内容**: 只输出纯粹的英文提示词。
*   **禁止添加质量词**: 不自动添加 masterpiece, best quality, 8k 等质量标签。
*   **禁止自主发挥**: 严格按照用户描述转换，不添加任何个人理解或补充。

---
### **# 示例 (简洁自然语言)**

#### **示例 1: 简单场景描述**
*   **用户输入**: "画一个女孩在雨中哭泣"
*   **输出**: `girl crying in rain, {{{{{{{{{{solo}}}}}}}}}}, 1girl`

#### **示例 2: 角色 + 用户具体描述**
*   **用户输入**: "画雷姆穿着白色连衣裙站在花园里"
*   **输出**: `rem (re zero) in white dress, standing in garden, {{{{{{{{{{solo}}}}}}}}}}, 1girl`

#### **示例 3: 自然语言场景**
*   **用户输入**: "画一个宇航员在红色星球上发现发光的花"
*   **输出**: `astronaut discovering glowing flower on red planet, {{{{{{{{{{solo}}}}}}}}}}, 1girl`

#### **示例 4: 角色但无额外描述**
*   **用户输入**: "画初音未来"
*   **输出**: `hatsune miku (vocaloid), {{{{{{{{{{solo}}}}}}}}}}, 1girl`

#### **示例 5: 非人物场景**
*   **用户输入**: "画一个美丽的日落海滩"
*   **输出**: `beautiful sunset beach, golden light on waves`

#### **示例 6: 复杂场景简化**
*   **用户输入**: "画一个穿着校服的女学生坐在教室里看书"
*   **输出**: `schoolgirl in uniform reading book in classroom, {{{{{{{{{{solo}}}}}}}}}}, 1girl`
""".strip()

_PROMPT_GENERATOR_TEMPLATE = f"""
{_PROMPT_RULES_TEXT}

【用户描述】
<<USER_REQUEST>>
<<SELFIE_HINT>>
""".strip()


class NaiDrawCommand(AutoRecallMixin, BaseCommand):
    """NovelAI 快速生图命令：/nai [描述]"""

    command_name = "nai_draw"
    command_description = "使用自然语言描述生成图片，例如：/nai 画一张初音未来"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+(?P<description>.+)$"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_client = NaiWebClient(self)

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行 /nai 命令"""
        logger.info(f"{self.log_prefix} 执行 /nai 命令")

        # 检查用户权限
        has_permission = self._check_user_permission()
        if not has_permission:
            await self.send_text("❌ 当前会话已开启管理员模式，仅管理员可使用此命令", storage_message=False)
            return False, "没有权限", True

        # 获取用户输入的描述
        description = self.matched_groups.get("description", "").strip()

        if not description:
            await self.send_text("请输入你想画的内容，例如：/nai 画一张初音未来")
            return False, "未提供描述", True

        # 检测是否为自拍模式
        selfie_mode = "自拍" in description or "selfie" in description.lower()

        # 使用 LLM 生成提示词
        generated_prompt = await self._generate_prompt_with_llm(selfie_mode, description)

        if not generated_prompt:
            logger.warning(f"{self.log_prefix} LLM 提示词生成失败")
            await self.send_text("提示词生成失败，请稍后再试~")
            return False, "提示词生成失败", True

        logger.info(f"{self.log_prefix} 生成的提示词: {generated_prompt}")

        # 处理自拍模式
        if selfie_mode:
            generated_prompt = self._process_selfie_prompt(generated_prompt)

        # 获取模型配置
        model_config = self._get_model_config()
        if not model_config or not model_config.get("base_url"):
            await self.send_text("NovelAI 配置错误，请检查配置文件")
            return False, "配置错误", True

        # 获取图片尺寸
        image_size = model_config.get("nai_size") or model_config.get("default_size", "1024x1280")

        # 显示处理信息
        enable_debug = self.get_config("components.enable_debug_info", False)
        if enable_debug:
            await self.send_text(f"正在生成图片，请稍候...")

        try:
            # 调用 API 生成图片
            success, result = self.api_client.generate_image(
                prompt=generated_prompt,
                model_config=model_config,
                size=image_size
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 图片生成失败: {e!r}", exc_info=True)
            await self.send_text(f"生成图片时出错: {str(e)[:100]}")
            return False, f"生成失败: {e}", True

        if success:
            final_image_data = self._process_api_response(result)

            if final_image_data:
                send_time = time.time()

                # 判断是 URL 还是 base64
                if final_image_data.startswith(("http://", "https://")):
                    # 直接发送图片 URL（参考 lolicon 插件）
                    try:
                        send_success = await self.send_custom("imageurl", final_image_data)
                        if send_success:
                            self._last_send_timestamp = send_time
                            if enable_debug:
                                await self.send_text("图片生成完成！")
                            await self._schedule_auto_recall()
                            return True, "图片生成成功", True
                        else:
                            await self.send_text("图片发送失败")
                            return False, "发送失败", True
                    except Exception as e:
                        logger.error(f"{self.log_prefix} 图片URL发送失败: {e!r}")
                        await self.send_text(f"图片发送失败: {str(e)[:100]}")
                        return False, "发送失败", True
                elif final_image_data.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):
                    # Base64 格式 -> 保存为文件并以URL方式发送
                    image_path = save_base64_image_to_file(final_image_data)
                    if image_path:
                        send_success = await self.send_custom("imageurl", f"file://{image_path}")
                    else:
                        logger.warning(f"{self.log_prefix} 图片保存失败，回退为Base64发送")
                        send_success = await self.send_image(final_image_data)

                    if send_success:
                        self._last_send_timestamp = send_time
                        if enable_debug:
                            await self.send_text("图片生成完成！")
                        await self._schedule_auto_recall()
                        return True, "图片生成成功", True
                    else:
                        await self.send_text("图片发送失败")
                        return False, "发送失败", True
                else:
                    await self.send_text("API 返回了无法识别的图片格式")
                    return False, "数据格式错误", True
            else:
                await self.send_text("API 返回了无效的数据")
                return False, "数据格式错误", True
        else:
            await self.send_text(f"生成图片失败：{result}")
            return False, f"生成失败: {result}", True

    async def _generate_prompt_with_llm(self, selfie_mode: bool, request_text: str) -> Optional[str]:
        """使用 LLM 生成英文提示词"""
        generator_config = self._get_prompt_generator_config()

        # 准备提示词模板
        prompt_template = generator_config.get("prompt_template") or _PROMPT_GENERATOR_TEMPLATE
        prompt = self._render_generator_prompt(prompt_template, request_text, selfie_mode)

        # 获取 LLM 模型配置
        model_config = self._resolve_llm_model_config(generator_config.get("model_name", ""))
        if not model_config:
            logger.error(f"{self.log_prefix} 未找到可用的 LLM 模型")
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
            logger.error(f"{self.log_prefix} LLM 调用失败: {e}", exc_info=True)
            return None

        if not success or not response:
            logger.error(f"{self.log_prefix} LLM 生成失败")
            return None

        cleaned = self._cleanup_llm_prompt(response)
        return cleaned if cleaned else None

    def _render_generator_prompt(self, template: str, original_request: str, selfie_mode: bool) -> str:
        """渲染提示词生成模板"""
        selfie_hint = ""
        if selfie_mode:
            selfie_hint = (
                "\n\n【自拍模式】请确保提示词体现前置相机、近距离取景等自拍视角，同时严格遵守上述规则。"
            )

        prompt = template.replace("<<SELFIE_HINT>>", selfie_hint).strip()
        prompt = prompt.replace("<<USER_REQUEST>>", original_request.strip() or "N/A")
        return prompt

    def _resolve_llm_model_config(self, preferred_name: str):
        """获取可用的 LLM 模型配置"""
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
                logger.info(f"{self.log_prefix} 使用模型: {name}")
                return config

        fallback_name, fallback_config = next(iter(models.items()))
        logger.info(f"{self.log_prefix} 使用默认模型: {fallback_name}")
        return fallback_config

    def _cleanup_llm_prompt(self, prompt: str) -> str:
        """清理 LLM 返回的提示词"""
        if not prompt:
            return ""
        cleaned = prompt.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned.strip("`\n ")
        if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
            cleaned = cleaned[1:-1].strip()
        return cleaned

    def _get_prompt_generator_config(self) -> Dict[str, Any]:
        """获取提示词生成器配置"""
        config = self.get_config("prompt_generator", None)
        if config:
            return config
        legacy = self.get_config("prompt_fallback", None)
        return legacy or {}

    def _get_model_config(self) -> Dict[str, Any]:
        """获取模型配置"""
        model_config = self.get_config("model", {})
        if not model_config:
            return {}

        # 检查是否有用户选定的模型
        try:
            from .nai_admin_command import NaiAdminControlCommand

            platform = self.message.message_info.platform
            group_info = self.message.message_info.group_info

            if group_info and group_info.group_id:
                chat_id = group_info.group_id
            else:
                chat_id = self.message.message_info.user_info.user_id

            selected_model = NaiAdminControlCommand.get_selected_model(
                platform, chat_id, self.get_config
            )

            if selected_model:
                # 创建配置副本并覆盖模型
                model_config = dict(model_config)
                model_config["default_model"] = selected_model

                # 根据模型名称加载对应的提示词配置
                model_specific_config = self._get_model_specific_config(selected_model)
                if model_specific_config:
                    # 用模型特定配置覆盖默认配置中的提示词部分
                    model_config.update(model_specific_config)
                    logger.info(f"{self.log_prefix} 使用模型特定配置: {selected_model}")

                logger.info(f"{self.log_prefix} 使用选定的模型: {selected_model}")
        except Exception as e:
            logger.error(f"{self.log_prefix} 获取选定模型时出错: {e}", exc_info=True)

        return model_config

    def _get_model_specific_config(self, model_name: str) -> Optional[Dict[str, Any]]:
        """根据模型名称获取特定配置"""
        if not model_name:
            return None

        # NAI V3 系列（包括 nai-diffusion-3 和 nai-diffusion-3-furry）
        if model_name.startswith("nai-diffusion-3"):
            nai3_config = self.get_config("model_nai3", {})
            if nai3_config:
                config = {
                    "nai_artist_prompt": nai3_config.get("nai_artist_prompt", ""),
                    "custom_prompt_add": nai3_config.get("custom_prompt_add", ""),
                    "negative_prompt_add": nai3_config.get("negative_prompt_add", "")
                }
                # 检查用户选定的画师串
                selected_artist = self._get_selected_artist_preset(model_name)
                if selected_artist:
                    config["nai_artist_prompt"] = selected_artist
                return config

        # NAI V4 系列（nai-diffusion-4-* 系列）
        elif model_name.startswith("nai-diffusion-4"):
            nai4_config = self.get_config("model_nai4", {})
            if nai4_config:
                config = {
                    "nai_artist_prompt": nai4_config.get("nai_artist_prompt", ""),
                    "custom_prompt_add": nai4_config.get("custom_prompt_add", ""),
                    "negative_prompt_add": nai4_config.get("negative_prompt_add", "")
                }
                # 检查用户选定的画师串
                selected_artist = self._get_selected_artist_preset(model_name)
                if selected_artist:
                    config["nai_artist_prompt"] = selected_artist
                return config

        return None

    def _get_selected_artist_preset(self, model_name: str) -> Optional[str]:
        """获取用户选定的画师串"""
        try:
            from .nai_admin_command import NaiAdminControlCommand

            platform = self.message.message_info.platform
            group_info = self.message.message_info.group_info

            if group_info and group_info.group_id:
                chat_id = group_info.group_id
            else:
                chat_id = self.message.message_info.user_info.user_id

            return NaiAdminControlCommand.get_selected_artist_preset(
                platform, chat_id, model_name, self.get_config
            )
        except Exception as e:
            logger.warning(f"{self.log_prefix} 获取用户选定画师串失败: {e}")
            return None

    def _process_api_response(self, result: str) -> Optional[str]:
        """处理 API 响应"""
        if not result:
            return None

        if result.startswith(("http://", "https://")):
            return result

        if result.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):
            return result

        if "," in result and result.startswith("data:image"):
            return result.split(",", 1)[1]

        return result

    def _process_selfie_prompt(self, description: str) -> str:
        """处理自拍模式的提示词"""
        model_config = self._get_model_config()
        selfie_prompt_add = model_config.get("selfie_prompt_add", "") if model_config else ""

        if selfie_prompt_add:
            return f"{selfie_prompt_add}, {description}"
        return description

    def _is_auto_recall_enabled(self, platform: str, chat_id: str) -> bool:
        """检查是否启用自动撤回"""
        from .nai_recall_command import NaiRecallControlCommand
        return NaiRecallControlCommand.is_recall_enabled(platform, chat_id, self.get_config)

    def _check_user_permission(self) -> bool:
        """检查当前用户是否有权限使用生图命令"""
        try:
            from .nai_admin_command import NaiAdminControlCommand

            # 获取会话信息
            platform = self.message.message_info.platform
            group_info = self.message.message_info.group_info
            user_info = self.message.message_info.user_info

            if group_info and group_info.group_id:
                chat_id = group_info.group_id
            else:
                chat_id = user_info.user_id

            user_id = user_info.user_id

            # 检查用户权限
            return NaiAdminControlCommand.check_user_permission(
                platform, chat_id, user_id, self.get_config
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查用户权限时出错: {e}", exc_info=True)
            # 出错时默认允许
            return True

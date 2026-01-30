# -*- coding: utf-8 -*-
"""
/nai 命令：使用自然语言描述生成图片
"""
import re
import time
from typing import Tuple, Optional, Dict, Any

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger
from src.plugin_system import llm_api

from ..clients.nai_web_client import NaiWebClient
from ..mixins.auto_recall_mixin import AutoRecallMixin
from ..utils.image_url_helper import save_base64_image_to_file
from ..mixins.model_config_mixin import ModelConfigMixin
from ..rules.prompt_rules import PROMPT_GENERATOR_TEMPLATE, SFW_PROMPT_GENERATOR_TEMPLATE
from ..services.session_state import session_state

logger = get_logger("nai_pic_plugin")


class NaiDrawCommand(ModelConfigMixin, AutoRecallMixin, BaseCommand):
    """NovelAI 快速生图命令：/nai [描述]"""

    command_name = "nai_draw"
    command_description = "使用自然语言描述生成图片，例如：/nai 画一张初音未来"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+(?!on$|off$|st$|sp$|set\b|art\b|artgen\b|artr$|artfix\b|size\b|help$|pt\s|nsfw\b)(?P<description>.+)$"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_client = NaiWebClient(self)

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行 /nai 命令"""
        logger.info(f"{self.log_prefix} [LLM生图] 收到请求")

        # 检查用户权限
        has_permission = self._check_user_permission()
        if not has_permission:
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
            logger.warning(f"{self.log_prefix} [LLM生图] 提示词生成失败")
            await self.send_text("提示词生成失败，请稍后再试~")
            return False, "提示词生成失败", True

        logger.info(f"{self.log_prefix} [LLM生图] 提示词: {generated_prompt}")

        # 检查是否需要显示提示词
        if self._is_prompt_show_enabled():
            await self.send_text(f"📝 提示词:\n{generated_prompt}", storage_message=False)

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
            # 调用 API 生成图片（异步，不阻塞事件循环）
            success, result = await self.api_client.generate_image(
                prompt=generated_prompt,
                model_config=model_config,
                size=image_size
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [LLM生图] 图片生成失败: {e!r}", exc_info=True)
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
                        logger.error(f"{self.log_prefix} [LLM生图] 图片URL发送失败: {e!r}")
                        await self.send_text(f"图片发送失败: {str(e)[:100]}")
                        return False, "发送失败", True
                elif final_image_data.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):
                    # Base64 格式 -> 保存为文件并以URL方式发送
                    image_path = save_base64_image_to_file(final_image_data)
                    if image_path:
                        send_success = await self.send_custom("imageurl", f"file://{image_path}")
                    else:
                        logger.warning(f"{self.log_prefix} [LLM生图] 图片保存失败，回退为Base64发送")
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

        # 检查是否启用 NSFW 过滤，选择对应模板
        try:
            platform, chat_id, _ = self._get_chat_identity()
            nsfw_filter_enabled = False
            if platform and chat_id:
                nsfw_filter_enabled = session_state.is_nsfw_filter_enabled(platform, chat_id, self.get_config)
        except Exception:
            nsfw_filter_enabled = False

        # 根据过滤状态选择模板
        if nsfw_filter_enabled:
            default_template = SFW_PROMPT_GENERATOR_TEMPLATE
        else:
            default_template = PROMPT_GENERATOR_TEMPLATE

        prompt_template = generator_config.get("prompt_template") or default_template
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
                    logger.info(f"{self.log_prefix} 使用自定义模型配置: {model_list}")
                    return custom_task_config
                except Exception as e:
                    logger.warning(f"{self.log_prefix} 自定义模型配置创建失败: {e}，回退到系统模型")

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
        return session_state.is_recall_enabled(platform, chat_id, self.get_config)

    def _is_prompt_show_enabled(self) -> bool:
        """检查是否启用提示词显示"""
        try:
            platform, chat_id, _ = self._get_chat_identity()
            if not platform or not chat_id:
                return False
            return session_state.is_prompt_show_enabled(platform, chat_id, self.get_config)
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查提示词显示状态时出错: {e}")
            return False

    def _check_user_permission(self) -> bool:
        """检查当前用户是否有权限使用生图命令"""
        try:
            platform, chat_id, user_id = self._get_chat_identity()
            if not platform or not chat_id or not user_id:
                logger.warning(f"{self.log_prefix} 无法获取会话信息，默认允许")
                return True
            return session_state.check_user_permission(platform, chat_id, user_id, self.get_config)
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查用户权限时出错: {e}", exc_info=True)
            return True

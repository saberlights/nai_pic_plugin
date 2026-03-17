# -*- coding: utf-8 -*-
"""
提示词生成服务

统一处理 LLM 提示词生成逻辑，消除 NaiPicAction 和 NaiDrawCommand 中的重复代码

主要功能：
- 使用 LLM 生成英文提示词
- 渲染提示词模板
- 清理 LLM 响应
- 处理 NSFW 过滤
"""
import re
from typing import Optional, Dict, Any, Callable

from src.common.logger import get_logger
from src.plugin_system import llm_api

from .session_state import session_state
from ..rules.selfie_rules import get_selfie_hint
from ..utils.prompt_output_parser import parse_prompt_from_structured_output
from ..utils.prompt_postprocessor import normalize_prompt_order

logger = get_logger("nai_pic_plugin")


class PromptGeneratorService:
    """
    提示词生成服务

    使用方式：
        service = PromptGeneratorService(self.get_config, self.log_prefix)
        prompt = await service.generate_prompt(
            request_text="画一张初音未来",
            is_selfie=False,
            platform="qq",
            chat_id="123456"
        )
    """

    def __init__(self, get_config: Callable, log_prefix: str = ""):
        """
        Args:
            get_config: 获取配置的函数（通常是 self.get_config）
            log_prefix: 日志前缀
        """
        self.get_config = get_config
        self.log_prefix = log_prefix

    async def generate_prompt(
        self,
        request_text: str,
        is_selfie: bool = False,
        platform: str = "",
        chat_id: str = ""
    ) -> Optional[str]:
        """
        使用 LLM 生成英文提示词

        Args:
            request_text: 用户原始请求
            is_selfie: 是否自拍模式
            platform: 平台标识（用于检查 NSFW 过滤）
            chat_id: 会话ID（用于检查 NSFW 过滤）

        Returns:
            生成的提示词，失败返回 None
        """
        if not request_text or not request_text.strip():
            logger.warning(f"{self.log_prefix} 请求文本为空，无法生成提示词")
            return None

        generator_config = self._get_generator_config()

        # 检查是否启用 NSFW 过滤，选择对应模板
        nsfw_filter_enabled = False
        if platform and chat_id:
            try:
                nsfw_filter_enabled = session_state.is_nsfw_filter_enabled(platform, chat_id, self.get_config)
            except Exception:
                pass

        # 获取提示词模板
        prompt_template = generator_config.get("prompt_template")
        if not prompt_template:
            # 从 rules 模块导入默认模板
            try:
                from ..rules.prompt_rules import (
                    PROMPT_GENERATOR_TEMPLATE,
                    SFW_PROMPT_GENERATOR_TEMPLATE,
                    PROMPT_GENERATOR_JSON_TEMPLATE,
                    SFW_PROMPT_GENERATOR_JSON_TEMPLATE,
                )
                output_format = (generator_config.get("output_format") or "text").strip().lower()
                if nsfw_filter_enabled:
                    prompt_template = (
                        SFW_PROMPT_GENERATOR_JSON_TEMPLATE
                        if output_format == "json"
                        else SFW_PROMPT_GENERATOR_TEMPLATE
                    )
                else:
                    prompt_template = (
                        PROMPT_GENERATOR_JSON_TEMPLATE
                        if output_format == "json"
                        else PROMPT_GENERATOR_TEMPLATE
                    )
            except ImportError:
                # 兼容旧路径
                from ..prompt_rules import PROMPT_GENERATOR_TEMPLATE
                prompt_template = PROMPT_GENERATOR_TEMPLATE

        # 渲染模板
        prompt = self._render_template(prompt_template, request_text, is_selfie)

        # 获取 LLM 模型配置
        model_config = self._resolve_model_config(generator_config.get("model_name", ""))
        if not model_config:
            logger.error(f"{self.log_prefix} 未找到可用的 LLM 模型，提示词生成失败")
            return None

        # 调用 LLM
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
            logger.error(
                f"{self.log_prefix} LLM 生成失败，模型={model_name or 'unknown'}，响应={response or '无'}"
            )
            return None

        # 清理响应
        cleaned = self._cleanup_response(response)
        if not cleaned:
            return None

        if self.get_config("prompt_generator.enforce_tag_order", False):
            cleaned = normalize_prompt_order(cleaned)

        return cleaned

    def _get_generator_config(self) -> Dict[str, Any]:
        """获取提示词生成器配置，兼容新旧配置节"""
        return self.get_config("prompt_generator", None) or {}

    def _render_template(
        self,
        template: str,
        request: str,
        is_selfie: bool = False
    ) -> str:
        """渲染提示词模板"""
        # 获取自定义系统提示词
        custom_system_prompt = self.get_config("custom_prompt.system_prompt", "") or ""
        if custom_system_prompt:
            custom_system_prompt = custom_system_prompt.strip() + "\n\n"

        # 永远注入自拍提示，由 LLM 自行判断是否为自拍意图
        selfie_hint = get_selfie_hint()

        prompt = template.replace("<<CUSTOM_SYSTEM_PROMPT>>", custom_system_prompt).strip()
        prompt = prompt.replace("<<PREVIOUS_PROMPT>>", "").strip()
        prompt = prompt.replace("<<CURRENT_TIME_CONTEXT>>", "").strip()
        prompt = prompt.replace("<<SELFIE_HINT>>", selfie_hint).strip()
        prompt = prompt.replace("<<USER_REQUEST>>", request.strip() or "N/A")
        return prompt

    def _resolve_model_config(self, preferred_name: str):
        """
        获取可用的 LLM 模型配置

        优先级：
        1. 自定义模型配置（custom_model）
        2. 指定的模型名称（preferred_name）
        3. 系统模型（planner, replyer）
        4. 任意可用模型
        """
        # 检查自定义模型配置
        generator_config = self._get_generator_config()
        custom_model = generator_config.get("custom_model")

        if custom_model and isinstance(custom_model, dict):
            model_list = custom_model.get("model_list", [])
            if model_list:
                try:
                    from src.config.api_ada_configs import TaskConfig
                    custom_task_config = TaskConfig(
                        model_list=model_list if isinstance(model_list, list) else [model_list],
                        max_tokens=custom_model.get("max_tokens", 1024),
                        temperature=custom_model.get("temperature", 0.3),
                        slow_threshold=custom_model.get("slow_threshold", 30.0),
                        selection_strategy="random"  # 固定使用随机选择
                    )
                    logger.info(f"{self.log_prefix} 提示词生成使用自定义模型配置: {model_list}")
                    return custom_task_config
                except Exception as e:
                    logger.warning(f"{self.log_prefix} 自定义模型配置创建失败: {e}，回退到系统模型")

        # 回退到系统模型
        models = llm_api.get_available_models()
        if not models:
            return None

        # 尝试按优先级获取模型
        candidate_names = []
        if preferred_name:
            candidate_names.append(preferred_name)
        candidate_names.extend(["planner", "replyer"])

        for name in candidate_names:
            config = models.get(name)
            if config:
                if name == preferred_name:
                    logger.info(f"{self.log_prefix} 提示词生成使用指定模型: {name}")
                else:
                    logger.info(f"{self.log_prefix} 提示词生成使用系统模型: {name}")
                return config

        # 使用任意可用模型
        fallback_name, fallback_config = next(iter(models.items()))
        logger.info(f"{self.log_prefix} 提示词生成使用回退模型: {fallback_name}")
        return fallback_config

    def _cleanup_response(self, prompt: str) -> str:
        """
        清理 LLM 返回的提示词

        处理：
        - 代码块包裹
        - 引号包裹
        - 常见前缀
        - 多行内容
        """
        if not prompt:
            return ""

        # 优先尝试解析结构化 JSON 输出（成功则不再做文本清洗，避免误伤多人 | 分段）
        parsed = parse_prompt_from_structured_output(prompt)
        if parsed:
            logger.debug(f"{self.log_prefix} 结构化提示词解析命中（JSON->prompt），将跳过文本清洗")
            return parsed

        cleaned = prompt.strip()

        # 处理代码块包裹 ```...```
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

        # 处理单行代码包裹 `...`
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

# -*- coding: utf-8 -*-
"""
/nai art 命令：使用 LLM 生成画师串
"""
import asyncio
import re
import time
from typing import Tuple, Optional, Dict, Any, List

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger
from src.plugin_system import llm_api

from .model_config_mixin import ModelConfigMixin
from .artist_rules import (
    ARTIST_GENERATOR_TEMPLATE,
    RANDOM_GENERATION_HINT,
    POPULAR_ARTISTS_TEMPLATE,
    ARTIST_ITERATE_TEMPLATE
)
from .danbooru_api import (
    DanbooruAPI,
    extract_artist_names_from_prompt,
    validate_artist_prompt,
    get_artist_quality_score,
    format_validation_result,
    suggest_similar_artists,
    suggest_corrections_for_invalid
)

logger = get_logger("nai_pic_plugin")

# 会话画师串缓存：{chat_id: {"prompt": str, "timestamp": float, "model_version": str}}
# 用于迭代优化功能
_artist_session_cache: Dict[str, Dict[str, Any]] = {}
# 缓存过期时间（秒）
_CACHE_EXPIRE_SECONDS = 3600  # 1小时


class NaiArtistCommand(ModelConfigMixin, BaseCommand):
    """NovelAI 画师串生成命令：/nai artgen [风格描述]、/nai artr（随机）、/nai artfix <反馈>（迭代优化）"""

    command_name = "nai_artist"
    command_description = "使用LLM生成画师串，例如：/nai artgen 可爱萌系风格，/nai artr 随机生成，/nai artfix 线条太粗（迭代优化）"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+(?:artgen(?:\s+(?P<style>.+))?|artr|artfix(?:\s+(?P<feedback>.+))?)$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行 /nai artist 命令"""
        raw_text = self.message.processed_plain_text if self.message else ""

        # 判断命令类型
        is_random = "artr" in raw_text
        is_fix = "artfix" in raw_text

        if is_fix:
            return await self._execute_artfix()

        logger.info(f"{self.log_prefix} 执行 /nai artgen 命令")

        # 获取用户输入的风格描述
        style = self.matched_groups.get("style", "").strip() if self.matched_groups.get("style") else ""

        if not style and not is_random:
            # /nai artgen 无参数时提示用法
            await self.send_text(
                "用法：\n"
                "/nai artgen <风格描述> - LLM生成画师串\n"
                "/nai artr - 随机生成画师串\n"
                "/nai artfix <反馈> - 迭代优化上次的画师串"
            )
            return True, "显示用法", True

        if is_random:
            style = "随机"

        logger.info(f"{self.log_prefix} 风格描述: {style}, 随机模式: {is_random}")

        # 获取当前模型版本
        model_version = self._get_current_model_version()

        # 使用 LLM 生成画师串（带验证和重试）
        artist_prompt, validation_info = await self._generate_and_validate_artist(
            style, model_version, is_random
        )

        if not artist_prompt:
            await self.send_text("画师串生成失败，请稍后再试~")
            return False, "画师串生成失败", True

        # 缓存生成的画师串，用于后续迭代优化
        self._save_artist_to_cache(artist_prompt, model_version)

        # 构建输出
        mode_text = "🎲 随机" if is_random else f"🎨 {style}"
        output_lines = [f"{mode_text}\n", artist_prompt]

        # 添加验证信息
        if validation_info:
            output_lines.append(f"\n{validation_info}")

        output_lines.append("\n💡 使用 /nai artfix <反馈> 可迭代优化")

        await self.send_text("\n".join(output_lines))
        return True, "画师串生成成功", True

    async def _generate_and_validate_artist(
        self, style: str, model_version: str, is_random: bool, max_retries: int = 1
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        生成画师串并验证，如有无效画师则重试

        Returns:
            (画师串, 验证信息文本)
        """
        danbooru_api = DanbooruAPI(timeout=15)
        invalid_artists_feedback = ""

        for attempt in range(max_retries + 1):
            # 生成画师串
            artist_prompt = await self._generate_artist_with_llm(
                style, model_version, is_random, invalid_artists_feedback,
                danbooru_api=danbooru_api
            )

            if not artist_prompt:
                return None, None

            # 清理格式
            artist_prompt = self._cleanup_artist_prompt(artist_prompt)

            # 验证画师（使用 asyncio.to_thread 避免阻塞事件循环）
            try:
                all_valid, valid_artists, invalid_artists = await asyncio.to_thread(
                    validate_artist_prompt, artist_prompt, danbooru_api
                )

                if all_valid:
                    # 全部有效，返回带评级和预警的信息
                    validation_info = self._format_artist_grades(valid_artists)
                    return artist_prompt, validation_info

                elif attempt < max_retries and invalid_artists:
                    # 有无效画师且还有重试次数，准备反馈给 LLM
                    feedback_parts = [f"以下画师在 Danbooru 中不存在，请更换：{', '.join(invalid_artists)}"]

                    # 尝试模糊搜索纠正拼写错误（使用 asyncio.to_thread）
                    corrections = await asyncio.to_thread(
                        suggest_corrections_for_invalid, invalid_artists, danbooru_api
                    )
                    correction_hints = [f"{wrong} → {right}" for wrong, right in corrections.items() if right]
                    if correction_hints:
                        feedback_parts.append(f"可能的正确拼写：{', '.join(correction_hints)}")

                    # 使用已验证的有效画师来推荐相似画师作为替换建议
                    if valid_artists:
                        valid_names = [a.get("name", "") for a in valid_artists if a.get("name")]
                        suggested_replacements = await asyncio.to_thread(
                            suggest_similar_artists, valid_names, danbooru_api
                        )
                        if suggested_replacements:
                            feedback_parts.append(f"或使用这些风格相似的画师：{', '.join(suggested_replacements[:5])}")

                    invalid_artists_feedback = "\n".join(feedback_parts)
                    logger.info(f"{self.log_prefix} 发现无效画师，重试: {invalid_artists}，纠正建议: {correction_hints}")
                    continue

                else:
                    # 最后一次尝试，尝试自动纠正并补充画师串
                    corrected_prompt = artist_prompt
                    corrections_applied = []
                    substitutions_applied = []

                    if invalid_artists:
                        # 先尝试模糊搜索纠正拼写（使用 asyncio.to_thread）
                        corrections = await asyncio.to_thread(
                            suggest_corrections_for_invalid, invalid_artists, danbooru_api
                        )

                        # 获取相似画师作为替换候选
                        similar_candidates = []
                        if valid_artists:
                            valid_names = [a.get("name", "") for a in valid_artists if a.get("name")]
                            similar_candidates = await asyncio.to_thread(
                                suggest_similar_artists, valid_names, danbooru_api
                            )

                        similar_idx = 0
                        for wrong in invalid_artists:
                            right = corrections.get(wrong)
                            if right:
                                # 拼写纠正
                                corrected_prompt = corrected_prompt.replace(f"artist:{wrong}", f"artist:{right}")
                                corrections_applied.append(f"{wrong} → {right}")
                            elif similar_idx < len(similar_candidates):
                                # 用相似画师替换无效画师
                                replacement = similar_candidates[similar_idx]
                                corrected_prompt = corrected_prompt.replace(f"artist:{wrong}", f"artist:{replacement}")
                                substitutions_applied.append(f"{wrong} → {replacement}")
                                similar_idx += 1

                    # 重新验证纠正后的画师串（使用 asyncio.to_thread）
                    if corrections_applied or substitutions_applied:
                        all_valid_new, valid_artists_new, invalid_artists_new = await asyncio.to_thread(
                            validate_artist_prompt, corrected_prompt, danbooru_api
                        )
                        if all_valid_new or len(invalid_artists_new) < len(invalid_artists):
                            artist_prompt = corrected_prompt
                            valid_artists = valid_artists_new
                            invalid_artists = invalid_artists_new

                    # 构建验证信息
                    validation_info = format_validation_result(valid_artists, invalid_artists)

                    if corrections_applied:
                        validation_info += f"\n\n🔧 拼写纠正：{', '.join(corrections_applied)}"

                    if substitutions_applied:
                        validation_info += f"\n\n🔄 相似替换：{', '.join(substitutions_applied)}"

                    return artist_prompt, validation_info

            except Exception as e:
                logger.warning(f"{self.log_prefix} Danbooru 验证失败: {e}")
                # 验证失败时直接返回，不阻塞
                return artist_prompt, "⚠️ 画师验证跳过（API 超时）"

        return None, None

    def _format_artist_grades(self, valid_artists: List[Dict]) -> str:
        """格式化画师评级信息，包含低稳定性预警"""
        if not valid_artists:
            return ""

        lines = ["📊 画师稳定性："]
        low_stability_artists = []

        for info in valid_artists:
            name = info.get("name", "unknown")
            count = info.get("post_count", 0)
            grade = get_artist_quality_score(info)
            lines.append(f"  • {name} [{grade}] ({count:,})")

            # 记录低稳定性画师
            if grade in ("C", "D"):
                low_stability_artists.append(name)

        # 添加低稳定性预警
        if low_stability_artists:
            lines.append("")
            if len(low_stability_artists) == 1:
                lines.append(f"⚠️ {low_stability_artists[0]} 帖子数较少，效果可能不稳定")
            else:
                lines.append(f"⚠️ {', '.join(low_stability_artists)} 帖子数较少，效果可能不稳定")

        return "\n".join(lines)

    def _get_current_model_version(self) -> str:
        """获取当前使用的模型版本"""
        model_config = self._get_model_config()
        if not model_config:
            return "nai4.5"

        default_model = model_config.get("default_model", "nai-diffusion-4-5-full")

        if "nai-diffusion-3" in default_model:
            return "nai3"
        elif "nai-diffusion-4-5" in default_model:
            return "nai4.5"
        else:
            return "nai4"

    async def _generate_artist_with_llm(
        self, style: str, model_version: str, is_random: bool, invalid_feedback: str = "",
        danbooru_api: DanbooruAPI = None
    ) -> Optional[str]:
        """使用 LLM 生成画师串"""
        generator_config = self._get_artist_generator_config()

        # 准备提示词
        prompt = ARTIST_GENERATOR_TEMPLATE
        prompt = prompt.replace("<<USER_REQUEST>>", style)
        prompt = prompt.replace("<<MODEL_VERSION>>", model_version)

        # 处理随机提示和无效反馈
        extra_hint = ""
        if is_random:
            random_hint = RANDOM_GENERATION_HINT

            # 获取热门画师列表作为参考（使用 asyncio.to_thread 避免阻塞）
            popular_artists_hint = ""
            try:
                if danbooru_api is None:
                    danbooru_api = DanbooruAPI(timeout=15)
                popular = await asyncio.to_thread(danbooru_api.get_popular_artists, 30)
                if popular:
                    artist_names = [a.get("name", "") for a in popular if a.get("name")]
                    if artist_names:
                        popular_artists_hint = POPULAR_ARTISTS_TEMPLATE.format(
                            artists=", ".join(artist_names[:20])
                        )
            except Exception as e:
                logger.warning(f"{self.log_prefix} 获取热门画师失败: {e}")

            random_hint = random_hint.replace("<<POPULAR_ARTISTS_HINT>>", popular_artists_hint)
            extra_hint = random_hint

        if invalid_feedback:
            extra_hint += f"\n\n【重要修正】{invalid_feedback}"

        prompt = prompt.replace("<<RANDOM_HINT>>", extra_hint)

        # 获取 LLM 模型配置
        model_config = self._resolve_llm_model_config(
            generator_config.get("model_name", ""), generator_config
        )
        if not model_config:
            logger.error(f"{self.log_prefix} 未找到可用的 LLM 模型")
            return None

        # 温度设置：随机模式使用 random_temperature，否则使用 temperature
        if is_random:
            temperature = generator_config.get("random_temperature", 0.7)
        else:
            temperature = generator_config.get("temperature", 0.3)
        max_tokens = generator_config.get("max_tokens", 200)

        try:
            success, response, reasoning, model_name = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="nai_pic_plugin.artist_generator",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} LLM 调用失败: {e}", exc_info=True)
            return None

        if not success or not response:
            logger.error(f"{self.log_prefix} LLM 生成失败")
            return None

        return response

    def _cleanup_artist_prompt(self, prompt: str) -> str:
        """清理 LLM 返回的画师串"""
        if not prompt:
            return ""

        cleaned = prompt.strip()

        # 移除代码块
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3].strip()
            if "\n" in cleaned:
                first_line, rest = cleaned.split("\n", 1)
                if first_line.strip().isalpha() and len(first_line.strip()) < 15:
                    cleaned = rest.strip()

        # 移除单行代码包裹
        if cleaned.startswith("`") and cleaned.endswith("`"):
            cleaned = cleaned[1:-1].strip()

        # 移除引号包裹
        if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')):
            cleaned = cleaned[1:-1].strip()

        # 移除常见前缀
        prefix_patterns = [
            r"^(?:output|result|artist prompt|here(?:'s| is))\s*[:：]\s*",
            r"^(?:the )?(?:generated )?(?:artist )?prompt\s*(?:is|:)\s*",
        ]
        for pattern in prefix_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

        # 只取第一行（如果有多行解释）
        if "\n" in cleaned:
            lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
            valid_lines = []
            for line in lines:
                # 跳过解释性文字
                if re.match(r"^(note|explanation|this|i |the above|here|这|说明)", line, re.IGNORECASE):
                    continue
                valid_lines.append(line)
            if valid_lines:
                cleaned = valid_lines[0]

        return cleaned

    def _get_prompt_generator_config(self) -> Dict[str, Any]:
        """获取提示词生成器配置"""
        config = self.get_config("prompt_generator", None)
        if config:
            return config
        legacy = self.get_config("prompt_fallback", None)
        return legacy or {}

    def _get_artist_generator_config(self) -> Dict[str, Any]:
        """获取画师串生成器配置"""
        config = self.get_config("artist_generator", None)
        if config:
            return config
        # 回退到 prompt_generator 配置
        return self._get_prompt_generator_config()

    def _resolve_llm_model_config(self, preferred_name: str, generator_config: Dict[str, Any] = None):
        """获取可用的 LLM 模型配置"""
        if generator_config is None:
            generator_config = self._get_prompt_generator_config()
        custom_model = generator_config.get("custom_model")

        if custom_model and isinstance(custom_model, dict):
            model_list = custom_model.get("model_list", [])
            if model_list:
                from src.config.api_ada_configs import TaskConfig
                try:
                    custom_task_config = TaskConfig(
                        model_list=model_list if isinstance(model_list, list) else [model_list],
                        max_tokens=custom_model.get("max_tokens", 1024),
                        temperature=custom_model.get("temperature", 0.3),
                        slow_threshold=custom_model.get("slow_threshold", 30.0),
                        selection_strategy=custom_model.get("selection_strategy", "balance")
                    )
                    logger.info(f"{self.log_prefix} 使用自定义模型配置: {model_list}")
                    return custom_task_config
                except Exception as e:
                    logger.warning(f"{self.log_prefix} 自定义模型配置创建失败: {e}")

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

    async def _show_artist_presets(self) -> Tuple[bool, Optional[str], bool]:
        """显示当前画师预设列表"""
        model_config = self._get_model_config()
        if not model_config:
            await self.send_text("无法获取模型配置")
            return False, "配置错误", True

        # 获取当前模型版本名称
        default_model = model_config.get("default_model", "nai-diffusion-4-5-full")

        # 获取画师预设
        artist_presets = model_config.get("artist_presets", [])
        nai_artist_prompt = model_config.get("nai_artist_prompt", "")

        # 构建输出
        lines = [f"🎨 画师预设列表 ({default_model})\n"]

        if artist_presets:
            for i, preset in enumerate(artist_presets, 1):
                name = preset.get("name", f"预设{i}")
                prompt = preset.get("prompt", "")
                lines.append(f"{i}. {name}")
                lines.append(f"   {prompt}\n")
        elif nai_artist_prompt:
            lines.append(f"当前画师串：\n{nai_artist_prompt}")
        else:
            lines.append("暂无预设")

        lines.append("\n命令：")
        lines.append("/nai art <描述> - LLM生成画师串")
        lines.append("/nai artr - 随机生成画师串")
        lines.append("/nai artfix <反馈> - 迭代优化画师串")

        await self.send_text("\n".join(lines))
        return True, "显示画师预设列表", True

    # ==================== 迭代优化相关方法 ====================

    def _get_chat_id(self) -> str:
        """获取当前会话ID"""
        if self.message and hasattr(self.message, "chat_id"):
            return str(self.message.chat_id)
        return "default"

    def _save_artist_to_cache(self, artist_prompt: str, model_version: str) -> None:
        """保存画师串到会话缓存"""
        global _artist_session_cache
        chat_id = self._get_chat_id()
        _artist_session_cache[chat_id] = {
            "prompt": artist_prompt,
            "timestamp": time.time(),
            "model_version": model_version
        }
        logger.debug(f"{self.log_prefix} 画师串已缓存: {artist_prompt[:50]}...")

    def _get_artist_from_cache(self) -> Optional[Dict[str, Any]]:
        """从缓存获取画师串，返回 None 表示无缓存或已过期"""
        global _artist_session_cache
        chat_id = self._get_chat_id()
        cached = _artist_session_cache.get(chat_id)

        if not cached:
            return None

        # 检查是否过期
        if time.time() - cached.get("timestamp", 0) > _CACHE_EXPIRE_SECONDS:
            del _artist_session_cache[chat_id]
            return None

        return cached

    async def _execute_artfix(self) -> Tuple[bool, Optional[str], bool]:
        """执行 /nai artfix 命令 - 迭代优化画师串"""
        logger.info(f"{self.log_prefix} 执行 /nai artfix 命令")

        # 获取用户反馈
        feedback = self.matched_groups.get("feedback", "").strip() if self.matched_groups.get("feedback") else ""

        if not feedback:
            await self.send_text(
                "用法：/nai artfix <反馈描述>\n\n"
                "示例：\n"
                "• /nai artfix 线条太粗\n"
                "• /nai artfix 颜色太淡，想要更鲜艳\n"
                "• /nai artfix 风格不够萌\n"
                "• /nai artfix 某画师风格太强，弱化一下"
            )
            return True, "显示 artfix 用法", True

        # 获取缓存的画师串
        cached = self._get_artist_from_cache()
        if not cached:
            await self.send_text(
                "❌ 没有找到可优化的画师串\n\n"
                "请先使用以下命令生成画师串：\n"
                "• /nai artgen <风格描述>\n"
                "• /nai artr（随机生成）"
            )
            return False, "无缓存画师串", True

        original_prompt = cached["prompt"]
        model_version = cached.get("model_version", "nai4.5")

        logger.info(f"{self.log_prefix} 原画师串: {original_prompt}, 反馈: {feedback}")

        # 使用 LLM 迭代优化
        danbooru_api = DanbooruAPI(timeout=15)
        optimized_prompt, validation_info = await self._iterate_and_validate_artist(
            original_prompt, feedback, model_version, danbooru_api
        )

        if not optimized_prompt:
            await self.send_text("画师串优化失败，请稍后再试~")
            return False, "画师串优化失败", True

        # 更新缓存
        self._save_artist_to_cache(optimized_prompt, model_version)

        # 构建输出
        output_lines = [
            f"🔧 根据反馈「{feedback}」优化\n",
            f"原画师串：\n{original_prompt}\n",
            f"优化后：\n{optimized_prompt}"
        ]

        if validation_info:
            output_lines.append(f"\n{validation_info}")

        output_lines.append("\n💡 继续使用 /nai artfix <反馈> 可进一步优化")

        await self.send_text("\n".join(output_lines))
        return True, "画师串优化成功", True

    async def _iterate_and_validate_artist(
        self, original_prompt: str, feedback: str, model_version: str,
        danbooru_api: DanbooruAPI, max_retries: int = 1
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        迭代优化画师串并验证

        Returns:
            (优化后的画师串, 验证信息文本)
        """
        invalid_artists_feedback = ""

        # 获取原画师串中的画师信息（使用 asyncio.to_thread 避免阻塞）
        original_artists = extract_artist_names_from_prompt(original_prompt)
        artist_info_text = ""
        if original_artists:
            valid_infos = []
            for name in original_artists:
                info = await asyncio.to_thread(danbooru_api.search_artist, name)
                if info:
                    grade = get_artist_quality_score(info)
                    valid_infos.append(f"{name}[{grade}]({info.get('post_count', 0):,})")
            if valid_infos:
                artist_info_text = f"\n原画师串画师信息：{', '.join(valid_infos)}"

        for attempt in range(max_retries + 1):
            # 使用 LLM 迭代优化
            optimized_prompt = await self._iterate_artist_with_llm(
                original_prompt, feedback, model_version, artist_info_text, invalid_artists_feedback
            )

            if not optimized_prompt:
                return None, None

            # 清理格式
            optimized_prompt = self._cleanup_artist_prompt(optimized_prompt)

            # 验证画师（使用 asyncio.to_thread 避免阻塞）
            try:
                all_valid, valid_artists, invalid_artists = await asyncio.to_thread(
                    validate_artist_prompt, optimized_prompt, danbooru_api
                )

                if all_valid:
                    validation_info = self._format_artist_grades(valid_artists)
                    return optimized_prompt, validation_info

                elif attempt < max_retries and invalid_artists:
                    # 准备反馈给 LLM
                    feedback_parts = [f"以下画师在 Danbooru 中不存在，请更换：{', '.join(invalid_artists)}"]
                    corrections = await asyncio.to_thread(
                        suggest_corrections_for_invalid, invalid_artists, danbooru_api
                    )
                    correction_hints = [f"{wrong} → {right}" for wrong, right in corrections.items() if right]
                    if correction_hints:
                        feedback_parts.append(f"可能的正确拼写：{', '.join(correction_hints)}")

                    invalid_artists_feedback = "\n".join(feedback_parts)
                    logger.info(f"{self.log_prefix} 迭代优化发现无效画师，重试: {invalid_artists}")
                    continue

                else:
                    # 最后一次尝试，尝试自动纠正
                    corrected_prompt = optimized_prompt
                    corrections_applied = []

                    if invalid_artists:
                        corrections = await asyncio.to_thread(
                            suggest_corrections_for_invalid, invalid_artists, danbooru_api
                        )
                        for wrong in invalid_artists:
                            right = corrections.get(wrong)
                            if right:
                                corrected_prompt = corrected_prompt.replace(f"artist:{wrong}", f"artist:{right}")
                                corrections_applied.append(f"{wrong} → {right}")

                    if corrections_applied:
                        all_valid_new, valid_artists_new, invalid_artists_new = await asyncio.to_thread(
                            validate_artist_prompt, corrected_prompt, danbooru_api
                        )
                        if all_valid_new or len(invalid_artists_new) < len(invalid_artists):
                            optimized_prompt = corrected_prompt
                            valid_artists = valid_artists_new
                            invalid_artists = invalid_artists_new

                    validation_info = format_validation_result(valid_artists, invalid_artists)
                    if corrections_applied:
                        validation_info += f"\n\n🔧 拼写纠正：{', '.join(corrections_applied)}"

                    return optimized_prompt, validation_info

            except Exception as e:
                logger.warning(f"{self.log_prefix} Danbooru 验证失败: {e}")
                return optimized_prompt, "⚠️ 画师验证跳过（API 超时）"

        return None, None

    async def _iterate_artist_with_llm(
        self, original_prompt: str, feedback: str, model_version: str,
        artist_info: str = "", invalid_feedback: str = ""
    ) -> Optional[str]:
        """使用 LLM 迭代优化画师串"""
        generator_config = self._get_artist_generator_config()

        # 准备提示词
        prompt = ARTIST_ITERATE_TEMPLATE
        prompt = prompt.replace("<<ORIGINAL_PROMPT>>", original_prompt)
        prompt = prompt.replace("<<USER_FEEDBACK>>", feedback)
        prompt = prompt.replace("<<MODEL_VERSION>>", model_version)
        prompt = prompt.replace("<<ARTIST_INFO>>", artist_info)

        if invalid_feedback:
            prompt += f"\n\n【重要修正】{invalid_feedback}"

        # 获取 LLM 模型配置
        model_config = self._resolve_llm_model_config(
            generator_config.get("model_name", ""), generator_config
        )
        if not model_config:
            logger.error(f"{self.log_prefix} 未找到可用的 LLM 模型")
            return None

        temperature = generator_config.get("temperature", 0.3)
        max_tokens = generator_config.get("max_tokens", 200)

        try:
            success, response, reasoning, model_name = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="nai_pic_plugin.artist_iterator",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} LLM 调用失败: {e}", exc_info=True)
            return None

        if not success or not response:
            logger.error(f"{self.log_prefix} LLM 迭代优化失败")
            return None

        return response

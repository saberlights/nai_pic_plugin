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

from ..mixins.model_config_mixin import ModelConfigMixin
from ..rules.artist_rules import (
    EXTRACT_TAGS_TEMPLATE,
    EXTRACT_FEEDBACK_TAGS_TEMPLATE,
    ARTIST_FROM_POOL_TEMPLATE,
    ARTIST_FIX_FROM_POOL_TEMPLATE,
    format_candidate_pool
)
from ..utils.danbooru_api import (
    DanbooruAPI,
    extract_artist_names_from_prompt,
    get_artist_quality_score,
    validate_and_correct_tags,
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

        logger.info(f"{self.log_prefix} [画师串] 执行 /nai artgen 命令")

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

        logger.info(f"{self.log_prefix} [画师串] 风格描述: {style}, 随机模式: {is_random}")

        # 获取当前模型版本
        model_version = self._get_current_model_version()

        # 使用新流程：预筛选画师池 → LLM 组合
        artist_prompt, validation_info = await self._generate_with_pool(
            style, model_version, is_random
        )

        if not artist_prompt:
            error_msg = validation_info or "画师串生成失败，请稍后再试~"
            await self.send_text(error_msg)
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

    # ==================== 新流程：预筛选画师池 ====================

    async def _generate_with_pool(
        self, style: str, model_version: str, is_random: bool
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        新流程：预筛选画师池 → LLM 从池中组合

        Returns:
            (画师串, 验证信息文本)
        """
        danbooru_api = DanbooruAPI(timeout=15)

        # 步骤1: 提取英文标签（或画师名）
        if is_random:
            # 随机模式：使用通用标签
            search_tags = ["1girl", "solo"]
            logger.debug(f"{self.log_prefix} [画师串] 随机模式，使用通用标签搜索")
            target_artist = None
        else:
            # 从用户需求提取标签（复用 API 实例）
            search_tags = await self._extract_search_tags(style, danbooru_api)
            logger.info(f"{self.log_prefix} [画师串] 提取到搜索标签: {search_tags}")
            target_artist = None

            # 检查是否识别到了画师名
            if search_tags and search_tags[0].startswith("@"):
                target_artist = search_tags[0][1:]  # 去掉@前缀
                search_tags = []  # 清空，后面会用画师风格标签搜索

        if not search_tags and not target_artist:
            # 标签提取失败，提示用户
            logger.warning(f"{self.log_prefix} [画师串] 标签提取失败")
            return None, "无法理解需求，请尝试更具体的描述"

        # 如果识别到画师名，使用画师相关搜索
        if target_artist:
            candidate_artists = await self._search_similar_artists(target_artist, danbooru_api)
        else:
            # 步骤2: 搜索相关画师（逐步减少标签重试）
            candidate_artists = await asyncio.to_thread(
                danbooru_api.search_artists_by_tags, search_tags, 150, 2
            )

            if not candidate_artists or len(candidate_artists) < 5:
                # 尝试逐个标签搜索并合并结果
                logger.info(f"{self.log_prefix} [画师串] 候选不足({len(candidate_artists) if candidate_artists else 0}个)，尝试单标签搜索")
                merged_candidates = list(candidate_artists) if candidate_artists else []
                seen_names = {a["name"].lower() for a in merged_candidates}

                for tag in search_tags:
                    single_result = await asyncio.to_thread(
                        danbooru_api.search_artists_by_tags, [tag], 100, 2
                    )
                    if single_result:
                        for artist in single_result:
                            if artist["name"].lower() not in seen_names:
                                merged_candidates.append(artist)
                                seen_names.add(artist["name"].lower())

                candidate_artists = merged_candidates
                logger.info(f"{self.log_prefix} [画师串] 合并后候选画师: {len(candidate_artists)}个")

            if not candidate_artists or len(candidate_artists) < 5:
                # 最终兜底
                logger.warning(f"{self.log_prefix} [画师串] 候选画师仍不足，尝试宽泛搜索")
                candidate_artists = await asyncio.to_thread(
                    danbooru_api.search_artists_by_tags, ["1girl"], 150, 2
                )
                if not candidate_artists or len(candidate_artists) < 5:
                    return None, "找不到足够的相关画师，请尝试其他风格描述"

        logger.debug(f"{self.log_prefix} [画师串] 找到 {len(candidate_artists)} 个候选画师")

        # 步骤3: LLM 从池中组合
        artist_prompt = await self._generate_from_pool(
            style, model_version, candidate_artists, is_random
        )

        if not artist_prompt:
            return None, None

        # 清理格式
        artist_prompt = self._cleanup_artist_prompt(artist_prompt)

        # 验证生成的画师是否都在候选池中
        pool_names = {a["name"].lower() for a in candidate_artists}
        generated_artists = extract_artist_names_from_prompt(artist_prompt)

        valid_artists = []
        invalid_artists = []

        for name in generated_artists:
            if name.lower() in pool_names:
                # 在池中，获取详细信息
                for a in candidate_artists:
                    if a["name"].lower() == name.lower():
                        valid_artists.append({
                            "name": a["name"],
                            "post_count": a["post_count"]
                        })
                        break
            else:
                invalid_artists.append(name)

        # 如果有不在池中的画师，尝试验证（LLM 可能使用了池外的画师）
        if invalid_artists:
            logger.warning(f"{self.log_prefix} [画师串] LLM 使用了池外画师: {invalid_artists}")

            # 并行查询所有池外画师
            async def _verify_or_correct(name: str):
                info = await asyncio.to_thread(danbooru_api.search_artist, name)
                if info and info.get("post_count", 0) > 0:
                    return {"type": "valid", "name": name, "info": info}
                # 尝试纠正
                corrected = await asyncio.to_thread(
                    danbooru_api.fuzzy_search_artist, name, 3
                )
                if corrected:
                    return {"type": "corrected", "name": name, "info": corrected[0]}
                return {"type": "invalid", "name": name, "info": None}

            verify_tasks = [_verify_or_correct(name) for name in invalid_artists]
            verify_results = await asyncio.gather(*verify_tasks)

            for result in verify_results:
                if result["type"] == "valid":
                    valid_artists.append(result["info"])
                elif result["type"] == "corrected":
                    best = result["info"]
                    artist_prompt = artist_prompt.replace(
                        f"artist:{result['name']}", f"artist:{best['name']}"
                    )
                    valid_artists.append(best)

        # 格式化输出
        validation_info = self._format_artist_grades(valid_artists)

        return artist_prompt, validation_info

    async def _search_similar_artists(self, artist_name: str, danbooru_api: DanbooruAPI) -> List[Dict]:
        """
        根据指定画师搜索相似画师

        1. 查找目标画师信息
        2. 获取其风格标签
        3. 用风格标签搜索相似画师
        4. 将目标画师放在列表最前面
        """
        # 先搜索目标画师
        target_info = await asyncio.to_thread(danbooru_api.search_artist, artist_name)

        if not target_info or target_info.get("post_count", 0) <= 0:
            # 尝试模糊搜索
            fuzzy_results = await asyncio.to_thread(danbooru_api.fuzzy_search_artist, artist_name, 5)
            if fuzzy_results:
                target_info = fuzzy_results[0]
                artist_name = target_info.get("name", artist_name)
                logger.info(f"{self.log_prefix} [画师串] 画师名纠正: {artist_name}")
            else:
                logger.warning(f"{self.log_prefix} [画师串] 未找到画师: {artist_name}")
                return []

        logger.info(f"{self.log_prefix} [画师串] 找到目标画师: {artist_name} ({target_info.get('post_count', 0)} posts)")

        # 获取画师的风格标签
        style_info = await asyncio.to_thread(danbooru_api.get_artist_style_tags, artist_name, 20)
        style_tags = style_info.get("common_tags", [])[:6]

        candidates = []
        seen_names = set()

        # 将目标画师加入候选池首位
        target_entry = {
            "name": artist_name,
            "post_count": target_info.get("post_count", 0),
            "style_tags": style_tags
        }
        candidates.append(target_entry)
        seen_names.add(artist_name.lower())

        # 获取相关画师
        related = await asyncio.to_thread(danbooru_api.get_related_artists, artist_name, 15)
        for item in related:
            tag_info = item.get("tag", item)
            related_name = tag_info.get("name", "")
            if related_name and related_name.lower() not in seen_names:
                related_artist_info = await asyncio.to_thread(danbooru_api.search_artist, related_name)
                if related_artist_info and related_artist_info.get("post_count", 0) >= 100:
                    candidates.append({
                        "name": related_name,
                        "post_count": related_artist_info.get("post_count", 0),
                        "style_tags": []
                    })
                    seen_names.add(related_name.lower())

        # 如果风格标签存在，也用风格标签搜索相似画师
        if style_tags and len(candidates) < 20:
            style_artists = await asyncio.to_thread(
                danbooru_api.search_artists_by_tags, style_tags[:3], 50, 2
            )
            for artist in style_artists:
                name = artist.get("name", "")
                if name and name.lower() not in seen_names:
                    candidates.append(artist)
                    seen_names.add(name.lower())
                    if len(candidates) >= 30:
                        break

        logger.debug(f"{self.log_prefix} [画师串] 找到 {len(candidates)} 个相似画师（含目标画师）")
        return candidates

    async def _extract_search_tags(self, user_request: str, danbooru_api: DanbooruAPI = None) -> List[str]:
        """
        步骤1: 使用 LLM 从用户需求提取英文搜索标签

        如果 LLM 识别到画师名（@前缀），返回 ["@画师名"]
        否则返回风格标签列表
        """
        prompt = EXTRACT_TAGS_TEMPLATE.replace("<<USER_REQUEST>>", user_request)

        generator_config = self._get_artist_generator_config()
        model_config = self._resolve_llm_model_config(
            generator_config.get("model_name", ""), generator_config
        )
        if not model_config:
            return []

        try:
            max_tokens = generator_config.get("max_tokens", 50)
            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="nai_pic_plugin.extract_tags",
                temperature=0.2,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [画师串] 标签提取失败: {e}")
            return []

        if not success or not response:
            return []

        response = response.strip()

        # 检查是否识别到了画师名（@前缀）
        if response.startswith("@"):
            artist_name = response.lstrip("@").strip().lower().replace(" ", "_")
            if artist_name:
                logger.info(f"{self.log_prefix} [画师串] 识别到画师名: {artist_name}")
                return [f"@{artist_name}"]

        # 解析风格标签
        tags = response.lower().split()
        # 过滤无效标签，去掉标点符号
        tags = [t.strip(',.;:!?') for t in tags if t]
        tags = [t for t in tags if t and len(t) > 1 and t.isascii() and not t.startswith("@")]
        raw_tags = tags[:6]

        if not raw_tags:
            return []

        # 验证并纠正标签
        logger.info(f"{self.log_prefix} [画师串] LLM 提取的原始标签: {raw_tags}")
        if danbooru_api is None:
            danbooru_api = DanbooruAPI(timeout=10)
        validated_tags = await asyncio.to_thread(
            validate_and_correct_tags, raw_tags, danbooru_api
        )
        logger.info(f"{self.log_prefix} [画师串] 验证后的有效标签: {validated_tags}")

        return validated_tags if validated_tags else raw_tags[:2]

    async def _generate_from_pool(
        self, style: str, model_version: str, candidates: List[Dict], is_random: bool
    ) -> Optional[str]:
        """
        步骤3: LLM 从候选池中组合画师串
        """
        # 格式化候选池
        pool_text = format_candidate_pool(candidates)

        prompt = ARTIST_FROM_POOL_TEMPLATE
        prompt = prompt.replace("<<USER_REQUEST>>", style if not is_random else "随机风格")
        prompt = prompt.replace("<<MODEL_VERSION>>", model_version)
        prompt = prompt.replace("<<CANDIDATE_ARTISTS>>", pool_text)

        extra_hint = ""
        if is_random:
            extra_hint = "【随机模式】请随机选择一个有趣的风格方向进行组合。"
        prompt = prompt.replace("<<EXTRA_HINT>>", extra_hint)

        generator_config = self._get_artist_generator_config()
        model_config = self._resolve_llm_model_config(
            generator_config.get("model_name", ""), generator_config
        )
        if not model_config:
            return None

        temperature = generator_config.get("random_temperature", 0.7) if is_random else generator_config.get("temperature", 0.3)
        max_tokens = generator_config.get("max_tokens", 300)

        try:
            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="nai_pic_plugin.artist_from_pool",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [画师串] 画师组合生成失败: {e}")
            return None

        if not success or not response:
            return None

        return response

    def _format_artist_grades(self, valid_artists: List[Dict]) -> str:
        """格式化画师评级信息"""
        if not valid_artists:
            return ""

        lines = ["📊 画师稳定性："]
        low_stability_artists = []

        for info in valid_artists:
            name = info.get("name", "unknown")
            count = info.get("post_count", 0)
            grade = get_artist_quality_score(info)
            lines.append(f"  • {name} [{grade}] ({count:,})")

            if grade in ("C", "D"):
                low_stability_artists.append(name)

        if low_stability_artists:
            lines.append("")
            if len(low_stability_artists) == 1:
                lines.append(f"⚠️ {low_stability_artists[0]} 帖子数较少，效果可能不稳定")
            else:
                lines.append(f"⚠️ {', '.join(low_stability_artists)} 帖子数较少，效果可能不稳定")

        return "\n".join(lines)

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
        return self.get_config("prompt_generator", None) or {}

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
                        selection_strategy="random"  # 固定使用随机选择
                    )
                    logger.debug(f"{self.log_prefix} [画师串] 使用自定义模型配置: {model_list}")
                    return custom_task_config
                except Exception as e:
                    logger.warning(f"{self.log_prefix} [画师串] 自定义模型配置创建失败: {e}")

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
                logger.debug(f"{self.log_prefix} [画师串] 使用模型: {name}")
                return config

        fallback_name, fallback_config = next(iter(models.items()))
        logger.debug(f"{self.log_prefix} [画师串] 使用默认模型: {fallback_name}")
        return fallback_config

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
        logger.debug(f"{self.log_prefix} [画师串] 画师串已缓存: {artist_prompt[:50]}...")

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
        """执行 /nai artfix 命令 - 基于扩展候选池迭代优化画师串"""
        logger.info(f"{self.log_prefix} [画师串] 执行 /nai artfix 命令")

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

        logger.info(f"{self.log_prefix} [画师串] 原画师串: {original_prompt}, 反馈: {feedback}")

        # 使用扩展池流程优化
        optimized_prompt, validation_info = await self._fix_with_expanded_pool(
            original_prompt, feedback, model_version
        )

        if not optimized_prompt:
            error_msg = validation_info or "画师串优化失败，请稍后再试~"
            await self.send_text(error_msg)
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

    async def _fix_with_expanded_pool(
        self, original_prompt: str, feedback: str, model_version: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        扩展池流程优化画师串：
        1. 从反馈提取标签
        2. 搜索新候选画师
        3. 合并原画师 + 新候选为扩展池
        4. LLM 从扩展池重新组合

        Returns:
            (优化后的画师串, 验证信息文本)
        """
        danbooru_api = DanbooruAPI(timeout=15)

        # 步骤1: 从反馈提取搜索标签（复用 API 实例）
        feedback_tags = await self._extract_feedback_tags(feedback, danbooru_api)
        logger.debug(f"{self.log_prefix} [画师串] 反馈标签: {feedback_tags}")

        # 步骤2: 获取原画师的 Danbooru 信息（并发查询）
        original_artists = extract_artist_names_from_prompt(original_prompt)

        async def _fetch_original_artist(name: str):
            info = await asyncio.to_thread(danbooru_api.search_artist, name)
            if not info or info.get("post_count", 0) <= 0:
                return None
            style_info = await asyncio.to_thread(
                danbooru_api.get_artist_style_tags, name, 15
            )
            return {
                "name": info["name"],
                "post_count": info.get("post_count", 0),
                "style_tags": style_info.get("common_tags", [])[:6]
            }

        fetch_tasks = [_fetch_original_artist(name) for name in original_artists]
        fetch_results = await asyncio.gather(*fetch_tasks)
        original_artist_infos = [r for r in fetch_results if r is not None]

        # 步骤3: 根据反馈标签搜索新候选画师
        new_candidates = []
        if feedback_tags:
            new_candidates = await asyncio.to_thread(
                danbooru_api.search_artists_by_tags, feedback_tags, 100, 2
            )
            logger.debug(f"{self.log_prefix} [画师串] 反馈方向找到 {len(new_candidates)} 个新候选画师")

        # 步骤4: 合并为扩展池（原画师 + 新候选，去重）
        expanded_pool = list(original_artist_infos)
        existing_names = {a["name"].lower() for a in expanded_pool}

        for candidate in new_candidates:
            if candidate["name"].lower() not in existing_names:
                expanded_pool.append(candidate)
                existing_names.add(candidate["name"].lower())

        if len(expanded_pool) < 3:
            logger.warning(f"{self.log_prefix} [画师串] 扩展池画师太少({len(expanded_pool)}个)")
            return None, "找不到足够的候选画师，请尝试其他反馈描述"

        logger.debug(f"{self.log_prefix} [画师串] 扩展池共 {len(expanded_pool)} 个画师（原{len(original_artist_infos)} + 新{len(expanded_pool) - len(original_artist_infos)}）")

        # 步骤5: LLM 从扩展池重新组合
        pool_text = format_candidate_pool(expanded_pool)
        artist_prompt = await self._generate_fix_from_pool(
            original_prompt, feedback, model_version, pool_text
        )

        if not artist_prompt:
            return None, None

        # 清理格式
        artist_prompt = self._cleanup_artist_prompt(artist_prompt)

        # 验证生成的画师是否在扩展池中
        pool_names = {a["name"].lower() for a in expanded_pool}
        generated_artists = extract_artist_names_from_prompt(artist_prompt)

        valid_artists = []
        invalid_artists = []

        for name in generated_artists:
            if name.lower() in pool_names:
                for a in expanded_pool:
                    if a["name"].lower() == name.lower():
                        valid_artists.append({
                            "name": a["name"],
                            "post_count": a["post_count"]
                        })
                        break
            else:
                invalid_artists.append(name)

        # 池外画师尝试 Danbooru 验证（并行）
        if invalid_artists:
            logger.warning(f"{self.log_prefix} [画师串] LLM 使用了池外画师: {invalid_artists}")

            async def _verify_or_correct(name: str):
                info = await asyncio.to_thread(danbooru_api.search_artist, name)
                if info and info.get("post_count", 0) > 0:
                    return {"type": "valid", "name": name, "info": info}
                corrected = await asyncio.to_thread(
                    danbooru_api.fuzzy_search_artist, name, 3
                )
                if corrected:
                    return {"type": "corrected", "name": name, "info": corrected[0]}
                return {"type": "invalid", "name": name, "info": None}

            verify_tasks = [_verify_or_correct(name) for name in invalid_artists]
            verify_results = await asyncio.gather(*verify_tasks)

            for result in verify_results:
                if result["type"] == "valid":
                    valid_artists.append(result["info"])
                elif result["type"] == "corrected":
                    best = result["info"]
                    artist_prompt = artist_prompt.replace(
                        f"artist:{result['name']}", f"artist:{best['name']}"
                    )
                    valid_artists.append(best)

        validation_info = self._format_artist_grades(valid_artists)
        return artist_prompt, validation_info

    async def _extract_feedback_tags(self, feedback: str, danbooru_api: DanbooruAPI = None) -> List[str]:
        """从用户反馈提取搜索标签"""
        prompt = EXTRACT_FEEDBACK_TAGS_TEMPLATE.replace("<<USER_FEEDBACK>>", feedback)

        generator_config = self._get_artist_generator_config()
        model_config = self._resolve_llm_model_config(
            generator_config.get("model_name", ""), generator_config
        )
        if not model_config:
            return []

        try:
            max_tokens = generator_config.get("max_tokens", 50)
            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="nai_pic_plugin.extract_feedback_tags",
                temperature=0.2,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [画师串] 反馈标签提取失败: {e}")
            return []

        if not success or not response:
            return []

        tags = response.strip().lower().split()
        tags = [t for t in tags if t and len(t) > 1 and t.isascii()]
        raw_tags = tags[:4]

        if not raw_tags:
            return []

        # 验证并纠正标签
        logger.debug(f"{self.log_prefix} [画师串] LLM 提取的反馈标签: {raw_tags}")
        if danbooru_api is None:
            danbooru_api = DanbooruAPI(timeout=10)
        validated_tags = await asyncio.to_thread(
            validate_and_correct_tags, raw_tags, danbooru_api
        )
        logger.debug(f"{self.log_prefix} [画师串] 验证后的反馈标签: {validated_tags}")

        return validated_tags if validated_tags else raw_tags[:2]

    async def _generate_fix_from_pool(
        self, original_prompt: str, feedback: str,
        model_version: str, pool_text: str
    ) -> Optional[str]:
        """LLM 从扩展池重新组合画师串"""
        prompt = ARTIST_FIX_FROM_POOL_TEMPLATE
        prompt = prompt.replace("<<ORIGINAL_PROMPT>>", original_prompt)
        prompt = prompt.replace("<<USER_FEEDBACK>>", feedback)
        prompt = prompt.replace("<<MODEL_VERSION>>", model_version)
        prompt = prompt.replace("<<CANDIDATE_ARTISTS>>", pool_text)

        generator_config = self._get_artist_generator_config()
        model_config = self._resolve_llm_model_config(
            generator_config.get("model_name", ""), generator_config
        )
        if not model_config:
            return None

        temperature = generator_config.get("temperature", 0.3)
        max_tokens = generator_config.get("max_tokens", 300)

        try:
            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="nai_pic_plugin.artist_fix_from_pool",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [画师串] 画师优化生成失败: {e}")
            return None

        if not success or not response:
            return None

        return response

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


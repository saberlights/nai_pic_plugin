# -*- coding: utf-8 -*-
"""
Danbooru API 客户端 - 用于验证和查询画师标签
"""
import re
import asyncio
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

import requests

from src.common.logger import get_logger

logger = get_logger("nai_pic_plugin")

# Danbooru API 基础配置
DANBOORU_API_BASE = "https://danbooru.donmai.us"
DANBOORU_TAGS_ENDPOINT = "/tags.json"
DANBOORU_RELATED_TAG_ENDPOINT = "/related_tag.json"

# 标签类别
TAG_CATEGORY_GENERAL = 0
TAG_CATEGORY_ARTIST = 1
TAG_CATEGORY_COPYRIGHT = 3
TAG_CATEGORY_CHARACTER = 4

# 最小推荐帖子数（低于此数量的画师可能不稳定）
MIN_RECOMMENDED_POST_COUNT = 100


class DanbooruAPI:
    """Danbooru API 客户端"""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "NaiPicPlugin/1.0"
        })

    def search_artist(self, name: str) -> Optional[Dict]:
        """
        搜索单个画师标签

        Args:
            name: 画师名（Danbooru 格式）

        Returns:
            画师信息字典，包含 name, post_count 等，未找到返回 None
        """
        name_lower = name.lower()

        # 方法1: 使用 name_matches 精确匹配（比 search[name] 更可靠）
        try:
            params = {
                "search[category]": TAG_CATEGORY_ARTIST,
                "search[name_matches]": name_lower,
                "search[hide_empty]": "true",
                "limit": 5
            }
            response = self.session.get(
                f"{DANBOORU_API_BASE}{DANBOORU_TAGS_ENDPOINT}",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if data:
                    # 找完全匹配的
                    for item in data:
                        if item.get("name", "").lower() == name_lower:
                            return item
                    # 没有完全匹配，返回第一个结果（可能是近似）
                    if data[0].get("post_count", 0) > 0:
                        return data[0]
        except Exception as e:
            logger.warning(f"Danbooru API 查询失败 (name_matches): {e}")

        # 方法2: 回退到精确搜索
        try:
            params = {
                "search[category]": TAG_CATEGORY_ARTIST,
                "search[name]": name_lower,
                "limit": 1
            }
            response = self.session.get(
                f"{DANBOORU_API_BASE}{DANBOORU_TAGS_ENDPOINT}",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return data[0]
        except Exception as e:
            logger.warning(f"Danbooru API 查询失败 (exact): {e}")

        return None

    def search_artists_batch(self, names: List[str]) -> Dict[str, Optional[Dict]]:
        """
        批量搜索画师标签

        Args:
            names: 画师名列表

        Returns:
            {画师名: 画师信息} 字典
        """
        results = {}
        for name in names:
            results[name] = self.search_artist(name)
        return results

    def get_popular_artists(self, limit: int = 50) -> List[Dict]:
        """
        获取热门画师列表（按帖子数排序）

        Args:
            limit: 返回数量

        Returns:
            画师信息列表
        """
        try:
            params = {
                "search[category]": TAG_CATEGORY_ARTIST,
                "search[order]": "count",
                "search[hide_empty]": "true",
                "limit": min(limit, 200)
            }
            response = self.session.get(
                f"{DANBOORU_API_BASE}{DANBOORU_TAGS_ENDPOINT}",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.warning(f"Danbooru API 获取热门画师失败: {e}")
            return []

    def fuzzy_search_artist(self, partial_name: str, limit: int = 10) -> List[Dict]:
        """
        模糊搜索画师

        Args:
            partial_name: 部分画师名
            limit: 返回数量

        Returns:
            匹配的画师列表
        """
        try:
            params = {
                "search[category]": TAG_CATEGORY_ARTIST,
                "search[name_matches]": f"*{partial_name.lower()}*",
                "search[order]": "count",
                "limit": min(limit, 50)
            }
            response = self.session.get(
                f"{DANBOORU_API_BASE}{DANBOORU_TAGS_ENDPOINT}",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.warning(f"Danbooru API 模糊搜索失败: {e}")
            return []

    def get_related_artists(self, artist_name: str, limit: int = 10) -> List[Dict]:
        """
        获取与指定画师相关/相似的画师

        Args:
            artist_name: 画师名
            limit: 返回数量

        Returns:
            相关画师列表，包含 tag 信息和相关度
        """
        try:
            params = {
                "query": artist_name.lower(),
                "category": TAG_CATEGORY_ARTIST
            }
            response = self.session.get(
                f"{DANBOORU_API_BASE}{DANBOORU_RELATED_TAG_ENDPOINT}",
                params=params,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                # 返回格式可能是 {"query": "xxx", "tags": [...]} 或直接是列表
                if isinstance(data, dict) and "related_tags" in data:
                    related = data["related_tags"][:limit]
                    # 过滤掉自己
                    return [t for t in related if t.get("tag", {}).get("name") != artist_name.lower()]
                elif isinstance(data, list):
                    return data[:limit]
            return []
        except Exception as e:
            logger.warning(f"Danbooru API 获取相关画师失败: {e}")
            return []

    def get_similar_artists_by_style(self, artist_names: List[str], limit: int = 5) -> List[str]:
        """
        根据多个画师找出可能风格相似的其他画师

        Args:
            artist_names: 画师名列表
            limit: 每个画师返回的相关画师数量

        Returns:
            相似画师名列表（去重，按出现频率排序）
        """
        from collections import Counter

        related_counter = Counter()

        for name in artist_names:
            related = self.get_related_artists(name, limit=limit)
            for item in related:
                # 处理不同的返回格式
                if isinstance(item, dict):
                    tag_info = item.get("tag", item)
                    related_name = tag_info.get("name", "")
                    if related_name and related_name not in artist_names:
                        related_counter[related_name] += 1

        # 返回出现频率最高的（说明与多个输入画师都相关）
        return [name for name, _ in related_counter.most_common(limit * 2)]


def extract_artist_names_from_prompt(artist_prompt: str) -> List[str]:
    """
    从画师串中提取画师名

    Args:
        artist_prompt: 画师串，如 "1.2::artist:sususuyo ::, artist:fuzichoco"

    Returns:
        画师名列表
    """
    # 匹配 artist:xxx 格式
    pattern = r'artist:([a-zA-Z0-9_\-\(\)]+)'
    matches = re.findall(pattern, artist_prompt.lower())
    return list(set(matches))


def validate_artist_prompt(artist_prompt: str, api: DanbooruAPI = None) -> Tuple[bool, List[Dict], List[str]]:
    """
    验证画师串中的画师是否有效

    Args:
        artist_prompt: 画师串
        api: DanbooruAPI 实例（可选）

    Returns:
        (是否全部有效, 有效画师信息列表, 无效画师名列表)
    """
    if api is None:
        api = DanbooruAPI()

    artist_names = extract_artist_names_from_prompt(artist_prompt)
    if not artist_names:
        return False, [], []

    valid_artists = []
    invalid_artists = []

    for name in artist_names:
        info = api.search_artist(name)
        # 精确搜索失败时重试一次（应对 API 波动）
        if info is None:
            info = api.search_artist(name)
        if info and info.get("post_count", 0) > 0:
            valid_artists.append(info)
        else:
            invalid_artists.append(name)

    all_valid = len(invalid_artists) == 0
    return all_valid, valid_artists, invalid_artists


def try_correct_artist_name(invalid_name: str, api: DanbooruAPI = None) -> Optional[Dict]:
    """
    尝试使用模糊搜索纠正画师名拼写

    Args:
        invalid_name: 无效的画师名
        api: DanbooruAPI 实例

    Returns:
        最可能的正确画师信息，或 None
    """
    if api is None:
        api = DanbooruAPI()

    # 尝试模糊搜索
    candidates = api.fuzzy_search_artist(invalid_name, limit=5)
    if not candidates:
        return None

    # 过滤掉和原名完全相同的结果（避免无意义纠正）
    candidates = [c for c in candidates if c.get("name", "").lower() != invalid_name.lower()]
    if not candidates:
        return None

    # 返回帖子数最多的候选（更可能是用户想要的）
    best_match = max(candidates, key=lambda x: x.get("post_count", 0))

    # 只有当候选确实相似时才返回
    best_name = best_match.get("name", "")
    common_chars = sum(1 for c in invalid_name.lower() if c in best_name.lower())
    similarity = common_chars / max(len(invalid_name), 1)

    if similarity >= 0.6:
        return best_match

    return None


def suggest_corrections_for_invalid(invalid_artists: List[str], api: DanbooruAPI = None) -> Dict[str, Optional[str]]:
    """
    为无效画师名批量建议纠正

    Args:
        invalid_artists: 无效画师名列表
        api: DanbooruAPI 实例

    Returns:
        {无效名: 建议的正确名或None}
    """
    if api is None:
        api = DanbooruAPI()

    corrections = {}
    for name in invalid_artists:
        corrected = try_correct_artist_name(name, api)
        if corrected:
            corrections[name] = corrected.get("name")
        else:
            corrections[name] = None

    return corrections


def get_artist_quality_score(artist_info: Dict) -> str:
    """
    根据帖子数量评估画师稳定性

    Args:
        artist_info: Danbooru 返回的画师信息

    Returns:
        质量等级: "S", "A", "B", "C", "D"
    """
    post_count = artist_info.get("post_count", 0)

    if post_count >= 5000:
        return "S"  # 非常稳定
    elif post_count >= 1000:
        return "A"  # 稳定
    elif post_count >= 500:
        return "B"  # 较稳定
    elif post_count >= 100:
        return "C"  # 一般
    else:
        return "D"  # 可能不稳定


def format_validation_result(valid_artists: List[Dict], invalid_artists: List[str]) -> str:
    """
    格式化验证结果为用户可读的文本

    Args:
        valid_artists: 有效画师信息列表
        invalid_artists: 无效画师名列表

    Returns:
        格式化的结果文本
    """
    lines = []

    if valid_artists:
        lines.append("✅ 有效画师：")
        for info in valid_artists:
            name = info.get("name", "unknown")
            count = info.get("post_count", 0)
            grade = get_artist_quality_score(info)
            lines.append(f"  • {name} [{grade}] ({count:,} posts)")

    if invalid_artists:
        lines.append("⚠️ 未找到：")
        for name in invalid_artists:
            lines.append(f"  • {name}")

    return "\n".join(lines)


def suggest_similar_artists(artist_names: List[str], api: DanbooruAPI = None) -> List[str]:
    """
    根据给定画师推荐相似风格的画师

    Args:
        artist_names: 画师名列表
        api: DanbooruAPI 实例

    Returns:
        推荐的相似画师名列表
    """
    if api is None:
        api = DanbooruAPI()

    return api.get_similar_artists_by_style(artist_names, limit=5)

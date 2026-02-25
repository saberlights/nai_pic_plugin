# -*- coding: utf-8 -*-
"""
统一会话状态管理器

集中管理所有会话级别的运行时状态，包括：
- 管理员模式
- 模型选择
- 画师串选择
- 尺寸选择
- 自动撤回
- NSFW过滤
- 提示词显示

替代原来分散在各个 Command 类中的状态字典
"""
import time
from typing import Optional, Dict, List, Tuple, Callable, Any
from src.common.logger import get_logger

logger = get_logger("nai_pic_plugin")


class SessionStateManager:
    """
    单例模式的会话状态管理器

    使用方式：
        from .services.session_state import session_state

        # 查询状态
        enabled = session_state.is_admin_mode_enabled(platform, chat_id, get_config)

        # 设置状态
        session_state.set_admin_mode(platform, chat_id, True)
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_state()
        return cls._instance

    def _init_state(self):
        """初始化所有状态字典"""
        # 管理员模式：{chat_key: bool}
        self._admin_mode: Dict[str, bool] = {}

        # 模型选择：{chat_key: model_name}
        self._selected_models: Dict[str, str] = {}

        # 画师串选择：{chat_key: index}（索引从1开始）
        self._selected_artists: Dict[str, int] = {}

        # 尺寸选择：{chat_key: size_string}
        self._selected_sizes: Dict[str, str] = {}

        # 自动撤回：{chat_key: bool}
        self._recall_enabled: Dict[str, bool] = {}

        # NSFW过滤：{chat_key: bool}
        self._nsfw_filter: Dict[str, bool] = {}

        # 提示词显示：{chat_key: bool}
        self._prompt_show: Dict[str, bool] = {}

        # 画师串预览图模式：{chat_key: bool}
        self._artist_preview: Dict[str, bool] = {}

        # 上一轮 LLM 生成的正向提示词（用于 action 生图上下文继承）
        # key 使用 chat_stream.stream_id（BaseAction.chat_id），天然实现”全群共享”
        # value = (prompt, request, timestamp)
        self._last_nai_context: Dict[str, Tuple[str, str, float]] = {}

    @staticmethod
    def _make_key(platform: str, chat_id: str) -> str:
        """生成会话唯一标识"""
        return f"{platform}:{chat_id}"

    # ==================== 管理员模式 ====================

    def is_admin_mode_enabled(
        self,
        platform: str,
        chat_id: str,
        get_config: Callable
    ) -> bool:
        """
        检查指定会话是否启用了管理员模式

        Args:
            platform: 平台标识
            chat_id: 会话ID（group_id 或 user_id）
            get_config: 获取配置的函数

        Returns:
            bool: 是否启用管理员模式
        """
        key = self._make_key(platform, chat_id)
        if key in self._admin_mode:
            return self._admin_mode[key]
        return get_config("admin.default_admin_mode", False)

    def set_admin_mode(self, platform: str, chat_id: str, enabled: bool):
        """设置管理员模式"""
        key = self._make_key(platform, chat_id)
        self._admin_mode[key] = enabled
        logger.info(f"[nai_pic] 会话 {key} 管理员模式已{'开启' if enabled else '关闭'}")

    def check_user_permission(
        self,
        platform: str,
        chat_id: str,
        user_id: str,
        get_config: Callable
    ) -> bool:
        """
        检查用户是否有权限使用生图功能

        管理员模式关闭时：所有人都有权限
        管理员模式开启时：只有管理员有权限

        Args:
            platform: 平台标识
            chat_id: 会话ID
            user_id: 用户ID
            get_config: 获取配置的函数

        Returns:
            bool: 是否有权限
        """
        if not self.is_admin_mode_enabled(platform, chat_id, get_config):
            return True

        admin_users = get_config("admin.admin_users", [])
        if not admin_users:
            # 未配置管理员列表时，管理员模式不生效（与 is_admin_user 语义保持一致）
            return True
        return str(user_id) in admin_users

    def is_admin_user(self, user_id: str, get_config: Callable) -> bool:
        """检查用户是否是管理员"""
        admin_users = get_config("admin.admin_users", [])
        if not admin_users:
            # 未配置管理员列表时，默认允许所有人
            return True
        return str(user_id) in admin_users

    # ==================== 模型选择 ====================

    def get_selected_model(self, platform: str, chat_id: str) -> Optional[str]:
        """获取指定会话选定的模型"""
        key = self._make_key(platform, chat_id)
        return self._selected_models.get(key)

    def set_selected_model(self, platform: str, chat_id: str, model: str):
        """设置模型"""
        key = self._make_key(platform, chat_id)
        self._selected_models[key] = model
        logger.info(f"[nai_pic] 会话 {key} 已切换模型: {model}")

    # ==================== 画师串选择 ====================

    def get_selected_artist_index(self, platform: str, chat_id: str) -> int:
        """获取指定会话选定的画师串索引（从1开始）"""
        key = self._make_key(platform, chat_id)
        return self._selected_artists.get(key, 1)

    def set_selected_artist_index(self, platform: str, chat_id: str, index: int):
        """设置画师串索引"""
        key = self._make_key(platform, chat_id)
        self._selected_artists[key] = index
        logger.info(f"[nai_pic] 会话 {key} 已切换画师串: #{index}")

    def get_selected_artist_preset(
        self,
        platform: str,
        chat_id: str,
        model_name: str,
        get_config: Callable
    ) -> Optional[str]:
        """
        获取指定会话选定的画师串内容

        Args:
            platform: 平台标识
            chat_id: 会话ID
            model_name: 当前使用的模型名称
            get_config: 获取配置的函数

        Returns:
            选定的画师串内容，未设置则返回第一个预设
        """
        # 根据模型确定配置节
        if "nai-diffusion-3" in model_name:
            config_section = "model_nai3"
        elif "nai-diffusion-4-5" in model_name:
            config_section = "model_nai4_5"
        elif "nai-diffusion-4" in model_name:
            config_section = "model_nai4"
        else:
            return None

        # 获取画师串列表
        artist_presets_raw = get_config(f"{config_section}.artist_presets", [])
        if not artist_presets_raw:
            return None

        # 解析画师串列表
        artist_presets = self._parse_artist_presets(artist_presets_raw)
        if not artist_presets:
            return None

        # 获取选定的索引
        selected_index = self.get_selected_artist_index(platform, chat_id)

        # 确保索引有效
        if 1 <= selected_index <= len(artist_presets):
            return artist_presets[selected_index - 1]["prompt"]
        else:
            return artist_presets[0]["prompt"] if artist_presets else None

    @staticmethod
    def _parse_artist_presets(presets_raw: List) -> List[Dict[str, str]]:
        """
        解析画师串预设列表，兼容新旧格式

        新格式：[{"name": "风格名", "prompt": "画师串内容"}, ...]
        旧格式：["画师串内容1", "画师串内容2", ...]

        Returns:
            统一返回 [{"name": "...", "prompt": "..."}, ...]
        """
        if not presets_raw:
            return []

        result = []
        for i, preset in enumerate(presets_raw, 1):
            if isinstance(preset, dict):
                name = preset.get("name", f"画师串 {i}")
                prompt = preset.get("prompt", "")
                result.append({"name": name, "prompt": prompt})
            elif isinstance(preset, str):
                preview = preset[:30] + "..." if len(preset) > 30 else preset
                result.append({"name": f"#{i} {preview}", "prompt": preset})
            else:
                logger.warning(f"[nai_pic] 跳过无效的画师串格式: {type(preset)}")
                continue

        return result

    # ==================== 尺寸选择 ====================

    def get_selected_size(self, platform: str, chat_id: str) -> Optional[str]:
        """获取指定会话选定的尺寸"""
        key = self._make_key(platform, chat_id)
        return self._selected_sizes.get(key)

    def set_selected_size(self, platform: str, chat_id: str, size: str):
        """设置尺寸"""
        key = self._make_key(platform, chat_id)
        self._selected_sizes[key] = size
        logger.info(f"[nai_pic] 会话 {key} 已切换尺寸: {size}")

    # ==================== 自动撤回 ====================

    def is_recall_enabled(
        self,
        platform: str,
        chat_id: str,
        get_config: Callable
    ) -> bool:
        """检查是否启用自动撤回"""
        key = self._make_key(platform, chat_id)
        if key in self._recall_enabled:
            return self._recall_enabled[key]
        return get_config("auto_recall.enabled", False)

    def set_recall_enabled(self, platform: str, chat_id: str, enabled: bool):
        """设置自动撤回"""
        key = self._make_key(platform, chat_id)
        self._recall_enabled[key] = enabled
        logger.info(f"[nai_pic] 会话 {key} 自动撤回已{'开启' if enabled else '关闭'}")

    # ==================== NSFW过滤 ====================

    def is_nsfw_filter_enabled(
        self,
        platform: str,
        chat_id: str,
        get_config: Callable
    ) -> bool:
        """检查是否启用NSFW过滤"""
        key = self._make_key(platform, chat_id)
        if key in self._nsfw_filter:
            return self._nsfw_filter[key]
        return get_config("nsfw_filter.enabled", False)

    def set_nsfw_filter_enabled(self, platform: str, chat_id: str, enabled: bool):
        """设置NSFW过滤"""
        key = self._make_key(platform, chat_id)
        self._nsfw_filter[key] = enabled
        logger.info(f"[nai_pic] 会话 {key} NSFW过滤已{'开启' if enabled else '关闭'}")

    # ==================== 提示词显示 ====================

    def is_prompt_show_enabled(
        self,
        platform: str,
        chat_id: str,
        get_config: Callable
    ) -> bool:
        """检查是否启用提示词显示"""
        key = self._make_key(platform, chat_id)
        if key in self._prompt_show:
            return self._prompt_show[key]
        default_enabled = get_config("prompt_show.enabled", None)
        if default_enabled is not None:
            return bool(default_enabled)

        # 兼容旧配置：历史版本可能使用 prompt_generator.show_prompt
        return bool(get_config("prompt_generator.show_prompt", False))

    def set_prompt_show_enabled(self, platform: str, chat_id: str, enabled: bool):
        """设置提示词显示"""
        key = self._make_key(platform, chat_id)
        self._prompt_show[key] = enabled
        logger.info(f"[nai_pic] 会话 {key} 提示词显示已{'开启' if enabled else '关闭'}")

    # ==================== 画师串预览图模式 ====================

    def is_artist_preview_enabled(
        self,
        platform: str,
        chat_id: str,
        get_config: Callable
    ) -> bool:
        """检查是否启用画师串预览图模式"""
        key = self._make_key(platform, chat_id)
        if key in self._artist_preview:
            return self._artist_preview[key]
        return get_config("artist_generator.auto_preview", False)

    def set_artist_preview_enabled(self, platform: str, chat_id: str, enabled: bool):
        """设置画师串预览图模式"""
        key = self._make_key(platform, chat_id)
        self._artist_preview[key] = enabled
        logger.info(f"[nai_pic] 会话 {key} 画师串预览图模式已{'开启' if enabled else '关闭'}")

    # ==================== 调试/管理 ====================

    def get_session_state_summary(self, platform: str, chat_id: str) -> Dict[str, Any]:
        """获取指定会话的状态摘要（用于调试）"""
        key = self._make_key(platform, chat_id)
        return {
            "key": key,
            "admin_mode": self._admin_mode.get(key),
            "model": self._selected_models.get(key),
            "artist_index": self._selected_artists.get(key),
            "size": self._selected_sizes.get(key),
            "recall": self._recall_enabled.get(key),
            "nsfw_filter": self._nsfw_filter.get(key),
            "prompt_show": self._prompt_show.get(key),
            "artist_preview": self._artist_preview.get(key),
        }

    def clear_session_state(self, platform: str, chat_id: str):
        """清除指定会话的所有状态"""
        key = self._make_key(platform, chat_id)
        self._admin_mode.pop(key, None)
        self._selected_models.pop(key, None)
        self._selected_artists.pop(key, None)
        self._selected_sizes.pop(key, None)
        self._recall_enabled.pop(key, None)
        self._nsfw_filter.pop(key, None)
        self._prompt_show.pop(key, None)
        self._artist_preview.pop(key, None)
        logger.info(f"[nai_pic] 会话 {key} 状态已清除")

    # ==================== 上一轮提示词（Action 专用） ====================

    def get_last_nai_context(
        self, chat_stream_id: str, ttl: float = 0
    ) -> Tuple[Optional[str], Optional[str]]:
        """获取指定聊天流的上一轮 LLM 提示词及用户请求。

        Args:
            chat_stream_id: 聊天流 ID
            ttl: 有效时间（秒），>0 时检查过期；过期则删除并返回 (None, None)

        Returns:
            (prompt, request)；无数据或已过期时返回 (None, None)
        """
        if not chat_stream_id:
            return None, None
        entry = self._last_nai_context.get(chat_stream_id)
        if entry is None:
            return None, None
        prompt, request, ts = entry
        if ttl > 0 and (time.time() - ts) > ttl:
            self._last_nai_context.pop(chat_stream_id, None)
            return None, None
        return prompt, request or None

    def set_last_nai_context(
        self, chat_stream_id: str, prompt: str, request: str = ""
    ) -> None:
        """设置指定聊天流的上一轮 LLM 提示词及用户请求。

        自动附带当前时间戳。
        """
        if not chat_stream_id:
            return
        if not isinstance(prompt, str) or not prompt.strip():
            return
        self._last_nai_context[chat_stream_id] = (
            prompt.strip(),
            (request or "").strip(),
            time.time(),
        )

    # ---- 兼容包装器（旧调用方仍可使用） ----

    def get_last_nai_prompt(self, chat_stream_id: str) -> Optional[str]:
        """获取指定聊天流的上一轮 LLM 提示词（仅 action 生图使用）"""
        prompt, _ = self.get_last_nai_context(chat_stream_id)
        return prompt

    def set_last_nai_prompt(self, chat_stream_id: str, prompt: str) -> None:
        """设置指定聊天流的上一轮 LLM 提示词（仅 action 生图使用）"""
        self.set_last_nai_context(chat_stream_id, prompt)


# 全局单例实例
session_state = SessionStateManager()

# -*- coding: utf-8 -*-
"""
模型配置混入，统一处理模型/画师串选择及版本配置合并逻辑
"""
from typing import Dict, Any, Tuple

from src.common.logger import get_logger

logger = get_logger("nai_pic_plugin")


class ModelConfigMixin:
    """为命令和动作提供统一的模型配置解析逻辑"""

    def _get_model_config(self) -> Dict[str, Any]:
        base_config = self.get_config("model", {})  # type: ignore[attr-defined]
        if not base_config:
            logger.error(f"{self._log_prefix} 模型配置读取失败")
            return {}

        platform, chat_id, _ = self._get_chat_identity()

        model_name = base_config.get("default_model", "")
        # 运行时模型切换
        try:
            if platform and chat_id:
                from .nai_admin_command import NaiAdminControlCommand

                selected_model = NaiAdminControlCommand.get_selected_model(
                    platform, chat_id, self.get_config  # type: ignore[attr-defined]
                )
                if selected_model:
                    model_name = selected_model
                    logger.info(f"{self._log_prefix} 使用用户选定的模型: {selected_model}")
        except Exception as exc:
            logger.warning(f"{self._log_prefix} 获取用户选定模型失败: {exc}")

        version_config = self._get_version_config(model_name)

        merged_config = base_config.copy()
        if model_name:
            merged_config["default_model"] = model_name

        if version_config:
            for key, value in version_config.items():
                if key == "nai_extra_params":
                    base_extra = merged_config.get("nai_extra_params", {}) or {}
                    merged_extra = dict(base_extra)
                    merged_extra.update(value or {})
                    merged_config["nai_extra_params"] = merged_extra
                elif key == "artist_presets":
                    continue
                else:
                    merged_config[key] = value

        # 应用画师串选择
        try:
            if platform and chat_id and model_name:
                from .nai_admin_command import NaiAdminControlCommand

                selected_artist = NaiAdminControlCommand.get_selected_artist_preset(
                    platform, chat_id, model_name, self.get_config  # type: ignore[attr-defined]
                )
                if selected_artist:
                    merged_config["nai_artist_prompt"] = selected_artist
                    logger.info(f"{self._log_prefix} 使用用户选定的画师串: {selected_artist[:50]}...")
        except Exception as exc:
            logger.warning(f"{self._log_prefix} 获取用户选定画师串失败: {exc}")

        return merged_config

    def _get_version_config(self, model_name: str) -> Dict[str, Any]:
        if not model_name:
            return {}

        if "nai-diffusion-3" in model_name:
            config_section = "model_nai3"
            logger.info(f"{self._log_prefix} 检测到 NAI V3 模型，使用 {config_section} 配置")
        elif "nai-diffusion-4-5" in model_name:
            config_section = "model_nai4_5"
            logger.info(f"{self._log_prefix} 检测到 NAI V4.5 模型，使用 {config_section} 配置")
        elif "nai-diffusion-4" in model_name:
            config_section = "model_nai4"
            logger.info(f"{self._log_prefix} 检测到 NAI V4 模型，使用 {config_section} 配置")
        else:
            return {}

        return self.get_config(config_section, {})  # type: ignore[attr-defined]

    @property
    def _log_prefix(self) -> str:
        return getattr(self, "log_prefix", "nai_pic_plugin")

    def _get_chat_identity(self) -> Tuple[str, str, str]:
        """
        返回 (platform, chat_id, user_id)
        """
        message = getattr(self, "action_message", None) or getattr(self, "message", None)
        if not message or not getattr(message, "message_info", None):
            return "", "", ""

        info = message.message_info
        platform = str(getattr(info, "platform", "") or "")

        group_info = getattr(info, "group_info", None)
        user_info = getattr(info, "user_info", None)

        chat_id = ""
        if group_info and getattr(group_info, "group_id", None):
            chat_id = str(group_info.group_id)
        elif user_info and getattr(user_info, "user_id", None):
            chat_id = str(user_info.user_id)

        user_id = str(getattr(user_info, "user_id", "") if user_info else "")

        return platform, chat_id, user_id

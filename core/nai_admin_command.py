# -*- coding: utf-8 -*-
"""
NAI 管理员权限控制命令
"""
from typing import Tuple, Optional

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger

logger = get_logger("nai_admin_command")


class NaiAdminControlCommand(BaseCommand):
    """NAI 管理员模式控制命令"""

    # 类级别的管理员模式状态
    _admin_mode_enabled = {}

    # 类级别的模型选择状态（会话级别）
    _selected_models = {}

    # 类级别的画师串选择状态（会话级别）
    _selected_artist_presets = {}

    # 类级别的尺寸选择状态（会话级别）
    _selected_sizes = {}

    # 模型映射表
    MODEL_MAPPINGS = {
        "3": "nai-diffusion-3",
        "f3": "nai-diffusion-furry-3",
        "4": "nai-diffusion-4-full",
        "4.5": "nai-diffusion-4-5-full",
    }

    # 尺寸映射表
    SIZE_MAPPINGS = {
        "竖": "832x1216",
        "竖图": "832x1216",
        "横": "1216x832",
        "横图": "1216x832",
        "方": "1024x1024",
        "方图": "1024x1024",
        "h": "1216x832",  # horizontal
        "v": "832x1216",  # vertical
        "s": "1024x1024", # square
    }

    # Command基本信息
    command_name = "nai_admin_control_command"
    command_description = "NAI管理员模式控制命令：/nai <st|sp|set|art|size|help>"
    command_pattern = r"(?:.*，说：\s*)?/nai\s+(?P<action>st|sp|set|art|size|help)(?:\s+(?P<param>.+))?$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行管理员模式控制命令"""
        logger.info(f"{self.log_prefix} 执行NAI管理员模式控制命令")

        # 获取匹配的参数
        action = self.matched_groups.get("action", "").strip()
        param = self.matched_groups.get("param", "").strip() if self.matched_groups.get("param") else ""

        # 获取当前会话的key（支持群聊和私聊）
        if not self.message or not getattr(self.message, "message_info", None):
            await self.send_text("❌ 无法获取会话信息", storage_message=False)
            return False, "无法获取会话信息", True

        message_info = self.message.message_info
        platform = getattr(message_info, "platform", "")
        group_info = getattr(message_info, "group_info", None)
        user_info = getattr(message_info, "user_info", None)

        if not user_info:
            await self.send_text("❌ 无法获取用户信息", storage_message=False)
            return False, "无法获取用户信息", True

        if group_info and getattr(group_info, "group_id", None):
            chat_id = group_info.group_id
            chat_type = "群聊"
        else:
            chat_id = user_info.user_id
            chat_type = "私聊"

        current_chat_key = f"{platform}:{chat_id}"
        user_id = user_info.user_id

        # help 命令对所有人开放，不需要权限检查
        if action == "help":
            return await self._handle_help()

        # 权限检查逻辑：
        # 1. st/sp 始终需要管理员权限（控制开关）
        # 2. set/art 如果管理员模式开启则需要管理员权限，否则所有人可用
        is_admin = self._check_admin_permission()

        # st/sp 操作始终需要管理员权限
        if action in ["st", "sp"]:
            if not is_admin:
                await self.send_text("❌ 只有管理员可以开启/关闭管理员模式", storage_message=False)
                return False, "没有管理员权限", True

        # set/art/size 操作根据管理员模式状态判断
        elif action in ["set", "art", "size"]:
            # 检查是否启用了管理员模式
            admin_mode_enabled = self.is_admin_mode_enabled(platform, chat_id, self.get_config)
            if admin_mode_enabled and not is_admin:
                await self.send_text("❌ 当前会话已开启管理员模式，仅管理员可使用此命令", storage_message=False)
                return False, "没有权限", True

        # 执行具体操作
        if action == "set":
            return await self._handle_set_model(current_chat_key, param)

        if action == "art":
            return await self._handle_set_artist(current_chat_key, param)

        if action == "size":
            return await self._handle_set_size(current_chat_key, param)

        if action == "st":
            # 开启管理员模式
            self._admin_mode_enabled[current_chat_key] = True
            await self.send_text(
                f"✅ 已在{chat_type}中开启NAI管理员模式\n"
                f"🔒 现在所有NAI命令仅管理员可使用\n"
                f"💡 使用 /nai sp 可关闭此模式"
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已开启管理员模式")
            return True, "管理员模式已开启", True

        elif action == "sp":
            # 关闭管理员模式
            self._admin_mode_enabled[current_chat_key] = False
            await self.send_text(
                f"✅ 已在{chat_type}中关闭NAI管理员模式\n"
                f"🔓 现在所有人都可使用NAI命令\n"
                f"💡 使用 /nai st 可重新开启"
            )
            logger.info(f"{self.log_prefix} {chat_type} {current_chat_key} 已关闭管理员模式")
            return True, "管理员模式已关闭", True

        else:
            await self.send_text(
                "使用方法：\n"
                "/nai st - 开启管理员模式（仅管理员可用）\n"
                "/nai sp - 关闭管理员模式（所有人可用）\n"
                "/nai set <模型> - 切换生图模型 (3/f3/4/4.5)\n"
                "/nai art <编号> - 切换画师风格预设\n"
                "/nai size <尺寸> - 切换图片尺寸 (竖/横/方)\n"
                "/nai help - 查看所有命令帮助"
            )
            return False, "无效的操作参数", True

    async def _handle_help(self) -> Tuple[bool, Optional[str], bool]:
        """处理帮助命令"""
        help_text = """📖 NovelAI 图片生成插件命令帮助

【生图命令】
/nai <描述> - 使用自然语言生成图片
  示例：/nai 画一张初音未来
/nai0 <英文标签> - 直接使用英文标签生成图片
  示例：/nai0 1girl, hatsune miku, smile

【模型管理】
/nai set - 查看当前模型和可用模型列表
/nai set <代号> - 切换生图模型
  可用模型：3=V3, f3=Furry V3, 4=V4, 4.5=V4.5
  示例：/nai set 4.5

【画师风格】
/nai art - 查看当前画师串列表
/nai art <编号> - 切换画师风格预设
  示例：/nai art 2

【图片尺寸】
/nai size - 查看当前尺寸
/nai size <尺寸> - 切换图片尺寸
  可用尺寸：竖/v=竖图(832x1216), 横/h=横图(1216x832), 方/s=方图(1024x1024)
  示例：/nai size 横

【自动撤回】
/nai on - 开启图片自动撤回功能
/nai off - 关闭图片自动撤回功能

【提示词显示】
/nai pt on - 开启提示词显示（生图时显示生成的提示词）
/nai pt off - 关闭提示词显示

【管理员功能】（仅管理员可用）
/nai st - 开启管理员模式（限制所有命令仅管理员使用）
/nai sp - 关闭管理员模式（所有人可用）

【其他】
/nai help - 显示此帮助信息

💡 提示：管理员模式开启后，所有命令仅管理员可用"""

        await self.send_text(help_text)
        return True, "显示帮助信息", True

    async def _handle_set_model(self, chat_key: str, model_key: str) -> Tuple[bool, Optional[str], bool]:
        """处理模型切换命令"""
        if not model_key:
            # 显示当前模型和可用模型列表
            current_model = self._selected_models.get(chat_key)
            if current_model:
                current_display = f"当前模型: {current_model}"
            else:
                default_model = self.get_config("model.default_model", "nai-diffusion-4-5-full")
                current_display = f"当前使用默认模型: {default_model}"

            await self.send_text(
                f"{current_display}\n\n"
                "可用模型:\n"
                "3 - nai-diffusion-3\n"
                "f3 - nai-diffusion-furry-3\n"
                "4 - nai-diffusion-4-full\n"
                "4.5 - nai-diffusion-4-5-full\n\n"
                "使用方法: /nai set <模型代号>"
            )
            return True, "显示模型列表", True

        # 检查模型代号是否有效
        if model_key not in self.MODEL_MAPPINGS:
            await self.send_text(
                f"❌ 无效的模型代号: {model_key}\n\n"
                "可用模型:\n"
                "3 - nai-diffusion-3\n"
                "f3 - nai-diffusion-furry-3\n"
                "4 - nai-diffusion-4-full\n"
                "4.5 - nai-diffusion-4-5-full"
            )
            return False, "无效的模型代号", True

        # 设置模型
        model_name = self.MODEL_MAPPINGS[model_key]
        self._selected_models[chat_key] = model_name

        await self.send_text(
            f"✅ 已切换到模型: {model_name}\n"
            f"代号: {model_key}"
        )
        logger.info(f"{self.log_prefix} 会话 {chat_key} 已切换到模型 {model_name}")
        return True, f"已切换到模型 {model_name}", True

    async def _handle_set_artist(self, chat_key: str, preset_index: str) -> Tuple[bool, Optional[str], bool]:
        """处理画师串切换命令"""
        # 获取当前使用的模型
        current_model = self._selected_models.get(chat_key)
        if not current_model:
            current_model = self.get_config("model.default_model", "nai-diffusion-4-5-full")

        # 根据模型确定配置节
        if "nai-diffusion-3" in current_model:
            config_section = "model_nai3"
            model_display = "NAI V3"
        elif "nai-diffusion-4-5" in current_model:
            config_section = "model_nai4_5"
            model_display = "NAI V4.5"
        elif "nai-diffusion-4" in current_model:
            config_section = "model_nai4"
            model_display = "NAI V4"
        else:
            await self.send_text("❌ 当前模型不支持画师串切换")
            return False, "模型不支持画师串", True

        # 获取画师串列表（原始格式）
        artist_presets_raw = self.get_config(f"{config_section}.artist_presets", [])

        if not artist_presets_raw:
            await self.send_text(f"❌ {model_display} 模型未配置画师串预设")
            return False, "未配置画师串", True

        # 解析画师串列表，支持新旧格式
        artist_presets = self._parse_artist_presets(artist_presets_raw)

        # 如果没有提供索引，显示列表
        if not preset_index:
            current_index = self._selected_artist_presets.get(chat_key, 1)
            preset_list = "\n".join([
                f"{'→ ' if i == current_index else '  '}{i}. {preset['name']}"
                for i, preset in enumerate(artist_presets, 1)
            ])

            await self.send_text(
                f"当前模型: {model_display}\n"
                f"当前画师串: #{current_index} - {artist_presets[current_index - 1]['name']}\n\n"
                f"可用画师串:\n{preset_list}\n\n"
                f"使用方法: /nai art <编号>"
            )
            return True, "显示画师串列表", True

        # 验证索引
        try:
            index = int(preset_index)
            if index < 1 or index > len(artist_presets):
                await self.send_text(
                    f"❌ 无效的画师串编号: {index}\n"
                    f"可用范围: 1-{len(artist_presets)}"
                )
                return False, "无效的画师串编号", True
        except ValueError:
            await self.send_text("❌ 画师串编号必须是数字")
            return False, "无效的画师串编号", True

        # 设置画师串
        self._selected_artist_presets[chat_key] = index
        selected_preset = artist_presets[index - 1]

        await self.send_text(
            f"✅ 已切换到画师串 #{index}\n"
            f"名称: {selected_preset['name']}\n"
            f"模型: {model_display}"
        )
        logger.info(f"{self.log_prefix} 会话 {chat_key} 已切换到画师串 #{index} ({selected_preset['name']})")
        return True, f"已切换到画师串 #{index}", True

    async def _handle_set_size(self, chat_key: str, size_key: str) -> Tuple[bool, Optional[str], bool]:
        """处理尺寸切换命令"""
        if not size_key:
            # 显示当前尺寸和可用尺寸列表
            current_size = self._selected_sizes.get(chat_key)
            if current_size:
                # 反向查找尺寸的友好名称
                size_name = "自定义"
                for key, value in self.SIZE_MAPPINGS.items():
                    if value == current_size and key in ["竖图", "横图", "方图"]:
                        size_name = key
                        break
                current_display = f"当前尺寸: {size_name} ({current_size})"
            else:
                current_display = "当前使用默认配置尺寸"

            await self.send_text(
                f"{current_display}\n\n"
                "可用尺寸:\n"
                "竖/v - 竖图 (832x1216)\n"
                "横/h - 横图 (1216x832)\n"
                "方/s - 方图 (1024x1024)\n\n"
                "使用方法: /nai size <尺寸代号>"
            )
            return True, "显示尺寸列表", True

        # 检查尺寸代号是否有效
        if size_key not in self.SIZE_MAPPINGS:
            await self.send_text(
                f"❌ 无效的尺寸代号: {size_key}\n\n"
                "可用尺寸:\n"
                "竖/v - 竖图 (832x1216)\n"
                "横/h - 横图 (1216x832)\n"
                "方/s - 方图 (1024x1024)"
            )
            return False, "无效的尺寸代号", True

        # 设置尺寸
        size_value = self.SIZE_MAPPINGS[size_key]
        self._selected_sizes[chat_key] = size_value

        # 获取友好的尺寸名称
        size_names = {
            "832x1216": "竖图",
            "1216x832": "横图",
            "1024x1024": "方图"
        }
        size_display = size_names.get(size_value, size_value)

        await self.send_text(
            f"✅ 已切换到: {size_display}\n"
            f"尺寸: {size_value}"
        )
        logger.info(f"{self.log_prefix} 会话 {chat_key} 已切换到尺寸 {size_value}")
        return True, f"已切换到尺寸 {size_value}", True

    def _check_admin_permission(self) -> bool:
        """检查当前用户是否是管理员"""
        try:
            admin_users = self.get_config("admin.admin_users", [])
            if not admin_users:
                # 如果未配置管理员列表，默认允许所有人管理
                logger.warning(f"{self.log_prefix} 未配置管理员列表，允许所有人使用管理命令")
                return True

            if not self.message or not getattr(self.message, "message_info", None):
                logger.warning(f"{self.log_prefix} 无法获取消息信息")
                return False

            message_info = self.message.message_info
            user_info = getattr(message_info, "user_info", None)
            user_id = str(getattr(user_info, "user_id", "")) if user_info else None
            is_admin = user_id in admin_users

            logger.debug(f"{self.log_prefix} 用户 {user_id} 管理员检查结果: {is_admin}")
            return is_admin
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查管理员权限时出错: {e}", exc_info=True)
            return False

    @staticmethod
    def _parse_artist_presets(presets_raw):
        """
        解析画师串预设列表，兼容新旧格式

        新格式：[{"name": "风格名", "prompt": "画师串内容"}, ...]
        旧格式：["画师串内容1", "画师串内容2", ...]

        Returns:
            List[Dict]: 统一返回 [{"name": "...", "prompt": "..."}, ...]
        """
        if not presets_raw:
            return []

        result = []
        for i, preset in enumerate(presets_raw, 1):
            if isinstance(preset, dict):
                # 新格式：已经是字典
                name = preset.get("name", f"画师串 {i}")
                prompt = preset.get("prompt", "")
                result.append({"name": name, "prompt": prompt})
            elif isinstance(preset, str):
                # 旧格式：纯字符串，自动生成名称
                # 使用前30个字符作为默认名称
                preview = preset[:30] + "..." if len(preset) > 30 else preset
                result.append({"name": f"#{i} {preview}", "prompt": preset})
            else:
                logger.warning(f"跳过无效的画师串格式: {type(preset)}")
                continue

        return result

    @classmethod
    def is_admin_mode_enabled(cls, platform: str, chat_id: str, get_config_func) -> bool:
        """
        静态方法：检查指定会话是否启用了管理员模式

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）
            get_config_func: 获取配置的函数

        Returns:
            bool: 是否启用管理员模式
        """
        current_chat_key = f"{platform}:{chat_id}"

        # 检查运行时覆盖
        if current_chat_key in cls._admin_mode_enabled:
            return cls._admin_mode_enabled[current_chat_key]

        # 检查默认配置
        return get_config_func("admin.default_admin_mode", False)

    @classmethod
    def check_user_permission(cls, platform: str, chat_id: str, user_id: str, get_config_func) -> bool:
        """
        静态方法：检查用户是否有权限使用生图命令

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）
            user_id: 用户ID
            get_config_func: 获取配置的函数

        Returns:
            bool: 是否有权限
        """
        # 如果管理员模式未开启，所有人都有权限
        if not cls.is_admin_mode_enabled(platform, chat_id, get_config_func):
            return True

        # 管理员模式已开启，检查��否是管理员
        admin_users = get_config_func("admin.admin_users", [])
        return str(user_id) in admin_users

    @classmethod
    def get_selected_model(cls, platform: str, chat_id: str, get_config_func) -> Optional[str]:
        """
        静态方法：获取指定会话选定的模型

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）
            get_config_func: 获取配置的函数

        Returns:
            Optional[str]: 选定的模型名称，如果未设置则返回 None
        """
        current_chat_key = f"{platform}:{chat_id}"
        return cls._selected_models.get(current_chat_key)

    @classmethod
    def get_selected_artist_preset(cls, platform: str, chat_id: str, model_name: str, get_config_func) -> Optional[str]:
        """
        静态方法：获取指定会话选定的画师串

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）
            model_name: 当前使用的模型名称
            get_config_func: 获取配置的函数

        Returns:
            Optional[str]: 选定的画师串内容，如果未设置则返回第一个预设（如果存在）
        """
        current_chat_key = f"{platform}:{chat_id}"

        # 根据模型确定配置节
        if "nai-diffusion-3" in model_name:
            config_section = "model_nai3"
        elif "nai-diffusion-4-5" in model_name:
            config_section = "model_nai4_5"
        elif "nai-diffusion-4" in model_name:
            config_section = "model_nai4"
        else:
            return None

        # 获取画师串列表（原始格式）
        artist_presets_raw = get_config_func(f"{config_section}.artist_presets", [])
        if not artist_presets_raw:
            return None

        # 解析画师串列表，兼容新旧格式
        artist_presets = cls._parse_artist_presets(artist_presets_raw)
        if not artist_presets:
            return None

        # 获取选定的索引，默认为1（第一个）
        selected_index = cls._selected_artist_presets.get(current_chat_key, 1)

        # 确保索引有效，返回 prompt 内容
        if 1 <= selected_index <= len(artist_presets):
            return artist_presets[selected_index - 1]["prompt"]
        else:
            return artist_presets[0]["prompt"] if artist_presets else None

    @classmethod
    def get_selected_size(cls, platform: str, chat_id: str) -> Optional[str]:
        """
        静态方法：获取指定会话选定的尺寸

        Args:
            platform: 平台标识
            chat_id: 会话ID（可以是group_id或user_id）

        Returns:
            Optional[str]: 选定的尺寸（如 "832x1216"），如果未设置则返回 None
        """
        current_chat_key = f"{platform}:{chat_id}"
        return cls._selected_sizes.get(current_chat_key)

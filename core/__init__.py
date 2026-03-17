# -*- coding: utf-8 -*-
"""
NovelAI Web 图片生成插件核心模块

目录结构：
- services/  : 服务层（状态管理、提示词生成、图片生成）
- commands/  : 命令层（用户命令处理）
- actions/   : 动作层（智能触发）
- mixins/    : 混入层（通用功能复用）
- clients/   : 客户端层（外部API调用）
- rules/     : 规则层（提示词模板）
- utils/     : 工具层（通用工具函数）
"""

# 服务层
from .services.session_state import session_state, SessionStateManager
from .services.prompt_generator import PromptGeneratorService
from .services.image_generator import ImageGenerationService

# 命令层
from .commands.nai_draw_command import NaiDrawCommand
from .commands.nai_0_draw_command import Nai0DrawCommand
from .commands.nai_admin_command import NaiAdminControlCommand
from .commands.nai_recall_command import NaiRecallControlCommand
from .commands.nai_nsfw_command import NaiNsfwControlCommand
from .commands.nai_prompt_show_command import NaiPromptShowCommand

# 动作层
from .actions.nai_pic_action import NaiPicAction

# 混入层
from .mixins.model_config_mixin import ModelConfigMixin
from .mixins.auto_recall_mixin import AutoRecallMixin

# 客户端层
from .clients.nai_web_client import NaiWebClient

# 工具层
from .utils.image_url_helper import save_base64_image_to_file
from .utils.danbooru_api import DanbooruAPI

__all__ = [
    # 服务
    "session_state",
    "SessionStateManager",
    "PromptGeneratorService",
    "ImageGenerationService",
    # 命令
    "NaiDrawCommand",
    "Nai0DrawCommand",
    "NaiAdminControlCommand",
    "NaiRecallControlCommand",
    "NaiNsfwControlCommand",
    "NaiPromptShowCommand",
    # 动作
    "NaiPicAction",
    # 混入
    "ModelConfigMixin",
    "AutoRecallMixin",
    # 客户端
    "NaiWebClient",
    # 工具
    "save_base64_image_to_file",
    "DanbooruAPI",
]

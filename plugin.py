from typing import List, Tuple, Type

from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.component_types import ComponentInfo
from src.plugin_system import register_plugin
from src.plugin_system.base.config_types import ConfigField

from .core.nai_pic_action import NaiPicAction
from .core.nai_recall_command import NaiRecallControlCommand
from .core.nai_draw_command import NaiDrawCommand
from .core.nai_0_draw_command import Nai0DrawCommand
from .core.nai_admin_command import NaiAdminControlCommand


@register_plugin
class NaiPicPlugin(BasePlugin):
    """NovelAI Web 图片生成插件，专用于 std.loliyc.com 等 NovelAI 网页代理接口"""

    # 插件基本信息
    plugin_name = "nai_pic_plugin"
    plugin_version = "1.1.0"
    plugin_author = "Rabbit"
    enable_plugin = True
    dependencies: List[str] = []
    python_dependencies: List[str] = ["requests"]
    config_file_name = "config.toml"

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本配置",
        "model": "NovelAI Web 模型配置",
        "model_nai3": "NovelAI V3 模型专用配置（nai-diffusion-3 和 nai-diffusion-3-furry）",
        "model_nai4": "NovelAI V4 模型专用配置（nai-diffusion-4-curated、nai-diffusion-4-full 等）",
        "model_nai4_5": "NovelAI V4.5 模型专用配置（nai-diffusion-4-5-full 等最新模型）",
        "components": "组件配置",
        "auto_recall": "自动撤回配置",
        "admin": "管理员权限配置",
        "prompt_generator": "提示词生成配置",
        "prompt_fallback": "提示词生成配置（兼容旧配置名）",
    }

    # 配置Schema
    config_schema = {
        "plugin": {
            "name": ConfigField(
                type=str,
                default="nai_pic_plugin",
                description="NovelAI Web 图片生成插件",
                required=True
            ),
            "config_version": ConfigField(
                type=str,
                default="1.0.0",
                description="插件配置版本号"
            ),
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用插件"
            )
        },
        "model": {
            "name": ConfigField(
                type=str,
                default="NovelAI Web (std.loliyc.com)",
                description="模型显示名称"
            ),
            "base_url": ConfigField(
                type=str,
                default="https://std.loliyc.com",
                description="NovelAI Web API 基础地址",
                required=True
            ),
            "api_key": ConfigField(
                type=str,
                default="",
                description="API Token（如需要）",
                required=False
            ),
            "available_models": ConfigField(
                type=list,
                default=[
                    "nai-diffusion-3",
                    "nai-diffusion-3-furry",
                    "nai-diffusion-4-curated",
                    "nai-diffusion-4-full",
                    "nai-diffusion-4-5-full"
                ],
                description="可用的 NovelAI 模型列表"
            ),
            "default_model": ConfigField(
                type=str,
                default="nai-diffusion-4-5-full",
                description="当前使用的模型名称（从 available_models 中选择）"
            ),
            "nai_endpoint": ConfigField(
                type=str,
                default="/generate",
                description="API 端点路径"
            ),
        },
        "model_nai3": {
            "artist_presets": ConfigField(
                type=list,
                default=[
                    {"name": "示例风格1", "prompt": "artist:example1, artist:example2, year 2023"},
                    {"name": "示例风格2", "prompt": "artist:example3, artist:example4, year 2024"}
                ],
                description="NAI V3 画师风格预设列表（可配置多个），每个预设包含 name（显示名称）和 prompt（画师串内容）"
            ),
            "nai_artist_prompt": ConfigField(
                type=str,
                default="",
                description="NAI V3 专用画师风格提示词（可选，优先级低于 artist_presets）"
            ),
            "nai_size": ConfigField(
                type=str,
                default="竖图",
                description="NAI V3 专用图片尺寸"
            ),
            "nai_cfg": ConfigField(
                type=float,
                default=0.0,
                description="NAI V3 专用CFG参数"
            ),
            "nai_noise_schedule": ConfigField(
                type=str,
                default="karras",
                description="NAI V3 专用噪声调度器"
            ),
            "nai_nocache": ConfigField(
                type=int,
                default=0,
                description="NAI V3 专用缓存设置"
            ),
            "sampler": ConfigField(
                type=str,
                default="k_euler_ancestral",
                description="NAI V3 专用采样器"
            ),
            "num_inference_steps": ConfigField(
                type=int,
                default=28,
                description="NAI V3 专用推理步数"
            ),
            "guidance_scale": ConfigField(
                type=float,
                default=5.0,
                description="NAI V3 专用指导强度"
            ),
            "default_size": ConfigField(
                type=str,
                default="1024x1280",
                description="NAI V3 专用默认尺寸"
            ),
            "custom_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V3 专用自动添加的提示词后缀"
            ),
            "negative_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V3 专用负面提示词"
            ),
            "selfie_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V3 专用自拍模式提示词"
            ),
            "nai_extra_params": ConfigField(
                type=dict,
                default={},
                description="NAI V3 专用额外参数"
            )
        },
        "model_nai4": {
            "artist_presets": ConfigField(
                type=list,
                default=[
                    {"name": "风格组合1", "prompt": "1.2::artist1::, 1.0::artist2::, 0.9::artist3::"},
                    {"name": "风格组合2", "prompt": "1.5::artist4::, 1.0::artist5::, 0.8::artist6::"}
                ],
                description="NAI V4 画师风格预设列表（可配置多个），每个预设包含 name（显示名称）和 prompt（画师串内容）"
            ),
            "nai_artist_prompt": ConfigField(
                type=str,
                default="",
                description="NAI V4 专用画师风格提示词（可选，优先级低于 artist_presets）"
            ),
            "nai_size": ConfigField(
                type=str,
                default="竖图",
                description="NAI V4 专用图片尺寸"
            ),
            "nai_cfg": ConfigField(
                type=float,
                default=0.0,
                description="NAI V4 专用CFG参数"
            ),
            "nai_noise_schedule": ConfigField(
                type=str,
                default="karras",
                description="NAI V4 专用噪声调度器"
            ),
            "nai_nocache": ConfigField(
                type=int,
                default=0,
                description="NAI V4 专用缓存设置"
            ),
            "sampler": ConfigField(
                type=str,
                default="k_euler_ancestral",
                description="NAI V4 专用采样器"
            ),
            "num_inference_steps": ConfigField(
                type=int,
                default=28,
                description="NAI V4 专用推理步数"
            ),
            "guidance_scale": ConfigField(
                type=float,
                default=5.0,
                description="NAI V4 专用指导强度"
            ),
            "default_size": ConfigField(
                type=str,
                default="1024x1280",
                description="NAI V4 专用默认尺寸"
            ),
            "custom_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V4 专用自动添加的提示词后缀"
            ),
            "negative_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V4 专用负面提示词"
            ),
            "selfie_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V4 专用自拍模式提示词"
            ),
            "nai_extra_params": ConfigField(
                type=dict,
                default={},
                description="NAI V4 专用额外参数"
            )
        },
        "model_nai4_5": {
            "artist_presets": ConfigField(
                type=list,
                default=[
                    {"name": "风格示例1", "prompt": "1.2::artist:example1::, 1.0::artist:example2::, 0.8::artist:example3::"},
                    {"name": "风格示例2", "prompt": "1.5::artist:example4::, 1.3::artist:example5::"}
                ],
                description="NAI V4.5 画师风格预设列表（可配置多个），每个预设包含 name（显示名称）和 prompt（画师串内容）"
            ),
            "nai_artist_prompt": ConfigField(
                type=str,
                default="",
                description="NAI V4.5 专用画师风格提示词（可选，优先级低于 artist_presets）"
            ),
            "nai_size": ConfigField(
                type=str,
                default="竖图",
                description="NAI V4.5 专用图片尺寸"
            ),
            "nai_cfg": ConfigField(
                type=float,
                default=0.0,
                description="NAI V4.5 专用CFG参数"
            ),
            "nai_noise_schedule": ConfigField(
                type=str,
                default="karras",
                description="NAI V4.5 专用噪声调度器"
            ),
            "nai_nocache": ConfigField(
                type=int,
                default=0,
                description="NAI V4.5 专用缓存设置"
            ),
            "sampler": ConfigField(
                type=str,
                default="k_euler_ancestral",
                description="NAI V4.5 专用采样器"
            ),
            "num_inference_steps": ConfigField(
                type=int,
                default=28,
                description="NAI V4.5 专用推理步数"
            ),
            "guidance_scale": ConfigField(
                type=float,
                default=5.0,
                description="NAI V4.5 专用指导强度"
            ),
            "default_size": ConfigField(
                type=str,
                default="1024x1280",
                description="NAI V4.5 专用默认尺寸"
            ),
            "custom_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V4.5 专用自动添加的提示词后缀"
            ),
            "negative_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V4.5 专用负面提示词"
            ),
            "selfie_prompt_add": ConfigField(
                type=str,
                default="",
                description="NAI V4.5 专用自拍模式提示词"
            ),
            "nai_extra_params": ConfigField(
                type=dict,
                default={},
                description="NAI V4.5 专用额外参数"
            )
        },
        "components": {
            "enable_debug_info": ConfigField(
                type=bool,
                default=False,
                description="是否显示调试信息"
            ),
        },
        "auto_recall": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否默认启用自动撤回"
            ),
            "delay_seconds": ConfigField(
                type=int,
                default=5,
                description="撤回延迟时间（秒）"
            ),
            "id_wait_seconds": ConfigField(
                type=int,
                default=15,
                description="等待正式消息ID的最长时间（秒）"
            ),
            "allowed_groups": ConfigField(
                type=list,
                default=[],
                description="允许使用自动撤回功能的会话白名单（格式：platform:chat_id）"
            )
        },
        "admin": {
            "admin_users": ConfigField(
                type=list,
                default=[],
                description="管理员用户ID列表（字符串格式），管理员可以使用 /nai st/sp 命令控制管理员模式"
            ),
            "default_admin_mode": ConfigField(
                type=bool,
                default=False,
                description="是否默认启用管理员模式（开启后仅管理员可使用 /nai 生图命令）"
            )
        },
        "prompt_generator": {
            "model_name": ConfigField(
                type=str,
                default="",
                description="提示词生成使用的LLM模型代号，留空则自动选择"
            ),
            "temperature": ConfigField(
                type=float,
                default=0.2,
                description="提示词生成LLM的温度设置"
            ),
            "max_tokens": ConfigField(
                type=int,
                default=200,
                description="提示词生成LLM响应的最大token"
            ),
            "prompt_template": ConfigField(
                type=str,
                default="",
                description="自定义提示词生成模板，支持<<USER_REQUEST>>和<<SELFIE_HINT>>占位符"
            )
        },
        "prompt_fallback": {  # 兼容旧配置名
            "model_name": ConfigField(
                type=str,
                default="",
                description="[已兼容] 提示词生成使用的LLM模型代号，留空则自动选择"
            ),
            "temperature": ConfigField(
                type=float,
                default=0.2,
                description="[已兼容] 提示词生成LLM的温度设置"
            ),
            "max_tokens": ConfigField(
                type=int,
                default=200,
                description="[已兼容] 提示词生成LLM响应的最大token"
            ),
            "prompt_template": ConfigField(
                type=str,
                default="",
                description="[已兼容] 自定义提示词生成模板，支持<<USER_REQUEST>>和<<SELFIE_HINT>>占位符"
            )
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""
        components = []
        components.append((NaiPicAction.get_action_info(), NaiPicAction))
        components.append((NaiRecallControlCommand.get_command_info(), NaiRecallControlCommand))
        components.append((NaiAdminControlCommand.get_command_info(), NaiAdminControlCommand))
        components.append((NaiDrawCommand.get_command_info(), NaiDrawCommand))
        components.append((Nai0DrawCommand.get_command_info(), Nai0DrawCommand))
        return components

from typing import List, Tuple, Type

from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.component_types import ComponentInfo
from src.plugin_system import register_plugin
from src.plugin_system.base.config_types import ConfigField

from .core.actions.nai_pic_action import NaiPicAction
from .core.commands.nai_recall_command import NaiRecallControlCommand
from .core.commands.nai_nsfw_command import NaiNsfwControlCommand
from .core.commands.nai_draw_command import NaiDrawCommand
from .core.commands.nai_0_draw_command import Nai0DrawCommand
from .core.commands.nai_admin_command import NaiAdminControlCommand
from .core.commands.nai_prompt_show_command import NaiPromptShowCommand
from .core.commands.nai_tag_command import NaiTaggerCommand
from .core.commands.nai_manual_recall_command import NaiManualRecallCommand


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
        "prompt_show": "提示词显示配置",
        "prompt_generator": "提示词生成配置",
        "prompt_generator.custom_model": "自定义LLM模型配置（支持多模型、负载均衡）",
        "random_scene": "随机场景生成配置（/nai 随机）",
        "tagger": "图片打标配置（/打标）",
        "custom_prompt": "自定义系统提示词配置",
        "tag_retriever": "Danbooru Tag 检索增强配置",
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
            "default_artist_preset": ConfigField(
                type=str,
                default="",
                description="NAI V3 默认画师风格预设，支持填写预设名称或序号；留空时默认使用第一个预设"
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
            "default_artist_preset": ConfigField(
                type=str,
                default="",
                description="NAI V4 默认画师风格预设，支持填写预设名称或序号；留空时默认使用第一个预设"
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
            "default_artist_preset": ConfigField(
                type=str,
                default="",
                description="NAI V4.5 默认画师风格预设，支持填写预设名称或序号；留空时默认使用第一个预设"
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
        "prompt_show": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否默认启用提示词显示（使用 /nai pt on|off 可在运行时切换）"
            ),
            "hide_selfie_prompt_add": ConfigField(
                type=bool,
                default=False,
                description="提示词显示时是否隐藏配置文件中的自拍补充提示词（selfie_prompt_add）。仅影响展示，不影响实际生图。"
            )
        },
        "nsfw_filter": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否默认启用NSFW内容过滤（使用 /nai nsfw on|off 可在运行时切换）"
            ),
            "filter_tags": ConfigField(
                type=str,
                default="{{{{{nsfw}}}}}",
                description="NSFW过滤标签（高权重），当启用过滤时自动添加到负面提示词"
            )
        },
        "prompt_generator": {
            "model_name": ConfigField(
                type=str,
                default="",
                description="提示词生成使用的LLM模型代号，留空则自动选择"
            ),
            "output_format": ConfigField(
                type=str,
                default="json",
                description="提示词生成输出格式：json=结构化输出（默认，支持多人分段与意图元数据），text=纯提示词"
            ),
            "selfie_appearance_policy": ConfigField(
                type=str,
                default="auto",
                description="自拍外貌标签策略：auto=仅在用户未指定外貌时移除LLM随机发色/发型/瞳色（尽量保留配置中的自拍特征），never=始终移除（除非用户明确指定），keep=不移除"
            ),
            "enforce_tag_order": ConfigField(
                type=bool,
                default=False,
                description="是否对最终提示词做轻量排序（人数/视角前置、year后置），降低顺序混乱"
            ),
            "temperature": ConfigField(
                type=float,
                default=0.2,
                description="提示词生成LLM的温度设置"
            ),
            "max_tokens": ConfigField(
                type=int,
                default=500,
                description="提示词生成LLM响应的最大token"
            ),
            "prompt_template": ConfigField(
                type=str,
                default="",
                description="自定义提示词生成模板，支持<<USER_REQUEST>>、<<SELFIE_HINT>>、<<CURRENT_TIME_CONTEXT>>、<<SELFIE_SCENE_CONTEXT>>占位符"
            ),
            "inherit_ttl": ConfigField(
                type=int,
                default=3600,
                description="上一轮提示词继承的有效时间（秒），超过后不再继承。默认3600（1小时），0=永不过期"
            ),
            "custom_model": ConfigField(
                type=dict,
                default={
                    "model_list": [],
                    "max_tokens": 500,
                    "temperature": 0.2,
                    "slow_threshold": 30.0
                },
                description="自定义模型配置（可选），model_list 中的模型名称必须是系统 model_config 中已定义的模型"
            )
        },
        "random_scene": {
            "model_name": ConfigField(
                type=str,
                default="",
                description="随机场景生成使用的LLM模型代号，留空则回退到 prompt_generator 配置"
            ),
            "temperature": ConfigField(
                type=float,
                default=1.0,
                description="随机场景生成LLM的温度设置"
            ),
            "max_tokens": ConfigField(
                type=int,
                default=200,
                description="随机场景生成LLM响应的最大token"
            ),
        },
        "tagger": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用 /打标 命令"
            ),
            "model_task": ConfigField(
                type=str,
                default="vlm",
                description="打标使用的模型任务名（对应 model_config.model_task_config.<name>，默认 vlm）"
            ),
            "custom_model": ConfigField(
                type=dict,
                default={
                    "model_list": [],
                    "max_tokens": 1024,
                    "temperature": 0.2,
                    "slow_threshold": 30.0
                },
                description=(
                    "打标专用自定义模型配置（可选）。"
                    "当 model_list 非空时将优先使用该配置，完全独立于 model_task。"
                    "若未显式设置 tagger.max_tokens/tagger.temperature，将默认采用这里的同名值。"
                    "注意：所选模型必须支持图像输入。"
                )
            ),
            "temperature": ConfigField(
                type=float,
                default=0.2,
                description="打标模型温度（越低越稳定）"
            ),
            "max_tokens": ConfigField(
                type=int,
                default=1200,
                description="打标模型最大输出 token"
            ),
        },
        "custom_prompt": {
            "system_prompt": ConfigField(
                type=str,
                default="",
                description="自定义系统提示词，会添加到 LLM 提示词规则的最前面，可用于自定义额外指导或规则"
            ),
        },
        "tag_retriever": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用 Danbooru Tag 检索增强（使用 embedding 模型从 tag 对照表中检索相关标签注入 LLM 提示模板）"
            ),
            "top_k": ConfigField(
                type=int,
                default=40,
                description="检索返回的候选 tag 数量"
            ),
            "min_score": ConfigField(
                type=float,
                default=0.3,
                description="最低相似度阈值（低于此分数的不返回）"
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""
        components = []
        components.append((NaiPicAction.get_action_info(), NaiPicAction))
        components.append((NaiRecallControlCommand.get_command_info(), NaiRecallControlCommand))
        components.append((NaiNsfwControlCommand.get_command_info(), NaiNsfwControlCommand))
        components.append((NaiAdminControlCommand.get_command_info(), NaiAdminControlCommand))
        components.append((NaiDrawCommand.get_command_info(), NaiDrawCommand))
        components.append((Nai0DrawCommand.get_command_info(), Nai0DrawCommand))
        components.append((NaiPromptShowCommand.get_command_info(), NaiPromptShowCommand))
        if self.get_config("tagger.enabled", True):
            components.append((NaiTaggerCommand.get_command_info(), NaiTaggerCommand))
        components.append((NaiManualRecallCommand.get_command_info(), NaiManualRecallCommand))
        return components

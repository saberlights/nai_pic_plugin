# -*- coding: utf-8 -*-
"""
/nai0 命令：直接使用英文 tag 生成图片，不经过 LLM 处理
"""
import time
from typing import Tuple, Optional, Dict, Any

from src.plugin_system.base.base_command import BaseCommand
from src.common.logger import get_logger

from .nai_web_client import NaiWebClient
from .auto_recall_mixin import AutoRecallMixin
from .image_url_helper import save_base64_image_to_file
from .model_config_mixin import ModelConfigMixin

logger = get_logger("nai_pic_plugin")


class Nai0DrawCommand(ModelConfigMixin, AutoRecallMixin, BaseCommand):
    """NovelAI 直接标签生图命令：/nai0 [英文tag]"""

    command_name = "nai_0_draw"
    command_description = "直接使用英文标签生成图片，不经过LLM处理，例如：/nai0 hatsune miku, smile"
    command_pattern = r"(?:.*，说：\s*)?/nai0\s+(?P<tags>.+)$"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_client = NaiWebClient(self)

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """执行 /nai0 命令"""
        logger.info(f"{self.log_prefix} 执行 /nai0 命令")

        # 检查用户权限
        has_permission = self._check_user_permission()
        if not has_permission:
            await self.send_text("❌ 当前会话已开启管理员模式，仅管理员可使用此命令", storage_message=False)
            return False, "没有权限", True

        # 获取用户输入的英文 tags
        tags = self.matched_groups.get("tags", "").strip()

        if not tags:
            await self.send_text("请输入英文标签，例如：/nai0 hatsune miku, smile")
            return False, "未提供标签", True

        logger.info(f"{self.log_prefix} 用户输入的标签: {tags}")

        # 直接使用用户输入的 tags 作为提示词
        prompt = tags

        # 获取模型配置
        model_config = self._get_model_config()
        if not model_config or not model_config.get("base_url"):
            await self.send_text("NovelAI 配置错误，请检查配置文件")
            return False, "配置错误", True

        # 获取图片尺寸
        image_size = model_config.get("nai_size") or model_config.get("default_size", "1024x1280")

        # 显示处理信息
        enable_debug = self.get_config("components.enable_debug_info", False)
        if enable_debug:
            await self.send_text(f"正在生成图片，请稍候...")

        try:
            # 调用 API 生成图片
            success, result = self.api_client.generate_image(
                prompt=prompt,
                model_config=model_config,
                size=image_size
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 图片生成失败: {e!r}", exc_info=True)
            await self.send_text(f"生成图片时出错: {str(e)[:100]}")
            return False, f"生成失败: {e}", True

        if success:
            final_image_data = self._process_api_response(result)

            if final_image_data:
                send_time = time.time()

                # 判断是 URL 还是 base64
                if final_image_data.startswith(("http://", "https://")):
                    # 直接发送图片 URL
                    try:
                        send_success = await self.send_custom("imageurl", final_image_data)
                        if send_success:
                            self._last_send_timestamp = send_time
                            if enable_debug:
                                await self.send_text("图片生成完成！")
                            await self._schedule_auto_recall()
                            return True, "图片生成成功", True
                        else:
                            await self.send_text("图片发送失败")
                            return False, "发送失败", True
                    except Exception as e:
                        logger.error(f"{self.log_prefix} 图片URL发送失败: {e!r}")
                        await self.send_text(f"图片发送失败: {str(e)[:100]}")
                        return False, "发送失败", True
                elif final_image_data.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):
                    # Base64 格式 -> 保存为文件并以URL方式发送
                    image_path = save_base64_image_to_file(final_image_data)
                    if image_path:
                        send_success = await self.send_custom("imageurl", f"file://{image_path}")
                    else:
                        logger.warning(f"{self.log_prefix} 图片保存失败，回退为Base64发送")
                        send_success = await self.send_image(final_image_data)

                    if send_success:
                        self._last_send_timestamp = send_time
                        if enable_debug:
                            await self.send_text("图片生成完成！")
                        await self._schedule_auto_recall()
                        return True, "图片生成成功", True
                    else:
                        await self.send_text("图片发送失败")
                        return False, "发送失败", True
                else:
                    await self.send_text("API 返回了无法识别的图片格式")
                    return False, "数据格式错误", True
            else:
                await self.send_text("API 返回了无效的数据")
                return False, "数据格式错误", True
        else:
            await self.send_text(f"生成图片失败：{result}")
            return False, f"生成失败: {result}", True

    def _process_api_response(self, result: str) -> Optional[str]:
        """处理 API 响应"""
        if not result:
            return None

        if result.startswith(("http://", "https://")):
            return result

        if result.startswith(("iVBORw", "/9j/", "UklGR", "R0lGOD")):
            return result

        if "," in result and result.startswith("data:image"):
            return result.split(",", 1)[1]

        return result

    def _is_auto_recall_enabled(self, platform: str, chat_id: str) -> bool:
        """检查是否启用自动撤回"""
        from .nai_recall_command import NaiRecallControlCommand
        return NaiRecallControlCommand.is_recall_enabled(platform, chat_id, self.get_config)

    def _check_user_permission(self) -> bool:
        """检查当前用户是否有权限使用生图命令"""
        try:
            from .nai_admin_command import NaiAdminControlCommand

            # 获取会话信息
            if not self.message or not getattr(self.message, "message_info", None):
                logger.warning(f"{self.log_prefix} 无法获取 message_info，默认允许")
                return True

            message_info = self.message.message_info
            platform = getattr(message_info, "platform", "")
            group_info = getattr(message_info, "group_info", None)
            user_info = getattr(message_info, "user_info", None)

            if group_info and getattr(group_info, "group_id", None):
                chat_id = group_info.group_id
            elif user_info and getattr(user_info, "user_id", None):
                chat_id = user_info.user_id
            else:
                logger.warning(f"{self.log_prefix} 无法获取 chat_id，默认允许")
                return True

            user_id = getattr(user_info, "user_id", None) if user_info else None
            if not user_id:
                logger.warning(f"{self.log_prefix} 无法获取 user_id，默认允许")
                return True

            # 检查用户权限
            return NaiAdminControlCommand.check_user_permission(
                platform, chat_id, user_id, self.get_config
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 检查用户权限时出错: {e}", exc_info=True)
            # 出错时默认允许
            return True

import base64
import requests
from typing import Dict, Any, Tuple, Optional

from src.common.logger import get_logger

logger = get_logger("nai_pic_plugin")


class NaiWebClient:
    """NovelAI Web API 客户端（std.loliyc.com 风格）"""

    def __init__(self, action_instance):
        self.action = action_instance
        self.log_prefix = action_instance.log_prefix

    def generate_image(self, prompt: str, model_config: Dict[str, Any], size: str = None,
                      input_image_base64: str = None) -> Tuple[bool, str]:
        """调用网页式的NovelAI接口（std.loliyc.com风格）生成图片"""
        try:
            if input_image_base64:
                logger.warning(f"{self.log_prefix} (NaiWeb) 暂不支持图生图请求")
                return False, "当前Nai网页接口不支持图生图"

            base_url = (model_config.get("base_url") or "https://std.loliyc.com").rstrip('/')
            endpoint = model_config.get("nai_endpoint", "/generate")
            if not endpoint.startswith('/'):
                endpoint = f"/{endpoint}"
            url = f"{base_url}{endpoint}"

            api_key = model_config.get("api_key", "")
            token = api_key
            if isinstance(api_key, str) and api_key.lower().startswith("bearer "):
                token = api_key.split(" ", 1)[1]

            custom_prompt_add = model_config.get("custom_prompt_add", "")
            # custom_prompt_add 在最前面
            if custom_prompt_add:
                full_prompt = f"{custom_prompt_add}, {prompt}"
            else:
                full_prompt = prompt

            artist_prompt = model_config.get("nai_artist_prompt") or model_config.get("artist_prompt") or custom_prompt_add

            negative_prompt = model_config.get("negative_prompt_add", "")
            sampler = model_config.get("sampler", "")
            steps = model_config.get("num_inference_steps")
            guidance_scale = model_config.get("guidance_scale")
            cfg_value = model_config.get("nai_cfg")
            noise_schedule = model_config.get("noise_schedule") or model_config.get("nai_noise_schedule")
            nocache = model_config.get("nai_nocache")
            size_override = model_config.get("nai_size")
            extra_params = model_config.get("nai_extra_params") or {}

            params = {
                "tag": full_prompt,
                "model": model_config.get("model", "nai-diffusion-4-5-full")
            }

            if token:
                params["token"] = token
            if artist_prompt:
                params["artist"] = artist_prompt
            if negative_prompt:
                params["negative"] = negative_prompt
            if sampler:
                params["sampler"] = sampler
            if steps is not None:
                params["steps"] = steps
            if guidance_scale is not None:
                params["scale"] = guidance_scale
            if cfg_value is not None:
                params["cfg"] = cfg_value
            if noise_schedule:
                params["noise_schedule"] = noise_schedule
            if nocache is not None:
                params["nocache"] = nocache

            final_size = size_override or size
            if final_size:
                params["size"] = final_size

            if isinstance(extra_params, dict):
                for k, v in extra_params.items():
                    if v not in (None, ""):
                        params[k] = v

            request_kwargs = {
                "url": url,
                "params": params,
                "timeout": 120
            }

            logger.info(f"{self.log_prefix} (NaiWeb) 请求URL: {url}")
            logger.debug(f"{self.log_prefix} (NaiWeb) 参数: tag长度={len(params.get('tag', ''))}, model={params.get('model')}, size={params.get('size')}")
            response = requests.get(**request_kwargs)

            if response.status_code != 200:
                logger.error(f"{self.log_prefix} (NaiWeb) HTTP错误 {response.status_code}: {response.text[:200]}")
                return False, f"HTTP {response.status_code}: {response.text[:100]}"

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    data = response.json()
                except Exception:
                    data = {}

                for key in ("url", "image_url", "image", "data"):
                    value = data.get(key)
                    if isinstance(value, str) and value:
                        logger.info(f"{self.log_prefix} (NaiWeb) 收到JSON字段 {key}")
                        return True, value

                message = data.get("message") or data.get("error") or "未返回图片数据"
                logger.error(f"{self.log_prefix} (NaiWeb) JSON响应无图片: {message}")
                return False, message

            image_base64 = base64.b64encode(response.content).decode('utf-8')
            logger.info(f"{self.log_prefix} (NaiWeb) 图片生成成功，大小 {len(response.content)} bytes")
            return True, image_base64

        except requests.RequestException as e:
            logger.error(f"{self.log_prefix} (NaiWeb) 网络异常: {e}")
            return False, f"网络请求失败: {str(e)}"
        except Exception as e:
            logger.error(f"{self.log_prefix} (NaiWeb) 请求异常: {e!r}", exc_info=True)
            return False, f"Nai网页接口请求失败: {str(e)[:100]}"

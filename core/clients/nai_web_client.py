import asyncio
import base64
import requests
import urllib3
from typing import Dict, Any, Tuple, Optional
from requests.adapters import HTTPAdapter
from requests.exceptions import ProxyError
from urllib3.util.ssl_ import create_urllib3_context

from src.common.logger import get_logger

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_logger("nai_pic_plugin")


class SSLAdapter(HTTPAdapter):
    """自定义SSL适配器，用于处理SSL连接问题"""
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        context.check_hostname = False
        context.verify_mode = 0  # ssl.CERT_NONE
        # 设置更宽松的SSL选项
        context.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)


class NaiWebClient:
    """NovelAI Web API 客户端（std.loliyc.com 风格）"""

    def __init__(self, action_instance):
        self.action = action_instance
        self.log_prefix = action_instance.log_prefix
        self.session = self._create_session(trust_env=True)
        self.direct_session = self._create_session(trust_env=False)
        self._auto_proxy_direct_only = False

    @staticmethod
    def _create_session(trust_env: bool) -> requests.Session:
        """按是否继承环境代理创建 Session。"""
        session = requests.Session()
        session.trust_env = trust_env
        session.mount('https://', SSLAdapter())
        return session

    def _get_session(self, trust_env: bool) -> requests.Session:
        """兼容旧测试构造方式，按需懒加载 Session。"""
        attr_name = "session" if trust_env else "direct_session"
        session = getattr(self, attr_name, None)
        if session is None:
            session = self._create_session(trust_env=trust_env)
            setattr(self, attr_name, session)
        return session

    @staticmethod
    def _resolve_proxy_mode(model_config: Dict[str, Any]) -> str:
        """解析插件内代理模式。"""
        value = model_config.get("nai_proxy_mode") or model_config.get("proxy_mode") or "auto"
        return str(value).strip().lower() or "auto"

    async def generate_image(self, prompt: str, model_config: Dict[str, Any], size: str = None,
                      input_image_base64: str = None) -> Tuple[bool, str]:
        """调用网页式的NovelAI接口（std.loliyc.com风格）生成图片（异步，不阻塞事件循环）"""
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

            # artist 参数只能来自显式配置的画师串，不能回退到通用正向提示词。
            artist_prompt = model_config.get("nai_artist_prompt") or model_config.get("artist_prompt")

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
                "model": model_config.get("default_model", "nai-diffusion-4-5-full")
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

            logger.info(f"{self.log_prefix} (NaiWeb) 请求URL: {url}")
            logger.debug(f"{self.log_prefix} (NaiWeb) 参数: tag长度={len(params.get('tag', ''))}, model={params.get('model')}, size={params.get('size')}")

            # 在线程池中执行阻塞的 HTTP 请求，避免阻塞事件循环
            proxy_mode = self._resolve_proxy_mode(model_config)
            response = await asyncio.to_thread(self._send_request, url, params, proxy_mode)

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

    def _request_with_session(self, trust_env: bool, url: str, params: Dict[str, Any]):
        """使用指定 Session 发送 HTTP 请求。"""
        session = self._get_session(trust_env=trust_env)
        return session.get(
            url=url,
            params=params,
            timeout=120,
            verify=False
        )

    @staticmethod
    def _is_proxy_related_exception(exc: requests.RequestException) -> bool:
        """识别 requests/urllib3 包装后的代理相关异常。"""
        if isinstance(exc, ProxyError):
            return True

        current: Optional[BaseException] = exc
        visited = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            message = str(current).lower()
            if "proxy" in message or "407" in message:
                return True
            current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)

        return False

    def _send_request(self, url: str, params: Dict[str, Any], proxy_mode: str = "auto"):
        """发送 HTTP 请求（同步方法，由 asyncio.to_thread 调用）"""
        if proxy_mode == "direct":
            return self._request_with_session(False, url, params)

        if proxy_mode == "inherit":
            return self._request_with_session(True, url, params)

        if getattr(self, "_auto_proxy_direct_only", False):
            return self._request_with_session(False, url, params)

        try:
            return self._request_with_session(True, url, params)
        except requests.RequestException as exc:
            if not self._is_proxy_related_exception(exc):
                raise

            self._auto_proxy_direct_only = True
            logger.warning(
                f"{self.log_prefix} (NaiWeb) 代理连接失败，自动回退直连: {exc}"
            )
            return self._request_with_session(False, url, params)

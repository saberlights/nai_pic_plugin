import asyncio
import base64
import json
import re
import requests
import urllib3
from typing import Dict, Any, Tuple, Optional, List
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
    """BestNAI 图片生成客户端（OpenAI Chat Completions 兼容）"""

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
        """调用 BestNAI Chat Completions 接口生成图片（异步，不阻塞事件循环）"""
        try:
            if input_image_base64:
                logger.warning(f"{self.log_prefix} (BestNAI) 暂不支持图生图请求")
                return False, "当前 BestNAI 接口不支持图生图"

            base_url = (model_config.get("base_url") or "").rstrip('/')
            endpoint = model_config.get("nai_endpoint", "/v1/chat/completions")
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

            final_size = size_override or size
            generation_params = self._build_generation_params(
                prompt=full_prompt,
                artist_prompt=artist_prompt,
                negative_prompt=negative_prompt,
                sampler=sampler,
                steps=steps,
                guidance_scale=guidance_scale,
                cfg_value=cfg_value,
                noise_schedule=noise_schedule,
                nocache=nocache,
                final_size=final_size,
                extra_params=extra_params,
            )
            payload = {
                "model": model_config.get("default_model", "nai-diffusion-4-5-full-anlas-0"),
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(generation_params, ensure_ascii=False),
                    }
                ],
            }
            headers = {
                "Content-Type": "application/json",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"

            logger.info(f"{self.log_prefix} (BestNAI) 请求URL: {url}")
            logger.debug(
                f"{self.log_prefix} (BestNAI) 参数: prompt长度={len(generation_params.get('prompt', ''))}, "
                f"model={payload.get('model')}, size={generation_params.get('size')}"
            )

            # 在线程池中执行阻塞的 HTTP 请求，避免阻塞事件循环
            proxy_mode = self._resolve_proxy_mode(model_config)
            response = await asyncio.to_thread(self._send_request, url, headers, payload, proxy_mode)

            if 300 <= response.status_code < 400:
                location = response.headers.get("location", "")
                logger.error(
                    f"{self.log_prefix} (BestNAI) 接口发生重定向: "
                    f"status={response.status_code}, method={getattr(response.request, 'method', 'unknown')}, "
                    f"url={getattr(response.request, 'url', url)}, location={location}"
                )
                return False, f"HTTP {response.status_code}: 接口发生重定向，请检查 base_url 或反向代理配置"

            if response.status_code != 200:
                error_message = self._extract_error_message(response)
                logger.error(
                    f"{self.log_prefix} (BestNAI) HTTP错误 {response.status_code}: {error_message[:200]} "
                    f"(method={getattr(response.request, 'method', 'unknown')}, "
                    f"url={getattr(response.request, 'url', url)})"
                )
                return False, f"HTTP {response.status_code}: {error_message[:100]}"

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type or response.text.strip().startswith("{"):
                try:
                    data = response.json()
                except Exception:
                    data = {}

                image_value = self._extract_first_image(data)
                if image_value:
                    logger.info(f"{self.log_prefix} (BestNAI) 图片生成成功")
                    return True, image_value

                message = self._extract_error_message_from_payload(data) or "未返回图片数据"
                logger.error(f"{self.log_prefix} (BestNAI) JSON响应无图片: {message}")
                return False, message

            image_base64 = base64.b64encode(response.content).decode('utf-8')
            logger.info(f"{self.log_prefix} (BestNAI) 图片生成成功，大小 {len(response.content)} bytes")
            return True, image_base64

        except requests.RequestException as e:
            logger.error(f"{self.log_prefix} (BestNAI) 网络异常: {e}")
            return False, f"网络请求失败: {str(e)}"
        except Exception as e:
            logger.error(f"{self.log_prefix} (BestNAI) 请求异常: {e!r}", exc_info=True)
            return False, f"BestNAI 接口请求失败: {str(e)[:100]}"

    def _build_generation_params(
        self,
        prompt: str,
        artist_prompt: str,
        negative_prompt: str,
        sampler: str,
        steps: Any,
        guidance_scale: Any,
        cfg_value: Any,
        noise_schedule: str,
        nocache: Any,
        final_size: Optional[str],
        extra_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造 BestNAI 生成参数，并兼容旧配置映射。"""
        combined_prompt = prompt.strip()
        if artist_prompt:
            combined_prompt = f"{combined_prompt}, {artist_prompt.strip()}"

        params: Dict[str, Any] = {
            "prompt": combined_prompt,
        }

        normalized_size = self._normalize_size(final_size)
        if normalized_size:
            params["size"] = normalized_size
        if negative_prompt:
            params["negative_prompt"] = negative_prompt
        if sampler:
            params["sampler"] = sampler
        if steps is not None:
            params["steps"] = steps
        if guidance_scale is not None:
            params["scale"] = guidance_scale
        if noise_schedule:
            params["noise_schedule"] = noise_schedule

        if isinstance(cfg_value, (int, float)) and 0 <= float(cfg_value) <= 1 and "cfg_rescale" not in (extra_params or {}):
            params["cfg_rescale"] = float(cfg_value)

        if nocache is not None and "nocache" not in (extra_params or {}):
            params["nocache"] = nocache

        if isinstance(extra_params, dict):
            for key, value in extra_params.items():
                if value not in (None, ""):
                    params[key] = value

        return params

    @staticmethod
    def _normalize_size(size: Optional[str]) -> Optional[List[int]]:
        """将旧尺寸字符串兼容转换为 BestNAI 所需的 [宽, 高]。"""
        if not size:
            return None
        if isinstance(size, (list, tuple)) and len(size) == 2:
            try:
                return [int(size[0]), int(size[1])]
            except (TypeError, ValueError):
                return None

        size_text = str(size).strip().lower().replace("×", "x")
        size_aliases = {
            "竖": "832x1216",
            "竖图": "832x1216",
            "横": "1216x832",
            "横图": "1216x832",
            "方": "1024x1024",
            "方图": "1024x1024",
            "v": "832x1216",
            "h": "1216x832",
            "s": "1024x1024",
        }
        size_text = size_aliases.get(size_text, size_text)
        match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", size_text)
        if not match:
            return None
        return [int(match.group(1)), int(match.group(2))]

    @classmethod
    def _extract_first_image(cls, data: Dict[str, Any]) -> Optional[str]:
        """从 Chat Completions 返回中提取第一张图片。"""
        if not isinstance(data, dict):
            return None

        content = cls._extract_message_content(data)
        if not content:
            return None

        data_uri_matches = re.findall(
            r"data:image/(\w+);base64,([A-Za-z0-9+/=]+)",
            content,
        )
        if data_uri_matches:
            _fmt, b64 = data_uri_matches[0]
            return b64

        direct_match = re.search(r"!\[[^\]]*\]\((https?://[^)]+)\)", content)
        if direct_match:
            return direct_match.group(1)

        if content.startswith(("data:image/", "http://", "https://")):
            return content

        return None

    @staticmethod
    def _extract_message_content(data: Dict[str, Any]) -> str:
        """提取 Chat Completions 主消息内容。"""
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0] or {}
        message = first_choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        return ""

    @classmethod
    def _extract_error_message_from_payload(cls, data: Dict[str, Any]) -> str:
        """从标准错误结构或普通返回结构中提取错误文本。"""
        if not isinstance(data, dict):
            return ""
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or ""
            if isinstance(message, str):
                return message
        for key in ("message", "detail", "error"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        return ""

    @classmethod
    def _extract_error_message(cls, response: requests.Response) -> str:
        """优先解析 JSON 错误，否则回退纯文本。"""
        try:
            payload = response.json()
        except Exception:
            payload = None

        if isinstance(payload, dict):
            message = cls._extract_error_message_from_payload(payload)
            if message:
                return message

        text = (response.text or "").strip()
        return text or "未知错误"

    def _request_with_session(self, trust_env: bool, url: str, headers: Dict[str, Any], payload: Dict[str, Any]):
        """使用指定 Session 发送 HTTP 请求。"""
        session = self._get_session(trust_env=trust_env)
        return session.post(
            url=url,
            headers=headers,
            json=payload,
            timeout=120,
            verify=False,
            allow_redirects=False,
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

    def _send_request(self, url: str, headers: Dict[str, Any], payload: Dict[str, Any], proxy_mode: str = "auto"):
        """发送 HTTP 请求（同步方法，由 asyncio.to_thread 调用）"""
        if proxy_mode == "direct":
            return self._request_with_session(False, url, headers, payload)

        if proxy_mode == "inherit":
            return self._request_with_session(True, url, headers, payload)

        if getattr(self, "_auto_proxy_direct_only", False):
            return self._request_with_session(False, url, headers, payload)

        try:
            return self._request_with_session(True, url, headers, payload)
        except requests.RequestException as exc:
            if not self._is_proxy_related_exception(exc):
                raise

            self._auto_proxy_direct_only = True
            logger.warning(
                f"{self.log_prefix} (BestNAI) 代理连接失败，自动回退直连: {exc}"
            )
            return self._request_with_session(False, url, headers, payload)

import asyncio
import base64
import re
from http.client import IncompleteRead
from urllib.parse import urlsplit
import requests
import urllib3
from html import unescape
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
    _DEFAULT_REQUEST_TIMEOUT = 600.0
    _DEFAULT_REQUEST_HEADERS = {
        "Connection": "close",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
    }
    _RETRYABLE_STATUS_CODES = {502, 503, 504, 522, 524}
    _PROTECTION_STATUS_CODES = {418, 429}
    _RETRY_DELAY_SECONDS = 1.0
    _PROTECTION_RETRY_DELAY_SECONDS = 6.0
    _MAX_RESPONSE_RETRY_ATTEMPTS = 2
    _MAX_TRANSPORT_RETRY_ATTEMPTS = 3

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

    @classmethod
    def _resolve_request_timeout(cls, model_config: Dict[str, Any]) -> float:
        """解析图片请求超时，默认比旧实现更长。"""
        raw_timeout = model_config.get("nai_request_timeout")
        if raw_timeout in (None, ""):
            return cls._DEFAULT_REQUEST_TIMEOUT

        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            logger.warning(f"(NaiWeb) 非法超时配置 {raw_timeout!r}，回退到默认 {cls._DEFAULT_REQUEST_TIMEOUT:.1f}s")
            return cls._DEFAULT_REQUEST_TIMEOUT

        if timeout <= 0:
            logger.warning(f"(NaiWeb) 超时配置必须大于 0，收到 {raw_timeout!r}，回退到默认 {cls._DEFAULT_REQUEST_TIMEOUT:.1f}s")
            return cls._DEFAULT_REQUEST_TIMEOUT

        return timeout

    @staticmethod
    def _merge_artist_prompt_into_tag(tag_prompt: str, artist_prompt: str) -> str:
        """兼容只识别 tag 的上游代理，把画师串并入正向提示词。"""
        normalized_tag = str(tag_prompt or "").strip()
        normalized_artist = str(artist_prompt or "").strip().strip(",")
        if not normalized_artist:
            return normalized_tag
        if not normalized_tag:
            return normalized_artist

        lowered_tag = normalized_tag.lower()
        lowered_artist = normalized_artist.lower()
        if lowered_tag == lowered_artist or lowered_tag.startswith(f"{lowered_artist},"):
            return normalized_tag

        return f"{normalized_artist}, {normalized_tag}"

    def _resolve_target_platform(self) -> str:
        """尽力读取当前调用上下文的平台标识。"""
        platform_getter = getattr(self.action, "_get_target_platform", None)
        if not callable(platform_getter):
            return ""

        try:
            return str(platform_getter() or "").strip().lower()
        except Exception as exc:
            logger.debug(f"{self.log_prefix} (NaiWeb) 读取目标平台失败: {exc!r}")
            return ""

    def _should_return_generation_url_directly(self, model_config: Dict[str, Any]) -> bool:
        """仅在显式开启时，才直接返回公网生成 URL。"""
        raw_switch = model_config.get("nai_direct_url_fallback")
        if raw_switch is not None:
            normalized = str(raw_switch).strip().lower()
            if normalized in {"0", "false", "no", "off"}:
                return False
            if normalized in {"1", "true", "yes", "on"}:
                return True

        return False

    @staticmethod
    def _get_response_text(response) -> str:
        """提取响应文本，避免把整页 HTML 原样抛给用户。"""
        text = getattr(response, "text", "") or ""
        if not isinstance(text, str):
            text = str(text)
        return text[:2000]

    @classmethod
    def _looks_like_html_response(cls, content_type: str, response_text: str) -> bool:
        """识别被网关或站点返回的 HTML 错误页。"""
        normalized_content_type = (content_type or "").lower()
        if "text/html" in normalized_content_type:
            return True

        stripped = response_text.lstrip().lower()
        return stripped.startswith("<!doctype html") or stripped.startswith("<html")

    @staticmethod
    def _sanitize_response_text(response_text: str) -> str:
        """压缩文本响应，移除 HTML 标签与多余空白。"""
        if not response_text:
            return ""

        no_scripts = re.sub(r"<script\b[^>]*>.*?</script>", " ", response_text, flags=re.IGNORECASE | re.DOTALL)
        no_styles = re.sub(r"<style\b[^>]*>.*?</style>", " ", no_scripts, flags=re.IGNORECASE | re.DOTALL)
        no_tags = re.sub(r"<[^>]+>", " ", no_styles)
        compact = re.sub(r"\s+", " ", unescape(no_tags)).strip()
        return compact[:100]

    @classmethod
    def _looks_like_protection_response(cls, response) -> bool:
        """识别上游安全防护/限频页，避免把 HTML/CSS 垃圾暴露给用户。"""
        status_code = getattr(response, "status_code", None)
        if status_code in cls._PROTECTION_STATUS_CODES:
            return True

        compact = cls._sanitize_response_text(cls._get_response_text(response))
        if not compact:
            return False

        lowered = compact.lower()
        protection_markers = (
            "安全防护",
            "安全验证",
            "访问频繁",
            "请求过于频繁",
            "security protection",
            "checking your browser",
            "just a moment",
            "too many requests",
            "access denied",
        )
        return any(marker in lowered or marker in compact for marker in protection_markers)

    @classmethod
    def _build_request_headers(cls, base_url: str) -> Dict[str, str]:
        """构造更接近浏览器行为的请求头。"""
        headers = dict(cls._DEFAULT_REQUEST_HEADERS)
        headers["Referer"] = f"{base_url.rstrip('/')}/"
        return headers

    @staticmethod
    def _build_generation_request_url(url: str, params: Dict[str, Any]) -> str:
        """构造仅供服务端内部拉图使用的生成请求 URL。"""
        prepared = requests.Request("GET", url, params=params).prepare()
        return prepared.url or url

    @staticmethod
    def _looks_like_generation_request_url(url: str) -> bool:
        """识别上游返回的生成接口 URL，避免把它直接当图片外发。"""
        if not isinstance(url, str):
            return False

        normalized = url.strip()
        if not normalized.startswith(("http://", "https://")):
            return False

        try:
            parsed = urlsplit(normalized)
        except ValueError:
            return False

        path = parsed.path.rstrip("/").lower()
        if not path.endswith("/generate"):
            return False

        query = parsed.query.lower()
        return any(
            token in query
            for token in (
                "tag=",
                "model=",
                "negative=",
                "artist=",
                "token=",
                "sampler=",
                "steps=",
                "cfg=",
                "scale=",
                "size=",
            )
        )

    @staticmethod
    def _iter_exception_chain(exc: BaseException):
        """遍历异常链，识别 requests/urllib3/http.client 多层包装。"""
        visited = set()
        pending = [exc]
        while pending:
            current = pending.pop(0)
            if current is None or id(current) in visited:
                continue
            yield current
            visited.add(id(current))
            next_exception = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
            if isinstance(next_exception, BaseException):
                pending.append(next_exception)
            for arg in getattr(current, "args", ()):
                if isinstance(arg, BaseException):
                    pending.append(arg)

    @staticmethod
    def _normalize_partial_bytes(partial: Any) -> Optional[bytes]:
        if isinstance(partial, bytes):
            return partial
        if isinstance(partial, bytearray):
            return bytes(partial)
        return None

    @classmethod
    def _looks_like_complete_image_bytes(cls, data: bytes) -> bool:
        if not data:
            return False

        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return data.endswith(b"IEND\xaeB`\x82")

        if data.startswith(b"\xff\xd8\xff"):
            return data.endswith(b"\xff\xd9")

        if data.startswith((b"GIF87a", b"GIF89a")):
            return data.endswith(b"\x3b")

        if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 12:
            expected_size = int.from_bytes(data[4:8], "little") + 8
            return len(data) >= expected_size

        return False

    @classmethod
    def _extract_recoverable_image_bytes_from_request_exception(
        cls,
        exc: requests.RequestException,
    ) -> Optional[bytes]:
        for current in cls._iter_exception_chain(exc):
            if not isinstance(current, IncompleteRead):
                continue

            partial = cls._normalize_partial_bytes(current.partial)
            if partial and cls._looks_like_complete_image_bytes(partial):
                return partial

        return None

    @classmethod
    def _build_http_error_message(cls, response) -> str:
        """将上游错误响应归一化为适合聊天窗口展示的短消息。"""
        status_code = getattr(response, "status_code", None)
        response_text = cls._get_response_text(response)
        lowered_text = response_text.lower()
        content_type = getattr(response, "headers", {}).get("content-type", "")

        if cls._looks_like_protection_response(response):
            if status_code == 429:
                return "图片生成服务触发上游限频（HTTP 429），请稍后重试"
            return f"图片生成服务触发上游安全防护（HTTP {status_code}），请稍后重试"

        if (
            status_code == 504
            or "网站请求超时" in response_text
            or "gateway timeout" in lowered_text
            or "request timeout" in lowered_text
        ):
            return "图片生成服务网关超时（HTTP 504），请稍后重试"

        if status_code in {502, 503, 522, 524}:
            return f"图片生成服务暂时不可用（HTTP {status_code}），请稍后重试"

        if cls._looks_like_html_response(content_type, response_text):
            compact = cls._sanitize_response_text(response_text)
            return f"HTTP {status_code}: {compact}" if compact else f"HTTP {status_code}"

        compact = re.sub(r"\s+", " ", response_text).strip()
        if not compact:
            return f"HTTP {status_code}" if status_code is not None else "图片生成服务返回异常响应"
        return f"HTTP {status_code}: {compact[:100]}" if status_code is not None else compact[:100]

    @classmethod
    def _build_unexpected_html_message(cls, response) -> str:
        """处理 200 + HTML 这类非图片异常响应。"""
        response_text = cls._get_response_text(response)
        lowered_text = response_text.lower()
        if (
            "网站请求超时" in response_text
            or "gateway timeout" in lowered_text
            or "request timeout" in lowered_text
        ):
            return "图片生成服务返回了超时页面，请稍后重试"
        return "图片生成服务返回了异常页面，请稍后重试"

    @classmethod
    def _is_retryable_response(cls, response) -> bool:
        return (
            getattr(response, "status_code", None) in cls._RETRYABLE_STATUS_CODES
            or cls._looks_like_protection_response(response)
        )

    @classmethod
    def _get_response_retry_delay_seconds(cls, response, attempt: int) -> float:
        """风控页比普通网关错误等待更久，减少连续命中概率。"""
        delay = cls._get_retry_delay_seconds(attempt)
        if cls._looks_like_protection_response(response):
            return max(delay, cls._PROTECTION_RETRY_DELAY_SECONDS)
        return delay

    @classmethod
    def _is_retryable_request_exception(cls, exc: requests.RequestException) -> bool:
        """识别适合重试的传输层异常。"""
        if isinstance(
            exc,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ),
        ):
            return True

        for current in cls._iter_exception_chain(exc):
            if isinstance(current, IncompleteRead):
                return True

            message = str(current).lower()
            if any(
                token in message
                for token in (
                    "incompleteread",
                    "connection broken",
                    "remote end closed connection",
                    "connection reset by peer",
                    "chunked",
                    "read timed out",
                )
            ):
                return True

        return False

    @classmethod
    def _build_request_exception_message(cls, exc: requests.RequestException) -> str:
        """将传输层异常压缩为适合聊天窗口展示的短消息。"""
        if cls._is_retryable_request_exception(exc):
            for current in cls._iter_exception_chain(exc):
                message = str(current).lower()
                if isinstance(current, IncompleteRead) or "incompleteread" in message or "connection broken" in message:
                    return "图片生成结果传输中断，请稍后重试"
                if isinstance(current, requests.exceptions.Timeout) or "timed out" in message:
                    return "图片生成服务响应超时，请稍后重试"
            return "图片生成服务连接不稳定，请稍后重试"

        return f"网络请求失败: {str(exc)}"

    @classmethod
    def _get_retry_delay_seconds(cls, attempt: int) -> float:
        """指数退避，避免短时间内连续命中不稳定链路。"""
        return min(cls._RETRY_DELAY_SECONDS * (2 ** max(attempt - 1, 0)), 4.0)

    @classmethod
    def _should_retry_request(cls, url: str, params: Dict[str, Any]) -> bool:
        """仅对幂等拉取请求开启自动重试，避免重复触发生图额度消耗。"""
        if cls._looks_like_generation_request_url(url):
            return False

        try:
            parsed = urlsplit(str(url or "").strip())
        except ValueError:
            return True

        path = parsed.path.rstrip("/").lower()
        if path.endswith("/generate") and isinstance(params, dict):
            for key in ("tag", "model", "negative", "artist", "token", "sampler", "steps", "cfg", "scale", "size"):
                if params.get(key) not in (None, ""):
                    return False

        return True

    @classmethod
    def _should_retry_response(cls, url: str, params: Dict[str, Any], response) -> bool:
        """
        决定是否对 HTTP 响应做自动重试。

        418/429 安全防护页通常发生在网关层，未返回任何生成结果，
        允许做一次受控重试；其他错误仍只对幂等拉取请求重试。
        """
        if not cls._is_retryable_response(response):
            return False
        if cls._looks_like_protection_response(response):
            return True
        return cls._should_retry_request(url, params)

    async def _send_request_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
        proxy_mode: str,
        request_timeout: float,
        request_headers: Dict[str, str],
    ):
        """对网关类临时故障做一次受控重试。"""
        allow_transport_retry = self._should_retry_request(url, params)
        for attempt in range(1, self._MAX_TRANSPORT_RETRY_ATTEMPTS + 1):
            try:
                response = await asyncio.to_thread(
                    self._send_request,
                    url,
                    params,
                    proxy_mode,
                    request_timeout,
                    request_headers,
                )
            except requests.RequestException as exc:
                if (
                    not allow_transport_retry
                    or attempt >= self._MAX_TRANSPORT_RETRY_ATTEMPTS
                    or self._is_proxy_related_exception(exc)
                    or not self._is_retryable_request_exception(exc)
                ):
                    raise

                retry_delay = self._get_retry_delay_seconds(attempt)
                logger.warning(
                    f"{self.log_prefix} (NaiWeb) 第{attempt}次请求遇到可重试网络异常: {exc}; "
                    f"{retry_delay:.1f}s 后重试"
                )
                await asyncio.sleep(retry_delay)
                continue

            if (
                not self._should_retry_response(url, params, response)
                or attempt >= self._MAX_RESPONSE_RETRY_ATTEMPTS
            ):
                return response

            retry_delay = self._get_response_retry_delay_seconds(response, attempt)
            if self._looks_like_protection_response(response):
                logger.warning(
                    f"{self.log_prefix} (NaiWeb) 第{attempt}次请求触发上游安全防护（HTTP {response.status_code}），"
                    f"{retry_delay:.1f}s 后重试"
                )
            else:
                logger.warning(
                    f"{self.log_prefix} (NaiWeb) 第{attempt}次请求收到可重试HTTP {response.status_code}，"
                    f"{retry_delay:.1f}s 后重试"
                )
            await asyncio.sleep(retry_delay)

    async def _download_generated_image_as_base64(
        self,
        generation_url: str,
        model_config: Dict[str, Any],
        request_headers: Dict[str, str],
    ) -> Optional[str]:
        """使用生成接口 URL 在服务端再次拉图，成功时转成 Base64。"""
        request_timeout = self._resolve_request_timeout(model_config)
        proxy_mode = self._resolve_proxy_mode(model_config)

        try:
            response = await self._send_request_with_retry(
                generation_url,
                {},
                proxy_mode,
                request_timeout,
                request_headers,
            )
        except requests.RequestException as exc:
            logger.warning(f"{self.log_prefix} (NaiWeb) 后端拉取生成URL失败: {exc}")
            return None

        if response.status_code != 200:
            logger.warning(
                f"{self.log_prefix} (NaiWeb) 后端拉取生成URL返回 HTTP {response.status_code}"
            )
            return None

        content_type = str(response.headers.get("content-type") or "").lower()
        if not content_type.startswith("image/"):
            response_text = self._get_response_text(response)
            if "application/json" in content_type or self._looks_like_html_response(
                content_type,
                response_text,
            ):
                logger.warning(
                    f"{self.log_prefix} (NaiWeb) 后端拉取生成URL收到非图片响应: {content_type or 'unknown'}"
                )
                return None

        content = response.content
        if not content:
            logger.warning(f"{self.log_prefix} (NaiWeb) 后端拉取生成URL内容为空")
            return None

        logger.info(f"{self.log_prefix} (NaiWeb) 后端拉取生成URL成功，大小 {len(content)} bytes")
        return base64.b64encode(content).decode("utf-8")

    async def generate_image(self, prompt: str, model_config: Dict[str, Any], size: str = None,
                      input_image_base64: str = None) -> Tuple[bool, str]:
        """调用网页式的NovelAI接口（std.loliyc.com风格）生成图片（异步，不阻塞事件循环）"""
        request_headers: Dict[str, str] = {}
        generation_request_url: Optional[str] = None
        request_params: Dict[str, Any] = {}
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
            # custom_prompt_add 放最后（质量词应在 prompt 结尾，与 NAI quality_toggle 协同；
            # NAI 4/4.5 推荐 masterpiece / very aesthetic / year / no text 等都放结尾）
            if custom_prompt_add:
                full_prompt = f"{prompt}, {custom_prompt_add}"
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

            effective_prompt = self._merge_artist_prompt_into_tag(full_prompt, artist_prompt)
            params = {
                "tag": effective_prompt,
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

            request_params = dict(params)
            request_timeout = self._resolve_request_timeout(model_config)
            request_headers = self._build_request_headers(base_url)
            generation_request_url = self._build_generation_request_url(url, request_params)
            logger.info(f"{self.log_prefix} (NaiWeb) 请求URL: {url}")
            logger.debug(
                f"{self.log_prefix} (NaiWeb) 参数: tag长度={len(params.get('tag', ''))}, "
                f"model={params.get('model')}, size={params.get('size')}, timeout={request_timeout}"
            )

            if generation_request_url and self._should_return_generation_url_directly(model_config):
                logger.info(f"{self.log_prefix} (NaiWeb) 当前平台走公网生成URL直发")
                return True, generation_request_url

            # 在线程池中执行阻塞的 HTTP 请求，避免阻塞事件循环
            proxy_mode = self._resolve_proxy_mode(model_config)
            response = await self._send_request_with_retry(
                url,
                params,
                proxy_mode,
                request_timeout,
                request_headers,
            )

            if response.status_code != 200:
                error_message = self._build_http_error_message(response)
                logger.error(f"{self.log_prefix} (NaiWeb) HTTP错误 {response.status_code}: {error_message}")
                return False, error_message

            content_type = response.headers.get("content-type", "").lower()
            if "application/json" in content_type:
                try:
                    data = response.json()
                except Exception:
                    data = {}

                for key in ("url", "image_url", "image", "data"):
                    value = data.get(key)
                    if isinstance(value, str) and value:
                        if self._looks_like_generation_request_url(value):
                            logger.error(
                                f"{self.log_prefix} (NaiWeb) 收到JSON字段 {key}，但值仍是 /generate 请求URL；"
                                "为避免重复扣费，已停止自动补拉"
                            )
                            return False, "上游返回了生成请求链接，已停止自动补拉以避免重复扣费，请稍后重试"
                        logger.info(f"{self.log_prefix} (NaiWeb) 收到JSON字段 {key}")
                        return True, value

                message = data.get("message") or data.get("error") or "未返回图片数据"
                logger.error(f"{self.log_prefix} (NaiWeb) JSON响应无图片: {message}")
                return False, message

            response_text = self._get_response_text(response)
            if self._looks_like_html_response(content_type, response_text):
                error_message = self._build_unexpected_html_message(response)
                logger.error(f"{self.log_prefix} (NaiWeb) 收到非预期HTML响应: {error_message}")
                return False, error_message

            image_base64 = base64.b64encode(response.content).decode('utf-8')
            logger.info(f"{self.log_prefix} (NaiWeb) 图片生成成功，大小 {len(response.content)} bytes")
            return True, image_base64

        except requests.RequestException as e:
            recovered_image = self._extract_recoverable_image_bytes_from_request_exception(e)
            if recovered_image is not None:
                logger.warning(
                    f"{self.log_prefix} (NaiWeb) 连接异常但已从不完整响应中恢复完整图片，大小 {len(recovered_image)} bytes"
                )
                return True, base64.b64encode(recovered_image).decode("utf-8")
            if (
                generation_request_url
                and request_headers
                and self._is_retryable_request_exception(e)
            ):
                logger.warning(
                    f"{self.log_prefix} (NaiWeb) 首次回图连接异常，尝试对同一生成URL补拉结果"
                )
                image_base64 = await self._download_generated_image_as_base64(
                    generation_request_url,
                    model_config,
                    request_headers,
                )
                if image_base64:
                    logger.info(f"{self.log_prefix} (NaiWeb) 生成结果补拉成功")
                    return True, image_base64
            logger.error(f"{self.log_prefix} (NaiWeb) 网络异常: {e}")
            return False, self._build_request_exception_message(e)
        except Exception as e:
            logger.error(f"{self.log_prefix} (NaiWeb) 请求异常: {e!r}", exc_info=True)
            return False, f"Nai网页接口请求失败: {str(e)[:100]}"

    def _request_with_session(
        self,
        trust_env: bool,
        url: str,
        params: Dict[str, Any],
        request_timeout: float,
        request_headers: Dict[str, str],
    ):
        """使用指定 Session 发送 HTTP 请求。"""
        session = self._get_session(trust_env=trust_env)
        return session.get(
            url=url,
            params=params,
            timeout=request_timeout,
            verify=False,
            headers=request_headers,
        )

    @staticmethod
    def _is_proxy_related_exception(exc: requests.RequestException) -> bool:
        """识别 requests/urllib3 包装后的代理相关异常。"""
        if isinstance(exc, ProxyError):
            return True

        for current in NaiWebClient._iter_exception_chain(exc):
            message = str(current).lower()
            if "proxy" in message or "407" in message:
                return True

        return False

    def _send_request(
        self,
        url: str,
        params: Dict[str, Any],
        proxy_mode: str = "auto",
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT,
        request_headers: Optional[Dict[str, str]] = None,
    ):
        """发送 HTTP 请求（同步方法，由 asyncio.to_thread 调用）"""
        final_headers = dict(request_headers or self._DEFAULT_REQUEST_HEADERS)

        if proxy_mode == "direct":
            return self._request_with_session(False, url, params, request_timeout, final_headers)

        if proxy_mode == "inherit":
            return self._request_with_session(True, url, params, request_timeout, final_headers)

        if getattr(self, "_auto_proxy_direct_only", False):
            return self._request_with_session(False, url, params, request_timeout, final_headers)

        try:
            return self._request_with_session(True, url, params, request_timeout, final_headers)
        except requests.RequestException as exc:
            if not self._is_proxy_related_exception(exc):
                raise

            self._auto_proxy_direct_only = True
            logger.warning(
                f"{self.log_prefix} (NaiWeb) 代理连接失败，自动回退直连: {exc}"
            )
            return self._request_with_session(False, url, params, request_timeout, final_headers)

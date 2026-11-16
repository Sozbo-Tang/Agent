import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

_BLOCKED_HOSTS = ("localhost", "::1")
_BLOCKED_SUFFIXES = (".local", ".internal")


class LLMError(Exception):
    pass


def _guard_outbound_url(base_url):
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise LLMError("LLM_BASE_URL 必须是合法的 https 地址")
    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        raise LLMError("LLM_BASE_URL 不允许指向本机或内网域名")
    try:
        addr_infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise LLMError(f"LLM_BASE_URL 的域名无法解析：{exc}")
    for info in addr_infos:
        address = ipaddress.ip_address(info[4][0])
        blocked = address.is_private or address.is_loopback or address.is_link_local
        blocked = blocked or address.is_reserved or address.is_multicast or address.is_unspecified
        if blocked:
            raise LLMError(f"LLM_BASE_URL 解析到内网或保留地址 {address}，已拒绝请求")
    return base_url.rstrip("/") + "/chat/completions"


class OpenAICompatibleClient:
    def __init__(self, config):
        if not config.api_key:
            raise LLMError("请先设置环境变量 LLM_API_KEY，参考 README 的配置说明")
        if not config.base_url:
            raise LLMError("请先设置环境变量 LLM_BASE_URL，例如 https://open.bigmodel.cn/api/paas/v4")
        self.config = config

    def chat(self, messages, tools=None):
        import requests

        payload = {"model": self.config.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        url = _guard_outbound_url(self.config.base_url)
        last_error = None
        for attempt in range(2):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.config.timeout)
                if response.status_code == 200:
                    return self._extract_message(response.json())
                if response.status_code >= 500 or response.status_code == 429:
                    last_error = LLMError(f"服务端异常 HTTP {response.status_code}")
                else:
                    raise LLMError(f"请求失败 HTTP {response.status_code}：{response.text[:200]}")
            except requests.RequestException as exc:
                last_error = LLMError(f"网络错误：{exc}")
            if attempt == 0:
                time.sleep(1)
        raise last_error or LLMError("模型调用失败")

    def summarize(self, text):
        messages = [
            {
                "role": "system",
                "content": "你是对话压缩助手，把输入的多轮对话压缩成简洁要点，保留用户目标、关键结论和数字。",
            },
            {"role": "user", "content": text},
        ]
        message = self.chat(messages)
        return message.get("content") or ""

    def _extract_message(self, data):
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"模型没有返回任何结果：{json.dumps(data, ensure_ascii=False)[:200]}")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise LLMError("模型返回里缺少 message 字段")
        return message

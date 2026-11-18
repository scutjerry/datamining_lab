# -*- coding: utf-8 -*-
"""
llm.py — LLM 接入层（OpenAI 兼容协议）+ 离线规则兜底

设计目标
1. 真实调用链：任何 OpenAI 兼容服务（DeepSeek / 通义千问 / Kimi / 本地 vLLM）都能用，
   只靠三个环境变量切换，不需要改代码：
       LLM_API_KEY   = sk-xxxx
       LLM_BASE_URL  = https://api.deepseek.com/v1   （默认值）
       LLM_MODEL     = deepseek-flash                （默认值，服务端名为 DeepSeek-V4.1-Flash）
   不想设环境变量时，也可以在代码目录放一个 llm_config.local.json：
       {"LLM_API_KEY": "sk-xxx", "LLM_MODEL": "deepseek-flash"}
   该文件已被 .gitignore 忽略，不会进仓库；环境变量优先级高于它。
2. 离线可跑：没配 key 时抛 LLMUnavailable，由 agent 切到规则后端，
   保证评审老师在没有 key 的机器上也能复现完整 ReAct 轨迹。
3. 只用 requests（anaconda 自带），不引入 openai/langchain 这类重依赖。

命令行自检：
    python llm.py            # 打印当前后端状态
    python llm.py "你好"      # 有 key 时真的发一次请求
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-flash"  # 服务端 display name: DeepSeek-V4.1-Flash


class LLMUnavailable(RuntimeError):
    """没有配置 key、或依赖缺失、或服务不可达时抛出。"""


# 本地密钥文件（不进 git，.gitignore 已忽略）：方便别人在自己的机器上填自己的 key
# 查找顺序：环境变量 → 代码目录下 llm_config.local.json → ~/.dsh/secrets/llm.local.json → 默认值
_LOCAL_CANDIDATES = [
    Path(__file__).with_name("llm_config.local.json"),
    Path.home() / ".dsh" / "secrets" / "llm.local.json",
]
# 同义环境变量：LLM_API_KEY 为主，也认官方 SDK 常用的别名
_ALIASES = {
    "LLM_API_KEY": ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
    "LLM_BASE_URL": ("OPENAI_BASE_URL", "DEEPSEEK_BASE_URL"),
    "LLM_MODEL": ("OPENAI_MODEL", "DEEPSEEK_MODEL"),
}
_PLACEHOLDER_WORDS = {
    "sk-xxxx", "sk-xxx", "sk-x", "sk-你的key", "sk-你自己的key",
    "your-key", "your_api_key", "changeme", "none", "null", "填你自己的key",
}


def _is_placeholder(value: str) -> bool:
    """判断是不是模板里没改的占位符（如「你的api」/「sk-你自己的key」）。

    占位符当作"没填"，否则程序会以为配好了、然后每次调用都 401。
    """
    if not value:
        return True
    if any(ord(ch) > 127 for ch in value):   # 含中文/全角，肯定是模板文字
        return True
    low = value.strip().lower()
    if low in _PLACEHOLDER_WORDS:
        return True
    if set(low) <= set("x-*"):               # 形如 xxx / --- / ***
        return True
    return False


_local_cache: dict | None = None


def _local_config() -> dict:
    """读本地密钥文件；不存在或格式坏就当没有，绝不抛异常。"""
    global _local_cache
    if _local_cache is None:
        _local_cache = {}
        for path in _LOCAL_CANDIDATES:
            try:
                if path.is_file():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, str) and v.strip():
                                _local_cache.setdefault(k, v.strip())
            except Exception:
                continue
    return _local_cache


def _env(name: str, default: str = "") -> str:
    """两段式查找，保证"环境变量整体优先于本地文件"。

    先扫完所有环境变量（主名 + 别名），再扫本地文件的所有键，
    避免出现"本地文件里的主名"压过"环境变量里的别名"这种反直觉行为。
    """
    names = (name, *_ALIASES.get(name, ()))
    check = name.endswith("_KEY")            # 只对 key 做占位符检查

    for key in names:
        value = (os.environ.get(key) or "").strip()
        if value and not (check and _is_placeholder(value)):
            return value
    config = _local_config()
    for key in names:
        value = (config.get(key) or "").strip()
        if value and not (check and _is_placeholder(value)):
            return value
    return default


class LLM:
    """最小可用的 OpenAI 兼容 chat 客户端。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 60,
        temperature: float = 0.2,
    ):
        self.api_key = api_key if api_key is not None else _env("LLM_API_KEY")
        self.base_url = (base_url or _env("LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.model = model or _env("LLM_MODEL", DEFAULT_MODEL)
        # 模板占位符兜底：抄了示例文件但没改 base_url/model 时，退回默认值而不是带着
        # 中文占位符去发请求（那会得到一个很难懂的错误）
        if not self.base_url.startswith("http"):
            self.base_url = DEFAULT_BASE_URL
        if not self.model.isascii():
            self.model = DEFAULT_MODEL
        self.timeout = timeout
        self.temperature = temperature
        self.calls: list[dict] = []  # 记录每次真实调用，供证据留痕

    # -- 状态 ----------------------------------------------------------
    @property
    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import requests  # noqa: F401
        except ImportError:
            return False
        return True

    def status(self) -> dict:
        return {
            "available": self.available,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_set": bool(self.api_key),
            "api_key_masked": (self.api_key[:6] + "…" + self.api_key[-4:]) if self.api_key else "",
            "api_key_note": (
                "未配置（或仍是模板占位符），当前走规则后端"
                if not self.api_key else "已配置"
            ),
            "calls": len(self.calls),
        }

    # -- 调用 ----------------------------------------------------------
    def chat(self, messages: list[dict], temperature: float | None = None, max_tokens: int = 900) -> str:
        if not self.available:
            raise LLMUnavailable(
                "未配置 LLM_API_KEY（或缺少 requests），无法调用在线模型；"
                "请设置环境变量后重试，或使用 --offline 走规则后端"
            )
        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except Exception as exc:
            raise LLMUnavailable(f"请求 {url} 失败：{type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMUnavailable(f"HTTP {resp.status_code}：{resp.text[:300]}")
        body = resp.json()
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = body.get("usage", {})
        self.calls.append(
            {
                "model": body.get("model", self.model),
                "url": url,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reply_chars": len(text or ""),
            }
        )
        if not text:
            raise LLMUnavailable(f"模型返回空内容：{json.dumps(body, ensure_ascii=False)[:300]}")
        return text


# ---------------------------------------------------------------- 解析辅助
def extract_json(text: str) -> dict | None:
    """从模型回复里抠出第一个 JSON 对象（容忍 ```json 围栏与前后废话）。"""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    fallback = None
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    while start != -1:
        depth, end = 0, -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > start:
            candidates.append(text[start : end + 1])
        start = text.find("{", start + 1)
        if len(candidates) > 6:
            break
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            # 优先取真正带 thought/action 的那个对象，避免抓到示例模板
            if "action" in obj or "thought" in obj:
                return obj
            fallback = fallback or obj
    return fallback


if __name__ == "__main__":
    llm = LLM()
    print(json.dumps(llm.status(), ensure_ascii=False, indent=2))
    if len(sys.argv) > 1 and llm.available:
        print(llm.chat([{"role": "user", "content": sys.argv[1]}]))

"""
LLM Client Module
==================
多提供商大模型客户端（统一走 OpenAI 兼容接口）。

切换模型 = 换 base_url + api_key + model，代码无需改动。
支持：DeepSeek / 通义千问 / 智谱 GLM / OpenAI / Ollama 本地 / 自定义端点。
"""

import openai

from i18n import t

# ─── 服务商预设 ─────────────────────────────────────────
PROVIDER_PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "models_hint": "deepseek-chat / deepseek-reasoner",
    },
    "qwen": {
        "label": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "models_hint": "qwen-plus / qwen-turbo / qwen-max",
    },
    "glm": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "models_hint": "glm-4-flash / glm-4-plus / glm-4-air",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models_hint": "gpt-4o-mini / gpt-4o / gpt-5 系列",
    },
    "ollama": {
        "label": "Ollama (本地)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5",
        "models_hint": "本地已拉取的模型名，如 qwen2.5 / llama3.1",
    },
    "custom": {
        "label": "自定义 (OpenAI 兼容)",
        "base_url": "",
        "default_model": "",
        "models_hint": "任意 OpenAI 兼容端点",
    },
}


class LLMError(Exception):
    """模型调用错误（kind: auth / connection / timeout / rate_limit / other）"""

    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        self.detail = detail
        super().__init__(f"LLMError[{kind}]: {detail}")


def _map_error(e: Exception) -> LLMError:
    if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LLMError("auth", str(e))
    if isinstance(e, openai.RateLimitError):
        return LLMError("rate_limit", str(e))
    if isinstance(e, openai.APITimeoutError):
        return LLMError("timeout", str(e))
    if isinstance(e, openai.APIConnectionError):
        return LLMError("connection", str(e))
    return LLMError("other", str(e))


def stream_chat(profile: dict, messages: list, lang: str = "en",
                temperature: float = 0.7, max_tokens: int = None):
    """
    流式调用模型，返回文本块生成器（每次 yield 一小段文本）。

    profile:  {"api_key", "base_url", "model", ...}（来自本地配置）
    messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]
    lang:     错误提示使用的语言

    出错时不抛异常，改为产出本地化错误提示文本，保证界面不崩。
    """
    api_key = (profile or {}).get("api_key") or ""
    base_url = (profile or {}).get("base_url") or ""
    model = (profile or {}).get("model") or ""

    if not api_key or not model:
        yield t("llm_error_not_configured", lang)
        return

    try:
        client = openai.OpenAI(api_key=api_key, base_url=base_url or None, timeout=60)
        kwargs = dict(model=model, messages=messages, stream=True,
                      temperature=temperature)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        yield _error_text(_map_error(e), lang)
        return

    try:
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content
    except Exception as e:
        yield "\n\n" + _error_text(_map_error(e), lang)


def _error_text(err: LLMError, lang: str) -> str:
    """把错误转成本地化提示文本"""
    if err.kind == "other":
        return t("llm_error_other", lang, error=str(err.detail)[:200])
    return t(f"llm_error_{err.kind}", lang)

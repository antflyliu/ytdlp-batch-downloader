#!/usr/bin/env python3
"""
scripts/llm_client.py — 多后端 LLM 客户端

支持后端:
  - qwen:      通义千问 (dashscope / OpenAI兼容接口)
  - openai:    OpenAI GPT-4o 等
  - ollama:    本地 Ollama
  - groq:      Groq API (llama-3.1 / mixtral)

用法:
    client = LLMClient(provider="qwen", model="qwen-plus")
    client = LLMClient(provider="openai", model="gpt-4o")
    client = LLMClient(provider="ollama", model="llama3")
    response = client.call("你是谁？")
    response = client.call_with_retry("...", max_retries=3)
"""
from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 基础接口
# ─────────────────────────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """LLM Provider 抽象接口"""

    @abstractmethod
    def chat(self, messages: list[dict], model: str, **kwargs) -> str:
        """
        调用 LLM，返回原始文本响应。

        Args:
            messages: [{"role": "user", "content": "..."}, ...]
            model:    模型名称
            **kwargs: 额外参数（如 temperature, max_tokens 等）

        Returns:
            LLM 返回的文本内容
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────
# 通义千问 (dashscope / OpenAI 兼容接口)
# ─────────────────────────────────────────────────────────────────────────────

class QwenProvider(LLMProvider):
    """通义千问后端（dashscope）"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def chat(self, messages: list[dict], model: str, **kwargs) -> str:
        import requests

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
        }
        # temperature 默认 0.7，避免过度随机
        payload.setdefault("temperature", kwargs.get("temperature", 0.7))
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=kwargs.get("timeout", 120),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI (GPT-4o 等)
# ─────────────────────────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    """OpenAI 后端（GPT-4o / GPT-4o-mini 等）"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, messages: list[dict], model: str, **kwargs) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens") or 4096,
        )
        return response.choices[0].message.content or ""


# ─────────────────────────────────────────────────────────────────────────────
# Ollama (本地 LLM)
# ─────────────────────────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    """Ollama 本地后端"""

    def __init__(self, base_url: str | None = None):
        import requests

        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"

    def chat(self, messages: list[dict], model: str, **kwargs) -> str:
        import requests

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
            },
        }
        if kwargs.get("max_tokens"):
            payload["options"]["num_predict"] = kwargs["max_tokens"]

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=kwargs.get("timeout", 300),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# Groq (低延迟 API)
# ─────────────────────────────────────────────────────────────────────────────

class GroqProvider(LLMProvider):
    """Groq API 后端"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.base_url = base_url or "https://api.groq.com/openai/v1"

    def chat(self, messages: list[dict], model: str, **kwargs) -> str:
        import requests

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
        }
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=kwargs.get("timeout", 60),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# LLMClient — 统一入口
# ─────────────────────────────────────────────────────────────────────────────

_PROVIDER_CLASSES = {
    "qwen":   QwenProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
    "groq":   GroqProvider,
}

# 各后端默认模型
_DEFAULT_MODELS = {
    "qwen":   "qwen-plus",
    "openai": "gpt-4o",
    "ollama": "llama3",
    "groq":   "llama-3.1-8b-instant",
}


class LLMClient:
    """
    统一 LLM 客户端，自动选择后端。

    Args:
        provider: 后端类型，"qwen" | "openai" | "ollama" | "groq"
        model:    模型名称（覆盖默认）
        api_key:  API Key（优先用此参数，其次环境变量）
        base_url: 自定义端点（可选）
    """

    def __init__(
        self,
        provider: str = "qwen",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        if provider not in _PROVIDER_CLASSES:
            raise ValueError(
                f"未知的 LLM provider: {provider!r}，支持: {list(_PROVIDER_CLASSES.keys())}"
            )

        self.provider_name = provider
        self.model = model or _DEFAULT_MODELS.get(provider, "")

        # 实例化对应后端
        cls = _PROVIDER_CLASSES[provider]
        self._impl: LLMProvider = cls(api_key=api_key, base_url=base_url)
        logger.info(f"LLMClient 初始化: provider={provider}, model={self.model}")

    def call(self, prompt: str, input_data: Any = None, **kwargs) -> str:
        """
        单次 LLM 调用。

        Args:
            prompt:     系统/用户 prompt 模板（支持 {input_data} 占位符）
            input_data: 注入到 prompt 的数据（dict / list / str）
            **kwargs:   透传给底层 provider

        Returns:
            LLM 响应文本
        """
        if input_data is not None:
            if isinstance(input_data, (dict, list)):
                prompt = prompt.format(input_data=json.dumps(input_data, ensure_ascii=False, indent=2))
            else:
                prompt = prompt.format(input_data=str(input_data))

        messages = [{"role": "user", "content": prompt}]
        return self._impl.chat(messages, self.model, **kwargs)

    def call_with_retry(
        self,
        prompt: str,
        input_data: Any = None,
        max_retries: int = 3,
        **kwargs,
    ) -> str | None:
        """
        带重试的 LLM 调用（网络错误 / 限流自动重试）。

        Args:
            prompt:     同 call()
            input_data: 同 call()
            max_retries: 最大重试次数
            **kwargs:   透传给底层 provider

        Returns:
            成功返回响应文本，失败返回 None
        """
        for attempt in range(max_retries):
            try:
                return self.call(prompt, input_data, **kwargs)
            except Exception as e:
                wait = (attempt + 1) * 5  # 5s / 10s / 15s
                logger.warning(f"LLM 调用失败 (attempt {attempt+1}/{max_retries}): {e}，{wait}s 后重试...")
                if attempt < max_retries - 1:
                    time.sleep(wait)
        logger.error(f"LLM 调用在 {max_retries} 次重试后仍失败")
        return None

    def parse_json_response(self, response: str) -> Any:
        """
        尝试从 LLM 响应中解析 JSON。

        支持三种格式：
          1. ```json ... ``` 代码块
          2. ``` ... ``` 普通代码块
          3. 裸 JSON
        """
        import re

        response = response.strip()

        # 尝试提取代码块
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        if m:
            response = m.group(1)
        else:
            # 找第一对 {} 或 []
            first = response.find("{")
            last_brace = response.rfind("}")
            first_sq = response.find("[")
            last_sq = response.rfind("]")
            if first != -1 and last_brace != -1 and (first_sq == -1 or first < first_sq):
                response = response[first : last_brace + 1]
            elif first_sq != -1 and last_sq != -1:
                response = response[first_sq : last_sq + 1]

        return json.loads(response)

    @staticmethod
    def list_providers() -> list[str]:
        """返回支持的 provider 列表"""
        return list(_PROVIDER_CLASSES.keys())


# ─────────────────────────────────────────────────────────────────────────────
# 便捷工厂
# ─────────────────────────────────────────────────────────────────────────────

def create_llm_client(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMClient:
    """
    工厂函数：从环境变量或参数创建 LLM 客户端。

    环境变量优先级：
      LLM_PROVIDER  → provider
      LLM_API_KEY   → api_key
      LLM_MODEL     → model
      LLM_BASE_URL  → base_url
    """
    return LLMClient(
        provider=provider or os.environ.get("LLM_PROVIDER", "qwen"),
        model=model or os.environ.get("LLM_MODEL"),
        api_key=api_key or os.environ.get("LLM_API_KEY"),
        base_url=base_url or os.environ.get("LLM_BASE_URL"),
    )

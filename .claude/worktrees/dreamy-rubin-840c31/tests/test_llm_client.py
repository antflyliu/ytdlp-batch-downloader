"""
tests/test_llm_client.py — llm_client 单元测试
使用 unittest.mock 模拟所有 HTTP 请求，不调用真实 API。
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock
import pytest


class TestLLMClientFactory:
    def test_create_qwen_client(self):
        from scripts.llm_client import create_llm_client, LLMClient
        with patch.dict("os.environ", {"LLM_API_KEY": "test-key"}):
            client = create_llm_client(provider="qwen")
            assert client.provider_name == "qwen"
            assert client.model == "qwen-plus"

    @patch("scripts.llm_client.OpenAIProvider.__init__", return_value=None)
    def test_create_openai_client(self, mock_init):
        from scripts.llm_client import create_llm_client
        with patch.dict("os.environ", {"LLM_API_KEY": "sk-test"}):
            client = create_llm_client(provider="openai")
            assert client.provider_name == "openai"

    def test_unknown_provider_raises(self):
        from scripts.llm_client import LLMClient
        with pytest.raises(ValueError, match="未知的 LLM provider"):
            LLMClient(provider="unknown_backend")


class TestLLMClientCall:
    @patch("scripts.llm_client.QwenProvider.chat")
    def test_call_with_string_input(self, mock_chat):
        mock_chat.return_value = "这是LLM的回复"
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        result = client.call("你是谁？")
        assert result == "这是LLM的回复"
        mock_chat.assert_called_once()

    @patch("scripts.llm_client.QwenProvider.chat")
    def test_call_with_dict_input(self, mock_chat):
        mock_chat.return_value = "回复"
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        result = client.call("提取关键词：__INPUT_DATA__", {"text": "hello world"})
        assert result == "回复"
        # 验证 prompt 被正确注入
        call_args = mock_chat.call_args
        # call_args = ((messages, model), kwargs) → call_args[0] = positional args
        messages = call_args[0][0]
        assert "hello world" in messages[0]["content"]

    @patch("scripts.llm_client.QwenProvider.chat")
    def test_call_payload_with_braces_does_not_break(self, mock_chat):
        """字幕等正文中的 { } 不应触发模板解析错误（已不用 str.format）。"""
        mock_chat.return_value = "ok"
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        body = '文本含 { "title": "x" } 花括号'
        client.call("前缀__INPUT_DATA__后缀", body)
        messages = mock_chat.call_args[0][0]
        assert '{ "title": "x" }' in messages[0]["content"]

    def test_call_missing_placeholder_raises(self):
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        with pytest.raises(ValueError, match="缺少占位符"):
            client.call("无占位符", {"a": 1})


class TestLLMClientRetry:
    @patch("scripts.llm_client.QwenProvider.chat")
    def test_retry_success_first_attempt(self, mock_chat):
        mock_chat.return_value = "成功"
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        result = client.call_with_retry("prompt", max_retries=3)
        assert result == "成功"
        assert mock_chat.call_count == 1

    @patch("scripts.llm_client.QwenProvider.chat")
    def test_retry_success_after_failures(self, mock_chat):
        mock_chat.side_effect = [Exception("fail1"), Exception("fail2"), "成功"]
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        result = client.call_with_retry("prompt", max_retries=3)
        assert result == "成功"
        assert mock_chat.call_count == 3

    @patch("scripts.llm_client.QwenProvider.chat")
    def test_retry_all_fail_return_none(self, mock_chat):
        mock_chat.side_effect = Exception("always fail")
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        result = client.call_with_retry("prompt", max_retries=3)
        assert result is None


class TestParseJSONResponse:
    def test_parse_json_block(self):
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        text = '```json\n[{"name": "测试", "score": 8.5}]\n```'
        result = client.parse_json_response(text)
        assert isinstance(result, list)
        assert result[0]["name"] == "测试"
        assert result[0]["score"] == 8.5

    def test_parse_code_block_no_json(self):
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        text = '```\n{"name": "测试"}\n```'
        result = client.parse_json_response(text)
        assert result["name"] == "测试"

    def test_parse_bare_json(self):
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        text = '[{"id": 1}, {"id": 2}]'
        result = client.parse_json_response(text)
        assert len(result) == 2

    def test_parse_object_json(self):
        from scripts.llm_client import LLMClient
        client = LLMClient(provider="qwen", api_key="fake")
        text = '{"title": "hello", "score": 9.5}'
        result = client.parse_json_response(text)
        assert result["title"] == "hello"
        assert result["score"] == 9.5


class TestListProviders:
    def test_list_providers(self):
        from scripts.llm_client import LLMClient
        providers = LLMClient.list_providers()
        assert "qwen" in providers
        assert "openai" in providers
        assert "ollama" in providers
        assert "groq" in providers
        assert len(providers) == 4

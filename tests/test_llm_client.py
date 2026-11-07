# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""LLM istemcisi: yanıt çözümlemesi, token/gecikme eşlemesi ve erişilemeyen endpoint.

Ağ işi buraya kadar girmez: başarılı yanıtlar sahte completion nesneleriyle kurulur, HTTP
hatası sahte bir APIStatusError ile, erişilemeyen endpoint ise gerçekten kapalı bir bağlantı
noktasına bağlanmaya çalışılarak sınanır. Asıl mesele ikisi de aynı yerde biter: istemci
traceback değil LLMError yükseltir ve mesajı kullanıcının ne yapacağını söyler.
"""

import socket
import time
import types

import pytest
from openai import APIStatusError

from bilgin import config
from bilgin.agent.llm import LLMError, OpenAIClient, strip_think

BASE_URL = "http://127.0.0.1:9/v1"
MESSAGES = [{"role": "user", "content": "Ankara carileri"}]


def ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


def completion(content=None, tool_calls=None, prompt_tokens=11, completion_tokens=7, usage=True):
    return ns(
        choices=[ns(message=ns(content=content, tool_calls=tool_calls))],
        usage=(
            ns(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens) if usage else None
        ),
    )


def tool_call(id_, name, arguments):
    return ns(id=id_, function=ns(name=name, arguments=arguments))


class StubSDK:
    """chat.completions.create yerine geçen nesne: döndürülen yanıtı ve verilen argümanları tutar."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None
        self.chat = ns(completions=ns(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        # gerçek bir endpoint gibi biraz zaman harcayınca gecikme ölçülebilir oluyor
        time.sleep(0.002)
        return self.response


def client(response=None, error=None):
    instance = OpenAIClient(base_url=BASE_URL, model="stub", api_key="test")
    instance._sdk = StubSDK(response, error)
    return instance


def closed_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_error(status=400):
    body = {"error": {"message": "context length exceeded"}}
    response = ns(request=ns(), status_code=status, headers={})
    return APIStatusError("model endpoint'i hata döndürdü", response=response, body=body)


# ----------------------------------------------------------------- content

def test_answer_keeps_only_the_visible_text():
    response = client(completion("<think>önce sayı sayayım</think>Ankara'da 4 cari var.")).chat(
        MESSAGES
    )
    assert response.content == "Ankara'da 4 cari var."


def test_tool_turn_without_content_is_an_empty_string():
    response = client(completion(tool_calls=[tool_call("c1", "run_sql", '{"sql": "SELECT 1"}')])).chat(
        MESSAGES
    )
    assert response.content == ""


def test_strip_think_drops_every_block_and_stray_openings():
    assert strip_think("<think>a</think>son<think>b</think>") == "son"
    assert strip_think("<think>yarım kalan akıl yürütme") == ""
    assert strip_think("düz metin") == "düz metin"
    assert strip_think(None) == ""


# ----------------------------------------------------------------- tool calls

def test_tool_arguments_are_handed_over_as_a_dict():
    calls = [tool_call("c1", "get_schema", "{}"), tool_call("c2", "run_sql", '{"sql": "SELECT 1"}')]
    response = client(completion(tool_calls=calls)).chat(MESSAGES)
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("c1", "get_schema", {}),
        ("c2", "run_sql", {"sql": "SELECT 1"}),
    ]
    assert all(not c.parse_error for c in response.tool_calls)


def test_broken_tool_json_becomes_empty_arguments_and_a_parse_error():
    response = client(
        completion(tool_calls=[tool_call("c1", "run_sql", '{"sql": "SELECT'), tool_call("c2", "submit_sql", "")])
    ).chat(MESSAGES)
    broken, empty = response.tool_calls
    assert (broken.arguments, broken.parse_error) == ({}, True)
    assert (empty.arguments, empty.parse_error) == ({}, False), "argümansız çağrı hata değildir"


def test_json_that_is_not_an_object_is_also_a_parse_error():
    response = client(completion(tool_calls=[tool_call("c1", "run_sql", "[1, 2]")])).chat(MESSAGES)
    assert (response.tool_calls[0].arguments, response.tool_calls[0].parse_error) == ({}, True)


# ----------------------------------------------------------------- usage and request

def test_tokens_and_latency_come_from_the_response():
    response = client(completion("ok", prompt_tokens=1234, completion_tokens=56)).chat(MESSAGES)
    assert (response.prompt_tokens, response.completion_tokens) == (1234, 56)
    assert response.latency_ms > 0


def test_missing_usage_counts_as_zero_tokens():
    response = client(completion("ok", usage=False)).chat(MESSAGES)
    assert (response.prompt_tokens, response.completion_tokens) == (0, 0)


def test_request_carries_the_model_tools_and_thinking_flag():
    sdk = StubSDK(completion("ok"))
    instance = client()
    instance._sdk = sdk
    tools = [{"type": "function", "function": {"name": "run_sql"}}]
    instance.chat(MESSAGES, tools)
    assert sdk.kwargs["model"] == "stub"
    assert sdk.kwargs["messages"] == MESSAGES
    assert sdk.kwargs["tools"] == tools
    assert sdk.kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": config.ENABLE_THINKING}
    }


def test_endpoint_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("BILGIN_LLM_BASE_URL", "http://127.0.0.1:8888/v1")
    monkeypatch.setenv("BILGIN_LLM_MODEL", "qwen3.8-27b")
    monkeypatch.setenv("BILGIN_LLM_API_KEY", "token-1")
    instance = OpenAIClient()
    assert (instance.base_url, instance.model) == ("http://127.0.0.1:8888/v1", "qwen3.8-27b")


# ----------------------------------------------------------------- failures

def test_unreachable_endpoint_is_an_llm_error_naming_the_url():
    instance = OpenAIClient(base_url=f"http://127.0.0.1:{closed_port()}/v1", model="stub")
    with pytest.raises(LLMError) as caught:
        instance.chat(MESSAGES)
    message = str(caught.value)
    assert "127.0.0.1:" in message and "/v1" in message
    assert "BILGIN_LLM_BASE_URL" in message


def test_http_error_becomes_an_llm_error_with_the_status():
    with pytest.raises(LLMError) as caught:
        client(error=http_error(400)).chat(MESSAGES)
    assert "HTTP 400" in str(caught.value)


def test_answer_without_choices_is_an_llm_error():
    with pytest.raises(LLMError) as caught:
        client(ns(choices=[], usage=None)).chat(MESSAGES)
    assert BASE_URL in str(caught.value)

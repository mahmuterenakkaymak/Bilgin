# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Model profilleri: ``config/models.json`` -> ``ModelProfile`` -> hazır istemci (PLAN R4-10).

Bir profil modelin hangi uç noktada olduğunu, hangi adla çağrılacağını ve kaç token'lık bir
pencereyi doldurabileceğimizi söyler; ``prompt_limit`` o pencereden cevabın payını düşürür.
Dosya sırrın kendisini taşımaz, yalnız hangi ortam değişkeninde olduğunu söyler, o yüzden
testlerin yarısı sayıları (bütçe, ``prompt_limit``), yarısı dosyanın sır taşımadığını tutar.
Anahtar çağrı anında okunur: profili bir kez okuyup sonra ortamı değiştirmek de çalışmalı.
"""

import json
import re
import types

import pytest

from nl2sql import config
from nl2sql.agent.llm import (
    LLMError,
    ModelProfile,
    OpenAIClient,
    ProfileError,
    client_for,
    get_profile,
    load_profiles,
)

MESSAGES = [{"role": "user", "content": "Ankara carileri"}]

# R4-10'da yazılı olan adlar ve sayılar: uç nokta, model, anahtar değişkeni, bütçe, en fazla çıktı.
SHIPPED = {
    "strata": ("http://127.0.0.1:8080/v1", "strata", None, 262144, 8192),
    "qwen27b-24k": (
        "http://127.0.0.1:8888/v1",
        "unsloth/Qwen3.8-27B-GGUF",
        "UNSLOTH_API_KEY",
        24576,
        4096,
    ),
    "qwen27b-16k": (
        "http://127.0.0.1:8888/v1",
        "unsloth/Qwen3.8-27B-GGUF",
        "UNSLOTH_API_KEY",
        16384,
        4096,
    ),
}

# Contracts (Run 4 additions): models.json'un kabul ettiği alan adları.
FIELDS = {
    "base_url",
    "model",
    "api_key_env",
    "context_budget",
    "max_output_tokens",
    "sampling",
    "enable_thinking",
    "auto_full_max_tokens",
    "description",
}
SECRET_WORDS = ("key", "token", "secret", "password", "credential")
# alan adı taraması "token"ı dışarıda bırakır: max_output_tokens meşru bir alan adı.
SECRET_FIELDS = ("key", "secret", "password", "credential")
SECRET_SHAPES = re.compile(r"sk-[A-Za-z0-9]|Bearer\s|-----BEGIN|[A-Za-z0-9+/]{40,}")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


def models_file(tmp_path, profiles):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"profiles": profiles}, ensure_ascii=False), encoding="utf-8")
    return path


def entry(**overrides):
    """Sözleşmenin zorunlu üç alanı; gerisi varsayılanla gelir."""
    values = {"base_url": "http://127.0.0.1:9/v1", "model": "denek", "context_budget": 8192}
    values.update(overrides)
    return values


class StubSDK:
    """chat.completions.create yerine geçer ve verilen argümanları tutar."""

    def __init__(self):
        self.kwargs = None
        self.chat = ns(completions=ns(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return ns(choices=[ns(message=ns(content="ok", tool_calls=None))], usage=None)


def stubbed(client):
    client._sdk = StubSDK()
    return client


# ------------------------------------------------------------------ yüklenen profiller


@pytest.mark.parametrize("name", sorted(SHIPPED))
def test_shipped_profiles_carry_their_endpoints_and_budgets(name):
    base_url, model, key_env, budget, output = SHIPPED[name]
    profile = get_profile(name)
    assert (profile.name, profile.base_url, profile.model, profile.api_key_env) == (
        name,
        base_url,
        model,
        key_env,
    )
    assert (profile.context_budget, profile.max_output_tokens) == (budget, output)
    assert profile.prompt_limit == budget - output


def test_prompt_limit_is_the_window_minus_the_answer():
    profile = ModelProfile(
        name="x", base_url="http://127.0.0.1:9/v1", model="m", context_budget=16384
    )
    assert profile.prompt_limit == 16384 - 4096, "en fazla çıktı için varsayılan 4096"


def test_minimal_profile_gets_the_contract_defaults(tmp_path):
    profile = load_profiles(models_file(tmp_path, {"mini": entry()}))["mini"]
    assert (profile.api_key_env, profile.max_output_tokens, profile.sampling) == (None, 4096, {})
    assert profile.enable_thinking is config.ENABLE_THINKING
    assert (profile.auto_full_max_tokens, profile.description) == (None, "")


def test_profile_fields_are_read_from_the_file(tmp_path):
    profile = load_profiles(
        models_file(
            tmp_path,
            {
                "dolu": entry(
                    api_key_env="TEST_KEY",
                    max_output_tokens=1024,
                    sampling={"temperature": 0.2},
                    enable_thinking=False,
                    auto_full_max_tokens=6000,
                    description="deneme",
                )
            },
        )
    )["dolu"]
    assert profile.api_key_env == "TEST_KEY"
    assert profile.sampling == {"temperature": 0.2}
    assert profile.enable_thinking is False
    assert profile.auto_full_max_tokens == 6000
    assert profile.description == "deneme"
    assert profile.prompt_limit == 8192 - 1024


# ------------------------------------------------------------------ hatalar


def test_unknown_profile_lists_the_known_ones_sorted(tmp_path):
    path = models_file(tmp_path, {"strata": entry(), "qwen27b-16k": entry()})
    with pytest.raises(ProfileError) as caught:
        get_profile("gpt-5", path)
    assert str(caught.value) == "Bilinmeyen model profili: gpt-5 (bilinenler: qwen27b-16k, strata)"


@pytest.mark.parametrize(
    "budget, output",
    [(2048, 4096), (4096, 4096), (None, 4096), (0, 1024), (8192, 0), (8192, -1)],
)
def test_a_window_with_no_room_left_is_a_profile_error_naming_the_profile(
    budget, output, tmp_path
):
    path = models_file(
        tmp_path, {"kisa": entry(context_budget=budget, max_output_tokens=output)}
    )
    with pytest.raises(ProfileError) as caught:
        load_profiles(path)
    assert "kisa" in str(caught.value)


def test_a_profile_without_an_endpoint_is_a_profile_error(tmp_path):
    broken = entry()
    del broken["model"]
    with pytest.raises(ProfileError) as caught:
        load_profiles(models_file(tmp_path, {"eksik": broken}))
    assert "eksik" in str(caught.value)


def test_a_missing_or_broken_file_is_a_profile_error(tmp_path):
    with pytest.raises(ProfileError):
        load_profiles(tmp_path / "yok.json")
    bad = tmp_path / "bozuk.json"
    bad.write_text("{profiles:", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profiles(bad)
    empty = tmp_path / "bosh.json"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profiles(empty)


# ------------------------------------------------------------------ anahtar


def test_key_is_read_from_the_named_variable_at_call_time(tmp_path, monkeypatch):
    profile = get_profile("q", models_file(tmp_path, {"q": entry(api_key_env="NL2SQL_TEST_KEY")}))
    monkeypatch.setenv("NL2SQL_TEST_KEY", "token-9")
    assert client_for(profile)._sdk.api_key == "token-9"


def test_profile_without_a_variable_is_a_local_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("NL2SQL_TEST_KEY", raising=False)
    client = client_for(get_profile("q", models_file(tmp_path, {"q": entry()})))
    assert client._sdk.api_key == "local"
    assert (client.base_url, client.model) == ("http://127.0.0.1:9/v1", "denek")


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_variable_names_the_variable_to_define(tmp_path, monkeypatch, value):
    monkeypatch.delenv("NL2SQL_TEST_KEY", raising=False)
    if value is not None:
        monkeypatch.setenv("NL2SQL_TEST_KEY", value)
    profile = get_profile("q", models_file(tmp_path, {"q": entry(api_key_env="NL2SQL_TEST_KEY")}))
    with pytest.raises(LLMError) as caught:
        client_for(profile)
    assert str(caught.value) == "API anahtarı yok: NL2SQL_TEST_KEY ortam değişkenini tanımlayın."


# ------------------------------------------------------------------ istek


def test_client_for_hands_the_profile_numbers_to_every_request(tmp_path):
    profile = get_profile(
        "q",
        models_file(
            tmp_path,
            {
                "q": entry(
                    max_output_tokens=512,
                    sampling={"temperature": 0.2},
                    enable_thinking=False,
                )
            },
        ),
    )
    client = stubbed(client_for(profile))
    client.chat(MESSAGES)
    assert client._sdk.kwargs["max_tokens"] == 512
    assert client._sdk.kwargs["temperature"] == 0.2
    assert client._sdk.kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_request_without_a_profile_stays_exactly_what_it_was():
    client = stubbed(
        OpenAIClient(base_url="http://127.0.0.1:9/v1", model="stub", api_key="test")
    )
    client.chat(MESSAGES)
    assert set(client._sdk.kwargs) == {"model", "messages", "tools", "extra_body"}
    assert client._sdk.kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": config.ENABLE_THINKING}
    }


# ------------------------------------------------------------------ dosyanın kendisi


def assert_no_secret(where, value):
    if isinstance(value, str):
        assert not any(word in value.lower() for word in SECRET_WORDS), f"{where} sır içeriyor"
        assert not SECRET_SHAPES.search(value), f"{where} sırra benziyor"
    elif isinstance(value, dict):
        for field, nested in value.items():
            assert_no_secret(f"{where}.{field}", nested)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            assert_no_secret(f"{where}[{index}]", nested)


def test_shipped_models_file_holds_no_secrets():
    raw = json.loads(config.MODELS_PATH.read_text(encoding="utf-8"))
    assert set(raw) == {"profiles"} and raw["profiles"]
    for name, values in raw["profiles"].items():
        assert set(values) <= FIELDS, f"{name}: sözleşmede olmayan alan"
        for field, value in values.items():
            if field == "api_key_env":
                assert value is None or ENV_NAME.match(value), (
                    f"{name}.api_key_env bir ortam değişkeni adı olmalı"
                )
                continue
            assert not any(word in field.lower() for word in SECRET_FIELDS), f"{name}.{field}"
            assert_no_secret(f"{name}.{field}", value)

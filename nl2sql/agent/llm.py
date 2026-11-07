# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""The one place that talks to the model, and the shapes it hands back to the loop.

Everything the loop needs is here: a chat call that returns content plus tool calls, the
think-block stripped so the model's private reasoning never reaches a report, token counts and
latency for the Step lines, and a single failure type. Any transport or HTTP problem becomes an
`LLMError` carrying a readable Turkish sentence - the loop turns that into the `llm_error`
outcome instead of letting a traceback reach the console.

Model profiles (`config/models.json`) live here too: a profile names the endpoint, the model id,
how large a window the loop may fill, and the environment variable its key sits in - never the
key itself.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import APIConnectionError, APIError, OpenAI

from nl2sql import config
from nl2sql.service.secrets import read_secret

# Qwen-style reasoning blocks; an unterminated one runs to the end of the text.
THINK_BLOCK = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.DOTALL)

UNREACHABLE = (
    "Model endpoint'ine ulaşılamadı: {url}. Strata'nın açık olup olmadığına bakın, gerekirse "
    "NL2SQL_LLM_BASE_URL ile doğru adresi verin."
)
FAILED = "Model endpoint'i hatası: {url} ({error})"
EMPTY_REPLY = "Model beklenen yanıt biçiminde bir yanıt dönmedi: {url}."


class LLMError(RuntimeError):
    """Model endpoint'i çalışmadı ya da yanıtı çözülemedi; döngü bunu llm_error sayar."""


class ProfileError(RuntimeError):
    """Profil dosyası yok, bozuk ya da o adta bir profil yok; CLI bunu exit 2 sayar."""


@dataclass(frozen=True)
class ToolCall:
    """One tool call as the model asked for it; invalid JSON leaves the arguments empty."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)
    # ASSUMPTION: sözleşmedeki parse_error bir bool; argümanın boş mu yoksa bozuk JSON'dan mı geldiği döngüye böyle görünür.
    parse_error: bool = False


@dataclass(frozen=True)
class ChatResponse:
    """One turn from the model: what it said, what it wants to run, and what it cost."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


def strip_think(text: str | None) -> str:
    """Remove reasoning blocks so only the answer the user should see is left."""
    return THINK_BLOCK.sub("", text or "").strip()


@dataclass(frozen=True)
class ModelProfile:
    """One model endpoint and the window it was served with (PLAN R4-10)."""

    name: str
    base_url: str
    model: str
    api_key_env: str | None = None
    context_budget: int = 0
    max_output_tokens: int = 4096
    sampling: dict = field(default_factory=dict)
    enable_thinking: bool = config.ENABLE_THINKING
    auto_full_max_tokens: int | None = None
    description: str = ""

    @property
    def prompt_limit(self) -> int:
        """Tokens the prompt may take: the window minus the answer still owed out of it."""
        return self.context_budget - self.max_output_tokens


def load_profiles(path: str | Path = config.MODELS_PATH) -> dict[str, ModelProfile]:
    """`config/models.json` -> `name -> ModelProfile`, the contract defaults applied."""
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(
            f"Model profili dosyası yok: {file}. `--models-file` ile bir tane gösterin."
        ) from exc
    except ValueError as exc:
        raise ProfileError(f"Model profili dosyası okunamadı: {file} ({exc})") from exc
    entries = raw.get("profiles")
    if not isinstance(entries, dict):
        raise ProfileError(f"Model profili dosyasında 'profiles' bölümü yok: {file}")
    return {name: _profile(name, values) for name, values in entries.items()}


def get_profile(name: str, path: str | Path | None = None) -> ModelProfile:
    """The profile called `name`; an unknown name is answered with the known ones, sorted."""
    profiles = load_profiles(config.MODELS_PATH if path is None else path)
    if name not in profiles:
        raise ProfileError(
            f"Bilinmeyen model profili: {name} (bilinenler: {', '.join(sorted(profiles))})"
        )
    return profiles[name]


def _profile(name: str, raw: dict) -> ModelProfile:
    """One profile line, with the numbers checked: a window has to leave room for the answer."""
    budget = raw.get("context_budget")
    output = raw.get("max_output_tokens", 4096)
    if not raw.get("base_url") or not raw.get("model"):
        raise ProfileError(f"Model profili geçersiz: {name} (base_url ve model zorunlu)")
    if (
        not isinstance(budget, int)
        or not isinstance(output, int)
        or budget <= 0
        or output <= 0
        or budget <= output
    ):
        raise ProfileError(
            f"Model profili geçersiz: {name} (bağlam bütçesi {budget}, en fazla çıktı {output} "
            "token; bütçe çıktının üzerinde olmalı)"
        )
    return ModelProfile(
        name=name,
        base_url=raw["base_url"],
        model=raw["model"],
        api_key_env=raw.get("api_key_env"),
        context_budget=budget,
        max_output_tokens=output,
        sampling=dict(raw.get("sampling") or {}),
        enable_thinking=raw.get("enable_thinking", config.ENABLE_THINKING),
        auto_full_max_tokens=raw.get("auto_full_max_tokens"),
        description=raw.get("description") or "",
    )


class OpenAIClient:
    """OpenAI-compatible chat endpoint (Strata, vLLM, Unsloth Studio) with tool calling."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
        max_tokens: int | None = None,
        sampling: dict | None = None,
        enable_thinking: bool | None = None,
    ) -> None:
        settings = config.llm_settings()
        self.base_url = base_url or settings.base_url
        self.model = model or settings.model
        self._timeout_s = timeout_s if timeout_s is not None else config.LLM_CALL_TIMEOUT_S
        self._max_tokens = max_tokens
        self._sampling = dict(sampling or {})
        self._enable_thinking = enable_thinking
        self._sdk = OpenAI(
            base_url=self.base_url,
            api_key=api_key or settings.api_key,
            timeout=self._timeout_s,
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResponse:
        """One chat turn; raises LLMError instead of an openai exception on any failure."""
        started = time.perf_counter()
        try:
            response = self._sdk.chat.completions.create(**self._request(messages, tools))
        except APIConnectionError as exc:
            raise LLMError(UNREACHABLE.format(url=self.base_url)) from exc
        except APIError as exc:
            raise LLMError(FAILED.format(url=self.base_url, error=_explain(exc))) from exc

        latency = _elapsed(started)
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LLMError(EMPTY_REPLY.format(url=self.base_url))
        message = choices[0].message
        usage = getattr(response, "usage", None)
        return ChatResponse(
            content=strip_think(getattr(message, "content", None)),
            tool_calls=[
                _tool_call(call) for call in (getattr(message, "tool_calls", None) or [])
            ],
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_ms=latency,
        )

    def list_models(self, timeout_s: float | None = None) -> None:
        """What the endpoint serves; the reachability probe asks this once, on a short clock.

        A probe that retried would multiply its own timeout, so the retry the chat call wants is
        switched off here - one answer, either way, is what "is it up" means.
        """
        options = {"max_retries": 0, **({} if timeout_s is None else {"timeout": timeout_s})}
        try:
            self._sdk.with_options(**options).models.list()
        except APIConnectionError as exc:
            raise LLMError(UNREACHABLE.format(url=self.base_url)) from exc
        except APIError as exc:
            raise LLMError(FAILED.format(url=self.base_url, error=_explain(exc))) from exc

    def _request(self, messages: list[dict], tools: list[dict] | None) -> dict:
        """The completion call's arguments; a profile's numbers join the plain request."""
        kwargs: dict = {
            "model": self.model,
            "messages": list(messages),
            "tools": list(tools) if tools else None,
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": (
                        config.ENABLE_THINKING
                        if self._enable_thinking is None
                        else self._enable_thinking
                    )
                }
            },
        }
        if self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens
        kwargs.update(self._sampling)
        return kwargs


def client_for(profile: ModelProfile) -> OpenAIClient:
    """A client for one profile; the key is read from the environment here, not before."""
    return OpenAIClient(
        base_url=profile.base_url,
        model=profile.model,
        api_key=_api_key(profile.api_key_env),
        max_tokens=profile.max_output_tokens,
        sampling=profile.sampling,
        enable_thinking=profile.enable_thinking,
    )


def ping(profile: ModelProfile, timeout_s: float = config.PING_TIMEOUT_S) -> str | None:
    """Uç nokta sağ mı: ``models.list()`` yanıt verirse None, değilse tek cümlelik sebep.

    Karşılaştırma koşusu bu cevabı bloktan önce sorar; kapalı bir endpoint bütün bloğu
    düşürmesin diye sebep döner, fırlatılmaz (PLAN R4-13). Eksik API anahtarı da aynı kapıdan
    geçer - ikisi de "şu yüzden bu modelle şimdi ölçüm yapılamaz" demektir.
    """
    try:
        client_for(profile).list_models(timeout_s)
    except LLMError as exc:
        return str(exc)
    return None


def key_missing_reason(api_key_env: str | None) -> str | None:
    """The named variable the profile needs and the user has not set, in its own sentence.

    The CLI asks this before it repeats an endpoint failure: a missing key is not a down server,
    and the advice it wants is the variable's name (PLAN R4-10). Naming no variable is no failure.
    A Windows service has no environment to set the variable in, so the secrets folder answers the
    same question (PLAN R8-21); the sentence still names the variable, because writing that blob is
    what the operator does with the advice.
    """
    if not api_key_env:
        return None
    if _secret_value(api_key_env):
        return None
    return f"API anahtarı yok: {api_key_env} ortam değişkenini tanımlayın."


def _api_key(api_key_env: str | None) -> str:
    """Local endpoints take any key; a profile that names a variable requires it to be supplied."""
    if not api_key_env:
        return config.DEFAULT_LLM_API_KEY
    value = _secret_value(api_key_env)
    if value is None:
        raise LLMError(key_missing_reason(api_key_env))
    return value


def _secret_value(env_name: str) -> str | None:
    """Anahtarın değeri: önce ortam değişkeni, yoksa ``NL2SQL_HOME/secrets`` blobu (R8-21).

    İkisi de yoksa - ya da boşsa - ``None``: "kurulu" sayılmaz, çünkü reddin cümlesi kullanıcının
    bir sonraki adımını söyleyebilmeli.
    """
    value = os.environ.get(env_name)
    if value and value.strip():
        return value.strip()
    stored = read_secret(env_name)
    return stored.strip() if stored and stored.strip() else None


def _tool_call(call) -> ToolCall:
    """A local server can hand back half a JSON object; that is a parse_error, not a crash."""
    function = getattr(call, "function", None)
    raw = getattr(function, "arguments", None) or ""
    parse_error = False
    try:
        arguments = json.loads(raw) if raw else {}
    except ValueError:
        arguments, parse_error = {}, True
    if not isinstance(arguments, dict):
        arguments, parse_error = {}, True
    return ToolCall(
        id=str(getattr(call, "id", "") or ""),
        name=str(getattr(function, "name", "") or ""),
        arguments=arguments,
        parse_error=parse_error,
    )


def _explain(exc: APIError) -> str:
    status = getattr(exc, "status_code", None)
    text = " ".join(str(exc).split())
    if status is not None:
        return f"HTTP {status}{': ' + text if text else ''}"
    return text or type(exc).__name__


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)

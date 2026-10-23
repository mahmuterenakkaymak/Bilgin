"""The one place that talks to the model, and the shapes it hands back to the loop.

Everything the loop needs is here: a chat call that returns content plus tool calls, the
think-block stripped so the model's private reasoning never reaches a report, token counts and
latency for the Step lines, and a single failure type. Any transport or HTTP problem becomes an
`LLMError` carrying a readable Turkish sentence - the loop turns that into the `llm_error`
outcome instead of letting a traceback reach the console.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from openai import APIConnectionError, APIError, OpenAI

from nl2sql import config

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


class OpenAIClient:
    """OpenAI-compatible chat endpoint (Strata, vLLM, Unsloth Studio) with tool calling."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        settings = config.llm_settings()
        self.base_url = base_url or settings.base_url
        self.model = model or settings.model
        self._timeout_s = timeout_s if timeout_s is not None else config.LLM_CALL_TIMEOUT_S
        self._sdk = OpenAI(
            base_url=self.base_url,
            api_key=api_key or settings.api_key,
            timeout=self._timeout_s,
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResponse:
        """One chat turn; raises LLMError instead of an openai exception on any failure."""
        started = time.perf_counter()
        try:
            response = self._sdk.chat.completions.create(
                model=self.model,
                messages=list(messages),
                tools=list(tools) if tools else None,
                extra_body={"chat_template_kwargs": {"enable_thinking": config.ENABLE_THINKING}},
            )
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

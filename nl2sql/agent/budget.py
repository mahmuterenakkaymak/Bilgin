# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""The prompt budget: what a request costs before it is sent, and what gets cut when it does not.

The endpoint reports token counts only after it has answered, and a request over a small model's
window comes back as no answer at all (PLAN R4-11). So the loop estimates first, with the same
char-based rule ``doc.estimate_tokens`` uses, and trims when the estimate is over the limit.

Trimming touches tool answers only: a tool message cannot be dropped, because the tool call it
answers would be left without its reply and the endpoint rejects the transcript. The message stays
in place and its content gets shorter; the cut is permanent, the model is not asked to re-read it.
"""

from __future__ import annotations

import json

from nl2sql import config
from nl2sql.schema_map import doc

# ASSUMPTION: N kısaltılan karakter sayısı - model hangi cevabın ne kadarının atıldığını görsün.
TRIM_MARKER = "… (bağlam bütçesi için kısaltıldı: {removed} karakter)"
TRIM_MARKER_PREFIX = TRIM_MARKER.split("{", 1)[0]
TRIM_MARKER_SUFFIX = TRIM_MARKER.split("}", 1)[1]


def estimate_prompt(messages: list[dict], tools: list[dict] | None = None) -> int:
    """The estimated cost in tokens: every message, its tool calls and the tool schemas."""
    text = _prompt_text(messages, tools)
    return doc.estimate_tokens(text) + len(messages) * config.MESSAGE_OVERHEAD_TOKENS


def trim_tool_answers(
    messages: list[dict], limit: int, tools: list[dict] | None = None
) -> tuple[list[dict], int, int]:
    """Cut tool answers oldest first until the estimate fits: returns (transcript, cuts, estimate).

    The newest tool answer is never cut - it is the one the model is about to answer - and no
    message is ever removed, so every tool_call_id keeps its answer. An answer that already carries
    the marker is left alone, so one answer is counted once no matter how many turns re-measure the
    transcript. When nothing more can be cut the estimate comes back still over the limit; what
    that means is the caller's decision.
    """
    trimmed = list(messages)
    estimate = estimate_prompt(trimmed, tools)
    if estimate <= limit:
        return trimmed, 0, estimate

    tool_indexes = [i for i, message in enumerate(trimmed) if message.get("role") == "tool"]
    newest = tool_indexes[-1] if tool_indexes else -1
    cuts = 0
    for index, message in enumerate(trimmed):
        if index == newest or message.get("role") != "tool":
            continue
        content = message.get("content") or ""
        # ASSUMPTION: "kırpma kısaltmıyorsa atla" marker'lı cevapla karşılanır; test_budget.py sınırın 1 üstündeki ilk kesimi sözleşme sayıyor.
        if len(content) <= config.TRIM_TOOL_CHARS or _already_trimmed(content):
            continue
        removed = len(content) - config.TRIM_TOOL_CHARS
        trimmed[index] = {
            **message,
            "content": content[: config.TRIM_TOOL_CHARS] + TRIM_MARKER.format(removed=removed),
        }
        cuts += 1
        estimate = estimate_prompt(trimmed, tools)
        if estimate <= limit:
            break
    return trimmed, cuts, estimate


def _already_trimmed(content: str) -> bool:
    """True when a previous pass already appended the marker: cutting again would only rewrite it."""
    _, found, tail = content.rpartition(TRIM_MARKER_PREFIX)
    if not found:
        return False
    return tail.endswith(TRIM_MARKER_SUFFIX) and tail[: -len(TRIM_MARKER_SUFFIX)].isdigit()


def _prompt_text(messages: list[dict], tools: list[dict] | None) -> str:
    """The request as flat text: contents, every tool_calls entry and the tool schemas' JSON."""
    parts: list[str] = []
    for message in messages:
        parts.append(message.get("content") or "")
        parts += [_json(call) for call in message.get("tool_calls") or []]
    if tools:
        parts.append(_json(tools))
    return "".join(parts)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)

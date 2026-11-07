# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""The conversation: ask the model, run what it asks for, hand the answer back, until it submits.

The loop is the only part that owns a run's shape. It keeps the transcript in the OpenAI form the
endpoint expects (one assistant message per turn, then a tool message per call), records a Step for
every tool call and every prose-only turn so the CLI can show what happened, and enforces the three
limits that stop a run from spending forever: the mode's tool-call limit, MAX_FAILED_RUNS and
AGENT_TIMEOUT_S. A model that never calls submit_sql ends as no_submission; an endpoint that is down
ends as llm_error, because the LLMError it raises is caught here rather than allowed to reach the
console.

With a prompt budget (PLAN R4-11) every turn is estimated before it is sent: an over-budget
transcript is trimmed with ``budget.trim_tool_answers`` (permanently, tool answers only) and, if it
still does not fit, the run ends as ``context_overflow`` without ever reaching the model.

With a history (PLAN R7-4) the earlier turns join the run as one block appended to the system
message — the user message stays the bare question — and the block is what the budget shrinks
first: ``context.fit_history`` drops the oldest turn, then rows, and only a budget that cannot
carry the bare prompt stops the run. Such a run also shows ``submit_sql`` a ``context`` field and
keeps whatever the model writes there on the run, raw, for the caller to validate (R7-5).

The mode (PLAN R2-5) decides the rest of the run: the system prompt, the tools the model is shown
and the tool-call limit all come from ``modes``, so the three arms of the A/B differ in nothing but
the context and the tools they hand the model. A context with ``clarify`` adds one tool to that list
(R5-10) and ends the run as ``needs_clarification`` instead of submitting, with the question and its
options on the run for the caller to ask.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace

from bilgin import config
from bilgin.agent import modes
from bilgin.agent.budget import estimate_prompt, trim_tool_answers
from bilgin.agent.context import context_block, fit_history, followup_hints
from bilgin.agent.llm import LLMError
from bilgin.agent.refine import refine_hint
from bilgin.agent.tools import answer_is_ok, clarify_request, dispatch, submit_sql_with_context

# Sözleşmede adı geçen dördüncü bir sınır yok; bu yalnızca hiç araç çağırmayıp metin üreten bir
# modelin sonsuz dönmemesi için bir emniyet.
# ASSUMPTION: varsayılan MAX_TOOL_CALLS'in üstünde seçildi ki araç sınırını sınayan senaryolarda
# döngüyü durduran şey bu emniyet değil, adlandırılmış sınırın kendisi olsun.
DEFAULT_MAX_TURNS = 16

TIMEOUT_STOP = "Zaman aşımı: {seconds:.0f} sn."
TURN_STOP = "Tur sınırına ulaşıldı ({turns})."
TOOL_STOP = "Araç çağrı sınırı: {limit}."
FAILED_STOP = "Başarısız sorgu sınırı: {limit}."
OVERFLOW_STOP = "Bağlam bütçesi aşıldı: tahmin {estimate} > sınır {limit} token."


@dataclass
class Step:
    """One thing that happened: a tool call and its answer, or a turn that only talked."""

    n: int
    tool: str
    args: dict = field(default_factory=dict)
    summary: str = ""
    ok: bool = True
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


@dataclass
class AgentRun:
    """A finished run: the steps, what was submitted (if anything), why it stopped, what it cost."""

    question: str
    mode: str = "full"
    steps: list[Step] = field(default_factory=list)
    submitted_sql: str | None = None
    # submitted | no_submission | timeout | llm_error | context_overflow | needs_clarification
    status: str = "no_submission"
    stop_reason: str = ""
    clarification: dict | None = None  # {"question", "options"}; yalnız needs_clarification'da dolu
    max_prompt_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    elapsed_s: float = 0.0
    peak_estimate: int = 0  # en yüksek gönderilen istem tahmini (R4-11); taşmada reddedilen tahmin
    trimmed: int = 0  # bütçe için kısaltılan araç cevabı sayısı
    overflows: int = 0  # 1: bütçeye sığmadığı için modele gitmeden durdu
    # R7-5: submit_sql'in ham context alanı; doğrulama çağıranın (validate_note).
    context_note: dict | None = None
    history_turns: int = 0  # bloğa giren önceki tur sayısı (R7-4; bütçe eksilttiyse daha azı)
    history_rows_dropped: int = 0  # bütçe için bloktan düşürülen satır sayısı


def run_agent(
    question: str,
    llm,
    executor,
    schema: dict,
    source: str = "",
    *,
    mode: str = "full",
    context: modes.ToolContext | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    timeout_s: float = config.AGENT_TIMEOUT_S,
    budget: int | None = None,
    history: list[dict] | None = None,
    answer_lang: str = "tr",
) -> AgentRun:
    """Drive one question to a submitted SQL, a limit, or a model failure, in one mode; with a
    prompt budget, keep every request under it (R4-11); with a history, let the earlier turns say
    what "bu müşteri" means (R7-4); ``answer_lang="en"`` tells the model to answer in English
    (R8-9), while the default leaves the prompt byte-identical to every earlier run."""
    started = time.perf_counter()
    deadline = started + timeout_s
    mode_def = modes.get_mode(mode)
    limit = mode_def.max_tool_calls
    run = AgentRun(question=question, mode=mode)
    audited = _Audited(executor, source)
    ctx = _context(context, audited, schema, mode, answer_lang)
    sent_tools = modes.mode_tools(ctx)
    messages = [
        {"role": "system", "content": modes.system_prompt(ctx)},
        {"role": "user", "content": question},
    ]
    turns = list(history or [])[-config.CONV_TURNS :]
    if turns:
        # R7-4: geçmiş tek system mesajının sonuna eklenir, kullanıcının çıplak sorusu olduğu gibi
        # kalır. Bütçe daralıyorsa ilk eksilen de geçmiştir; bloğa hiç tur sığmıyorsa hiçbir şey
        # eklenmez ve kararı aşağıdaki bütçe denetimi verir - Run 6'nın tek başarısızlığı.
        kept, rows_dropped, _ = fit_history(turns, messages, sent_tools, budget)
        run.history_turns, run.history_rows_dropped = kept, rows_dropped
        if kept:
            # ASSUMPTION: ipucu satırlarını followup_hints ve refine_hint doldurur (R7-11) -
            # bloğun üretebileceği soru ile şema ikili burada, döngünün elinde; context_block kendi
            # ipucusunu kurmuyor.
            block = context_block(
                turns, followup_hints(question, ctx.schema), refine_hint(question)
            )
            messages[0] = {"role": "system", "content": f"{messages[0]['content']}\n\n{block}"}
            sent_tools = [
                submit_sql_with_context() if shown["function"]["name"] == "submit_sql" else shown
                for shown in sent_tools
            ]
    tool_calls = failed_runs = 0
    peak = 0

    def finish(status: str, reason: str = "") -> AgentRun:
        run.status = status
        run.stop_reason = reason
        run.peak_estimate = peak
        run.elapsed_s = round(time.perf_counter() - started, 3)
        return run

    for _ in range(max_turns):
        if time.perf_counter() >= deadline:
            return finish("timeout", TIMEOUT_STOP.format(seconds=timeout_s))
        if tool_calls >= limit:
            return finish("no_submission", TOOL_STOP.format(limit=limit))

        # Her çağrı öncesi tahmin: bütçe varsa aşan sohbet kalıcı olarak kırpılır, kırpma da
        # yetmezse modele hiç gidilmez (R4-11). Bütçe yoksa yalnız tepe tahmini izlenir.
        estimate = estimate_prompt(messages, sent_tools)
        if budget is not None and estimate > budget:
            messages, cuts, estimate = trim_tool_answers(messages, budget, sent_tools)
            run.trimmed += cuts
            if estimate > budget:
                run.overflows = 1
                if peak == 0:  # daha hiçbir tur gönderilmedi: reddedilen tahmin tepe olur
                    peak = estimate
                return finish(
                    "context_overflow", OVERFLOW_STOP.format(estimate=estimate, limit=budget)
                )
        peak = max(peak, estimate)

        try:
            response = llm.chat(messages, sent_tools)
        except LLMError as exc:
            return finish("llm_error", str(exc))

        # Endpoint maliyeti yanıt başına bir kez bildirir; aşağıda kaç adım üretilirse üretilsin
        # koşunun toplamına da bir kez yazılır.
        _count_turn(run, response)

        if response.tool_calls:
            messages.append(_assistant_message(response))
            for index, call in enumerate(response.tool_calls):
                if tool_calls >= limit:
                    return finish("no_submission", TOOL_STOP.format(limit=limit))
                tool_calls += 1
                answer = dispatch(call.name, call.arguments, ctx)
                ok = answer_is_ok(answer)
                run.steps.append(
                    Step(
                        n=len(run.steps) + 1,
                        tool=call.name,
                        args=call.arguments,
                        summary=answer,
                        ok=ok,
                        # Adımlar da maliyeti bir kez taşısın: aynı yanıtın sonraki çağrısı 0 yazar.
                        prompt_tokens=response.prompt_tokens if index == 0 else 0,
                        completion_tokens=response.completion_tokens if index == 0 else 0,
                        latency_ms=response.latency_ms,
                    )
                )
                messages.append({"role": "tool", "tool_call_id": call.id, "content": answer})
                if call.name == "submit_sql" and ok:
                    run.submitted_sql = str(call.arguments.get("sql") or "")
                    note = call.arguments.get("context")
                    if isinstance(note, dict):  # ham kalır; doğrulayacak olan çağıran (R7-5)
                        run.context_note = note
                    return finish("submitted")
                if call.name == "ask_clarification" and ok:
                    # Geçersiz çağrı yukarıdaki red satırından okunur ve çalışma burada durmaz;
                    # duran tek şey kabul edilmiş bir soru, devamı kullanıcının seçimine kalır.
                    asked, options = clarify_request(call.arguments)
                    run.clarification = {"question": asked, "options": options}
                    return finish("needs_clarification")
                if call.name in ("run_sql", "submit_sql") and not ok:
                    failed_runs += 1
                    if failed_runs >= config.MAX_FAILED_RUNS:
                        return finish("no_submission", FAILED_STOP.format(limit=config.MAX_FAILED_RUNS))
        else:
            run.steps.append(
                Step(
                    n=len(run.steps) + 1,
                    tool="",
                    summary=response.content,
                    ok=True,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    latency_ms=response.latency_ms,
                )
            )
            messages.append({"role": "assistant", "content": response.content})

    return finish("no_submission", TURN_STOP.format(turns=max_turns))


def _context(
    context, audited, schema: dict, mode: str, answer_lang: str = "tr"
) -> modes.ToolContext:
    """This run's dispatch world: the caller's index and graph, the audited executor, this mode.

    ``full_rules`` without a context is a wiring mistake, not a mode: an empty ``rules`` makes its
    system prompt identical to ``full``, so the A/B would measure the same arm twice. It raises.
    ``answer_lang`` (R8-9) wins over the context's own, the way ``mode`` already does.
    """
    if context is None:
        if mode == "full_rules":
            raise ValueError(
                "full_rules modu bağlam istiyor: context.rules verilmedi; kuralsız bir full_rules "
                "istemi full ile aynıdır."
            )
        return modes.ToolContext(
            executor=audited, schema=schema, mode=mode, answer_lang=answer_lang
        )
    # ASSUMPTION: bağlamın kendi şeması varsa o kazanır; run_agent'ın şema argümanı yalnız
    # bağlam verilmeyince devreye girer, böylece ikisi çelişirse sessiz olan yutulmaz.
    return replace(
        context, executor=audited, schema=context.schema or schema, mode=mode,
        answer_lang=answer_lang,
    )


class _Audited:
    """Binds a source to the executor so every query this run makes is audited under the question.

    dispatch is the fixed boundary and calls ``execute(sql, budget)`` with no source, so the source
    is attached here instead of changing it; the real executor (and its policy) still runs.
    """

    def __init__(self, executor, source: str) -> None:
        self._executor = executor
        self._source = source

    def execute(self, sql, budget=None):
        return self._executor.execute(sql, budget, self._source)


def _assistant_message(response) -> dict:
    """Echo the model's turn back so the next call sees the transcript it is continuing."""
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": _as_json(call.arguments)},
            }
            for call in response.tool_calls
        ],
    }


def _as_json(arguments: dict) -> str:
    return json.dumps(arguments, ensure_ascii=False)


def _count_turn(run: AgentRun, response) -> None:
    """Charge a turn's tokens once, no matter how many tool calls it asked for."""
    run.total_prompt_tokens += response.prompt_tokens
    run.total_completion_tokens += response.completion_tokens
    run.max_prompt_tokens = max(run.max_prompt_tokens, response.prompt_tokens)

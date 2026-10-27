"""Araç listesi ve sistem istemi, mod başına (PLAN R2-5, R2-6).

Üç mod aynı soruyu aynı kurallarla çözer; farkı bağlam ve araçtır. `full` bütün şema detayını
isteme koyar, `full_rules` bir de iş kurallarını yazar, `rag` yalnız tablo adlarını görür ve
kolonu, join yolunu, kuralı ve gerçek değeri araçlardan ister. A/B ölçümü bu yüzden üç modun
tepe token ile puan karşılaştırmasıdır: pahalı bağlamın satın aldığı şey ölçülmeli, varsayılmasın.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from nl2sql import config
from nl2sql.agent import prompt, tools


@dataclass
class ToolContext:
    """Bir çalışmanın dünyası: her araç çağrısı executor, şema, kural ve mod bilgisini buradan alır."""

    executor: Any
    schema: dict
    rules: list = field(default_factory=list)
    search: Any = None
    graph: Any = None
    mode: str = "full"
    # R4-4: referans tarih verinin parçasıdır; bir kümenin "geçen ay"ı kendi as_of'una göredir.
    as_of: str = config.AS_OF
    # R5-10: ask_clarification yalnız açıkken görünen bir araçtır; kapalıyken araç listesi de sistem
    # istemi de Run 1-4 ile bayt aynıdır, yani eski parmak izleri ve ölçümler değişmez.
    clarify: bool = False
    # R8-9: cevabın dili; "en" modun sistem istemine tek satır ekler, "tr" bayt bayt bugünküdür.
    # ASSUMPTION: auto ayrı bir istem kurmaz, çözüldüğü modun builder'ından geçtiği için dili de oradan alır.
    answer_lang: str = "tr"


@dataclass(frozen=True)
class Mode:
    """Modun sözleşmesi: çağrılabilecek araçlar, ilk sistem mesajı ve araç çağrısı limiti."""

    name: str
    tools: list[dict]
    system_prompt: Callable[[ToolContext], str]
    max_tool_calls: int


def _full_prompt(ctx: ToolContext) -> str:
    return prompt.full_prompt(ctx.as_of, ctx.schema, ctx.answer_lang)


def _full_rules_prompt(ctx: ToolContext) -> str:
    return prompt.full_rules_prompt(ctx.as_of, ctx.schema, ctx.rules, ctx.answer_lang)


def _rag_prompt(ctx: ToolContext) -> str:
    return prompt.rag_prompt(ctx.as_of, ctx.schema, ctx.answer_lang)


_SQL_TOOLS = [tools.RUN_SQL, tools.SUBMIT_SQL]

MODES: dict[str, Mode] = {
    "full": Mode(
        name="full",
        tools=[tools.GET_SCHEMA, *_SQL_TOOLS],
        system_prompt=_full_prompt,
        max_tool_calls=config.MAX_TOOL_CALLS_BY_MODE["full"],
    ),
    "full_rules": Mode(
        name="full_rules",
        tools=[tools.GET_SCHEMA, *_SQL_TOOLS],
        system_prompt=_full_rules_prompt,
        max_tool_calls=config.MAX_TOOL_CALLS_BY_MODE["full_rules"],
    ),
    "rag": Mode(
        name="rag",
        tools=[
            tools.SEARCH_SCHEMA,
            tools.GET_TABLE_DETAILS,
            tools.FIND_JOIN_PATH,
            tools.SEARCH_RULES,
            tools.SAMPLE_VALUES,
            *_SQL_TOOLS,
        ],
        system_prompt=_rag_prompt,
        max_tool_calls=config.MAX_TOOL_CALLS_BY_MODE["rag"],
    ),
}


def get_mode(name: str) -> Mode:
    """Modu adıyla bulur; bilinmeyen ad komut satırındaki bir yazım hatası, ne olduğunu gör."""
    mode = MODES.get(name)
    if mode is None:
        raise ValueError(f"Bilinmeyen mod: {name}. Modlar: {', '.join(MODES)}.")
    return mode


def mode_tools(ctx: ToolContext) -> list[dict]:
    """Modele gösterilen araçlar: modun kendi araçları, clarify açıksa bir de açıklama sorusu.

    Döngü bunu hem istem tahminine hem çağrıya veriyor, dispatch de aynı yerden kabul ediyor; liste
    ile kabul ayrı iki yerde ayrılmaz, yoksa modelin gördüğü bir aracı çalıştıramazsın.
    """
    declared = get_mode(ctx.mode).tools
    if not ctx.clarify:
        return declared
    return [*declared, tools.ASK_CLARIFICATION]


def system_prompt(ctx: ToolContext) -> str:
    """Modun sistem istemi; clarify açıksa açıklama sorusunun kuralları da sonda (R5-10)."""
    text = get_mode(ctx.mode).system_prompt(ctx)
    return f"{text}{prompt.CLARIFY_RULES}" if ctx.clarify else text

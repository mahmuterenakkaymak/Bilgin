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


@dataclass(frozen=True)
class Mode:
    """Modun sözleşmesi: çağrılabilecek araçlar, ilk sistem mesajı ve araç çağrısı limiti."""

    name: str
    tools: list[dict]
    system_prompt: Callable[[ToolContext], str]
    max_tool_calls: int


def _full_prompt(ctx: ToolContext) -> str:
    return prompt.full_prompt(config.AS_OF, ctx.schema)


def _full_rules_prompt(ctx: ToolContext) -> str:
    return prompt.full_rules_prompt(config.AS_OF, ctx.schema, ctx.rules)


def _rag_prompt(ctx: ToolContext) -> str:
    return prompt.rag_prompt(config.AS_OF, ctx.schema)


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

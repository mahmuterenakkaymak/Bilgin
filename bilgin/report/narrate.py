# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Anlatı: cümleyi LLM kurar, sayıları bekçi onaylar (PLAN R5-9, Contracts Narration).

LLM dil katmanıdır, hesap makinesi değil: satırların ve olguların sayılarını olduğu gibi kullanır,
bekçi de tam olarak bunu denetler. Bekçiyi geçmeyen cümle bir kez daha istenir; ikinci deneme de
geçmezse ya da endpoint çalışmazsa koddan kurulan cümle konuşur — o cümle sayılarını olguların
`display` alanından aldığı için bekçiyi her zaman geçer. Bekçiyi geçmeyen ya da boş bir metin
kullanıcıya gitmez; şablonun arkasına saklandığı yer burasıdır.

Anlatının dili cevabın dilidir (R8-8): `lang="en"` kural listesinin İngilizce ikizini, satırları
İngilizce okunuşla ve bekçiyi İngilizce gramerle getirir; yeniden yazma ve şablon cümleleri
catalog'dan gelir. Türkçe tarafın mesajları eskisiyle bayt bayttır.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal

from bilgin import config
from bilgin.agent.llm import LLMError
from bilgin.i18n import t
from bilgin.report import fmt, guard

SYSTEM = """Sen bir sorgu sonucunu kullanıcıya Türkçe anlatan bir rapor asistanısın.

KURALLAR
1. 1-3 cümle düz metin yaz: başlık, madde işareti ve tablo yok.
2. Yalnızca aşağıdaki satırlarda ve GERÇEKLER'de gördüğün sayıları kullan. Hiçbir hesap yapma: \
toplam, fark, oran, yüzde veya ortalamayı kendin üretme; sayı gerektirmeyen bir şeyi sayıyla söyleme.
3. Sayıyı gösterildiği biçimde aynen yaz: binlik ayıracı nokta, ondalık virgül, yüzde `%12,3`. \
Basamak ekleme ya da atma; İngilizce yazım (`1,234.56`) bekçi tarafından reddedilir.
4. KOLONLAR satırındaki teknik adları (StateProvinceName, ToplamCiro, CIRO gibi) cümlede ASLA yazma; \
ne anlattıklarını sorunun dilinde Türkçe söyle ("eyalet", "toplam ciro", "tedarikçi"). Satırlardaki değerleri \
(ürün, firma, şehir adları) olduğu gibi yaz.
5. Cümle sorunun doğrudan cevabı olsun ve bir insanın konuşacağı gibi doğal Türkçe olsun; cümleye sayıyla \
başlamak zorunda değilsin.
"""

SYSTEM_EN = """You are a report assistant that explains a query result to the user in English.

RULES
1. Write 1-3 sentences of plain text: no heading, no bullet points and no table.
2. Use only the numbers you see in the rows below and in FACTS. Do not compute anything: never \
produce a total, a difference, a ratio, a percentage or an average yourself; never state something \
that needs no number with a number.
3. Write each number exactly as it is shown: comma as the thousands separator, dot as the decimal \
mark, percent as `12.3%`. Do not add or drop digits; the Turkish spelling (`1.234,56`) is rejected \
by the guard.
4. NEVER write the technical names from the COLUMNS line (StateProvinceName, ToplamCiro, CIRO) in \
the sentence; say what they mean in English ("state province", "total revenue", "supplier"). Write \
the values in the rows (product, company and city names) exactly as they are.
5. The sentence must answer the question directly and read as natural English, the way a person \
would say it; you do not have to start the sentence with a number.
"""

# Şablon cümlenin anlattığı olgular; tuple sırası cümlenin akışını da verir (PLAN R5-9).
_TEMPLATE_FACTS = ("row_count", "total", "top_item", "change")


@dataclass(frozen=True)
class Narration:
    """Cümlenin kendisi, kimin kurduğu ve bekçinin reddettiği sayıların ham yazımları."""

    text: str
    source: str
    rejected: list[str] = field(default_factory=list)


def narrate(question, columns, rows, facts, llm, max_rows=config.NARRATE_MAX_ROWS, lang: str = "tr") -> Narration:
    """Sonucu 1-3 cümleyle anlatır; bekçiyi geçmeyen cümle bir kez daha istenir, sonra şablon konuşur.

    `lang` cevabın dilidir: anlatıcıya o dilin kural listesi ve o dilin sayı yazımı gösterilir,
    bekçi ve yeniden yazma cümlesi de o dili konuşur.
    """
    if not rows:
        return Narration(template_sentence(question, facts, lang), "template")

    allowed = guard.allowed_values(columns, rows, facts, question)
    messages = _messages(question, columns, rows, facts, max_rows, lang)
    rejected: list[str] = []
    for source in ("llm", "llm_retry"):
        try:
            text = (llm.chat(messages, None).content or "").strip()
        except LLMError:
            break
        if not text:
            break
        result = guard.check_text(text, allowed, lang)
        leaked = _leaked_names(text, columns)
        if result.ok and not leaked:
            return Narration(text, source, rejected)
        rejected += result.offending + leaked
        feedback = t("narrate.retry.numbers", lang, tokens=", ".join(result.offending)) if not result.ok else ""
        if leaked:
            feedback = (feedback + " " + t("narrate.retry.names", lang, names=", ".join(leaked))).strip()
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": feedback},
        ]
    return Narration(template_sentence(question, facts, lang), "template", rejected)


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _technical(name: str) -> bool:
    """A column name a person would not say: snake_case, camelCase/PascalCase, or an all-caps code."""
    return "_" in name or re.search(r"[a-z][A-Z]", name) is not None or (name.isupper() and len(name) >= 3)


def _leaked_names(text: str, columns) -> list[str]:
    """Technical column names that appear in the sentence as whole words, exactly as written (2026-10-25,
    Eren: "StateProvinceName gibi kolon adları değil, doğal dil")."""
    words = set(_IDENT.findall(text))
    return [name for name in columns if _technical(str(name)) and str(name) in words]


def template_sentence(question: str, facts, lang: str = "tr") -> str:
    """Koddan kurulan cümle: sayılar yalnız olguların dildeki okunuşlarıdır, o yüzden bekçiyi geçer."""
    shown: dict[str, dict] = {}
    for fact in _fact_dicts(facts):
        name = str(fact.get("name") or "")
        if name in _TEMPLATE_FACTS and name not in shown:
            shown[name] = fact
    parts = [
        t("narrate.template.item", lang, label=shown[name].get("label"), display=shown[name].get("display"))
        for name in _TEMPLATE_FACTS
        if name in shown
    ]
    if not parts:
        return t("narrate.none", lang)
    if len(parts) == 1:
        # ASSUMPTION: sayısal olgu yoksa şablon ne sorulduğunu gösterir; sorunun kendi sayıları
        # bekçinin izin listesinde zaten vardır (PLAN R5-8), o yüzden cümleye taşımak güvenlidir.
        parts.append(t("narrate.template.question", lang, question=(question or "").strip()))
    return " ".join(parts)


def _messages(question, columns, rows, facts, max_rows, lang) -> list[dict]:
    """Anlatıcıya verilen her şey tek kullanıcı mesajında: soru, kolonlar, satırlar ve olgular."""
    shown = list(rows[:max_rows])
    header = (
        t("narrate.input.rows_partial", lang, shown=len(shown), total=len(rows))
        if len(shown) < len(rows)
        else t("narrate.input.rows", lang)
    )
    lines = [
        t("narrate.input.question", lang, question=question),
        "",
        t("narrate.input.columns", lang, columns=", ".join(columns)),
        header,
        *(_row_text(row, lang) for row in shown),
        "",
        t("narrate.input.facts", lang),
        json.dumps(_fact_dicts(facts), ensure_ascii=False),
    ]
    system = SYSTEM_EN if lang == "en" else SYSTEM
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]


def _row_text(row, lang) -> str:
    return " | ".join(_cell_text(cell, lang) for cell in row)


def _cell_text(value, lang) -> str:
    """Hücrenin anlatıcıya gösterimi: sayı dilin okunuşuyla ki kopyaladığı sayı bekçiyi geçsin."""
    if value is None:
        return fmt.NULL_TEXT
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return str(value)
    return fmt.format_number(value, lang)


def _fact_dicts(facts) -> list[dict]:
    """Olgular hem Fact nesnesi hem payload sözlüğü olabilir; anlatıcı düz JSON görür."""
    return [fact.to_dict() if hasattr(fact, "to_dict") else dict(fact) for fact in facts or []]

"""Anlatı: cümleyi LLM kurar, sayıları bekçi onaylar (PLAN R5-9, Contracts Narration).

LLM dil katmanıdır, hesap makinesi değil: satırların ve olguların sayılarını olduğu gibi kullanır,
bekçi de tam olarak bunu denetler. Bekçiyi geçmeyen cümle bir kez daha istenir; ikinci deneme de
geçmezse ya da endpoint çalışmazsa koddan kurulan cümle konuşur — o cümle sayılarını olguların
`display` alanından aldığı için bekçiyi her zaman geçer. Bekçiyi geçmeyen ya da boş bir metin
kullanıcıya gitmez; şablonun arkasına saklandığı yer burasıdır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from nl2sql import config
from nl2sql.agent.llm import LLMError
from nl2sql.report import fmt, guard

SYSTEM = """Sen bir sorgu sonucunu kullanıcıya Türkçe anlatan bir rapor asistanısın.

KURALLAR
1. 1-3 cümle düz metin yaz: başlık, madde işareti ve tablo yok.
2. Yalnızca aşağıdaki satırlarda ve GERÇEKLER'de gördüğün sayıları kullan. Hiçbir hesap yapma: \
toplam, fark, oran, yüzde veya ortalamayı kendin üretme; sayı gerektirmeyen bir şeyi sayıyla söyleme.
3. Sayıyı gösterildiği biçimde aynen yaz: binlik ayıracı nokta, ondalık virgül, yüzde `%12,3`. \
Basamak ekleme ya da atma; İngilizce yazım (`1,234.56`) bekçi tarafından reddedilir.
4. Satır ve kolon adlarını olduğu gibi kullan, onların arasına sayı sıkıştırma.
5. Cümle sorunun cevabı olsun: en önemli sayıyı en başa koy.
"""

_RETRY = "Şu sayılar sonuçta yok: {tokens}. Yalnız verilen sayılarla yeniden yaz."

# Şablon cümlenin anlattığı olgular; tuple sırası cümlenin akışını da verir (PLAN R5-9).
_TEMPLATE_FACTS = ("row_count", "total", "top_item", "change")

_NO_NUMBER = "Sonuçta anlatılacak sayısal özet yok."


@dataclass(frozen=True)
class Narration:
    """Cümlenin kendisi, kimin kurduğu ve bekçinin reddettiği sayıların ham yazımları."""

    text: str
    source: str
    rejected: list[str] = field(default_factory=list)


def narrate(question, columns, rows, facts, llm, max_rows=config.NARRATE_MAX_ROWS) -> Narration:
    """Sonucu 1-3 cümleyle anlatır; bekçiyi geçmeyen cümle bir kez daha istenir, sonra şablon konuşur."""
    if not rows:
        return Narration(template_sentence(question, facts), "template")

    allowed = guard.allowed_values(columns, rows, facts, question)
    messages = _messages(question, columns, rows, facts, max_rows)
    rejected: list[str] = []
    for source in ("llm", "llm_retry"):
        try:
            text = (llm.chat(messages, None).content or "").strip()
        except LLMError:
            break
        if not text:
            break
        result = guard.check_text(text, allowed)
        if result.ok:
            return Narration(text, source, rejected)
        rejected += result.offending
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": _RETRY.format(tokens=", ".join(result.offending))},
        ]
    return Narration(template_sentence(question, facts), "template", rejected)


def template_sentence(question: str, facts) -> str:
    """Koddan kurulan cümle: sayılar yalnız olguların Türkçe okunuşlarıdır, o yüzden bekçiyi geçer."""
    shown: dict[str, dict] = {}
    for fact in _fact_dicts(facts):
        name = str(fact.get("name") or "")
        if name in _TEMPLATE_FACTS and name not in shown:
            shown[name] = fact
    parts = [f"{shown[name].get('label')} {shown[name].get('display')}." for name in _TEMPLATE_FACTS if name in shown]
    if not parts:
        return _NO_NUMBER
    if len(parts) == 1:
        # ASSUMPTION: sayısal olgu yoksa şablon ne sorulduğunu gösterir; sorunun kendi sayıları
        # bekçinin izin listesinde zaten vardır (PLAN R5-8), o yüzden cümleye taşımak güvenlidir.
        parts.append(f"Soru: {(question or '').strip()}")
    return " ".join(parts)


def _messages(question, columns, rows, facts, max_rows) -> list[dict]:
    """Anlatıcıya verilen her şey tek kullanıcı mesajında: soru, kolonlar, satırlar ve olgular."""
    shown = list(rows[:max_rows])
    header = f"SATIRLAR (ilk {len(shown)} / {len(rows)}):" if len(shown) < len(rows) else "SATIRLAR:"
    lines = [
        f"Soru: {question}",
        "",
        f"KOLONLAR: {', '.join(columns)}",
        header,
        *(_row_text(row) for row in shown),
        "",
        "GERÇEKLER:",
        json.dumps(_fact_dicts(facts), ensure_ascii=False),
    ]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


def _row_text(row) -> str:
    return " | ".join(_cell_text(cell) for cell in row)


def _cell_text(value) -> str:
    """Hücrenin anlatıcıya gösterimi: sayı Türkçe okunuşuyla ki kopyaladığı sayı bekçiyi geçsin."""
    if value is None:
        return fmt.NULL_TEXT
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return str(value)
    return fmt.tr_number(value)


def _fact_dicts(facts) -> list[dict]:
    """Olgular hem Fact nesnesi hem payload sözlüğü olabilir; anlatıcı düz JSON görür."""
    return [fact.to_dict() if hasattr(fact, "to_dict") else dict(fact) for fact in facts or []]

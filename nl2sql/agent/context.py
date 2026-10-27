"""Bir turun sonraki tura miras bıraktığı kadarı (PLAN R7-3, Contracts "TurnSummary").

Konuşmanın bağlamı sonuçların tamamı değil, modelin bir sonraki soruyu anlaması için gereken
kadarıdır: kolon adları, satır sayısı, maskelenmiş en fazla ``CONV_KEEP_ROWS`` satır ve olgular.
Satırlar yürütücünün maskesini olduğu gibi taşır - burada maske yeniden hesaplanmaz, ham bir pii
değeri bir daha hiçbir yere yazılmaz. Grafikten yalnız türü kalır; option'ın kendisi konuşmaya
girmez.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from nl2sql import config
from nl2sql.agent.budget import estimate_prompt
from nl2sql.i18n import t
from nl2sql.index.text import fold, tokens

HISTORY_HEADER = "## Önceki turlar"
ROW_SEPARATOR = " | "
ROW_INDENT = "  "

_LABEL_CUT = re.compile(r"[;,.:(\n]")

FOLLOWUP_RULES = (
    "Kurallar:\n"
    '- "bu / bunlar / o müşteri / aynı dönem / sadece X / bunu" gibi ifadeleri bu turlardan çöz.\n'
    "- Kullanıcı bir raporu daraltıyorsa önceki turun SQL'ini başlangıç al, sıfırdan yazma.\n"
    "- Her sayı bu turun SQL'inden gelir; önceki turlardaki bir sayıyı cevaba kopyalama.\n"
    "- submit_sql'in context alanını doldur: hangi turları kullandığını ve gördüğün değerleri yaz."
)


def turn_summary(payload: dict) -> dict:
    """AskPayload'ı ``summary_json``a yazılacak öze indirir (Contracts "TurnSummary").

    ``context`` yalnız konuşma deposuyla koşan bir payloadda vardır, yoksa None kalır (Contracts
    "ContextNote"). Özet bir başka modülün sözlüğünden kurulduğu için anahtarlar ``get`` ile
    okunur: eksik bir alan ekranda ya da toplamda NaN/undefined olacağına boş kalır.
    """
    chart = payload.get("chart")
    return {
        "columns": payload.get("columns", []),
        "row_count": payload.get("row_count", 0),
        "rows": [[_cell(cell) for cell in row] for row in payload.get("rows", [])[: config.CONV_KEEP_ROWS]],
        "facts": payload.get("facts", []),
        "chart_kind": chart.get("type") if chart else None,
        "context": payload.get("context"),
        "clarification": payload.get("clarification"),
    }


def _cell(value):
    """JSONa yazılabilir hücre: Decimal ve tarih metne döner, başkası olduğu gibi kalır.

    Maskeli bir hücre çoktan metindir, o yüzden buradan ham haliyle değil yürütücünün maskesiyle
    geçer.
    """
    if isinstance(value, (Decimal, date)):
        return str(value)
    return value


def followup_hints(question: str, schema: dict) -> dict:
    """Soru kendi başına mı okunuyor, yoksa önceki tura mı bağlı (PLAN R7-11).

    ``markers`` ``FOLLOWUP_MARKERS`` ile İngilizce ikizleri ``FOLLOWUP_MARKERS_EN``da soruda
    geçtiği sırayla duranlar - katlanmış tam kelime eşitliği, "Ortalama" içindeki "o" işaret
    sayılmaz. ``table_noun`` sorunun bir tabloyu adlandırdığını söyler; işaret varsa ama tablo adı
    yoksa soru tek başına okunamıyordur. Katlama indeksle aynı ``fold``'dan geçer, aksi halde
    "Müşteri" ile "müşteri" ayrışırdı.
    """
    words = tokens(question)
    markers = [
        word
        for word in words
        if word in config.FOLLOWUP_MARKERS or word in config.FOLLOWUP_MARKERS_EN
    ]
    nouns = _table_words(schema)
    return {
        "markers": list(dict.fromkeys(markers)),
        "table_noun": any(word in nouns for word in words),
    }


def _table_words(schema: dict) -> set[str]:
    """Tabloyu adlandıran katlanmış kelimeler: ad parçaları, anahtar kelimeler, tanımın başı."""
    words: set[str] = set()
    for table in (schema or {}).get("tables", []):
        words.update(tokens(table.get("name", "")))
        words.update(fold(keyword) for keyword in table.get("keywords", []))
        # tanımdan yalnız ilk kelime: tamamı "detail", "group" gibi genel sözcükleri de sokardı
        words.update(tokens(table.get("description", ""))[:1])
    return words


def context_block(turns: list[dict] | None, hints: dict | None, refine: str | None = None) -> str:
    """Önceki turların system mesajına düşen bölümü (PLAN R7-4, Contracts "history turn").

    Her tur kendi sorusu, SQL'i, kolon adları ve en fazla ``CONV_KEEP_ROWS`` maskeli satırı ile
    yazılır; altındaki iki ipucu satırı sırasıyla ``followup_hints``ın sonucunu modelin diline
    çevirir ve ``refine_hint``ın tek satırını taşır (R7-11 - bloğun üretebileceği soru ikisinin de
    elinde değildir), en altta netleştirme kuralları durur. Satırlar özetten geldiği gibi basılır -
    ham pii burada yeniden üretilmez, yürütücünün maskesi zaten özetin içindedir.
    """
    lines = [HISTORY_HEADER]
    for turn in turns or []:
        lines += _turn_lines(turn)
    lines.append(_hint_line(hints))
    if refine:
        lines.append(refine)
    lines.append(FOLLOWUP_RULES)
    return "\n".join(lines)


def fit_history(
    turns: list[dict], messages: list[dict], tools: list[dict] | None, budget: int | None
) -> tuple[int, int, int]:
    """Geçmişi bütçeye sığdırır: (kalan tur, atlanan satır, tahmin) (PLAN R7-4).

    ``turns`` yerinde kısalır - en eski tur düşer, sonra kalan turların satırları eksilir - böylece
    çağıran dönen sayı kadar turu olduğu gibi ``context_block``a verir. ``messages`` değişmez:
    tahmin, bloğun system mesajının sonuna eklendiği transkript üzerinden ölçülür, yani kullanıcının
    çıplak sorusu hiçbir kesimin içine girmez. ``budget`` None ise her şey kalır. Bütçe çıplak
    prompt'a bile yetmiyorsa tur kalmaz ve tahmin bütçenin üstünde döner; kararı çağıran verir.

    ASSUMPTION: kesim sırası PLAN R7-4ün sırasıyla okundu - önce en eski turun tamamı, sonra kalan
    turların satırları; satırlar bitince sıradaki en eski tur düşer.
    """
    turns = turns if turns is not None else []
    estimate = _estimate(messages, turns, tools)
    if budget is None:
        return len(turns), 0, estimate

    rows_dropped = 0
    turn_dropped = False
    while estimate > budget:
        if turns and not turn_dropped:
            del turns[0]
            turn_dropped = True
        elif _drop_row(turns):
            rows_dropped += 1
        elif turns:
            del turns[0]
        else:
            break
        estimate = _estimate(messages, turns, tools)
    return len(turns), rows_dropped, estimate


def _turn_lines(turn: dict) -> list[str]:
    """Bir turun dört satırı ve altında örnek satırları; çok satırlı SQL tek satıra iner."""
    summary = turn.get("summary") or {}
    rows = (summary.get("rows") or [])[: config.CONV_KEEP_ROWS]
    n = turn.get("n")
    columns = ROW_SEPARATOR.join(_text(column) for column in summary.get("columns") or [])
    lines = [
        f"Tur {n} sorusu: {_line(turn.get('question'))}",
        f"Tur {n} SQL: {_line(turn.get('sql'))}",
        f"Tur {n} kolonlar: {columns}",
        f"Tur {n} satırlar ({len(rows)} / {summary.get('row_count', 0)}):",
    ]
    lines += [ROW_INDENT + ROW_SEPARATOR.join(_text(cell) for cell in row) for row in rows]
    return lines


def _hint_line(hints: dict | None) -> str:
    """İşaretlerin modelce okunabilir hali: işaret yoksa soru kendi başına da okunabilir."""
    hints = hints or {}
    markers = hints.get("markers") or []
    if not markers:
        if hints.get("table_noun"):
            return "İpucu: soru tek başına da okunabilir; bir tabloyu adlandırıyor, önceki turlara bağlı olmak zorunda değil."
        return "İpucu: soru önceki turlardan birine bağlanıyor olabilir; öyleyse onu bu turlardan çöz."
    bound = "tablo adı da geçiyor." if hints.get("table_noun") else "tablo adı geçmiyor, soru tek başına okunmaz."
    return f"İpucu: soruda önceki tura bağlanan {', '.join(markers)} var; {bound}"


def _estimate(messages: list[dict], turns: list[dict], tools: list[dict] | None) -> int:
    """Bloğun system mesajının sonunda durduğu transkriptin tahmini; mesajlara dokunmaz.

    Ölçüm ``context_block(turns, None)`` ile yapılır: ipucu satırının uzunluğu işaretlerin sayısına
    göre bir iki token oynar, kesim kararı o kadar ince değil.
    """
    block = context_block(turns, None) if turns else ""
    probe = list(messages)
    for index, message in enumerate(probe):
        if message.get("role") == "system":
            content = message.get("content") or ""
            probe[index] = {**message, "content": f"{content}\n\n{block}" if block else content}
            return estimate_prompt(probe, tools)
    if block:
        probe.insert(0, {"role": "system", "content": block})
    return estimate_prompt(probe, tools)


def _drop_row(turns: list[dict]) -> bool:
    """Gösterilen en eski turun son satırını düşürür: en eski kanıt en son kaybedilir."""
    for turn in turns:
        summary = turn.get("summary") or {}
        rows = summary.get("rows") or []
        if not rows:
            continue
        # gösterim sınırı zaten CONV_KEEP_ROWS: fazlası bloğa hiç girmediği için kesmek bir şey eksiltmezdi
        shown = rows[: config.CONV_KEEP_ROWS]
        turn["summary"] = {**summary, "rows": shown[:-1]}
        return True
    return False


def _line(value) -> str:
    """Bloğun satır düzenini bozmayan tek satırlık metin."""
    return " ".join(str(value or "").split())


def _text(value) -> str:
    return "" if value is None else str(value)


def _name(value) -> str:
    """Teknik ad karşılaştırması: düz küçültme.

    ``fold`` Türkçe katlar, o yüzden "ADI" "adı", "ID" "ıd" olur; büyük/küçük harf farkı aynı
    kolonun adı olduğu için burada kaybolmalı, başka bir kolona dönüşmemeli.
    """
    return str(value or "").strip().lower()


def validate_note(note: dict | None, turns: list[dict] | None) -> tuple[dict | None, str | None]:
    """Modelin ``submit_sql.context`` notunu kanıtla doğrular (PLAN R7-5, Contracts "ContextNote").

    Not ya olduğu gibi kalır ya da tamamı düşer: ``evidence_line``ın gösterdiği her değer konuşmanın
    kendi satırlarında ya da SQL'inde bulunabilmeli, uydurma bir değer kullanıcıya kanıt diye
    verilmemeli. Eksik ya da None not geçersiz değildir - kendi başına duran bir sorunun boş notudur.
    """
    note = note or {}
    known = {turn.get("n"): turn for turn in turns or []}
    uses = note.get("uses_turns") or []
    entities = note.get("entities") or []
    refines = note.get("refines_sql_of")
    if not isinstance(uses, list) or not isinstance(entities, list):
        return None, "uses_turns ve entities liste olmalı"
    for number in uses:
        if not isinstance(number, int) or number not in known:
            return None, f"{number}. tur bu konuşmada yok"
    if refines is not None and refines not in uses:
        return None, "refines_sql_of kullanılan turlarda değil"
    for entity in entities:
        reason = _entity_reason(entity, [known[number] for number in uses])
        if reason:
            return None, reason
    return {
        "uses_turns": list(uses),
        "entities": [{"column": _text(item.get("column")), "value": _text(item.get("value"))} for item in entities],
        "refines_sql_of": refines,
    }, None


def evidence_line(
    note: dict | None, turns: list[dict] | None, schema: dict | None, lang: str = "tr"
) -> str | None:
    """Kullanıcıya gösterilen tek satırlık kanıt: hangi turun hangi değeri (PLAN R7-5).

    Satırın cümleleri ``context.evidence.*`` anahtarlarının ``lang``deki metnidir. Etiket
    şemadaki açıklamanın başıdır - teknik kolon adı ekrana çıkmaz, açıklama yoksa ``lang``in
    genel etiketi kalır. Parantez değerin bulunduğu satırın diğer metin hücresi, yani kaydın adı;
    değer yalnız SQL'de geçiyorsa parantez olmaz. Varlık yoksa kanıtın kendisi önceki sorgudur.
    """
    note = note or {}
    entities = [item for item in (note.get("entities") or []) if isinstance(item, dict)]
    if not entities:
        number = note.get("refines_sql_of") or (note.get("uses_turns") or [None])[0]
        if number is None:
            return None
        return t("context.evidence.prefix", lang) + t("context.evidence.query", lang, n=number)
    used = _used_turns(note, turns)
    parts = []
    for entity in entities:
        value = _text(entity.get("value"))
        part = f"{_column_label(schema, _text(entity.get('column')), lang)} {value}"
        other = _row_hint(used, value)
        parts.append(f"{part} ({other})" if other else part)
    return t("context.evidence.prefix", lang) + ", ".join(parts)


def _entity_reason(entity, used_turns: list[dict]) -> str | None:
    """Bir varlığın kanıtı: kolon kullanılan turun kolonlarında, değer onun satırlarında ya da SQL'inde."""
    if not isinstance(entity, dict):
        return "varlık bir nesne değil"
    column = _text(entity.get("column")).strip()
    value = _text(entity.get("value")).strip()
    if not column or not value:
        return "varlığın kolonu ya da değeri boş"
    named = [turn for turn in used_turns if _has_column(turn, column)]
    if not named:
        return f"{column} kolonu kullanılan turlarda yok"
    if not any(_shows(turn, fold(value)) for turn in named):
        return f"{value} değeri kullanılan turun satırlarında ya da sorgusunda yok"
    return None


def _has_column(turn: dict, column: str) -> bool:
    """Kolon turun başlıklarında mı - büyük/küçük harf farkı aynı kolonun adıdır."""
    name = _name(column)
    return any(_name(item) == name for item in (turn.get("summary") or {}).get("columns") or [])


def _shows(turn: dict, folded_value: str) -> bool:
    """Katlanmış değer turun gösterdiği satırlardan birinde ya da SQL'inde geçiyor mu."""
    summary = turn.get("summary") or {}
    rows = (summary.get("rows") or [])[: config.CONV_KEEP_ROWS]
    if any(folded_value in fold(_text(cell)) for row in rows for cell in row):
        return True
    return folded_value in fold(_text(turn.get("sql")))


def _used_turns(note: dict, turns: list[dict] | None) -> list[dict]:
    """Notın kullandığını söylediği turlar; sayı verilmemişse gösterilen turların tümü."""
    known = {turn.get("n"): turn for turn in turns or []}
    used = [known[number] for number in (note.get("uses_turns") or []) if isinstance(number, int) and number in known]
    return used or [turn for turn in turns or []]


def _row_hint(turns: list[dict], value: str) -> str | None:
    """Değerin bulunduğu satırın diğer metin hücresi: parantezdeki kayıt adı."""
    folded = fold(value)
    for turn in turns:
        rows = ((turn.get("summary") or {}).get("rows") or [])[: config.CONV_KEEP_ROWS]
        for row in rows:
            if not any(folded in fold(_text(cell)) for cell in row):
                continue
            for cell in row:
                if isinstance(cell, str) and cell.strip() and folded not in fold(cell):
                    return cell
    return None


def _column_label(schema: dict | None, column: str, lang: str) -> str:
    """Kolonun ekrandaki adı: açıklamanın başı, cümle içinde küçükle başlar; teknik ad asla."""
    name = _name(column)
    for table in (schema or {}).get("tables", []):
        for item in table.get("columns", []):
            if _name(item.get("name")) != name:
                continue
            head = _description_head(item.get("description"))
            # yalnız baş harf küçülür: İngilizce açıklamadaki "ID" "ıd" olmasın
            return fold(head[:1]) + head[1:] if head else t("context.evidence.label", lang)
    return t("context.evidence.label", lang)


def _description_head(description) -> str:
    """Açıklamanın etiket olarak duracak ilk bölümü: nokta, virgül, iki nokta ya da paranteze kadar."""
    return _LABEL_CUT.split(str(description or "").strip(), maxsplit=1)[0].strip()

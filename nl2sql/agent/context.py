"""Bir turun sonraki tura miras bıraktığı kadarı (PLAN R7-3, Contracts "TurnSummary").

Konuşmanın bağlamı sonuçların tamamı değil, modelin bir sonraki soruyu anlaması için gereken
kadarıdır: kolon adları, satır sayısı, maskelenmiş en fazla ``CONV_KEEP_ROWS`` satır ve olgular.
Satırlar yürütücünün maskesini olduğu gibi taşır - burada maske yeniden hesaplanmaz, ham bir pii
değeri bir daha hiçbir yere yazılmaz. Grafikten yalnız türü kalır; option'ın kendisi konuşmaya
girmez.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nl2sql import config
from nl2sql.agent.budget import estimate_prompt
from nl2sql.index.text import fold, tokens

HISTORY_HEADER = "## Önceki turlar"
ROW_SEPARATOR = " | "
ROW_INDENT = "  "

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

    ``markers`` ``FOLLOWUP_MARKERS``da soruda geçtiği sırayla duranlar - katlanmış tam kelime
    eşitliği, "Ortalama" içindeki "o" işaret sayılmaz. ``table_noun`` sorunun bir tabloyu
    adlandırdığını söyler; işaret varsa ama tablo adı yoksa soru tek başına okunamıyordur.
    Katlama indeksle aynı ``fold``'dan geçer, aksi halde "Müşteri" ile "müşteri" ayrışırdı.
    """
    words = tokens(question)
    markers = [word for word in words if word in config.FOLLOWUP_MARKERS]
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


def context_block(turns: list[dict] | None, hints: dict | None) -> str:
    """Önceki turların system mesajına düşen bölümü (PLAN R7-4, Contracts "history turn").

    Her tur kendi sorusu, SQL'i, kolon adları ve en fazla ``CONV_KEEP_ROWS`` maskeli satırı ile
    yazılır; altındaki ipucu satırı ``followup_hints``ın sonucunu modelin diline çevirir, en altta
    netleştirme kuralları durur. Satırlar özetten geldiği gibi basılır - ham pii burada yeniden
    üretilmez, yürütücünün maskesi zaten özetin içindedir.
    """
    lines = [HISTORY_HEADER]
    for turn in turns or []:
        lines += _turn_lines(turn)
    lines.append(_hint_line(hints))
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

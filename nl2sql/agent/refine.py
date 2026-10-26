"""Sohbette model koşmadan çözülen istekler (PLAN R7-10).

Kullanıcı bazen yeni bir cevap istemez, gördüğü cevabın sunumunu değiştirir: "Grafiği çubuk yap".
Böyle bir soru agent'a giderse aynı sorgu baştan kurulur ve uydurma sayı riski yeniden doğar; oysa
tek gereken önceki turun SQL'ini olduğu gibi yeniden koşup grafiğin türünü değiştirmektir.
``chart_only`` bu eşiği deterministik olarak ayırt eder: soru yalnızca bir grafik isteğinden ibaretse
istenen türü döner, içinde yeni bir bilgi barındırıyorsa None.

Modeli koşurmamanın ikinci yolu şık sormaktır (PLAN R7-12): "Bu müşteriye başka ne sattık?" tek
başına çözülmez, cevabı da modelden değil kullanıcıdan gelir. ``ambiguous_entity`` bunu da
deterministik olarak ayırt eder ve şıklarını kendisi kurar.
"""

from __future__ import annotations

from nl2sql import config
from nl2sql.index.text import fold, tokens

# R7-10: soruda geçerse anlaşılan grafik türü. Sözlük sırası, iki istek birden geçerse hangisinin
# kazanacağını da söyler.
CHART_WISHES = {
    "line": ("çizgi", "line", "trend"),
    "bar": ("çubuk", "sütun", "bar"),
    "pie": ("pasta", "dilim", "pie"),
    "table": ("tablo", "tablo olarak"),
}

# İsteğin etrafındaki dolgu: "grafiği ... yap/göster/çevir", "olarak", "olsun", "lütfen".
CHART_FILLERS = ("grafik", "grafiği", "göster", "yap", "çevir", "olarak", "olsun", "lütfen")

# İstek, dolgu ve önceki tura bağlayan işaretler düşünce geriye bir şey kalmıyorsa soru yeni bir
# şey sormuyordur - sunum dışında.
_NOTHING_LEFT = (
    {word for wishes in CHART_WISHES.values() for wish in wishes for word in wish.split()}
    | set(CHART_FILLERS)
    | set(config.FOLLOWUP_MARKERS)
)

# R7-12: ardışık sorunun işaret edebildiği varlıklar. Anahtar Türkçe sözcük - soruda ve şıkkın
# cümlesinde o geçer; değerler son turun kolon adlarında ve şemadaki açıklamalarında aranır.
ENTITY_NOUNS = {
    "müşteri": ("customer", "müşteri", "cari"),
    "ürün": ("stockitem", "product", "ürün", "stok"),
    "tedarikçi": ("supplier", "tedarikçi"),
    "fatura": ("invoice", "fatura"),
}

# Tekil işaret zamirleri: "bunlar / onlar" birden çok varlığa işaret eder, o yüzden tek bir varlık
# sorulamaz - çoğulları FOLLOWUP_MARKERSda kalır, burada yalnız tekilleri sayılır.
ENTITY_MARKERS = ("bu", "şu", "o")

# Şıkkın soracağı cümle: Türkçe hal eki kurala değil sözlüğe sığar.
ENTITY_QUESTIONS = {
    "müşteri": "Hangi müşteriyi kastediyorsunuz?",
    "ürün": "Hangi ürünü kastediyorsunuz?",
    "tedarikçi": "Hangi tedarikçiyi kastediyorsunuz?",
    "fatura": "Hangi faturayı kastediyorsunuz?",
}


def chart_wish(question: str) -> str | None:
    """Soruda geçen grafik türü isteği: "line"|"bar"|"pie"|"table", hiç yoksa None."""
    words = tokens(question or "")
    for kind, wishes in CHART_WISHES.items():
        if any(_mentions(words, tokens(wish)) for wish in wishes):
            return kind
    return None


def chart_only(question: str, turns: list[dict] | None) -> str | None:
    """Soru yalnızca son cevabın sunumunu mu değiştiriyor: istenen tür, yoksa None (PLAN R7-10).

    Eşik üç koşulun kesişimi: soruda bir istek var, yeniden koşulacak SQL'i bırakmış yanıtlanmış
    bir tur var, ve istekle dolgu ve işaretler düşünce soruda yeni bir bilgi kalmıyor. Kalan tek bir
    kelime bile ("Sadece Texas, çubuk grafik"taki "Texas") sorunun agent'a dönmesini söyler - orada
    sunum değil veri değişiyordur.
    """
    kind = chart_wish(question)
    if kind is None or _last_answered(turns) is None:
        return None
    return kind if all(word in _NOTHING_LEFT for word in tokens(question)) else None


def ambiguous_entity(question: str, turns: list[dict] | None, schema: dict | None) -> dict | None:
    """Soru tekil bir işaretyle son cevabın çok değerli bir kolonuna mı bakıyor (PLAN R7-12).

    "Bu müşteriye başka ne sattık?" tek başına çözülmez: son turun satırlarında beş farklı cari
    kodu varsa hangisinin kastedildiğini yalnız kullanıcı bilir, model tahmin ederse uydurur - o
    yüzden soru modelden önce burada sorulur. Eşik üç koşulun kesişimi: soruda tekil zamir ve bir
    varlık sözcüğü geçiyor, son yanıtlanmış turun kolonlarından biri o varlığın sözlüğüyle
    eşleşiyor, o kolonun gösterilen satırlarda en az iki farklı değeri var. Tek değer bellidir,
    çoğul zamir ("bunlar") tek bir varlığı sormayı gerektirmez - ikisinde de None.

    Dönüş ``needs_clarification``ın kendisidir: ``{"question", "options", "column"}``. ``column``
    şıkkın hangi kolonun değeri olduğunu söyler ve turda dolaşır, böylece seçim bağlam notunun
    varlığı olur - değeri kod yazar, model değil.
    """
    turn = _last_answered(turns)
    if turn is None:
        return None
    noun = _entity_noun(tokens(question or ""))
    if noun is None:
        return None
    column = _entity_column(turn, noun, schema)
    if column is None:
        return None
    rows = _entity_rows(turn, column)
    if len(rows) < 2:
        return None
    return {
        "question": ENTITY_QUESTIONS[noun],
        "options": [f"{value} ({name})" if name else value for value, name in rows],
        "column": column,
    }


def _entity_noun(words: list[str]) -> str | None:
    """Varlığın adı: tekil zamirle birlikte geçen varlık sözcüğü; ek almış hali de aynı sözcüktür."""
    words = [_loose(word) for word in words]
    if not any(word in ENTITY_MARKERS for word in words):
        return None
    for noun, aliases in ENTITY_NOUNS.items():
        prefixes = [prefix for prefix in (_loose(alias) for alias in aliases) if prefix]
        if any(word.startswith(prefix) for word in words for prefix in prefixes):
            return noun
    return None


def _entity_column(turn: dict, noun: str, schema: dict | None) -> str | None:
    """Varlığın kolonu: turun kolon adlarından ya da şemadaki açıklamasından eşanlamlıyı taşıyan ilki."""
    aliases = [_loose(alias) for alias in ENTITY_NOUNS[noun]]
    descriptions = _descriptions(schema)
    for column in (turn.get("summary") or {}).get("columns") or []:
        name = _loose(column)
        if any(alias in f"{name} {descriptions.get(name, '')}" for alias in aliases):
            return str(column)
    return None


def _descriptions(schema: dict | None) -> dict[str, str]:
    """Kolon adının şemadaki açıklaması: ad ASCII kısaltmayla duruyorsa varlık sözcüğü burada geçer."""
    found: dict[str, str] = {}
    for table in (schema or {}).get("tables", []):
        for column in table.get("columns", []):
            name = _loose(column.get("name"))
            if name:
                found.setdefault(name, _loose(column.get("description")))
    return found


def _entity_rows(turn: dict, column: str) -> list[tuple[str, str]]:
    """Kolonun gösterilen satırlardaki farklı değerleri ve yanlarındaki ad: (değer, ad) sırasıyla."""
    summary = turn.get("summary") or {}
    columns = summary.get("columns") or []
    if column not in columns:
        return []
    index = columns.index(column)
    rows: list[tuple[str, str]] = []
    for row in (summary.get("rows") or [])[: config.CONV_KEEP_ROWS]:
        if index >= len(row) or row[index] is None or not str(row[index]).strip():
            continue
        value = str(row[index])
        if not any(value == seen for seen, _ in rows):
            rows.append((value, _row_name(row, index)))
    return rows


def _row_name(row: list, index: int) -> str:
    """Satırın değer dışındaki ilk dolu metin hücresi: şıkkın parantezindeki kayıt adı."""
    for n, cell in enumerate(row):
        if n != index and isinstance(cell, str) and cell.strip():
            return cell.strip()
    return ""


def _loose(value) -> str:
    """Yumuşak katlama: ı ile i aynı sayılır - BÜYÜK HARFLİ kolon adlarında "I" ikisinin de yazımı."""
    return fold(str(value or "")).replace("ı", "i")


def _last_answered(turns: list[dict] | None) -> dict | None:
    """Son yanıtlanmış tur: yeni sorgu kurulmayacaksa takılacak tek yer orası.

    ``last_turns``tan gelen turlar yalnız yanıtlıları taşır, o yüzden ``status`` alanları yoktur;
    konuşma deposundan olduğu gibi okunan turlarda "answered" olanı sayılır.
    """
    for turn in reversed(list(turns or [])):
        if turn.get("status", "answered") == "answered" and turn.get("sql"):
            return turn
    return None


def _mentions(words: list[str], phrase: list[str]) -> bool:
    """İfadeli isteğin ("tablo olarak") bitişik geçtiği bir yer var mı."""
    return any(words[i : i + len(phrase)] == phrase for i in range(len(words) - len(phrase) + 1))

"""Sohbette model koşmadan çözülen istekler (PLAN R7-10).

Kullanıcı bazen yeni bir cevap istemez, gördüğü cevabın sunumunu değiştirir: "Grafiği çubuk yap".
Böyle bir soru agent'a giderse aynı sorgu baştan kurulur ve uydurma sayı riski yeniden doğar; oysa
tek gereken önceki turun SQL'ini olduğu gibi yeniden koşup grafiğin türünü değiştirmektir.
``chart_only`` bu eşiği deterministik olarak ayırt eder: soru yalnızca bir grafik isteğinden ibaretse
istenen türü döner, içinde yeni bir bilgi barındırıyorsa None.
"""

from __future__ import annotations

from nl2sql import config
from nl2sql.index.text import tokens

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

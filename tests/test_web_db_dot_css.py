# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T459: telefon başlığında veritabanı noktasının kendi sözcüğü kalır (M25 görsel inceleme 4).

`.db-status .db-label { display: none }` dar ekranda 10px'lik bir halkayı modelin yeşil noktasının
yanına bırakıyordu: her telefon ekranı "○ ● Hazır" okunuyor — iki nokta, tek sözcük
(landing-empty-state-390.png, users-screen-390.png, rules-screen-validation-390.png). O ölçüde
`none`ın boş halkası ile `unknown`ın gri dolgusu aynı iz; yalnız `down` bir şey söylüyor, o da
banttan. Sözcük tam hâliyle de satıra sığmıyor, o yüzden dar ekranda kısaltması yazılıyor.
İddia kaynak CSS'te kurulur: ölçülen yazarın niyeti, küçültücünün metni değil.
"""

import re

from bilgin import config

STYLES = config.WEB_DIR / "src" / "styles.css"

# Görsel incelemede iki noktanın ayırt edilemediği genişlik.
PHONE_PX = 390

LABEL = ".db-status .db-label"
SHORT = f"{LABEL}::after"
NONE_DOT = ".db-status .db-dot-none"
UNKNOWN_DOT = ".db-dot-unknown"

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def media_spans(css: str) -> list[tuple[str, int, int]]:
    """(koşul, gövde başı, gövde sonu): küme derinliği sayılır, media bloğunun içi kural taşır."""
    spans = []
    for match in re.finditer(r"@media([^{]*)\{", css):
        depth = 0
        for index in range(match.end() - 1, len(css)):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
                if depth == 0:
                    spans.append((match.group(1).strip(), match.end(), index))
                    break
        else:
            raise AssertionError(f"{STYLES.name}: eşleşmeyen süslü parantez")
    return spans


def upper_bound(condition: str) -> int | None:
    """Koşulun üst sınırı px olarak; alt sınırlı (min-width) koşullar telefon için işlemez."""
    match = re.search(r"max-width:\s*(\d+)px", condition)
    return int(match.group(1)) if match else None


def phone_bodies(css: str) -> list[str]:
    """Telefon genişliğinde gerçekten işleyen bloklar: üst sınırı telefon genişliğinden dar değil."""
    bodies = [
        css[start:end]
        for condition, start, end in media_spans(css)
        if (bound := upper_bound(condition)) is not None and bound >= PHONE_PX
    ]
    assert bodies, f"{STYLES.name} içinde {PHONE_PX}px'e inen bir max-width bloğu yok"
    return bodies


def base_css(css: str) -> str:
    """Media sorgularından arınmış kısım: ekran genişliğinden bağımsız temeller."""
    keep, cursor = [], 0
    for _, start, end in media_spans(css):
        keep.append(css[cursor : start - 1])
        cursor = end + 1
    keep.append(css[cursor:])
    return "".join(keep)


def rules(css: str) -> list[tuple[list[str], dict[str, str]]]:
    """Yaprak kurallar: (seçiciler, bildirimler). Küme işareti taşımadığı için @-başlıklar sayılmaz."""
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for chunk in match.group(2).split(";"):
            prop, sep, value = chunk.partition(":")
            if sep:
                decls[prop.strip().lower()] = " ".join(value.split()).lower()
        selectors = [part.strip() for part in match.group(1).split(",") if part.strip()]
        out.append((selectors, decls))
    return out


def effective(selector: str) -> dict[str, str]:
    """Telefon genişliğinde kazanan bildirimler: temeller, sonra işleyen media blokları, sıra ile."""
    won: dict[str, str] = {}
    for body in [base_css(CSS), *phone_bodies(CSS)]:
        for selectors, decls in rules(body):
            if selector in selectors:
                won.update(decls)
    return won


# ------------------------------------------------------------------ dar ekran


def test_the_phone_keeps_a_word_next_to_the_dot():
    """Nokta dar ekrada adını taşımak zorunda: `display: none` iki durumu birbirine karıştıran
    şeydi — modelin yeşil noktasının yanında anlamı olmayan bir iz kalıyordu."""
    label = effective(LABEL)
    assert label.get("display", "inline") != "none", f"{LABEL} hâlâ gizli: {label}"


def test_the_word_written_for_the_phone_is_the_short_form():
    """Tam ad üst satırın payını veri seti çipinin üstüne çıkarıyor ("Veritabanı" + "Bilinmiyor"),
    o yüzden dar ekranda okunan sözcük kısaltmadır: öğenin kendi sözcüğü sıfıra iner, ardına
    kısa hâl yazılır. Yeni işarete ihtiyaç yok — aynı öğe, başka metin."""
    label = effective(LABEL)
    short = effective(SHORT)
    assert label.get("font-size") == "0", (
        f"{LABEL} tam sözcüğünü boyamaya devam ediyor: {label}"
    )
    assert "content" in short, f"{LABEL}::after kısa sözcüğü nerede yazıyor: {short}"
    word = short["content"].strip("\"'")
    assert word and len(word) <= 4, f"kısa hâl {word!r} kısaltma değil: {short['content']}"


def test_the_status_cluster_stays_on_one_line():
    """Küme iki satıra inerse başlığın üst çizgisi kabarıyor: nokta ile sözcük tek satırda
    durduğunu kendisi söylemeli (temel nowrap'ı dar ekranda kaybetmemeli)."""
    cluster = effective(".db-status")
    assert cluster.get("white-space") == "nowrap", f".db-status satırı yazılmamış: {cluster}"


def test_the_two_grey_states_stay_distinguishable():
    """İki gri ton 10px'te renk ile ayrılmıyor: `none` halka, `unknown` dolgu taşır. İkisi de
    aynı iz olursa telefon ekranında "bağlantısı olmayan küme" ile "henüz ölçülmemiş" okunmaz."""
    none = effective(NONE_DOT)
    unknown = effective(UNKNOWN_DOT)
    assert "box-shadow" in none, f"{NONE_DOT} halkasını yitirmiş: {none}"
    assert none.get("background") == "transparent", f"{NONE_DOT} dolgulu: {none}"
    assert unknown.get("background", "none") not in ("none", "transparent"), (
        f"{UNKNOWN_DOT} dolgusuz, halkasız gri bir iz: {unknown}"
    )
    assert "box-shadow" not in unknown, f"{UNKNOWN_DOT} de halka taşıyor, iki ton aynı iz: {unknown}"

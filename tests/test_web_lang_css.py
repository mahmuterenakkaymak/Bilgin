# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T442: uzun etiket satırı taşırmasın (PLAN R8-17).

Telefon satırları Türkçe metne göre ölçüldü; iki dilli arayüzde İngilizcenin uzun adları aynı
kutuya sığmıyor: cevap kartının iş sırası ile haritanın adım listesi kendi kutularından geniş sözü
dışarı boyuyor, iki seçenekli dil düğmesi ise sarmaya kapalı olduğu için başlığın sütununu iki
seçeneğin toplamı kadar şişiriyor. İddia kaynak CSS'te kurulur - ölçülen yazarın niyeti,
küçültücünün metni değil. Telefon bildirimleri tek ``max-width`` bloğunun içinde kalmalı
(test_web_narrow_table ve test_web_table_css hepsini tarar) ve temelin aynı bildirimi taşımadığı
yerde satır küçülme hakkını üstlenmeli.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"
PHONE_PX = 720

# Görevin satırları ve dar ekranda kendilerinden beklenen bildirim: sıra payını kendine
# saklamıyor (min-width: 0), söz kendi içinde kırılıyor (overflow-wrap), grup bölünebiliyor.
WRAP = {
    ".masthead-nav": {"min-width": "0"},
    ".answer-actions": {"overflow-wrap": "anywhere"},
    ".map-steps": {"overflow-wrap": "anywhere"},
    "#lang-toggle": {"flex-wrap": "wrap", "min-width": "0"},
}

PX = re.compile(r"^\d+(?:\.\d+)?px$")

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """Yaprak kurallar: (seçiciler tek satır, bildirimler). Media kümelerinin içi de okunur."""
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for chunk in match.group(2).split(";"):
            prop, sep, value = chunk.partition(":")
            if sep:
                decls[prop.strip().lower()] = value.strip().lower()
        out.append((" ".join(match.group(1).split()), decls))
    return out


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


def base_css(css: str) -> str:
    """Media sorgularından arınmış kısım: ekran genişliğinden bağımsız temeller."""
    keep, cursor = [], 0
    for _condition, start, end in media_spans(css):
        keep.append(css[cursor:start])
        cursor = end
    keep.append(css[cursor:])
    return "".join(keep)


def parts(selector: str) -> list[str]:
    """Kuralın seçici listesi: ``.answer-actions, .map-steps`` iki parçadır, virgül payı değil."""
    return [part.strip().strip(",") for part in selector.split()]


def covers(token: str, name: str) -> bool:
    """Seçici parçası ``name`` mi ya da onun bir hâli: ``#lang-toggle`` evet, ``.lang-toggle``
    ve ``.map-step-n`` hayır - alt sınıf adları ayrı seçicidir."""
    return token == name or token.startswith(f"{name}[") or token.startswith(f"{name}:")


def merged(name: str, rules: list[tuple[str, dict[str, str]]]) -> dict[str, str]:
    """Bir seçicinin verilen kurallardaki son hâli: onu taşıyan her kuralın bildirimleri üstüne biner."""
    decls: dict[str, str] = {}
    for selector, rule in rules:
        if any(covers(part, name) for part in parts(selector)):
            decls.update(rule)
    return decls


RULES = parse_rules(CSS)
PHONE = [span for span in media_spans(CSS) if upper_bound(span[0]) is not None]


def test_the_single_narrow_block_is_still_the_only_one():
    """Telefon kuralları ikinci bir ``max-width`` bloğu açmaz: hepsi tek 720px bloğunda toplanır."""
    assert len(PHONE) == 1, (
        f"{STYLES.name} içinde {len(PHONE)} max-width bloğu var; telefon kuralları tek "
        f"{PHONE_PX}px bloğunda olmalı"
    )
    condition, _start, _end = PHONE[0]
    assert upper_bound(condition) == PHONE_PX, f"telefon bloğu {condition.strip()} - 720px olmalı"


def test_the_narrow_block_writes_the_wrap_rules():
    """Dört satırın her biri dar ekranda sarmayı/taşmamayı üstlenen bildirimi kendi bloğunda taşıyor."""
    body = parse_rules(CSS[PHONE[0][1] : PHONE[0][2]])
    for name, expected in WRAP.items():
        won = merged(name, body)
        for prop, value in expected.items():
            assert won.get(prop) == value, (
                f"{PHONE_PX}px bloğunda {name} için {prop}: {value} yok, geçen: {won.get(prop)!r}"
            )


def test_the_wrap_rules_are_not_outwritten_by_the_base():
    """Telefon istisnası istisna olarak kalmalı: aynı bildirimi temel de taşıyor ve bloğun
    altında duruyorsa eşit özgüllükte sıra kazanır, satır bildiğini okur."""
    base = parse_rules(base_css(CSS))
    for name, expected in WRAP.items():
        for prop in expected:
            for selector, decls in base:
                if any(covers(part, name) for part in parts(selector)):
                    assert prop not in decls, (
                        f"{name} için {prop} temelde de var ({selector}) - telefon kuralı onu yenmez"
                    )


def test_no_fixed_px_width_holds_those_rows():
    """Sabit px genişlik sarmayı iptal eder: payı yazılan satır küçülemez, taşıdığı söz kesilir."""
    for selector, decls in RULES:
        for name in WRAP:
            if not any(covers(part, name) for part in parts(selector)):
                continue
            width = decls.get("width", "")
            assert not PX.match(width), f"{name} için sabit genişlik yazılmış: {selector} — {width}"


def test_the_lang_toggle_keeps_its_look():
    """Dizilim değişirken T431'in düğme grubu bozulmaz: çerçeveli hap grup ve basınç hâli."""
    toggle = merged(".lang-toggle", RULES)
    assert toggle.get("display") == "inline-flex", f"dil düğmesi grup olmaktan çıkmış: {toggle}"
    for prop in ("border", "border-radius", "background"):
        assert prop in toggle, f".lang-toggle için {prop} yitirilmiş: {toggle}"
    pressed: dict[str, str] = {}
    for selector, decls in RULES:
        if '.lang-option[aria-pressed="true"]' in parts(selector):
            pressed.update(decls)
    assert pressed.get("background"), "seçili dilin zemini yok: hangisi etkin okunmuyor"

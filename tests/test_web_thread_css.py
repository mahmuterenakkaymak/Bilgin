# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T311: konuşma akışının görünümü (PLAN R7-15, R6-19).

Akışın bileşenleri T307-T310'da geldi (Thread.jsx, TurnCard.jsx, ConversationList.jsx,
Evidence.jsx) ama styles.css'te tek kuralı yoktu: soru balonu çıplak bir paragraf, katlanmış
tur çizgisiz bir blokti, bağlam satırı ile cevap aynı renkteydi. İddia kaynak CSS'te kurulur -
ölçülen yazarın niyeti, küçültücünün metni değil. Telefon bildirimleri tek ``max-width``
bloğunun içinde kalmalı, renkler token'lardan gelmeli; koyu tema o yüzden kendiliğinden uyar.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"
PHONE_PX = 720

# Görevin seçicileri: her biri bir kuralın seçicisinde çıplak olarak geçmeli.
SELECTORS = (
    "#thread",
    ".turn",
    ".turn-question",
    ".turn-collapsed",
    "#context-line",
    "#new-conversation",
    "#conversation-list",
)

# Bölümün öteki kuralları: renk taraması bunları da kapsıyor.
EXTRA = (".turn-table", ".turn-actions", ".turn-note", ".turn-close", ".turn-sentence")

HEX = re.compile(r"#[0-9a-f]{3,8}\b", re.IGNORECASE)

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """Yaprak kurallar: (seçiciler tek satır, bildirimler). Media kümelerinin içi de okunur.

    Gövde küme işareti taşımadığı için ``@media`` başlıkları kural sayılmaz; içlerindeki her
    kural kendi seçicisiyle ayrı satıra düşer.
    """
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


def covers(token: str, name: str) -> bool:
    """Seçici parçası ``name`` mi: ``.turn-collapsed[role="button"]`` onun bir hâlidir,
    ``.turn-table`` değildir - alt sınıf adları ayrı seçicidir."""
    return token == name or token.startswith(f"{name}[") or token.startswith(f"{name}:")


def selectors_with(name: str, rules: list[tuple[str, dict[str, str]]]) -> list[dict[str, str]]:
    return [decls for selector, decls in rules if any(covers(t, name) for t in selector.split())]


def merged(name: str, rules: list[tuple[str, dict[str, str]]] | None = None) -> dict[str, str]:
    """Bir seçicinin CSS'teki son hâli: onu taşıyan her kuralın bildirimleri sırayla üstüne biner."""
    decls: dict[str, str] = {}
    for rule in selectors_with(name, RULES if rules is None else rules):
        decls.update(rule)
    assert decls, f"{STYLES.name} içinde {name} kuralı yok"
    return decls


RULES = parse_rules(CSS)


def test_every_thread_selector_has_a_rule():
    for name in SELECTORS:
        merged(name)


def test_the_phone_rules_live_in_the_one_max_width_block():
    """Telefon kuralları ikinci bir ``max-width`` bloğu açmaz (test_web_narrow_table ve
    test_web_table_css hepsini tarar): tek 720px bloğunun içine yazılır."""
    narrow = [span for span in media_spans(CSS) if upper_bound(span[0]) is not None]
    assert len(narrow) == 1, (
        f"{STYLES.name} içinde {len(narrow)} max-width bloğu var; telefon kuralları tek "
        f"{PHONE_PX}px bloğunda toplanmalı"
    )
    condition, start, end = narrow[0]
    assert upper_bound(condition) == PHONE_PX, f"telefon bloğu {condition.strip()} - 720px olmalı"

    body = parse_rules(CSS[start:end])
    bubble = merged(".turn-question", body)
    assert bubble.get("max-width") == "none", "balon telefonda tüm genişliği almıyor"
    assert bubble.get("justify-self") == "stretch", "balon sağa yaslı kalınca genişlemiyor"
    wrap = {}
    for decls in selectors_with(".turn-table-wrap", body):
        wrap.update(decls)
    assert wrap.get("overflow-x") == "auto", "katlanmış turun tablosu kartın içinde kaymıyor"

    # Aynı bildirim temel tarafta duramaz: telefon istisnası istisna olarak kalmalı.
    base = parse_rules(base_css(CSS))
    for decls in selectors_with(".turn-question", base):
        assert decls.get("max-width") != "none", "telefon kuralı media bloğunun dışına taşmış"


def test_the_new_rules_take_their_colours_from_tokens():
    """Sabit renk koyu temayı ezdiği için bölümün renkleri token'dan gelir."""
    for name in SELECTORS + EXTRA:
        for decls in selectors_with(name, RULES):
            for prop, value in decls.items():
                assert not HEX.search(value), f"{name}: {prop}: {value} — token yerine sabit renk"


def test_accent_soft_is_defined_for_every_theme():
    """Balonun zemini iki temada da ayrı ton taşır: koyu kendi köpüğünü almalı."""
    blocks = [decls for selector, decls in RULES if selector.startswith(":root")]
    assert len(blocks) == 3, "açık kök + koyu iki blok (T222) bekleniyordu"
    tones = set()
    for decls in blocks:
        tone = decls.get("--accent-soft", "")
        assert HEX.fullmatch(tone), f"--accent-soft tanımsız ya da renk değil: {tone!r}"
        tones.add(tone)
    assert len(tones) == 2, "--accent-soft koyu temada kendi tonuna sahip değil"


def test_the_question_bubble_is_the_askers_side():
    # Temel hâl okunur: telefon bloğu balonu zaten tüm genişliğe çıkarıyor.
    bubble = merged(".turn-question", parse_rules(base_css(CSS)))
    assert bubble.get("justify-self") == "end", "soru balonu sağa yaslanmıyor"
    assert bubble.get("background") == "var(--accent-soft)", "balon cevap kartından ayrılmıyor"


def test_the_collapsed_turn_reads_as_a_quiet_button():
    card = merged(".turn-collapsed")
    assert card.get("color") == "var(--muted)", "katlanmış tur canlı turun yanında soluk değil"
    assert card.get("cursor") == "pointer", "katlanmış turun açıldığı imleçten okunmuyor"
    caps = [
        decls
        for selector, decls in RULES
        if ".turn-table-wrap" in selector and ".turn-collapsed" in selector and "max-height" in decls
    ]
    assert caps, "katlanmış kartın beş satırlık penceresi (max-height) yok"


def test_the_context_line_draws_the_band_accent():
    """Bağlam satırının vurgusu T281'in bandı: dört yanı saran çizginin kalınlaşmış solu,
    bastığı iki köşe kare - yuvarlak köşeye binen kalın kenar "(" gibi görünüyor."""
    line = merged("#context-line")
    assert line.get("color") == "var(--muted)", "bağlam satırı cevabın önüne geçiyor"
    assert "border" in line, "vurgu dört yanı saran çizgiden gelmiyor"
    width = re.search(r"([\d.]+)px", line.get("border-left", ""))
    assert width and float(width.group(1)) > 1.0, "sol vurgu kalınlaşmamış"
    assert "var(" in line.get("border-left", ""), "vurgunun rengi token değil"
    radii = line.get("border-radius", "").split("/")[0].split()
    assert radii and radii[0] == "0" and radii[-1] == "0", "kalın sol yuvarlak köşeye biniyor"

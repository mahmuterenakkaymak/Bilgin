# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T210: dar ekranda sonuç tablosunun sayıları (M17 görsel incelemesi, 390px).

Telefon genişliğinde ``white-space: nowrap`` olan hücreler tabloyu kutunun dışına taşıyor ve
soru sayıyordu: başlık ``SATIS_MIK`` diye kesiliyor, 160/148/141/139 hiç görünmüyordu. İddia
derlenmiş CSS üstünde kurulur, kaynak dosya okunmaz - küçültme bir kuralı yutabilir ya da
sırasını bozabilir, oysa iddia tam olarak "390px'te sayı ekranda" demek. Sıra ayrıca sınanıyor:
eşit özgüllükte sonra gelen kazanır, yani nowrap'ı eden kuralın önüne düşen bir kural ekranda
hiçbir şeyi değiştirmez.
"""

import re
import shutil
import subprocess

import pytest

from bilgin import config

# Görsel incelemede sayının kutu dışında kaldığı genişlik.
PHONE_PX = 390

# Saratılması gereken hücreler: küçültülmüş CSS'te boşluk olmadığı için seçiciler de boşluksuz.
CELLS = {".result-tableth", ".result-tabletd"}


def run_npm(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde npm; Windows'ta ``npm`` bir .cmd, o yüzden tam yolla çağrılır."""
    return subprocess.run(
        [shutil.which("npm") or "npm", *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture(scope="module")
def built_css() -> str:
    """``npm --prefix web run build``ın ürettiği tek stil dosyası."""
    build = run_npm("--prefix", "web", "run", "build")
    assert build.returncode == 0, f"npm run build: {build.stdout}{build.stderr}"

    sheets = sorted((config.STATIC_DIR / "assets").glob("*.css"))
    assert sheets, f"derlemede CSS yok: {config.STATIC_DIR / 'assets'}"
    for sheet in sheets:
        text = sheet.read_text(encoding="utf-8")
        if ".result-table" in text:
            return text
    pytest.fail(f"derlenmiş CSS'te .result-table yok: {[s.name for s in sheets]}")


def flat(value: str) -> str:
    """Boşluklardan arınmış metin: kaynak ve küçültülmüş çıktı aynı şekilde karşılaştırılır."""
    return re.sub(r"\s+", "", value)


def block_body(css: str, brace: int) -> tuple[str, int]:
    """``brace`` konumundaki '{' ile açılan kümenin içeriği ve kapanıştan sonraki konum."""
    depth = 0
    for index in range(brace, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[brace + 1 : index], index + 1
    pytest.fail("derlenmiş CSS'te süslü parantezler eşleşmiyor")


def rules(body: str) -> list[tuple[list[str], str]]:
    """Küme içindeki kuralar: (seçiciler, bildirimler)."""
    out = []
    for chunk in body.split("}"):
        head, brace, decls = chunk.partition("{")
        if not brace:
            continue
        out.append(([flat(part) for part in head.split(",")], decls))
    return out


def media_blocks(css: str) -> list[tuple[int, str, str]]:
    """Tüm media blokları: (dosyadaki konum, koşul, gövde)."""
    blocks = []
    for match in re.finditer(r"@media([^{]*)\{", css):
        body, _ = block_body(css, match.end() - 1)
        blocks.append((match.start(), match.group(1), body))
    return blocks


def base_css(css: str) -> str:
    """Media sorgularından arınmış kısım: ekran genişliğinden bağımsız temeller."""
    keep, cursor = [], 0
    for match in re.finditer(r"@media([^{]*)\{", css):
        _, end = block_body(css, match.end() - 1)
        keep.append(css[cursor : match.start()])
        cursor = end
    keep.append(css[cursor:])
    return "".join(keep)


def upper_bound(condition: str) -> int | None:
    """Koşulun üst sınırı px olarak: ``max-width: 720px``, küçültücü onu ``width<=720px`` yapıyor."""
    match = re.search(r"max-width:\s*(\d+)", condition) or re.search(r"width\s*<=\s*(\d+)", condition)
    return int(match.group(1)) if match else None


def phone_blocks(built_css: str) -> list[tuple[int, str, str]]:
    """390px'te gerçekten çalışan bloklar: üst sınırı telefon genişliğinden dar olmayanlar."""
    blocks = [block for block in media_blocks(built_css) if upper_bound(block[1]) is not None]
    assert blocks, "derlenmiş CSS'te üst sınırlı (max-width) media sorgusu yok"
    applying = [block for block in blocks if upper_bound(block[1]) >= PHONE_PX]
    assert applying, f"390px'e inen bir üst sınır yok: {[b[1] for b in blocks]}"
    return applying


def wrapping_rule(body: str) -> tuple[list[str], str] | None:
    """Hücreleri sarmayı üstlenen kural: ``white-space: normal`` (ya da sabit sütun düzeni)."""
    for selectors, decls in rules(body):
        text = flat(decls)
        if "white-space:normal" in text and CELLS <= set(selectors):
            return selectors, decls
        if "table-layout:fixed" in text and ".result-table" in selectors:
            return selectors, decls
    return None


def declarations_of(css: str, selector: str) -> list[str]:
    """``css`` kümesindeki ``selector`` kuralarının bildirimleri."""
    return [decls for selectors, decls in rules(css) if selector in selectors]


# ------------------------------------------------------------------ dar ekran


def test_a_narrow_screen_wraps_the_result_cells(built_css):
    for _, condition, body in phone_blocks(built_css):
        rule = wrapping_rule(body)
        assert rule is not None, f"{condition} içinde hücreleri saran kural yok: {body}"
        _, decls = rule
        # Uzun başlık tek başına sığmaz: kelime bölünmezse sütun yine taşar.
        assert "overflow-wrap" in flat(decls) or "table-layout:fixed" in flat(decls), decls


def test_the_numbers_keep_their_own_room(built_css):
    """Sağ yaslama temelden gelir; dar ekranda sayı sütunu ayrıca kendi genişliğini alır."""
    wide = declarations_of(base_css(built_css), ".result-table.num")
    assert wide and all("text-align:right" in flat(decls) for decls in wide), wide

    for _, condition, body in phone_blocks(built_css):
        narrow = declarations_of(body, ".result-table.num")
        assert narrow, f"{condition} içinde .num kuralı yok: {body}"
        assert any("min-width" in flat(decls) for decls in narrow), narrow


# ------------------------------------------------------------------ sıra ve geniş ekran


def test_the_narrow_rule_comes_after_the_wide_one(built_css):
    """Eşit özgüllükte sıra kazanır: nowrap'ı eden kuralın arkasına düşerse hiçbir iş yapmaz."""
    wide = re.search(r"\.result-table[^{@]*\{[^}]*white-space:\s*nowrap", built_css)
    assert wide, "geniş ekran için nowrap kuralı bulunamadı"
    for start, condition, _ in phone_blocks(built_css):
        assert wide.start() < start, f"{condition} nowrap kuralından önce geliyor, sarmaz"


def test_the_wide_table_stays_as_it_is(built_css):
    """1366px'te tablo eskisi gibi tek satır: nowrap, media sorgusunun dışında duruyor."""
    assert re.search(r"white-space:\s*nowrap", base_css(built_css))

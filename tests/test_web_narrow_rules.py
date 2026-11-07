# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T213: dar ekranda kural satırının düğmeleri (M17 görsel incelemesi, 390px).

Görsel incelemede 390px'lik kural ekranında İşlem sütunu hiç yoktu: ``.rules-table``'ın
min-content genişliği (``.rules-term`` 160px + ``.rules-actions`` nowrap) ekranı aştığı için
``.table-wrap`` onu kırpıyor, hiçbir kural düzenlenemiyor ya da silinemiyordu. İddia derlenmiş
CSS üstünde kurulur, kaynak dosya okunmaz - küçültme bir kuralı yutabilir, oysa iddia tam olarak
"390px'te Düzenle/Sil ekranda" demek. Kuralın nasıl kazandığı da sınanıyor: kural ekranının
temelleri dar bloğun aşağısında duruyor, o yüzden eşit özgüllükte temel kazanır ve bloğa dönüş
ekranda hiçbir şeyi değiştirmez.
"""

import re
import shutil
import subprocess

import pytest

from nl2sql import config

# Görsel incelemede İşlem sütununun kaybolduğu genişlik.
PHONE_PX = 390

# Küçültülmüş CSS'te boşluk olmadığı için seçiciler de boşluksuz ölçülür.
TABLE = ".rules-table"
ROW_CELLS = {".rules-tableth", ".rules-tabletd"}
BASE_CELL = ".rules-table th"


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
        if TABLE in text:
            return text
    pytest.fail(f"derlenmiş CSS'te {TABLE} yok: {[s.name for s in sheets]}")


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


def rules(body: str) -> list[tuple[str, str]]:
    """Küme içindeki kuralar: (seçiciler ham metin, bildirimler)."""
    out = []
    for chunk in body.split("}"):
        head, brace, decls = chunk.partition("{")
        if brace:
            out.append((head.strip(), decls))
    return out


def cell_selectors(body: str, declaration: str) -> list[str]:
    """``declaration``ı taşıyan kuralların satır hücresi seçicileri.

    Hücreyi hedefleyen kural temelden derin olabilir (``.rules-table tbody td``); hangisi
    olduğu aşağıda özgüllük ölçüsüne girdiği için olduğu gibi, ham hâliyle döner.
    """
    out = []
    for head, decls in rules(body):
        if declaration not in flat(decls):
            continue
        for part in head.split(","):
            key = flat(part)
            if key.startswith(TABLE) and key.endswith(("th", "td")):
                out.append(part.strip())
    return out


def has_rule(body: str, selector: str, declaration: str) -> bool:
    """``selector``ü birebir seçen ve ``declaration``ı taşıyan kural var mı?"""
    return any(
        declaration in flat(decls) and any(flat(part) == selector for part in head.split(","))
        for head, decls in rules(body)
    )


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


def rules_blocks(built_css: str) -> list[tuple[int, str, str]]:
    """390px'te kural tablosunu ele alan bloklar: aynı üst sınırı paylaşan başkaları da var."""
    blocks = [
        block
        for block in media_blocks(built_css)
        if (upper_bound(block[1]) or 0) >= PHONE_PX and TABLE in block[2]
    ]
    assert blocks, f"390px'e inen hiçbir blok {TABLE} için bir şey söylemiyor"
    return blocks


def weight(selector: str) -> tuple[int, int]:
    """Özgüllüğün bu CSS'te iş gören iki basamağı: (sınıf/öznitelik/yapay-sınıf, öğe adı).

    Derlenmiş stil dosyasındaki seçimcelerin hiçbiri id taşımıyor, o yüzden iki seçimceyi
    karşılaştırırken bu iki sayı sıralamayı tam olarak verir.
    """
    classes = len(re.findall(r"[.:\[]", selector))
    elements = len(re.findall(r"(?<![#.:\w-])[a-z][\w-]*", selector))
    return classes, elements


# ------------------------------------------------------------------ dar ekran


def test_a_narrow_screen_stacks_the_rule_rows(built_css):
    """Satırın her hücresi bloğa iner; Düzenle/Sil'in olduğu hücre de bir ``td``.

    Tablonun kendisi de bloğa dönmeli: hücreler bloğa dönüp tablo tablo kalırsa anonim hücreler
    aynı min-content tavanını korur ve yan kaydırma ekranda kalmaya devam eder.
    """
    for _, condition, body in rules_blocks(built_css):
        stacked = cell_selectors(body, "display:block")
        assert any(s.endswith("td") for s in stacked), (
            f"{condition} içinde hücreleri bloğa çeviren kural yok: {stacked}"
        )
        assert any(s.endswith("th") for s in stacked), (
            f"{condition} içinde Terim hücresi (th) bloğa dönmüyor: {stacked}"
        )
        assert has_rule(body, TABLE, "display:block"), (
            f"{condition} içinde {TABLE} kendisi bloğa dönmüyor: {body}"
        )


def test_the_stacked_row_outranks_its_base(built_css):
    """Hücreleri saran kural temeli gerçekten yenmeli: özgüllükle ya da sırayla.

    Kural ekranının temelleri dar bloğun aşağısında duruyor; eşit özgüllükte temel kazanır ve
    hücrelerin altındaki çizgi geri gelir - ekranda her satır dört çizgi görür.
    """
    base = re.search(r"\.rules-table (?:th|td)[^{]*\{[^}]*box-shadow", built_css)
    assert base, "temel hücre kuralı (alt çizgi) bulunamadı"
    for start, condition, body in rules_blocks(built_css):
        narrow = cell_selectors(body, "box-shadow:none")
        assert narrow, f"{condition} içinde hücre çizgisini kaldıran kural yok: {body}"
        assert weight(narrow[0]) > weight(BASE_CELL) or base.start() < start, (
            f"{condition} {narrow[0]!r} temeli yenmiyor: {BASE_CELL} ondan sonra geliyor"
        )


# ------------------------------------------------------------------ geniş ekran


def test_the_wide_table_stays_as_it_is(built_css):
    """1366px'te tablo eskisi gibi: nowrap ve Terim'in 160px'i media sorgusunun dışında duruyor."""
    wide = base_css(built_css)
    assert re.search(r"\.rules-actions\s*\{[^}]*white-space:\s*nowrap", wide)
    assert re.search(r"\.rules-term\s*\{[^}]*min-width:\s*160px", wide)
    assert not re.search(r"\.rules-table[^{@]*\{[^}]*display:\s*block", wide)

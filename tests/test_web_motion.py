# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T215: cevabın gelişi bir olay, indirme düğmesi kendi haberini verir (M17 görsel incelemesi).

Görsel incelemede ``export-buttons-after-export-390.png``, ``export-buttons-390.png`` ile pik pik
aynıydı: CSV/Excel bir ``<a>``, sekme yer değiştirmediği için tıklamanın ekranda hiçbir karşılığı
yoktu. Cevap kartı da bir anda beliriyordu. İddialar derlenmiş çıktı üstünde kurulur - küçültücü
bir kuralı yutabilir, sırasını bozabilir ya da ``180ms``yi ``.18s`` yapabilir, oysa asıl soru
"tarayıcı hareketi görüyor mu ve ``prefers-reduced-motion`` onu gerçekten kapatıyor mu". Sıra
ayrıca sınanır: eşit özgüllükte sonra gelen kazanır, yani ``animation: none`` temelin önünde
durursa ekranda hiçbir hareketi durdurmaz.
"""

import re
import shutil
import subprocess

import pytest

from nl2sql import config

# Kartın girişi: bekleme değil işaret - 150-200ms aralığının dışına çıkmaz.
MIN_MS, MAX_MS = 150, 200

# Cevap kartının derlenmiş CSS'te bulunabileceği seçiciler: öğe üçünü de taşıyor.
CARD = {"#answer-card", ".card", ".answer-card"}

# Küçültücü Türkçe adı kaçış da yazabilir; ikisi de aynı ad.
DONE_LABEL = re.compile(r"İndirildi|\\u0130ndirildi")


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
def built() -> tuple[str, str]:
    """``npm --prefix web run build``ın stil dosyası ve tarayıcının yüklediği betikler."""
    build = run_npm("--prefix", "web", "run", "build")
    assert build.returncode == 0, f"npm run build: {build.stdout}{build.stderr}"

    assets = config.STATIC_DIR / "assets"
    sheets = sorted(assets.glob("*.css"))
    assert sheets, f"derlemede CSS yok: {assets}"
    for sheet in sheets:
        text = sheet.read_text(encoding="utf-8")
        if ".answer-card" in text:
            scripts = sorted(assets.glob("*.js"))
            assert scripts, f"derlemede betik yok: {assets}"
            return text, "\n".join(s.read_text(encoding="utf-8") for s in scripts)
    pytest.fail(f"derlenmiş CSS'te .answer-card yok: {[s.name for s in sheets]}")


def flat(value: str) -> str:
    """Boşluklardan arınmış metin: kaynak ve küçültülmüş çıktı aynı şekilde karşılaştırılır."""
    return re.sub(r"\s+", "", value)


def body_end(css: str, brace: int) -> int:
    """``brace`` konumundaki '{' ile açılan kümenin kapanışından sonraki konum."""
    depth = 0
    for index in range(brace, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    pytest.fail("derlenmiş CSS'te süslü parantezler eşleşmiyor")


def rules(css: str, offset: int = 0, condition: str = "") -> list[tuple[int, str, list[str], str]]:
    """Seçicili tüm kuralar: (dosyadaki konum, içindeki media koşulu, seçiciler, bildirimler).

    Media kümelerinin içine de girilir - hareketi kapatan kural orada duruyor, hangi koşulun
    altında olduğu da oradan okunuyor. ``@keyframes`` adımları seçici taşımadığı için dışarıda.
    """
    out = []
    cursor, length = 0, len(css)
    while cursor < length:
        brace = css.find("{", cursor)
        if brace < 0:
            break
        end = body_end(css, brace)
        head, prelude = css[cursor:brace], flat(css[cursor:brace])
        if prelude.startswith("@media"):
            out.extend(rules(css[brace + 1 : end - 1], offset + brace + 1, prelude))
        elif not prelude.startswith("@"):
            selectors = [flat(part) for part in head.split(",")]
            if any(selectors):
                out.append((offset + brace, condition, selectors, css[brace + 1 : end - 1]))
        cursor = end
    return out


def entrance(css: str) -> tuple[int, str, str]:
    """Karta hareket veren kural: (konum, kart seçicisi, ``animation``/``transition`` değeri).

    Hareketi kapatan ``none`` giriş değildir; o, aşağıdaki prefers-reduced-motion iddiasının konusu.
    """
    found = []
    for start, _, selectors, decls in rules(css):
        motion = re.search(r"(?:^|;)(?:animation|transition):\s*([^;}]+)", decls)
        card = set(selectors) & CARD
        if motion and card and flat(motion.group(1)) != "none":
            found.append((start, sorted(card)[0], motion.group(1)))
    assert found, f"derlenmiş CSS'te cevap kartına hareket veren kural yok: {[s for _, _, s, _ in rules(css)][:20]}"
    return found[-1]


def keyframes(css: str, name: str) -> str:
    """``@keyframes`` adımlarının metni: girişin ne yaptığı oradan okunur."""
    match = re.search(r"@keyframes\s*" + re.escape(name) + r"\s*\{", css)
    assert match, f"@keyframes {name} yok"
    return css[match.end() : body_end(css, match.end() - 1) - 1]


def duration_ms(value: str) -> int:
    """Kısaltmadaki birimli süre: gecikme ayrı yazılmadığı için tek değer girişin süresidir.

    Küçültücü ``180ms``yi ``.18s`` yapar ve kısaltmanın sırasını da değiştirebiliyor; birim burada
    tek ölçüdür, o yüzden ad ya da anahtar sözcük aramak yerine birimli tek token okunur.
    """
    times = [re.fullmatch(r"(\d*\.?\d+)(ms|s)", token) for token in value.split()]
    times = [float(m.group(1)) * (1000 if m.group(2) == "ms" else 1000) for m in times if m]
    assert len(times) == 1, f"girişin süresi tek birimle bildirilmemiş: {value}"
    return int(times[0])


# ------------------------------------------------------------------ cevabın girişi


def test_the_answer_card_enters(built):
    css, _ = built
    _, selector, value = entrance(css)

    names = {m.group(1) for m in re.finditer(r"@keyframes\s*([\w-]+)", css)}
    name = next((token for token in value.split() if token in names), None)
    assert name, f"giriş bir @keyframes adıyla kurulmamış: {value}"

    steps = keyframes(css, name)
    # Soluklaşarak gelme ve birkaç piksel yükselme: biri düşerse kart yine "pat" diye belirir.
    assert re.search(r"opacity:\s*0(?:\.0+)?(?![\d.])", steps), f"girişte solma yok: {steps}"
    moved = re.search(r"transform:\s*([^;}]+)", steps)
    assert moved, f"girişte yükselme yok: {steps}"
    offsets = [abs(float(px)) for px in re.findall(r"(-?\d+(?:\.\d+)?)px", moved.group(1))]
    assert any(2 <= px <= 16 for px in offsets), f"yükselme ölçüsü anormal: {moved.group(1)}"
    assert selector in CARD, selector


def test_the_entrance_is_short(built):
    css, _ = built
    ms = duration_ms(entrance(css)[2])
    assert MIN_MS <= ms <= MAX_MS, f"giriş {ms}ms: bekleme ile işaret arasındaki sınır şaştı"


# ------------------------------------------------------------------ hareketi istemeyen kullanıcı


def test_reduced_motion_turns_the_entrance_off(built):
    css, _ = built
    start, _, _ = entrance(css)

    off = [
        (rule_start, condition, sorted(set(selectors) & CARD)[0])
        for rule_start, condition, selectors, decls in rules(css)
        if set(selectors) & CARD and "animation:none" in flat(decls)
    ]
    assert off, "kartın hareketini kapatan kural yok: hareketi istemeyen kullanıcı onu almaya devam ediyor"
    rule_start, condition, selector = off[-1]

    assert "prefers-reduced-motion" in condition, f"{selector} {condition or 'koşulsuz'} altında kapanıyor"
    assert rule_start > start, f"{selector} girişten önce geliyor; eşit özgüllükte sıra kazanır, kapatmaz"


# ------------------------------------------------------------------ indirme düğmesi


def test_the_download_button_has_a_done_state(built):
    css, js = built

    done = [decls for _, _, selectors, decls in rules(css) if any("btn-downloaded" in s for s in selectors)]
    assert done, "indirme düğmesinin bitti hâli için kural yok"
    assert any("color:" in flat(decls) for decls in done), done

    # Ad değişikliği düğmenin tek söz hakkı: tarayıcının gerçekten yüklediği betikte durduğunu ölç.
    assert DONE_LABEL.search(js), "derlenmiş betikte İndirildi adı yok"

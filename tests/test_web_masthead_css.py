"""T272: telefon başlığı iki satır olmalı, üç değil (M19 görsel inceleme 7).

T264 kimlik çipiyle Çıkış'ı gezinme satırına çağırdı, gelen yalnız durum sözcüğü oldu: `flex-wrap`
kırılacak yeri içeriğin genişliğine bıraktığı için 390px'te Çıkış kendi satırına düştü ve başlık
üç satır kaldı (landing-empty-state-390.png, users-screen-390.png) — layout'tan düşmüş bir düğme
gibi okunuyor. Doğrusu satırı yazmak: dar ekranda ızgara, her parça hangi satırda olduğunu kendisi
söyler. İddia kaynak CSS'te kurulur - ölçülen yazarın niyeti, küçültücünün metni değil.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"

# Görsel incelemede başlığın üç satıra indiği genişlik.
PHONE_PX = 390
HEAD = ".masthead"

# İstenen dizilim: üst satır neye bakıldığını, alt satır nerede gezinildiğini ve kim olunduğunu söyler.
ROW_OF = {
    ".wordmark": 1,
    "#model-chip": 1,
    ".btn-theme": 1,
    ".health": 1,
    ".masthead-nav": 2,
    "#user-chip": 2,
    "#logout": 2,
}

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


def split_tracks(value: str) -> list[str]:
    """Sütun listesini boşluktan böler ama parantez dibine inmez: ``minmax(0, 1fr)`` tek parça kalır."""
    parts, depth, current = [], 0, ""
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == " " and depth == 0:
            if current:
                parts.append(current)
                current = ""
            continue
        current += char
    if current:
        parts.append(current)
    return parts


def rows_of(decls: dict[str, str]) -> list[list[str]]:
    """``grid-template-areas`` değerinden satırlar: adların satır sırası düzenin ta kendisidir."""
    return [row.split() for row in re.findall(r'"([^"]*)"', decls.get("grid-template-areas", ""))]


def head_rows() -> list[list[str]]:
    head = effective(HEAD)
    assert head.get("display") == "grid", f"{HEAD} dar ekranda ızgara değil: {head}"
    rows = rows_of(head)
    assert rows, f"{HEAD} kaç satıra diziliyor, nereden okunacak: {head}"
    return rows


# ------------------------------------------------------------------ dar ekran


def test_the_phone_head_is_a_two_row_grid():
    """İki satır satırın kendisinde yazılı olmalı: sarmaya bırakılan kırma, içeriğin genişliğine
    göre üçüncü satırı açıyor — Çıkış tek başına orada kalıyordu."""
    rows = head_rows()
    assert len(rows) == 2, f"{HEAD} {len(rows)} satıra dizilmiş: {rows}"
    widths = {len(row) for row in rows}
    assert len(widths) == 1, f"satırlar sütun sayısında uyuşmuyor: {rows}"
    # Kırma elemanı olarak kullanılan sahte kutu ızgarada yeri olmayan bir öğedir: üçüncü satırı o açar.
    stray = effective(f"{HEAD}::after").get("content", "none")
    assert stray in ("none", "normal", ""), f"{HEAD}::after hâlâ kırma kutusu taşıyor: {stray}"


def test_every_part_of_the_head_knows_its_row():
    """Yeri olmayan çocuk kenara yerleşir ve satırı kendisi açar: başlığın parçalarının hepsi
    iki satırdan birine adıyla yazılmış olmalı."""
    rows = head_rows()
    for selector, expected in ROW_OF.items():
        area = effective(selector).get("grid-area", "")
        placed = [number for number, row in enumerate(rows, 1) if area and area in row]
        assert placed == [expected], (
            f"{selector}: {area!r} {expected}. satırda değil, dizilen: {rows}"
        )


def test_the_dataset_chip_keeps_its_right_to_shrink():
    """Çip küçülemezse satır taşar ve Çıkış yine kendi satırına düşer: küçülme hakkı iki yerden
    gelir — sütunun tabanı (minmax(0, ...)) ve çipin kendi min-width'ı. Tavanı ellipsis çalıştırır."""
    rows = head_rows()
    chip = effective("#model-chip")
    area = chip.get("grid-area", "")
    assert area, f"#model-chip'in ızgarada yeri yok: {chip}"
    column = next(row for row in rows if area in row).index(area)
    tracks = split_tracks(effective(HEAD).get("grid-template-columns", ""))
    assert len(tracks) == len(rows[0]), f"sütun listesi ile alanlar uyuşmuyor: {tracks} / {rows}"
    assert tracks[column].replace(" ", "").startswith("minmax(0,"), (
        f"çipin sütunu {tracks[column]!r}: tabanı sıfır değil, çip küçülemez"
    )
    assert effective(f"{HEAD} .chip").get("min-width") == "0", (
        "çipin min-width'ı sıfıra inmiyor: uzun ad sütunu şişirir, satır taşar"
    )


def test_the_nav_line_is_written_not_wrapped():
    """Run 6 dördüncü bağlantıyı (Veritabanı haritası) ekleyince gezinme kendi alanında saraya
    durdu: 390'da "Sor Kurallar", sonra "Veritabanı haritası", sonra "Kullanıcılar" tek başına —
    başlık dört dağınık satır okunuyor (landing-empty-state-390.png, users-screen-390.png). Sarma
    kırılacak yeri içeriğin genişliğine bırakır; satırın yazılmış sayılması için iki yol var:
    ızgarada en az iki sütun ya da tek sıra kaydırılan bir satır. İkisi de dört bağlantının birer
    birer alt alta inmesini engeller.
    """
    nav = effective(".masthead-nav")
    tracks = split_tracks(nav["grid-template-columns"]) if nav.get("display") == "grid" else []
    scrollable = nav.get("overflow-x") in ("auto", "scroll")
    assert len(tracks) >= 2 or scrollable, (
        f".masthead-nav satırı yazılmamış: sığmayan bağlantılar sarmaya kalıyor, bir bağlantı "
        f"kendi satırında tek başına kalıyor: {nav}"
    )
    if scrollable:
        assert nav.get("flex-wrap", "nowrap") != "wrap", (
            "kaydırma ile sarma bir arada: sarma kazanıyor, bağlantılar yine alt alta iniyor"
        )
        # Esneyen bağlantı sığmayan adını kendi içinde kırıyor: satır yine ikinci kata çıkıyor.
        assert effective(".nav-link").get("flex", "0 1 auto") in ("none", "0 0 auto"), (
            "bağlantı esneyebiliyor: uzun ad kendi içinde kırılıp satırı kabartıyor"
        )


# ------------------------------------------------------------------ geniş ekran

# Yöneticinin başlığının ikiyeindiği genişlik: sıradan bir dizüstü, telefon değil.
WIDE_PX = 1200


def lower_bound(condition: str) -> int | None:
    """Koşulun alt sınırı px olarak; üst sınırlı (max-width) koşullar geniş ekran için işlemez."""
    match = re.search(r"min-width:\s*(\d+)px", condition)
    return int(match.group(1)) if match else None


def wide_bodies(css: str) -> list[str]:
    """Geniş ekranda gerçekten işleyen bloklar: alt sınırı genişliğe inen, üst sınırı onu kesmeyen."""
    bodies = []
    for condition, start, end in media_spans(css):
        low = lower_bound(condition)
        high = upper_bound(condition)
        if low is None or low > WIDE_PX:
            continue
        if high is not None and high < WIDE_PX:
            continue
        bodies.append(css[start:end])
    assert bodies, f"{STYLES.name} içinde {WIDE_PX}px'e çıkan bir min-width bloğu yok"
    return bodies


def effective_wide(selector: str) -> dict[str, str]:
    """Geniş ekranda kazanan bildirimler: temeller, sonra işleyen media blokları, sıra ile."""
    won: dict[str, str] = {}
    for body in [base_css(CSS), *wide_bodies(CSS)]:
        for selectors, decls in rules(body):
            if selector in selectors:
                won.update(decls)
    return won


def test_the_wide_head_is_one_row():
    """`flex-wrap: wrap` telefonun iki satırlık ızgarası için yazıldı; geniş tarafın karşılığı
    yazılmayınca altı bağlantı kimlik çipiyle Çıkış'ı kendi satırına indirdi ve her yönetici
    ekranı iki satırlık başlık taşıdı (admin-ready-questions-ready-list-1366.png,
    users-screen-users-table-1366.png) — 1366'da kırılma "başlığın bir parçası düşmüş" okunuyor.
    Temelde sarma açık kaldığı için nowrap'u ancak 1200px'e çıkan bir blok verebilir.
    """
    head = effective_wide(HEAD)
    assert head.get("display") == "flex", f"{HEAD} geniş ekranda ızgaraya dönmüş: {head}"
    assert head.get("flex-wrap") == "nowrap", (
        f"{HEAD} geniş ekranda hâlâ sarıyor: sığmayan parça kendi satırına düşüyor: {head}"
    )


def test_the_wide_row_wraps_instead_of_scrolling():
    """Run 8 gezinmeye Bağlantılar'ı ve TR/EN düğmesini de çağırdı: 1366'da altı ad sığmadı,
    telefonun kaydırılan sırası maskeyle "Hazır sor"u yuttu ve gizli çubuk devamı da söylemedi
    (en-map-screen-map-blank-1366.png, admin-connections-connections-list-1366.png) — sıradan bir
    dizüstünde bir ekran ulaşılmaz görünüyordu. Geniş tarafta satır yazılmaz, sarar: sığmayan
    bağlantı ikinci kata çıkar, hiçbir ad kesilmez. Kaydırma ve uç maskesi telefona kalır."""
    nav = effective_wide(".masthead-nav")
    assert nav.get("flex-wrap") == "wrap", (
        f".masthead-nav geniş ekranda sarmıyor: sığmayan bağlantı kesiliyor: {nav}"
    )
    assert nav.get("overflow-x", "visible") not in ("auto", "scroll"), (
        f"geniş ekranda hâlâ kaydırılan satır var: {nav}"
    )
    assert nav.get("mask-image", "none") == "none", f"geniş ekranda uç maskesi yanmış: {nav}"
    assert effective_wide(".masthead-nav .nav-link").get("flex", "0 1 auto") in ("none", "0 0 auto"), (
        "bağlantı esneyebiliyor: uzun ad kendi içinde kırılıp satırı kabartıyor"
    )
    chip = effective_wide("#user-chip")
    assert chip.get("max-width", "none") != "none", (
        "kimlik çipinin tavanı yok: uzayan ad satırı uzatır, Çıkış yine sığmıyor"
    )


def test_no_wide_rule_drops_logout_onto_its_own_row():
    """Çıkış'ın ikinci satıra inmesinin tek yolu satırın kendisinin açılması: sarmanın kapalı
    olduğu bir flex sırasında onu oraya ancak tüm satırı isteyen bir pay taşır — `flex-basis:
    100%` ya da `width: 100%` gibi. Geniş ekranda o payı hiçbir kural vermemeli."""
    head = effective_wide(HEAD)
    assert head.get("flex-wrap") == "nowrap", f"{HEAD} sarmaya açık: {head}"
    out = effective_wide("#logout")
    for prop in ("flex", "flex-basis", "width", "min-width"):
        assert "100%" not in out.get(prop, ""), (
            f"#logout {prop} ile tüm satırı istiyor: {out}"
        )
    assert out.get("display", "inline-block") != "block", (
        f"#logout blok olarak diziliyor: {out}"
    )

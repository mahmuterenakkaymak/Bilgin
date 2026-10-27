"""T381: cevabın beş eylemi iki ağırlıkta (M24 craft 1).

CSV, Excel, Soruyu kaydet, Panoma ekle ve Hazır soru yap aynı çerçeveli beş hap olarak
dizildiğinde veriyi almak - kartın varlık sebebi - panoya iğnelemekten farksız okunuyor ve sıra
390'da 2/2/1 kırılıyordu (ask-golden-answer-chart-answer-with-chart-390.png). İddia kaynak CSS'te
ve kartın markupında kurulur: indirme tek çerçeveli bir ikili olarak üstte durur, iş düğmeleri
ince çizginin altında ikincil metne iner.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"
CARD = config.WEB_DIR / "src" / "components" / "AnswerCard.jsx"

# İndirme sırasından çizginin altına inen üç iş: id'ler görsel akışların tıkladığı adlar.
WORKFLOW = ("save-question", "pin-card", "make-ready")

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)
JSX = CARD.read_text(encoding="utf-8")


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


def covers(token: str, name: str) -> bool:
    """Seçici parçası ``name`` mi ya da onun bir hâli: ``.answer-export:hover`` evet,
    ``.answer-export-pair`` hayır - alt sınıf adları ayrı seçicidir."""
    return token == name or token.startswith(f"{name}[") or token.startswith(f"{name}:")


def merged(name: str) -> dict[str, str]:
    """Bir seçicinin CSS'teki son hâli: onu taşıyan her kuralın bildirimleri sırayla üstüne biner."""
    decls: dict[str, str] = {}
    for selector, rule in RULES:
        if any(covers(part, name) for part in selector.split()):
            decls.update(rule)
    assert decls, f"{STYLES.name} içinde {name} kuralı yok"
    return decls


def declared(name: str) -> dict[str, str]:
    """Yalnız çıplak seçicinin bildirimleri: durum hâlleri (``:hover``, ``:disabled``) temeli
    ezmesin - burada sorulan şey düğmenin dururken nasıl göründüğüdür."""
    decls: dict[str, str] = {}
    for selector, rule in RULES:
        if name in selector.split():
            decls.update(rule)
    assert decls, f"{STYLES.name} içinde çıplak {name} kuralı yok"
    return decls


def token(value: str) -> str:
    """Bildirimdeki tasarım token'ı: ``1px solid var(--line)`` -> ``--line``."""
    match = re.search(r"var\((--[a-z-]+)\)", value)
    return match.group(1) if match else value


def balanced(source: str, start: int) -> str:
    """``start``taki ``{`` ile kapanan parça: JSX ifadesi iç içe küme taşıyabilir."""
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"{CARD.name}: kapanmamış küme")


def tag(marker: str) -> str:
    """``marker``ı taşıyan açılış etiketi. ``=>`` bir ifade bloğunun içinde kalır; sayılan küme
    derinliği sıfırken gelen ilk ``>`` etiketi kapatır."""
    start = JSX.rindex("<", 0, JSX.index(marker))
    depth = 0
    for index in range(start, len(JSX)):
        char = JSX[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ">" and depth == 0:
            return JSX[start : index + 1]
    raise AssertionError(f"{CARD.name}: {marker} etiketi kapanmamış")


def classes(element: str) -> set[str]:
    """Etiketteki sınıf adları: sabit metin ile şablonun sabit parçası aynı kümede toplanır -
    durum sonekinin hangisi olduğu markup'ın değil durumun konusu."""
    match = re.search(r"\sclassName=(\"[^\"]*\"|\{)", element)
    assert match, f"etikette className yok: {element}"
    value = match.group(1)
    if value == "{":
        value = balanced(element, match.end() - 1)
    names: set[str] = set()
    for literal in re.findall(r"`([^`]*)`|\"([^\"]*)\"|'([^']*)'", value):
        for part in re.split(r"\$\{[^}]*\}", " ".join(literal)):
            names.update(part.split())
    return names


def block(marker: str, closing: str) -> str:
    """``marker``lı öğenin gövdesi: bu bölümlerin içinde aynı türden iç içe öğe yok."""
    start = JSX.index(marker)
    return JSX[start : JSX.index(closing, start)]


RULES = parse_rules(CSS)


def test_the_export_group_exists():
    """İndirme kendi satırında bir grup: etiketle ikili yan yana, sıranın geri kalanından ayrı."""
    group = merged(".answer-exports")
    assert group.get("display") == "flex", f".answer-exports satır değil: {group.get('display')!r}"
    assert 'className="answer-exports"' in JSX, "kartta grup kurulmuyor"


def test_the_pair_shares_one_border():
    """Çerçeve taşıyıcıda, üyeler kendi kenarını çizmez: ikili tek bir nesne olarak okunur.
    Aralarındaki tek dikey çizgi bölüntüdür ve çerçevenin rengini paylaşır."""
    pair = merged(".answer-export-pair")
    border = pair.get("border", "")
    assert border.startswith("1px solid var("), f"ikilinin tek çerçevesi yok: {border!r}"
    assert pair.get("border-radius"), "ikilinin köşeleri yuvarlak değil: iki kare yan yana durur"

    members = merged(".answer-export")
    for prop in ("border", "border-top", "border-right", "border-bottom", "border-radius"):
        assert prop not in members, f"üye kendi kenarını çiziyor: {prop}: {members[prop]!r}"
    divider = members.get("border-left", "")
    assert divider, "iki üyenin arasında bölüntü yok: ayrı iki düğme gibi duruyorlar"
    assert token(divider) == token(border), (
        f"bölüntü {token(divider)} ile çerçeve {token(border)} ayrı renkte"
    )


def test_both_export_links_live_in_the_pair():
    """CSV ve Excel ikilinin üyeleridir ve hap sınıfını taşımaz: id'ler ``export-${kind}``dan gelir."""
    pair = block('className="answer-export-pair"', "</span>")
    assert "export-${kind}" in pair, "iki indirme bağlantısı ikilinin içinde kurulmuyor"
    assert "answer-export" in classes(tag("id={`export-${kind}`}")), "üyenin sınıfı ikiliye ait değil"
    assert "btn" not in classes(tag("id={`export-${kind}`}")), "bağlantı hâlâ birincil hap"


def test_the_workflow_actions_are_secondary():
    for marker in WORKFLOW:
        names = classes(tag(f'id="{marker}"'))
        assert "answer-action" in names, f"#{marker} ikincil sınıfı taşımıyor: {sorted(names)}"
        assert "btn" not in names, f"#{marker} hâlâ birincil hap: {sorted(names)}"


def test_the_secondary_style_is_not_the_pill():
    """İkincil sınıf birincil hapın taşıdığı şeyi taşımaz: çerçeve yok, hap köşesi yok, zemin yok."""
    quiet = declared(".answer-action")
    pill = declared(".btn")
    assert quiet.get("border") == "0", f"ikincil düğmenin kenarı var: {quiet.get('border')!r}"
    assert "border-radius" not in quiet, "ikincil düğme de hap oldu"
    assert quiet.get("background") == "none", "ikincil düğmenin zemini var"
    assert quiet.get("color") == "var(--text)", (
        f"iş düğmesi ya vurguyla yarışıyor ya da bilgi notuna dönmüş: {quiet.get('color')!r}"
    )
    assert pill.get("border-radius"), "birincil hapın hap köşesi mi yok?"


def test_the_workflow_sits_under_a_hairline():
    """İşler ince çizginin altında: indirme ile yan iş aynı çerçevenin içinde değil."""
    row = merged(".answer-workflow")
    top = row.get("border-top", "")
    assert re.match(r"1px solid var\(--[a-z-]+\)$", top), f"çizgi ince değil ya da token değil: {top!r}"
    assert "padding-top" in row, "düğmeler çizgiye bitişik"
    assert 'className="answer-workflow"' in JSX, "kartta iş sırası kurulmuyor"


def test_the_split_is_the_markups_split():
    """Üç iş çizginin altında, iki indirme onun üstünde: aynı satırda karışmıyorlar."""
    row = block('className="answer-workflow"', "</div>")
    for marker in WORKFLOW:
        assert f'id="{marker}"' in row, f"#{marker} hâlâ indirme sırasının yanında"
    assert "export-" not in row, "indirme bağlantısı iş sırasına düşmüş"

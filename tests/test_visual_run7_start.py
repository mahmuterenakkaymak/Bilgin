"""T329: başlangıç ekranının görünümü ve Run 7'nin dört akış sayfası (PLAN R7-21, R7-28).

``.hybrid/visual.json``ın dört sayfası (``start-sales``, ``start-purchasing``,
``card-answer-followup``, ``admin-ready-questions``) panoyu ve hazır soru defterini tarayıcıda
koşar. Üçü birden doğru olmadan inceleme boşluğa tıklar: kum havuzunda o panoyu görecek iş
rolünün hesabı, sayfada tıklanacak seçici ve kartların yan yana durduğu bir ızgara. Sayfalar
``from: M24`` taşıdığı için ``test_visual_flows`` seçicilerini M24 bitene dek denetlemiyor; bu
dosya denetliyor. Telefon kurallarının tek ``max-width`` bloğunda durduğunu da burada ölçüyoruz:
``test_web_narrow_table`` ve ``test_web_table_css`` bütün blokları tarıyor, ikincisi açılırsa
sessiz kalıyor (``test_web_thread_css`` onu tek başına kırmızıya çeviriyor).
"""

import json
import re

import pytest

from nl2sql import config
from nl2sql.auth.store import UserStore
from scripts import visual_serve

VISUAL_PATH = config.ROOT / ".hybrid" / "visual.json"
STYLES = config.WEB_DIR / "src" / "styles.css"
SRC_DIR = config.ROOT / "web" / "src"
PHONE_PX = 720

# Akışın kiminle açıldığı göreceği panoyu belirliyor: satın alma kartları yalnız `satinalma`da.
BOARDS = {
    "start-sales": "analist",
    "start-purchasing": "satinalma",
    "card-answer-followup": "analist",
    "admin-ready-questions": "admin",
}

# Görevin seçicileri: her biri bir kuralın seçicisinde çıplak geçmeli.
CARD_SELECTORS = (".start-card", ".start-card-error", ".start-card-chart", ".start-card-table", "#ready-screen")

ID_PART = re.compile(r"#([\w-]+)")
CLASS_PART = re.compile(r"\.([\w-]+)")
ATTR_PART = re.compile(r"\[\s*([\w-]+)")
HEXLESS = re.compile(r"([^{}]+)\{([^{}]*)\}")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Kum havuzu tmp'nin içine taşınır: test ne ``data/`` ne ``real_datasets/`` dokunur."""
    monkeypatch.setattr(visual_serve, "VISUAL_DIR", tmp_path / "visual")
    return visual_serve.VISUAL_DIR


def visual() -> dict:
    return json.loads(VISUAL_PATH.read_text(encoding="utf-8"))


def page(name: str) -> dict:
    return next(item for item in visual()["pages"] if item["name"] == name)


def fills(page_name: str) -> dict:
    """Sayfanın alanlara yazdığı değerler: ``{seçici: değer}``, son yazan kazanır."""
    return {
        step["fill"][0]: step["fill"][1]
        for step in page(page_name)["steps"]
        if isinstance(step, dict) and "fill" in step
    }


def source_text() -> str:
    """Arayüzün kaynak dosyaları: testler ve sabit veriler değil, bileşenlerin kendileri."""
    files = [
        path
        for path in sorted(SRC_DIR.rglob("*"))
        if path.suffix in (".js", ".jsx") and ".test." not in path.name and "fixtures" not in path.parts
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def missing_parts(selector: str, text: str) -> list[str]:
    """Seçicinin kaynakta karşılığı olmayan parçaları: id'ler, sınıflar ve özellik adları.

    Dört sayfanın id'leri düz yazılıyor (``id="pin-card"``), o yüzden düz arama yeterli; şablonlu
    id'nin genel denetimi ``test_visual_flows``ta duruyor.
    """
    out = []
    for name in ID_PART.findall(selector):
        if f'id="{name}"' not in text:
            out.append(f"id {name}")
    for name in CLASS_PART.findall(selector):
        if not re.search(rf'className="[^"]*\b{re.escape(name)}\b[^"]*"', text):
            out.append(f"sınıf {name}")
    for name in ATTR_PART.findall(selector):
        if not re.search(rf"\b{re.escape(name)}\s*=", text):
            out.append(f"özellik {name}")
    return out


CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """Yaprak kurallar: (seçiciler tek satır, bildirimler). Media kümelerinin içi de okunur."""
    out = []
    for match in HEXLESS.finditer(css):
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


RULES = parse_rules(CSS)


def merged(name: str, rules: list[tuple[str, dict[str, str]]] | None = None) -> dict[str, str]:
    """Bir seçicinin CSS'teki son hâli: onu taşıyan her kuralın bildirimleri sırayla üstüne biner."""
    decls: dict[str, str] = {}
    for selector, rule in RULES if rules is None else rules:
        if any(token == name for token in selector.split()):
            decls.update(rule)
    assert decls, f"{STYLES.name} içinde {name} kuralı yok"
    return decls


# ------------------------------------------------------------------ kum havuzunun iş rolleri


def test_the_three_boards_are_seeded_with_their_business_roles(sandbox):
    """Pano kartları iş rolüne göre geliyor: inceleme en az iki farklı rolün panosunu koşabilmeli."""
    visual_serve.seed_users(sandbox / "bilgin.db")
    users = visual_serve.seed_business_roles(sandbox / "bilgin.db")

    store = UserStore(sandbox / "bilgin.db")
    assert [(u["username"], u["role"], u["business_role"]) for u in store.list_users()] == [
        ("admin", "admin", "yonetim"),
        ("analist", "user", "satis"),
        ("satinalma", "user", "satin_alma"),
    ]
    assert [user["username"] for user in users] == ["admin", "analist", "satinalma"]


def test_the_third_board_account_signs_in_with_the_fixture_password(sandbox):
    """Üçüncü hesap ``USERS``ta yok: ``seed_users``tan sonra açıldığı için parolası da aynı olmalı."""
    visual_serve.seed_users(sandbox / "bilgin.db")
    visual_serve.seed_business_roles(sandbox / "bilgin.db")

    store = UserStore(sandbox / "bilgin.db")
    for username, _role in visual_serve.BUSINESS_USERS:
        assert store.authenticate(username, visual_serve.VISUAL_PASSWORD)["username"] == username


def test_the_seeded_business_roles_are_the_ones_the_product_offers():
    """Küme dosyaları bu adları taşıyor; config'den düşen bir rol akışta boş pano demek."""
    assert {role for _username, role in visual_serve.BUSINESS_USERS} <= set(config.BUSINESS_ROLES)


def test_the_business_step_refuses_a_store_outside_the_sandbox(sandbox):
    """İzolasyonun kendisi yol denetimi: iş rolü adımı da kum havuzu dışındaki bir depoya dokunmaz."""
    outside = sandbox.parent / "bilgin.db"

    with pytest.raises(visual_serve.VisualError):
        visual_serve.seed_business_roles(outside)

    assert not outside.exists(), "reddedilen yol kurulmuş"


# ------------------------------------------------------------------ dört akış sayfası


def test_the_four_run7_pages_are_declared():
    names = [item["name"] for item in visual()["pages"]]

    assert sorted(names) == sorted(set(names)), "aynı adta iki sayfa var; inceleme kareleri çarpışır"
    for name in BOARDS:
        assert name in names, f"{name} akış listesinde yok"


def test_every_board_page_logs_in_as_the_role_whose_cards_it_shoots():
    """Giriş adımı olmayan sayfa panoyu değil giriş kartını çeker; yanlış hesap boş pano çeker."""
    for name, username in BOARDS.items():
        typed = fills(name)
        steps = page(name)["steps"]

        assert typed.get("#login-username") == username, f"{name} {username} ile açılmıyor"
        assert typed.get("#login-password") == visual_serve.VISUAL_PASSWORD, f"{name} yanlış parola yazıyor"
        assert {"click": "#login-submit"} in steps, f"{name} giriş düğmesine basmıyor"


def step_selectors(name: str) -> list[str]:
    """Sayfanın ``click`` ve ``fill`` adımlarının seçicileri; ``wait`` ve ``shot`` taşımaz."""
    found = []
    for step in page(name)["steps"]:
        if not isinstance(step, dict):
            continue
        if "click" in step:
            found.append(step["click"])
        if "fill" in step:
            found.append(step["fill"][0])
    return found


def test_the_board_pages_click_the_card_and_the_ready_screen_actions():
    """Akışın adı neyse tıkı da o: pano kartı, kartın yenilemesi, cevabın hazır soruya dönüşü."""
    touched = {name: step_selectors(name) for name in BOARDS}

    assert "button[data-card-refresh]" in touched["start-sales"]
    assert ".start-card" in touched["card-answer-followup"]
    assert "#pin-card" in touched["card-answer-followup"]
    assert "#ready-suggest" in touched["admin-ready-questions"]
    assert "#make-ready" in touched["admin-ready-questions"]


@pytest.mark.parametrize("name", sorted(BOARDS))
def test_the_page_selectors_exist_in_the_ui_source(name):
    """``from: M24`` kapısı seçicileri M24 bitene dek esirgiyor; pano ekranı burada doğuyor."""
    text = source_text()

    for selector in step_selectors(name):
        missing = missing_parts(selector, text)
        assert not missing, f"{name} akışındaki {selector!r} artık kaynakta yok: {missing}"


# ------------------------------------------------------------------ görünüm


def test_the_phone_rules_stay_in_the_one_max_width_block():
    """Telefon istisnaları tek 720px bloğunda toplanır: ikinci bir blok açılırsa öteki CSS
    testleri hepsini tarar, yenisi sessiz kalır."""
    narrow = [span for span in media_spans(CSS) if upper_bound(span[0]) is not None]
    assert len(narrow) == 1, f"{STYLES.name} içinde {len(narrow)} max-width bloğu var"
    condition, start, end = narrow[0]
    assert upper_bound(condition) == PHONE_PX, f"telefon bloğu {condition.strip()} - {PHONE_PX}px olmalı"

    # Pano telefonda tek sütun; temeli bu bloğun altında durduğu için seçici sınıfıyla derinleşiyor.
    phone = parse_rules(CSS[start:end])
    assert merged("#start.start-grid", phone).get("grid-template-columns") == "1fr"


def test_the_board_is_a_grid_of_260px_tiles():
    start = merged("#start")
    assert start.get("display") == "grid"
    columns = start.get("grid-template-columns", "")
    assert "auto-fill" in columns and "minmax(260px, 1fr)" in columns, columns


def test_the_card_variants_and_the_ready_screen_have_rules():
    for name in CARD_SELECTORS:
        merged(name)


def test_the_gate_navigates_to_every_screen_address():
    """Girişten sonra varılacak adres ``Root.jsx``in tablosundan okunuyor: ``ready`` satırı
    eksik kaldığında kapı adresi ``#/``e çeviriyordu ve ``admin-ready-questions`` akışı defterde
    değil panoda kalıyordu."""
    routes = dict(re.findall(r'"(/[\w-]+)": "(\w+)"', (SRC_DIR / "lib" / "route.js").read_text(encoding="utf-8")))
    hashes = dict(re.findall(r'(\w+): "(#/[\w-]*)"', (SRC_DIR / "Root.jsx").read_text(encoding="utf-8")))
    assert routes and hashes, "ekran listesi ya da adres tablosu okunamadı"

    missing = [f"{path} → {name}" for path, name in routes.items() if hashes.get(name) != f"#{path}"]
    assert not missing, f"girişten sonra bu adreslere gidilemiyor: {missing}"

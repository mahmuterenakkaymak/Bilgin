"""T202: görsel akışların kaynakla birlikte yürümesi (PLAN R5-19).

``.hybrid/visual.json`` kilometre taşı görsel incelemesinin yürüdüğü listedir: tarayıcı oradaki
seçicileri tıklar, yani ekran bir id'yi bıraktığında akış hata vermez - boşluğa tıklar ve yanlış
bir kareyi "doğru" diye gösterir. Bunu önlemek için her ``click``/``fill`` seçicisi arayüzün
kaynağına karşı denetlenir; ayrıca akışın açtığı adres ile onu ayağa kaldıran komut aynı portu
söylemeli ve her sayfa incelemede görünecek bir şey bırakmalı.
"""

import json
import re
from urllib.parse import urlsplit

import pytest

from nl2sql import config

VISUAL_PATH = config.ROOT / ".hybrid" / "visual.json"
SRC_DIR = config.ROOT / "web" / "src"

# Runner'ın akışı kurabildiği anahtarlar: komut, adres, hazırlık yolu ve sayfaların kendisi.
REQUIRED = ("start", "base_url", "ready_path", "pages")

ID_PART = re.compile(r"#([\w-]+)")
CLASS_PART = re.compile(r"\.([\w-]+)")
ATTR_PART = re.compile(r"\[\s*([\w-]+)")

# ``id={`export-${kind}`}`` DOM'da ``id="export-csv"`` üretir: düz id arayan koruyucu böyle bir
# bileşeni "id silinmiş" sayardı. Şablonun kendisi kaynakta okunur, adı ondan türetiyoruz.
TEMPLATE_ID = re.compile(r"id=\{\s*`([^`]*)`\s*\}")
INTERP = re.compile(r"\$\{[^{}]*\}")


def visual() -> dict:
    return json.loads(VISUAL_PATH.read_text(encoding="utf-8"))


def selectors(step) -> list[str]:
    """``click`` ve ``fill`` seçici taşır; ``wait`` ve ``shot`` gibi öteki adımlar taşımaz."""
    if not isinstance(step, dict):
        return []
    found = []
    if "click" in step:
        found.append(step["click"])
    if "fill" in step:
        found.append(step["fill"][0])
    return found


def all_selectors() -> list[tuple[str, str]]:
    return [
        (page["name"], selector)
        for page in visual()["pages"]
        for step in page["steps"]
        for selector in selectors(step)
    ]


def source_text() -> str:
    """Arayüzün kaynak dosyaları: testler ve sabit veriler değil, bileşenlerin kendileri."""
    files = [
        path
        for path in sorted(SRC_DIR.rglob("*"))
        if path.suffix in (".js", ".jsx") and ".test." not in path.name and "fixtures" not in path.parts
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def yields_id(body: str, name: str) -> bool:
    """``${...}`` şablonlu bir id gövdesi ``name`` adını üretebilir mi?

    ``${...}`` en az bir karakter üreten bir boşluktur. Şablonun en az bir düz karakter
    taşıması da koşul: ``id={`${kind}`}`` her adı "üretebilir" ve koruyucu boş bir eşleşmeye
    döner - adın kaynakta okunur bir parçası kalmalı.
    """
    segments = INTERP.split(body)
    if not any(segments):
        return False
    return re.fullmatch(".+?".join(re.escape(segment) for segment in segments), name) is not None


def id_pattern(name: str, text: str) -> re.Pattern:
    """İki yazım da DOM'da aynı id'yi verir: ``id="export-csv"`` ve ``id={`export-${kind}`}``."""
    found = [rf'id="{re.escape(name)}"']
    found += [re.escape(match.group(0)) for match in TEMPLATE_ID.finditer(text) if yields_id(match.group(1), name)]
    return re.compile("|".join(found))


def parts(selector: str, text: str):
    """Seçicinin kaynakta aranacak parçaları: id'ler, sınıflar ve özellik adları.

    Birleştiriciler ve etiketler denetlenmez - ``button``ın düğme olduğu bir id kadar kırılgan
    değil, oysa ``#save-question`` ekranın kaybolduğu ilk anda sessizce ölü bir adıma döner.
    """
    for name in ID_PART.findall(selector):
        yield "id", name, id_pattern(name, text)
    for name in CLASS_PART.findall(selector):
        yield "sınıf", name, re.compile(rf'className="[^"]*\b{re.escape(name)}\b[^"]*"')
    for name in ATTR_PART.findall(selector):
        yield "özellik", name, re.compile(rf'\b{re.escape(name)}\s*=')


def is_shot(step) -> bool:
    return isinstance(step, str) and step.split(":")[0] == "shot"


SELECTORS = all_selectors()


# ------------------------------------------------------------------ dosyanın kendisi


def test_the_flow_file_parses_and_declares_what_the_runner_needs():
    doc = visual()

    for key in REQUIRED:
        assert doc.get(key), f"{key} yok"
    assert doc["ready_path"].startswith("/")
    assert doc["pages"], "akış listesi boş"
    for page in doc["pages"]:
        assert page["name"] and page["path"].startswith("/"), page
        assert page["steps"], f"{page['name']} hiç adım yok"


def test_the_flow_opens_the_address_its_own_command_starts():
    doc = visual()

    port = urlsplit(doc["base_url"]).port
    assert port == config.SERVE_PORT
    assert f"--port {port}" in doc["start"], "start komutu başka bir port açıyor"


# ------------------------------------------------------------------ seçiciler


@pytest.mark.parametrize("page_name,selector", SELECTORS, ids=[f"{n}:{s}" for n, s in SELECTORS])
def test_every_step_selector_still_exists_in_the_ui_source(page_name, selector):
    text = source_text()

    missing = [f"{kind} {name}" for kind, name, pattern in parts(selector, text) if not pattern.search(text)]
    assert not missing, f"{page_name} akışındaki {selector!r} artık kaynakta yok: {missing}"


def test_the_flow_actually_uses_selectors():
    """İd testi boş listede de geçerdi: akışta denenecek seçici olduğunun güvencesi."""
    assert SELECTORS


def test_the_id_guard_reads_a_template_id_but_not_a_renamed_or_hidden_one():
    """Şablonlu id kabul; adın kaynağı değiştiyse/okunur parça kaldırılsa yine kırmızı."""
    assert id_pattern("save-question", 'id="save-question"').search('id="save-question"')
    assert id_pattern("export-csv", 'id={`export-${kind}`}').search('id={`export-${kind}`}')

    assert not id_pattern("export-csv", 'id={`download-${kind}`}').search('id={`download-${kind}`}')
    assert not id_pattern("export-csv", "id={`${kind}`}").search("id={`${kind}`}")
    assert not id_pattern("export-csv", "<a href='#' />").search("<a href='#' />")


# ------------------------------------------------------------------ kareler


def test_every_page_shoots_something_or_ends_on_a_state():
    # ASSUMPTION: "durumda bitmek" son adımı bir etkileşim olan sayfadır - ekran o durumda
    # kalır, inceleme onu bir sonraki sayfanın ilk karesinde görür.
    for page in visual()["pages"]:
        ends_on_a_state = isinstance(page["steps"][-1], dict)
        assert any(is_shot(step) for step in page["steps"]) or ends_on_a_state, page["name"]

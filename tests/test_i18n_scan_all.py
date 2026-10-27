"""T425: sunucunun tamamının literal taraması - R8-4'ün modül listesi tek yerde burada koşulur.

Her geçiş görevi kendi modülüne "kullanıcıya Türkçe konuşan bir sabit kaldı mı?" diye sormuştu; bu
test aynı soruyu R8-4'ün *tam* listesine sorar, o yüzden bir modülün taraması kendi görevinden
düşse bile burada sessiz kalmaz. ``ALLOW`` yalnız modele giden sabitleri ve eşleştirme tablolarını
affeder - ekrana çıkmadıkları için kataloğa taşınmazlar; listeye giren her adın üstünde tek satır
sebebi durur. Listede adı geçen bir dosya artık yoksa test ağlar: taramanın sustuğu bir modül
haritadan silinmesin.
"""

from pathlib import Path

import pytest

from nl2sql.i18n.scan import user_literals

ROOT = Path(__file__).resolve().parents[1]

# PLAN R8-4 "Scanned modules (final list)" - kalıplar olduğu gibi oradan alındı.
PATTERNS = (
    "nl2sql/web/*.py",
    "nl2sql/cli/*.py",
    "nl2sql/app/ask.py",
    "nl2sql/report/{facts,narrate,chart,export,guard}.py",
    "nl2sql/eval/{report,runner,followups,compare,compare_models,compare_modes,retrieval}.py",
    "nl2sql/schema_map/{template,template_import,onboard,rules_edit,rules}.py",
    "nl2sql/engine/{guard,connections,dbstatus,dpapi}.py",
    "nl2sql/auth/store.py",
    "nl2sql/start/{ready,cards,suggest,seed}.py",
    "nl2sql/agent/{refine,context}.py",
)

# Muafiyet yalnız model-facing sabitler ve eşleştirme tabloları içindir; gerekçesiz ad giremez.
ALLOW = {
    # `sample_values` çıktısındaki "Değerler (N)" satırını eşleştiren regex - ekran satırı değil.
    "nl2sql/cli/main.py": ("VALUE_COUNT",),
    # Türkçe anlatıcının system promptu; İngilizce kopyası SYSTEM_EN'de, ikisi de modele gider.
    "nl2sql/report/narrate.py": ("SYSTEM",),
    # Grafik sözcüklerini katlayan Türkçe harf tablosu - `fold` okur, kullanıcı görmez.
    "nl2sql/report/chart.py": ("_FOLD",),
    # Şablonun iki dilin etiket tablosu: xlsx hücreleridir, İngilizcesi LABELS["en"]de.
    "nl2sql/schema_map/template.py": ("LABELS",),
    # Kural bloğunun bölük etiketleri: prompt bölümü ve indeks belgesi, ekran değil.
    "nl2sql/schema_map/rules.py": ("RULE_LABELS",),
    # Öneriyi yazan modele giden system prompt ve bölük başlıkları.
    "nl2sql/start/suggest.py": ("SYSTEM", "SECTIONS"),
    # Tohum satırı politika süzgecinden düşerse günlük satırına yazılan teknik not.
    "nl2sql/start/seed.py": ("SKIPPED",),
    # Eşleştirme tabloları: grafik isteği, doldurma sözcükleri, dönüm ipuçları, harf katlaması.
    "nl2sql/agent/refine.py": (
        "CHART_WISHES",
        "CHART_FILLERS",
        "REFINE_HINTS",
        "TOP_WORDS",
        "TOP_HINT",
        "ENTITY_NOUNS",
        "ENTITY_MARKERS",
        "ENTITY_PLURAL",
        "ENTITY_PERIOD_WORDS",
        "_TURKISH_TO_ASCII",
    ),
    # Modelin okuduğu bağlam bloğu: başlık, kurallar, tur satırları, ipuçları, not düşme gerekçeleri.
    "nl2sql/agent/context.py": (
        "HISTORY_HEADER",
        "FOLLOWUP_RULES",
        "TURN_LINES",
        "HINTS",
        "NOTE_REASONS",
    ),
}


def _expand(pattern: str) -> list[str]:
    if "{" in pattern:
        head, rest = pattern.split("{", 1)
        names, tail = rest.split("}", 1)
        return [head + name + tail for name in names.split(",")]
    return [path.relative_to(ROOT).as_posix() for path in sorted(ROOT.glob(pattern))]


MODULES = [module for pattern in PATTERNS for module in _expand(pattern)]


def test_every_pattern_covers_a_module():
    for pattern in PATTERNS:
        assert _expand(pattern), f"R8-4 kalıbı hiçbir modüle denk gelmiyor: {pattern}"


def test_allow_names_only_scanned_modules():
    assert set(ALLOW) <= set(MODULES), f"tarama dışında modül affediliyor: {sorted(set(ALLOW) - set(MODULES))}"


@pytest.mark.parametrize("module", MODULES)
def test_module_has_no_turkish_user_literals(module):
    path = ROOT / module
    assert path.is_file(), f"R8-4 listesindeki modül artık yok: {module}"
    assert user_literals(path, allow=ALLOW.get(module, ())) == []

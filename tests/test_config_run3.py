"""Run 3 config: yeni ayarlar, şema üretim yolları ve .gitignore kuralları.

``schema/`` altındaki import çıktıları (imported/skeleton/diff/mapping) makine üretimi-
dir; depo köküne sabitlenmiş kalıplar eler. ``--no-index`` izlenen yolları da sınadığı
için ``schema/schema.json`` gibi elle yazılan dosyaların elenmediği aynı komutla doğrulanır.
"""

import subprocess

from nl2sql import config


def check_ignore(path: str) -> int:
    """Yol elenme kuralına mı takılıyor; 0 = eleniyor, 1 = elenmiyor."""
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
    ).returncode


def test_run1_run2_tunables_unchanged():
    assert config.AS_OF == "2026-09-30"
    assert config.SEED == 42
    assert config.TOP_N == 1000
    assert config.MODEL_MAX_ROWS == 50
    assert config.COMPARE_MAX_ROWS == 100000
    assert config.MODES == ("full", "full_rules", "rag")
    assert config.SEARCH_K == 5
    assert config.SAMPLE_VALUES_N == 20


def test_run3_tunables_match_plan():
    assert config.EXCEL_PREVIEW_ROWS == 20
    assert config.AUTO_FULL_MAX_TOKENS == 12000
    assert config.NEIGHBOUR_EXPANSION is True
    assert config.NEIGHBOUR_MAX == 3
    assert config.SYNONYM_REWRITE is True
    assert config.SAMPLE_HINT_N == 5
    assert config.SAMPLE_HINT_MAX_LEN == 100


def test_run3_values_are_sane():
    assert config.EXCEL_PREVIEW_ROWS > 0
    assert config.AUTO_FULL_MAX_TOKENS > 0
    assert config.NEIGHBOUR_MAX > 0
    assert config.SAMPLE_HINT_N > 0
    assert config.SAMPLE_HINT_MAX_LEN > 0
    assert config.SAMPLE_HINT_N <= config.EXCEL_PREVIEW_ROWS


def test_pii_filter_lists_every_class():
    assert isinstance(config.PII_FILTER, frozenset)
    assert config.PII_FILTER == frozenset(
        {"tckn", "vkn", "iban", "phone", "email", "address", "salary", "person_name"}
    )
    assert len(config.PII_FILTER) == 8


def test_pii_filter_is_immutable():
    try:
        config.PII_FILTER.add("plaka")
    except AttributeError:
        return
    raise AssertionError("PII_FILTER değişebiliyor; varsayılanları test edilmemeli.")


def test_run3_paths_absolute_and_named():
    expected = {
        "SCHEMA_DIR": "schema",
        "IMPORTED_PATH": "schema/imported.json",
        "SKELETON_PATH": "schema/skeleton.json",
        "DIFF_JSON_PATH": "schema/diff.json",
        "DIFF_MD_PATH": "schema/diff.md",
        "LOGIN_SCRIPT_PATH": "db/mssql/readonly_login.sql",
    }
    for name, relative in expected.items():
        path = getattr(config, name)
        assert path.is_absolute(), name
        assert path.relative_to(config.ROOT).as_posix() == relative, name


def test_schema_outputs_sit_in_schema_dir():
    for name in ("IMPORTED_PATH", "SKELETON_PATH", "DIFF_JSON_PATH", "DIFF_MD_PATH"):
        assert getattr(config, name).parent == config.SCHEMA_DIR, name


def test_run3_paths_do_not_collide_with_existing():
    existing = {
        config.SCHEMA_PATH,
        config.RULES_PATH,
        config.INDEX_DIR,
        config.MSSQL_SCRIPT,
    }
    run3 = {
        config.SCHEMA_DIR,
        config.IMPORTED_PATH,
        config.SKELETON_PATH,
        config.DIFF_JSON_PATH,
        config.DIFF_MD_PATH,
        config.LOGIN_SCRIPT_PATH,
    }
    assert not existing & run3


def test_mapping_path_helper():
    path = config.mapping_path("stok")
    assert path.is_absolute()
    assert path.relative_to(config.ROOT).as_posix() == "schema/mapping.stok.json"
    assert path.parent == config.SCHEMA_DIR


def test_mapping_path_one_file_per_name():
    assert config.mapping_path("stok") != config.mapping_path("cari")
    assert config.mapping_path("stok").name == "mapping.stok.json"


def test_run3_build_outputs_are_ignored():
    for path in (
        "schema/imported.json",
        "schema/skeleton.json",
        "schema/diff.json",
        "schema/diff.md",
        "schema/mapping.stok.json",
    ):
        assert check_ignore(path) == 0, path


def test_handwritten_schema_files_are_not_ignored():
    for path in ("schema/schema.json", "schema/rules.json"):
        assert check_ignore(path) != 0, path

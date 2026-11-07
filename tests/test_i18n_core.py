# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""The guard every later i18n task has to pass: both catalogs carry the same keys and params."""

import json
import string

import pytest

from bilgin import config, i18n

CATALOG_LANGS = ("tr", "en")


def load(lang: str) -> dict[str, str]:
    return json.loads((i18n.CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture
def catalogs(monkeypatch, tmp_path):
    """Point the loader at a throwaway pair of catalogs instead of the shipped ones."""

    def write(**by_lang: dict[str, str]):
        for lang, texts in by_lang.items():
            (tmp_path / f"{lang}.json").write_text(json.dumps(texts), encoding="utf-8")
        monkeypatch.setattr(i18n, "CATALOG_DIR", tmp_path)
        i18n._catalog.cache_clear()

    write()
    yield write
    i18n._catalog.cache_clear()


def test_catalogs_have_identical_keys():
    assert set(load("tr")) == set(load("en"))


def test_every_key_has_the_same_placeholders():
    tr, en = load("tr"), load("en")
    for key in set(tr) & set(en):
        assert placeholders(tr[key]) == placeholders(en[key]), key


def test_keys_are_flat_dotted_and_values_are_text():
    for lang in CATALOG_LANGS:
        for key, value in load(lang).items():
            assert isinstance(key, str) and isinstance(value, str), lang
            assert key.strip(".") == key and "." in key, key


def test_language_names_are_cataloged():
    assert load("tr")["lang.tr"] == "Türkçe"
    assert load("en")["lang.tr"] == "Turkish"
    assert load("en")["lang.en"] == "English"
    assert load("tr")["lang.en"] == "İngilizce"


def test_unknown_language_uses_turkish(catalogs):
    catalogs(tr={"ask.hi": "merhaba"}, en={"ask.hi": "hello"})
    assert i18n.t("ask.hi", "de") == "merhaba"


def test_key_missing_in_language_uses_turkish(catalogs):
    catalogs(tr={"ask.hi": "merhaba"}, en={})
    assert i18n.t("ask.hi", "en") == "merhaba"


def test_key_missing_in_turkish_raises(catalogs, monkeypatch):
    monkeypatch.delenv("BILGIN_LANG", raising=False)
    catalogs(tr={}, en={"other.key": "hello"})
    with pytest.raises(KeyError, match="ask.hi"):
        i18n.t("ask.hi", "en")
    with pytest.raises(KeyError, match="ask.hi"):
        i18n.t("ask.hi")


def test_params_are_substituted(catalogs):
    catalogs(
        tr={"facts.rows": "{name}: {count} satır"},
        en={"facts.rows": "{name}: {count} rows"},
    )
    assert i18n.t("facts.rows", "tr", name="wwi", count=5) == "wwi: 5 satır"
    assert i18n.t("facts.rows", "en", name="wwi", count=5) == "wwi: 5 rows"


def test_text_without_params_is_returned_as_is(catalogs):
    catalogs(tr={"ask.hi": "merhaba {adi}"}, en={"ask.hi": "hello {name}"})
    assert i18n.t("ask.hi", "tr") == "merhaba {adi}"


def test_lang_none_follows_nl2sql_lang(catalogs, monkeypatch):
    catalogs(tr={"ask.hi": "merhaba"}, en={"ask.hi": "hello"})
    monkeypatch.setenv("BILGIN_LANG", "en")
    assert i18n.t("ask.hi") == "hello"


@pytest.mark.parametrize(
    "value, expected",
    [("tr", "tr"), ("EN", "en"), (" en ", "en"), ("en-US", "en"), ("tr_TR", "tr")],
)
def test_normalize_lang_accepts_language_names(value, expected):
    assert i18n.normalize_lang(value) == expected


@pytest.mark.parametrize("value", ["de", "english", "", "   ", None, 1, True])
def test_normalize_lang_rejects_anything_else(value):
    assert i18n.normalize_lang(value) is None


def test_run8_config_names():
    assert config.LANGUAGES == ("tr", "en")
    assert config.DEFAULT_LANG == "tr"
    assert config.TEMPLATE_FILENAMES == {
        "tr": "bilgin-veritabani-sablonu.xlsx",
        "en": "bilgin-database-template.xlsx",
    }
    assert config.TEMPLATE_FILENAMES["tr"] == config.TEMPLATE_FILENAME
    assert config.SERVICE_NAME == "Bilgin"
    assert config.SERVICE_PORT == config.SERVE_PORT
    assert config.SERVICE_HOME == r"C:\ProgramData\Bilgin"
    assert config.FOLLOWUP_MARKERS_EN == (
        "this",
        "these",
        "those",
        "it",
        "them",
        "that",
        "same",
        "only",
        "just",
        "their",
        "its",
    )
    for words in (config.DETECT_EN_WORDS, config.DETECT_TR_WORDS):
        assert len(words) >= 25 and len(set(words)) == len(words)
        assert all(w == w.strip().lower() for w in words)


def test_lang_default_without_env(monkeypatch):
    monkeypatch.delenv("BILGIN_LANG", raising=False)
    assert config.lang() == config.DEFAULT_LANG == "tr"


def test_lang_reads_env(monkeypatch):
    monkeypatch.setenv("BILGIN_LANG", "en")
    assert config.lang() == "en"


@pytest.mark.parametrize("value", ["xx", "fr", "TR"])
def test_lang_unknown_value_falls_back_without_crashing(monkeypatch, value):
    monkeypatch.setenv("BILGIN_LANG", value)
    assert config.lang() == "tr"

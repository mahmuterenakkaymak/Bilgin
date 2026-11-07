# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 7 config (PLAN R7-1): konuşma, başlangıç ekranı ve veritabanı bağlantısı sabitleri.

``FOLLOWUP_MARKERS`` küçültülmüş metinle karşılaştırılır, o yüzden her öğe küçük harfli olmalı.
``BUSINESS_ROLES`` sıralı bir sözlüktür: kartların ve rol seçeneklerinin listelenme sırası bu sıra.
"""

import pytest

from bilgin import config

RUN7_VALUES = {
    "CONV_KEEP_ROWS": 5,
    "CONV_TURNS": 3,
    "CONV_TITLE_CHARS": 80,
    "DEFAULT_BUSINESS_ROLE": "genel",
    "PERSONAL_CARDS": 6,
    "START_CACHE_S": 300,
    "CARD_REFRESH_MIN_S": 30,
    "CARD_TABLE_ROWS": 10,
    "SUGGEST_PER_ROLE": (2, 4),
    "DB_CHECK_S": 60,
    "DB_CHECK_TIMEOUT_S": 3,
    "CONN_ENV_PREFIX": "BILGIN_MSSQL_CONN_",
    "CONN_TABLE_SAMPLE": 10,
}


@pytest.mark.parametrize("name", sorted(RUN7_VALUES))
def test_run7_name_exists_with_its_value(name):
    assert getattr(config, name) == RUN7_VALUES[name]


def test_run7_followup_markers_are_the_plan_tuple():
    assert config.FOLLOWUP_MARKERS == (
        "bu",
        "bunlar",
        "bunları",
        "bunların",
        "şu",
        "şunlar",
        "o",
        "onlar",
        "aynı",
        "sadece",
        "yalnız",
        "bunu",
        "peki",
        "ya",
        "bunlardan",
        "onun",
        "bunun",
    )


def test_run7_followup_markers_are_lowercase_words():
    for marker in config.FOLLOWUP_MARKERS:
        assert isinstance(marker, str) and marker.strip() == marker and marker, marker
        assert marker == marker.lower(), marker
    assert len(set(config.FOLLOWUP_MARKERS)) == len(config.FOLLOWUP_MARKERS)


def test_run7_business_roles_in_plan_order():
    assert list(config.BUSINESS_ROLES) == [
        "satis",
        "satin_alma",
        "muhasebe",
        "yonetim",
        "genel",
    ]
    assert list(config.BUSINESS_ROLES.values()) == [
        "Satış",
        "Satın alma",
        "Muhasebe",
        "Yönetim",
        "Genel",
    ]


def test_run7_default_business_role_is_a_known_role():
    assert config.DEFAULT_BUSINESS_ROLE in config.BUSINESS_ROLES


def test_run7_counts_are_ints():
    for name in (
        "CONV_KEEP_ROWS",
        "CONV_TURNS",
        "CONV_TITLE_CHARS",
        "PERSONAL_CARDS",
        "START_CACHE_S",
        "CARD_REFRESH_MIN_S",
        "CARD_TABLE_ROWS",
        "DB_CHECK_S",
        "DB_CHECK_TIMEOUT_S",
        "CONN_TABLE_SAMPLE",
    ):
        value = getattr(config, name)
        assert isinstance(value, int) and not isinstance(value, bool), name

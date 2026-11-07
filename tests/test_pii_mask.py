# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""mask() her sınıfta satırı tanıtacak kadarını bırakır, ham değeri geri vermez (R3-6)."""

import pytest

from bilgin.policy import pii


def test_classes_are_the_eight():
    assert set(pii.CLASSES) == {
        "tckn",
        "vkn",
        "iban",
        "phone",
        "email",
        "address",
        "salary",
        "person_name",
    }


def test_tckn_keeps_the_last_four():
    assert pii.mask("tckn", "12345678901") == "*******8901"


def test_vkn_keeps_the_last_four():
    assert pii.mask("vkn", "1234567890") == "*******7890"


def test_iban_keeps_the_prefix_and_the_last_four():
    assert pii.mask("iban", "TR33 0006 1288 1282 7010 0000 09") == "TR** **** **** **** 0009"


def test_phone_keeps_the_last_three_digits():
    assert pii.mask("phone", "0212 345 67 89") == "*** ** 789"


def test_email_keeps_the_first_letter_and_the_domain():
    assert pii.mask("email", "eren.kimse@example.com") == "e***@example.com"


def test_email_without_a_domain_is_fully_masked():
    assert pii.mask("email", "bozuk-metin") == "***"


def test_address_keeps_the_first_segment():
    assert pii.mask("address", "Caferağa Mah. Moda Cad., Kadıköy/İstanbul") == "Caferağa Mah. Moda Cad."


def test_salary_is_never_shown():
    assert pii.mask("salary", "12345,67") == "***"


def test_person_name_keeps_the_initials():
    assert pii.mask("person_name", "Eren Kemal") == "E. K."


def test_person_name_keeps_the_initials_of_a_dotted_name():
    assert pii.mask("person_name", "İbrahim Şahin") == "İ. Ş."


def test_none_stays_none():
    for cls in pii.CLASSES:
        assert pii.mask(cls, None) is None


def test_blank_stays_blank():
    for cls in pii.CLASSES:
        assert pii.mask(cls, "") == ""


def test_non_str_values_are_read_as_text():
    assert pii.mask("tckn", 12345678901) == "*******8901"
    assert pii.mask("salary", 12345.67) == "***"


def test_unknown_class_is_refused():
    with pytest.raises(ValueError):
        pii.mask("kredi_karti", "1234")

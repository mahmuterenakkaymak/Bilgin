"""DPAPI secret box: a stored password seals to its own dataset (PLAN R7-22)."""

from __future__ import annotations

import secrets
import sys

import pytest

from nl2sql.engine import dpapi

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI yalnız Windows'ta vardır")


def test_round_trip():
    password = secrets.token_urlsafe(12).encode("utf-8")
    entropy = dpapi.entropy_for("wwi_real")

    assert dpapi.unprotect(dpapi.protect(password, entropy), entropy) == password


def test_blob_does_not_carry_the_plaintext():
    password = secrets.token_urlsafe(12).encode("utf-8")

    blob = dpapi.protect(password, dpapi.entropy_for("wwi_real"))

    assert blob != password
    assert password not in blob


def test_another_datasets_entropy_does_not_open_the_blob():
    password = b"GizliParola!"
    blob = dpapi.protect(password, dpapi.entropy_for("wwi_real"))

    with pytest.raises(ValueError):
        dpapi.unprotect(blob, dpapi.entropy_for("synthetic_erp"))


def test_empty_value_round_trips():
    entropy = dpapi.entropy_for("wwi_real")

    assert dpapi.unprotect(dpapi.protect(b"", entropy), entropy) == b""

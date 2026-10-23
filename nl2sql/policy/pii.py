"""Masked display values for PII columns (PLAN R3-6).

The executor masks every value that traces back to a column carrying `pii`, so the model,
the CLI and the eval only ever see the forms below. Each class keeps the smallest part that
still lets a reader recognise which row they are looking at - the tail of an account number,
the city of an address - and drops everything else; none of it is reversible.
"""

from __future__ import annotations

import re

CLASSES = (
    "tckn",
    "vkn",
    "iban",
    "phone",
    "email",
    "address",
    "salary",
    "person_name",
)

_WORDS = re.compile(r"[^\W\d_]+")


def mask(cls: str, value) -> str | None:
    """Masked text for one PII class: None stays None, a blank stays blank, a non-str is read as text."""
    if value is None:
        return None
    if cls not in CLASSES:
        raise ValueError(f"bilinmeyen pii sınıfı: {cls}")
    text = value if isinstance(value, str) else str(value)
    if not text.strip():
        return ""
    return _MASKERS[cls](text)


def _tail(text: str, n: int, digits_only: bool = False) -> str:
    """Last n characters of the value with its formatting (spaces) removed."""
    keep = str.isdigit if digits_only else lambda ch: not ch.isspace()
    return "".join(ch for ch in text if keep(ch))[-n:]


def _id_number(text: str) -> str:
    return "*******" + _tail(text, 4, digits_only=True)


def _iban(text: str) -> str:
    return "TR** **** **** **** " + _tail(text, 4)


def _phone(text: str) -> str:
    return "*** ** " + _tail(text, 3, digits_only=True)


def _salary(text: str) -> str:
    return "***"


def _address(text: str) -> str:
    return text.split(",")[0].strip()


def _email(text: str) -> str:
    local, at, domain = text.strip().rpartition("@")
    if not at:
        return "***"
    return f"{local[:1]}***@{domain}"


def _person_name(text: str) -> str:
    return " ".join(f"{word[0].upper()}." for word in _WORDS.findall(text))


_MASKERS = {
    "tckn": _id_number,
    "vkn": _id_number,
    "iban": _iban,
    "phone": _phone,
    "email": _email,
    "address": _address,
    "salary": _salary,
    "person_name": _person_name,
}

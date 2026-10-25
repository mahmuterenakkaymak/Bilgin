"""Run 6 parola karması: scrypt biçimi, tuz, doğrulama ve yeni parola denetimi.

Saklanan değer ``scrypt$n$r$p$salt_b64$hash_b64``; parçalar sabit sırada ve altı tanedir.
Doğrulama saklanan n/r/p ile yeniden hesaplar, bozuk/foreign değer asla istisna vermez.
"""

import base64
import hashlib

from nl2sql import config
from nl2sql.auth import passwords

PAROLA = "Bilgin2026!erp"


def test_round_trip():
    stored = passwords.hash_password(PAROLA)
    assert passwords.verify_password(PAROLA, stored) is True


def test_wrong_password_fails():
    stored = passwords.hash_password(PAROLA)
    assert passwords.verify_password("Bilgin2026!ERP", stored) is False


def test_stored_format_has_six_parts_with_config_params():
    parts = passwords.hash_password(PAROLA).split("$")
    assert len(parts) == 6
    assert parts[0] == "scrypt"
    assert parts[1:4] == [str(config.SCRYPT_N), str(config.SCRYPT_R), str(config.SCRYPT_P)]
    assert len(base64.b64decode(parts[4])) == 16  # salt
    assert len(base64.b64decode(parts[5])) == 32  # hash


def test_same_password_two_salts_two_hashes():
    first = passwords.hash_password(PAROLA)
    second = passwords.hash_password(PAROLA)
    assert first != second
    assert passwords.verify_password(PAROLA, first) is True
    assert passwords.verify_password(PAROLA, second) is True


def test_verify_uses_the_params_stored_in_the_value():
    """Farklı (düşük) maliyetle yazılmış eski kayıt yine doğrulanır."""
    raw = b"0123456789abcdef"
    digest = hashlib.scrypt(
        PAROLA.encode("utf-8"), salt=raw, n=1024, r=8, p=1, dklen=32, maxmem=passwords.MAXMEM
    )
    stored = "$".join(
        ("scrypt", "1024", "8", "1", base64.b64encode(raw).decode("ascii"),
         base64.b64encode(digest).decode("ascii"))
    )
    assert passwords.verify_password(PAROLA, stored) is True


def test_malformed_or_foreign_stored_values_give_false():
    stored = passwords.hash_password(PAROLA)
    scheme, n, r, p, salt, _ = stored.split("$")
    bad = [
        "",
        "scrypt",
        f"{scheme}${n}${r}${p}{salt}",  # beş parça
        f"bcrypt${n}${r}${p}${salt}${salt}",  # başka şema
        f"{scheme}${n}${r}${p}!!!${salt}",  # bozuk base64 tuz
        f"{scheme}${n}x${r}${p}${salt}${salt}",  # sayı olmayan n
        f"{scheme}${n}${r}${p}${salt}{'A' * 200}",  # tutarsız hash uzunluğu
        None,
    ]
    for value in bad:
        assert passwords.verify_password(PAROLA, value) is False


def test_short_password_message_and_ok_password():
    message = "Parola en az 10 karakter olmalı."
    assert passwords.check_new_password("Kisa1!") == message
    assert passwords.check_new_password("a" * (config.PASSWORD_MIN_LEN - 1)) == message
    assert passwords.check_new_password("a" * config.PASSWORD_MIN_LEN) is None
    assert passwords.check_new_password("UzunYeterli10!") is None


def test_plain_password_not_in_stored_value():
    stored = passwords.hash_password(PAROLA)
    assert PAROLA not in stored
    assert PAROLA.encode("utf-8").hex() not in stored

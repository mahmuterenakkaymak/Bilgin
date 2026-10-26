"""DPAPI secret box (PLAN R7-22).

A database password is kept only as a Windows DPAPI blob: the key lives in the machine's own
master key file, so the app database, the repository and every log stay free of the plaintext,
and a blob copied to another machine simply does not open. The scope is LOCAL MACHINE because the
app runs as a service account, not as whoever typed the password into the form.

Entropy is the dataset name (``entropy_for``): one stolen blob cannot be replayed as another
dataset's connection, and a wrong dataset fails to decrypt instead of returning garbage.
"""

from __future__ import annotations

import ctypes
import functools
import hashlib
import sys
from ctypes import wintypes

ENTROPY_PREFIX = "bilgin-conn:"
CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04
_FLAGS = CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE


class DpapiUnavailable(RuntimeError):
    """This OS (or this crypt32 call) cannot protect or unprotect a secret."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def available() -> bool:
    """True when protect/unprotect can work here; the API answers 409 when it is False."""
    try:
        _api()
    except (DpapiUnavailable, OSError, AttributeError):
        return False
    return True


def entropy_for(dataset: str) -> bytes:
    """The blob's extra secret for one dataset: sha256("bilgin-conn:" + dataset)."""
    return hashlib.sha256((ENTROPY_PREFIX + dataset).encode("utf-8")).digest()


def protect(data: bytes, entropy: bytes) -> bytes:
    """DPAPI-encrypt ``data``; the result is safe to store in the app database."""
    return _call(_api()[0], data, entropy, DpapiUnavailable, "Bu sunucuda sır şifrelenemedi")


def unprotect(blob: bytes, entropy: bytes) -> bytes:
    """The plaintext behind ``blob``, or ValueError when the entropy is not the one it sealed to."""
    return _call(_api()[1], blob, entropy, ValueError, "Bağlantı sırrı çözülemedi")


@functools.lru_cache(maxsize=1)
def _api():
    if sys.platform != "win32":
        raise DpapiUnavailable("DPAPI yalnız Windows'ta vardır.")
    crypt32 = ctypes.windll.crypt32
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.restype = wintypes.HANDLE
    local_free.argtypes = [ctypes.c_void_p]
    functions = []
    for name in ("CryptProtectData", "CryptUnprotectData"):
        function = getattr(crypt32, name)
        function.restype = wintypes.BOOL
        function.argtypes = [
            ctypes.POINTER(_DataBlob),  # pDataIn
            wintypes.LPCWSTR,  # szDataDescr
            ctypes.POINTER(_DataBlob),  # pOptionalEntropy
            ctypes.c_void_p,  # pvReserved
            ctypes.c_void_p,  # pPromptStruct
            wintypes.DWORD,  # dwFlags
            ctypes.POINTER(_DataBlob),  # pDataOut
        ]
        functions.append(function)
    return functions[0], functions[1], local_free


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    # A 0-length buffer has no address Windows may read, so the smallest buffer is one byte;
    # cbData stays 0 and the extra byte is never looked at.
    buffer = ctypes.create_string_buffer(data, max(len(data), 1))
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _call(function, value: bytes, entropy: bytes, error: type, message: str) -> bytes:
    blob_in, keep_in = _blob(value)
    blob_entropy, keep_entropy = _blob(entropy)
    blob_out = _DataBlob()
    ok = function(
        ctypes.byref(blob_in),
        None,
        ctypes.byref(blob_entropy),
        None,
        None,
        _FLAGS,
        ctypes.byref(blob_out),
        use_last_error=True,
    )
    if not ok:
        # ASSUMPTION: koruma tarafındaki hata ortamın yeteneğidir (DpapiUnavailable -> API 409),
        # çözmedeki hata ise yanlış entropy / bozuk blob, yani çağıranın verdiği bir değer (ValueError).
        raise error(f"{message} (WinError {ctypes.get_last_error()}).")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        # crypt32 allocated the output; anything but LocalFree leaks it.
        _api()[2](blob_out.pbData)

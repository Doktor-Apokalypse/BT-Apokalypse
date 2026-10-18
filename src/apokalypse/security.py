from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import os
from ctypes import wintypes

PASSWORD_ROUNDS = 310_000


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("WebUI password must be at least 8 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ROUNDS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.urlsafe_b64decode(salt),
            int(rounds),
        )
        return hmac.compare_digest(digest, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


class _DataBlob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(value)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(value), pointer), buffer


def _windows_crypto_functions():
    protect = ctypes.windll.crypt32.CryptProtectData
    unprotect = ctypes.windll.crypt32.CryptUnprotectData
    arguments = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    protect.argtypes = arguments
    protect.restype = wintypes.BOOL
    unprotect.argtypes = arguments
    unprotect.restype = wintypes.BOOL
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    return protect, unprotect, local_free


def protect_secret(value: str) -> str:
    if not value:
        return ""
    raw = value.encode("utf-8")
    if os.name != "nt":
        return "plain:" + base64.urlsafe_b64encode(raw).decode("ascii")
    protect, _, local_free = _windows_crypto_functions()
    source, source_buffer = _blob(raw)
    protected = _DataBlob()
    if not protect(
            ctypes.byref(source),
            "BT Apokalypse",
            None,
            None,
            None,
            0x01,
            ctypes.byref(protected),
    ):
        raise OSError("Windows could not protect the proxy password")
    try:
        encrypted = ctypes.string_at(protected.data, protected.size)
        return "dpapi:" + base64.urlsafe_b64encode(encrypted).decode("ascii")
    finally:
        local_free(protected.data)
        del source_buffer


def unprotect_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith("plain:"):
        return base64.urlsafe_b64decode(value[6:]).decode("utf-8")
    if not value.startswith("dpapi:"):
        return value
    if os.name != "nt":
        return ""
    _, unprotect, local_free = _windows_crypto_functions()
    encrypted = base64.urlsafe_b64decode(value[6:])
    source, source_buffer = _blob(encrypted)
    clear = _DataBlob()
    if not unprotect(
            ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(clear)
    ):
        return ""
    try:
        return ctypes.string_at(clear.data, clear.size).decode("utf-8")
    finally:
        local_free(clear.data)
        del source_buffer

from __future__ import annotations

import base64
import os
from typing import Optional


_PREFIX = "enc:v1:"


def secrets_encryption_enabled() -> bool:
    flag = os.environ.get("AIMN_SECRETS_ENCRYPTION", "1").strip().lower()
    if flag in {"0", "false", "no"}:
        return False
    return os.name == "nt"


def encrypt_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    if text.startswith(_PREFIX):
        return text
    if not secrets_encryption_enabled():
        return text
    blob = _dpapi_encrypt(text.encode("utf-8"))
    if not blob:
        return text
    encoded = base64.urlsafe_b64encode(blob).decode("ascii")
    return f"{_PREFIX}{encoded}"


def decrypt_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    if not text.startswith(_PREFIX):
        return text
    payload = text[len(_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
    except Exception:
        return text
    decoded = _dpapi_decrypt(raw)
    if decoded is None:
        return text
    try:
        return decoded.decode("utf-8")
    except Exception:
        return text


def _dpapi_encrypt(data: bytes) -> Optional[bytes]:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    if os.name != "nt":
        return None
    if not data:
        return b""

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def _to_blob(raw: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
        buffer = ctypes.create_string_buffer(raw)
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        return DATA_BLOB(len(raw), pointer), buffer

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buffer = _to_blob(data)
    out_blob = DATA_BLOB()
    description = "AIMN secrets"
    result = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not result:
        return None
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return bytes(protected)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
        _ = in_buffer


def _dpapi_decrypt(data: bytes) -> Optional[bytes]:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    if os.name != "nt":
        return None
    if not data:
        return b""

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def _to_blob(raw: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
        buffer = ctypes.create_string_buffer(raw)
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        return DATA_BLOB(len(raw), pointer), buffer

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buffer = _to_blob(data)
    out_blob = DATA_BLOB()
    result = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not result:
        return None
    try:
        decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return bytes(decrypted)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
        _ = in_buffer


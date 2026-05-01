from __future__ import annotations

import base64
import hashlib
import random
from functools import lru_cache
from math import gcd


def sign_rsa_sha256(message: bytes, private_exponent: int, modulus: int) -> str:
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
    key_size = (modulus.bit_length() + 7) // 8
    padding_length = key_size - len(digest_info) - 3
    if padding_length < 8:
        raise ValueError("rsa_key_too_small")
    encoded = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), private_exponent, modulus)
    return base64.b64encode(signature.to_bytes(key_size, "big")).decode("ascii")


@lru_cache(maxsize=None)
def generate_test_rsa_keypair(seed: str = "default") -> dict[str, int | str]:
    rng = random.Random(f"20260313:{seed}")
    e = 65537
    while True:
        p = _generate_prime(256, rng)
        q = _generate_prime(256, rng)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if gcd(e, phi) == 1:
            break
    n = p * q
    d = pow(e, -1, phi)
    return {
        "public_exponent": e,
        "private_exponent": d,
        "modulus": n,
        "modulus_hex": format(n, "x"),
    }


def _generate_prime(bits: int, rng: random.Random) -> int:
    while True:
        candidate = rng.getrandbits(bits)
        candidate |= (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def _is_probable_prime(value: int, rounds: int = 8) -> bool:
    if value in (2, 3):
        return True
    if value < 2 or value % 2 == 0:
        return False
    d = value - 1
    s = 0
    while d % 2 == 0:
        s += 1
        d //= 2
    for base in (2, 3, 5, 7, 11, 13, 17, 19)[:rounds]:
        if base >= value - 1:
            continue
        x = pow(base, d, value)
        if x in (1, value - 1):
            continue
        witness = True
        for _ in range(s - 1):
            x = pow(x, 2, value)
            if x == value - 1:
                witness = False
                break
        if witness:
            return False
    return True

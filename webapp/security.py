"""Password hash helpers. The application accepts a salted PBKDF2 hash only."""
from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
MIN_ITERATIONS = 200_000
MAX_ITERATIONS = 2_000_000


def hash_password(password: str, iterations: int = 310_000) -> str:
    if len(password) < 12:
        raise ValueError("A senha deve ter pelo menos 12 caracteres.")
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise ValueError("Número de iterações PBKDF2 fora do intervalo permitido.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def valid_hash(encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        rounds = int(iterations)
        return (algorithm == ALGORITHM and MIN_ITERATIONS <= rounds <= MAX_ITERATIONS
                and len(bytes.fromhex(salt)) >= 16 and len(bytes.fromhex(digest)) == 32)
    except (ValueError, TypeError):
        return False


def verify_password(password: str, encoded: str) -> bool:
    if not valid_hash(encoded):
        return False
    algorithm, iterations, salt, expected = encoded.split("$", 3)
    calculated = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(calculated, expected)

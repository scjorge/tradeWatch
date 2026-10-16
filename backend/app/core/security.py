"""Hash de senhas (Argon2id) e geração/verificação de tokens opacos."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Parâmetros alinhados à recomendação da OWASP para Argon2id.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

# Hash usado para equalizar o tempo de resposta quando o usuário não existe.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """Tokens de sessão/recuperação são guardados apenas como SHA-256 (alta entropia, sem necessidade de KDF)."""
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def validate_password_strength(password: str) -> None:
    from app.core.errors import AppError

    if len(password) < 10:
        raise AppError("A senha deve ter pelo menos 10 caracteres.", code="weak_password")
    if len(password) > 256:
        raise AppError("A senha é longa demais.", code="weak_password")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        raise AppError(
            "Use ao menos três tipos de caracteres: minúsculas, maiúsculas, números ou símbolos.",
            code="weak_password",
        )

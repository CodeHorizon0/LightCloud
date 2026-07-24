from __future__ import annotations

import bcrypt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError


_password_hasher = PasswordHasher(
    time_cost=4,              
    memory_cost=194560,       
    parallelism=4,            
    hash_len=64,              
    salt_len=16,               
    type=Type.ID,             
)

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False

    if password_hash.startswith(_BCRYPT_PREFIXES):
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except Exception:
            return False

    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash, TypeError, ValueError):
        return False
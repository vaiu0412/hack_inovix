"""Password hashing with the standard library only.

PBKDF2-HMAC-SHA256, 200 000 iterations, a random 16-byte salt per user.
Plain passwords are never stored or logged; comparisons are constant-time.
"""
import hashlib
import hmac
import os
from functools import lru_cache

ITERATIONS = 200_000


def hash_password(password, salt_hex=None):
    """Return (hash_hex, salt_hex). A new random salt is made when none is given."""
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password, hash_hex, salt_hex):
    candidate, _ = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


@lru_cache(maxsize=64)
def demo_hash(user_id, password):
    """Hash for a seeded demo account, computed once per process.

    Each account still gets its own random salt; caching only avoids re-hashing
    every time the demo data is reset (200 000 iterations per account).
    """
    return hash_password(password)

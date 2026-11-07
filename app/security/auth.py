"""Password hashing (stdlib scrypt - no custom crypto) and JWT sessions with server-side revocation."""
import base64
import hashlib
import hmac
import os
import re
import time
import uuid

import jwt

_N, _R, _P = 2 ** 14, 8, 1
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing")  # equalises timing for unknown users


def issue_token(secret: str, user_id: str, ttl_minutes: int) -> tuple[str, str, int]:
    jti = uuid.uuid4().hex
    exp = int(time.time()) + ttl_minutes * 60
    return jwt.encode({"sub": user_id, "jti": jti, "exp": exp}, secret, algorithm="HS256"), jti, exp


def decode_token(secret: str, token: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub", "jti"]})

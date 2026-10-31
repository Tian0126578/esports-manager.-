# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import hashlib
import hmac
import secrets

_PASSWORD_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(_PASSWORD_ITERATIONS),
            salt.hex(),
            password_hash.hex(),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt_hex, hash_hex = encoded_hash.split("$")
        iterations = int(iteration_text)
        if algorithm != "pbkdf2_sha256" or iterations != _PASSWORD_ITERATIONS:
            return False
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False

    actual_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual_hash, expected_hash)


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

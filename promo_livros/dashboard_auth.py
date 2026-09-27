from __future__ import annotations

import hmac
import secrets


class SessionStore:
    """Tokens vivem só neste processo. Reiniciar pede login de novo."""

    def __init__(self) -> None:
        self._tokens: set[str] = set()

    def login(
        self,
        username: str,
        password: str,
        expected_username: str,
        expected_password: str,
    ) -> str | None:
        user_ok = hmac.compare_digest(
            username.encode("utf-8"), expected_username.encode("utf-8")
        )
        password_ok = hmac.compare_digest(
            password.encode("utf-8"), expected_password.encode("utf-8")
        )
        if not (user_ok and password_ok):
            return None
        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        return token

    def valid(self, token: str | None) -> bool:
        return token is not None and token in self._tokens

    def forget(self, token: str | None) -> None:
        if token is not None:
            self._tokens.discard(token)

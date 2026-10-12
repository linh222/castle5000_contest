from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from .config import Settings


@dataclass
class LocalSession:
    dres_session_id: str
    dres_user_id: str
    username: str
    role: str
    created_at: float


class SessionStore:
    """Maps our own signed, HttpOnly cookie to the DRES session id.

    The DRES session token never reaches the browser (per technical note
    section 6); only our own opaque, signed token does. In-memory is fine
    since the whole system is a single backend process (note section 3/4).
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._signer = TimestampSigner(settings.session_secret)
        self._sessions: dict[str, LocalSession] = {}

    def create(self, dres_session_id: str, dres_user_id: str, username: str, role: str) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = LocalSession(
            dres_session_id=dres_session_id,
            dres_user_id=dres_user_id,
            username=username,
            role=role,
            created_at=time.time(),
        )
        return self._signer.sign(token).decode("utf-8")

    def resolve(self, cookie_value: str | None) -> LocalSession | None:
        if not cookie_value:
            return None
        try:
            token = self._signer.unsign(
                cookie_value, max_age=self._settings.session_max_age_s
            ).decode("utf-8")
        except (BadSignature, SignatureExpired):
            return None
        return self._sessions.get(token)

    def destroy(self, cookie_value: str | None) -> None:
        if not cookie_value:
            return
        try:
            token = self._signer.unsign(cookie_value).decode("utf-8")
        except (BadSignature, SignatureExpired):
            return
        self._sessions.pop(token, None)

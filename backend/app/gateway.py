from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .config import Settings
from .dres_client import DresAuthError, DresClient, DresError, DresTask, Verdict
from .sessions import LocalSession, SessionStore


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class DresGateway:
    """Single interface between a browser session cookie and DRES.

    Owns the session lookup and the DRES-to-HTTP error translation (expired
    DRES session -> forget it and demand a fresh login; any other DRES
    failure -> 502), so request handlers never repeat that logic.
    """

    def __init__(self, settings: Settings, client: DresClient, sessions: SessionStore):
        self._settings = settings
        self._client = client
        self._sessions = sessions

    def require_session(self, cookie: str | None) -> LocalSession:
        session = self._sessions.resolve(cookie)
        if session is None:
            raise GatewayError(401, "unauthorized", "Chưa đăng nhập hoặc phiên đã hết hạn")
        return session

    async def login(self, username: str, password: str) -> tuple[str, LocalSession]:
        try:
            user = await self._client.login(username, password)
        except DresAuthError as exc:
            raise GatewayError(401, exc.code, exc.message)
        except DresError as exc:
            raise GatewayError(502, exc.code, exc.message)
        cookie = self._sessions.create(
            dres_session_id=user.session_id,
            dres_user_id=user.id,
            username=user.username,
            role=user.role,
        )
        return cookie, self._sessions.resolve(cookie)

    async def logout(self, cookie: str | None) -> None:
        session = self._sessions.resolve(cookie)
        if session is not None:
            await self._client.logout(session.dres_session_id)
        self._sessions.destroy(cookie)

    async def current_task(self, cookie: str | None) -> tuple[DresTask | None, int]:
        session = self.require_session(cookie)
        with self._dres_errors(cookie):
            task = await self._client.current_task(
                self._require_evaluation_id(), session.dres_session_id
            )
            server_time_ms = await self._client.server_time()
        return task, server_time_ms

    async def submit(self, cookie: str | None, image_id: str) -> tuple[Verdict, str]:
        session = self.require_session(cookie)
        with self._dres_errors(cookie):
            return await self._client.submit(
                self._require_evaluation_id(), session.dres_session_id, image_id
            )

    def _require_evaluation_id(self) -> str:
        evaluation_id = self._settings.dres_evaluation_id
        if not evaluation_id:
            raise GatewayError(409, "no_evaluation", "Chưa cấu hình DRES_EVALUATION_ID")
        return evaluation_id

    @contextmanager
    def _dres_errors(self, cookie: str | None) -> Iterator[None]:
        try:
            yield
        except DresAuthError:
            # The password is never cached, so we cannot silently re-login.
            self._sessions.destroy(cookie)
            raise GatewayError(
                401, "session_expired", "Phiên DRES đã hết hạn, hãy đăng nhập lại"
            )
        except DresError as exc:
            raise GatewayError(502, exc.code, exc.message)

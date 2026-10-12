import httpx
import pytest

from app.config import Settings
from app.dres_client import DresClient
from app.gateway import DresGateway, GatewayError
from app.sessions import SessionStore
from tools.mock_dres import EVALUATION_ID, app as mock_dres_app


def make_gateway(evaluation_id: str | None = EVALUATION_ID) -> DresGateway:
    settings = Settings(
        dres_base_url="http://mock-dres",
        dres_evaluation_id=evaluation_id,
        session_secret="test-secret",
    )
    client = DresClient(settings, transport=httpx.ASGITransport(app=mock_dres_app))
    return DresGateway(settings, client, SessionStore(settings))


async def test_login_returns_cookie_and_session():
    gateway = make_gateway()
    cookie, session = await gateway.login("student", "student")
    assert session.username == "student"
    assert gateway.require_session(cookie).username == "student"


async def test_login_wrong_password_is_401():
    gateway = make_gateway()
    with pytest.raises(GatewayError) as exc:
        await gateway.login("student", "nope")
    assert exc.value.status == 401


async def test_require_session_without_cookie_is_401():
    gateway = make_gateway()
    with pytest.raises(GatewayError) as exc:
        gateway.require_session(None)
    assert exc.value.status == 401
    assert exc.value.code == "unauthorized"


async def test_logout_invalidates_session():
    gateway = make_gateway()
    cookie, _ = await gateway.login("student", "student")
    await gateway.logout(cookie)
    with pytest.raises(GatewayError):
        gateway.require_session(cookie)


async def test_submit_correct():
    gateway = make_gateway()
    cookie, _ = await gateway.login("student", "student")
    verdict, _ = await gateway.submit(cookie, "08_1002.jpg")
    assert verdict == "correct"


async def test_submit_without_evaluation_is_409():
    gateway = make_gateway(evaluation_id=None)
    cookie, _ = await gateway.login("student", "student")
    with pytest.raises(GatewayError) as exc:
        await gateway.submit(cookie, "08_1002.jpg")
    assert exc.value.status == 409


async def test_current_task_running():
    gateway = make_gateway()
    cookie, _ = await gateway.login("student", "student")
    task, server_time_ms = await gateway.current_task(cookie)
    assert task is not None and task.name == "Task 1"
    assert server_time_ms > 0


async def test_dres_session_expiry_destroys_local_session(monkeypatch):
    gateway = make_gateway()
    cookie, session = await gateway.login("student", "student")
    session.dres_session_id = "expired-on-dres"

    with pytest.raises(GatewayError) as exc:
        await gateway.submit(cookie, "08_1002.jpg")
    assert exc.value.status == 401
    assert exc.value.code == "session_expired"

    with pytest.raises(GatewayError):
        gateway.require_session(cookie)

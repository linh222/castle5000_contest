import httpx
import pytest

from app.config import Settings
from app.dres_client import DresAuthError, DresClient
from tools.mock_dres import EVALUATION_ID, SESSION_ID, app as mock_dres_app


@pytest.fixture
def client() -> DresClient:
    transport = httpx.ASGITransport(app=mock_dres_app)
    settings = Settings(dres_base_url="http://mock-dres")
    return DresClient(settings, transport=transport)


async def test_login_success(client: DresClient):
    user = await client.login("student", "student")
    assert user.session_id == SESSION_ID
    assert user.username == "student"


async def test_login_failure_raises_auth_error(client: DresClient):
    with pytest.raises(DresAuthError):
        await client.login("student", "wrong-password")


async def test_current_task_running(client: DresClient):
    task = await client.current_task(EVALUATION_ID, SESSION_ID)
    assert task is not None
    assert task.name == "Task 1"
    assert task.duration_s == 300


async def test_current_task_unknown_evaluation_returns_none(client: DresClient):
    task = await client.current_task("no-such-eval", SESSION_ID)
    assert task is None


async def test_current_task_bad_session_raises_auth_error(client: DresClient):
    with pytest.raises(DresAuthError):
        await client.current_task(EVALUATION_ID, "bad-session")


async def test_submit_correct(client: DresClient):
    verdict, _ = await client.submit(EVALUATION_ID, SESSION_ID, "any-id.jpg")
    assert verdict == "correct"


async def test_submit_wrong(client: DresClient):
    verdict, _ = await client.submit(EVALUATION_ID, SESSION_ID, "wrong-id")
    assert verdict == "wrong"


async def test_submit_pending_202(client: DresClient):
    verdict, _ = await client.submit(EVALUATION_ID, SESSION_ID, "trigger-202")
    assert verdict == "pending"


async def test_submit_not_found_404(client: DresClient):
    verdict, message = await client.submit(EVALUATION_ID, SESSION_ID, "trigger-404")
    assert verdict == "error"
    assert message


async def test_submit_rejected_412(client: DresClient):
    verdict, message = await client.submit(EVALUATION_ID, SESSION_ID, "trigger-412")
    assert verdict == "rejected"
    assert message


async def test_submit_bad_session_raises_auth_error(client: DresClient):
    with pytest.raises(DresAuthError):
        await client.submit(EVALUATION_ID, "bad-session", "any-id.jpg")


async def test_server_time(client: DresClient):
    ts = await client.server_time()
    assert ts > 0

"""Minimal fake DRES v2 server for testing retrieval without a real DRES.

Covers exactly the response codes the technical note (section 6/9) asks to
be testable: 200, 202, 401, 404, 412.

Run standalone:
    uvicorn tools.mock_dres:app --port 8080

Credentials: username "student", password "student".
Evaluation id: "mock-eval".
Submitting a mediaItemName of "trigger-202" / "trigger-404" / "trigger-412"
forces that response code; "wrong-id" returns a WRONG verdict; anything
else returns CORRECT. This lets tests exercise each path deliberately.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock DRES")

VALID_USERNAME = "student"
VALID_PASSWORD = "student"
SESSION_ID = "mock-session-1"
EVALUATION_ID = "mock-eval"


def _error(description: str, status_code: int) -> JSONResponse:
    return JSONResponse({"status": False, "description": description}, status_code=status_code)


@app.post("/api/v2/login")
async def login(request: Request):
    body = await request.json()
    if body.get("username") == VALID_USERNAME and body.get("password") == VALID_PASSWORD:
        return {
            "id": "user-1",
            "username": VALID_USERNAME,
            "role": "PARTICIPANT",
            "sessionId": SESSION_ID,
        }
    return _error("invalid credentials", 401)


@app.get("/api/v2/logout")
async def logout():
    return {"status": True, "description": "logged out"}


@app.get("/api/v2/client/evaluation/currentTask/{evaluation_id}")
async def current_task(evaluation_id: str, session: str | None = None):
    if session != SESSION_ID:
        return _error("unauthorized", 401)
    if evaluation_id != EVALUATION_ID:
        return _error("unknown evaluation", 404)
    return {
        "name": "Task 1",
        "taskGroup": "KIS",
        "taskType": "visual",
        "duration": 300,
    }


@app.post("/api/v2/submit/{evaluation_id}")
async def submit(evaluation_id: str, request: Request, session: str | None = None):
    if session != SESSION_ID:
        return _error("unauthorized", 401)
    if evaluation_id != EVALUATION_ID:
        return _error("unknown evaluation", 404)

    body = await request.json()
    answers = body.get("answerSets", [{}])[0].get("answers", [{}])
    media_item_name = answers[0].get("mediaItemName", "") if answers else ""

    if media_item_name == "trigger-404":
        return _error("unknown media item", 404)
    if media_item_name == "trigger-412":
        return _error("submission window closed", 412)
    if media_item_name == "trigger-202":
        return JSONResponse(
            {"status": True, "submission": "INDETERMINATE", "description": "pending judgement"},
            status_code=202,
        )
    if media_item_name == "wrong-id":
        return {"status": True, "submission": "WRONG", "description": "incorrect"}
    return {"status": True, "submission": "CORRECT", "description": "correct"}


@app.get("/api/v2/status/time")
async def server_time():
    return {"timeStamp": int(time.time() * 1000)}


@app.get("/api/v2/collection/list")
async def collection_list():
    return [{"id": "col-1", "name": "Castle5000", "description": "", "basePath": "", "itemCount": 5000}]


@app.get("/api/v2/collection/{collection_id}")
async def collection(collection_id: str):
    return {
        "collection": {"id": collection_id, "name": "Castle5000", "itemCount": 2},
        "items": [
            {
                "mediaItemId": "m1",
                "name": "08_1002.jpg",
                "type": "IMAGE",
                "collectionId": collection_id,
                "location": "08_1002.jpg",
                "metadata": [],
            },
            {
                "mediaItemId": "m2",
                "name": "08_1010.jpg",
                "type": "IMAGE",
                "collectionId": collection_id,
                "location": "08_1010.jpg",
                "metadata": [],
            },
        ],
    }

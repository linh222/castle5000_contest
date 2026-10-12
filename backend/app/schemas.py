from __future__ import annotations

from pydantic import BaseModel, Field

from .config import get_settings

_settings = get_settings()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    username: str
    role: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=_settings.query_max_len)
    k: int = Field(default=_settings.default_k, ge=1, le=_settings.max_k)


class SearchResultItem(BaseModel):
    id: str
    score: float
    thumb: str


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    took_ms: int


class SubmitRequest(BaseModel):
    id: str = Field(min_length=1, max_length=256)


class SubmitResponse(BaseModel):
    verdict: str
    message: str


class ImageMetadataResponse(BaseModel):
    owner: str
    day: str
    hour: str
    frame: str
    classes: list[str]
    class_count: dict[str, int]
    description: str


class TaskResponse(BaseModel):
    running: bool
    name: str | None = None
    task_group: str | None = None
    task_type: str | None = None
    duration_s: int | None = None
    server_time_ms: int | None = None


class ErrorResponse(BaseModel):
    code: str
    message: str

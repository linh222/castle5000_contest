from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DRES
    dres_base_url: str = "http://dres:8080"
    dres_evaluation_id: str | None = None
    dres_timeout_s: float = 5.0

    # Index / data
    index_path: Path = REPO_ROOT / "data" / "index.faiss"
    ids_path: Path = REPO_ROOT / "data" / "ids.json"
    images_dir: Path = REPO_ROOT / "data" / "images"
    thumbs_dir: Path = REPO_ROOT / "data" / "thumbs"
    metadata_path: Path = REPO_ROOT / "data" / "metadata.csv"

    # Embedding model (must match tools/build_index.py)
    embed_model_name: str = "ViT-B-32"
    embed_pretrained: str = "laion2b_s34b_b79k"
    encode_concurrency: int = 4

    # Session / security
    session_secret: str = "dev-only-insecure-secret-change-me"
    session_cookie_name: str = "retrieval_session"
    session_max_age_s: int = 60 * 60 * 8
    # Must be True in production (served over HTTPS via Caddy). Set False
    # only for local dev over plain http://127.0.0.1, otherwise browsers
    # silently drop the cookie.
    session_cookie_secure: bool = True

    # Request limits
    max_k: int = 100
    default_k: int = 50
    query_max_len: int = 300
    rate_limit_per_min: int = 30
    search_cache_size: int = 256

    @property
    def using_default_secret(self) -> bool:
        return self.session_secret == "dev-only-insecure-secret-change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()

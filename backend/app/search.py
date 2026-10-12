from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

# torch and faiss each bundle their own OpenMP runtime; on macOS loading both
# in one process aborts at import time ("OMP: Error #15"), and merely
# silencing that abort (KMP_DUPLICATE_LIB_OK alone) still segfaults once real
# work runs on both pools concurrently. Forcing everything to 1 OpenMP thread
# avoids that -- cheap here since we only encode one short query string per
# request; MPS/GPU work (used offline in tools/build_index.py) is unaffected.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import faiss
import numpy as np
import open_clip
import torch

faiss.omp_set_num_threads(1)
torch.set_num_threads(1)

from .config import Settings


class IndexNotBuiltError(RuntimeError):
    pass


class VectorIndex:
    """Pure top-k search over a FAISS flat index + parallel id table.

    Kept separate from the CLIP model so the top-k logic (order, k-limit,
    unknown-id lookups) can be unit tested without downloading any model
    weights -- see backend/tests/test_search.py.
    """

    def __init__(self, index: faiss.Index, ids: list[str]):
        if index.ntotal != len(ids):
            raise IndexNotBuiltError(
                f"Index has {index.ntotal} vectors but {len(ids)} ids were given"
            )
        self.index = index
        self.ids = ids
        self.id_set = set(ids)

    @classmethod
    def load(cls, index_path: Path, ids_path: Path) -> "VectorIndex":
        if not index_path.exists() or not ids_path.exists():
            raise IndexNotBuiltError(
                f"Missing index at {index_path} or ids at {ids_path}. "
                "Run `python tools/build_index.py` first."
            )
        ids = json.loads(ids_path.read_text())
        index = faiss.read_index(str(index_path))
        return cls(index, ids)

    @property
    def num_images(self) -> int:
        return len(self.ids)

    def has_id(self, image_id: str) -> bool:
        return image_id in self.id_set

    def search_vector(self, vec: np.ndarray, k: int) -> list[dict]:
        k = min(k, self.num_images)
        if k <= 0:
            return []
        scores, idxs = self.index.search(vec, k)
        results: list[dict] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0:
                continue
            results.append({"id": self.ids[idx], "score": float(score)})
        return results


class SearchEngine:
    """Loads the FAISS index + CLIP text encoder once and serves text->image search.

    Encoding a query is the expensive part, so concurrent encodes are bounded
    by a semaphore (per technical note section 4/8) instead of letting 40
    simultaneous requests fight over CPU with DRES.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache_lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, int], list[dict]] = OrderedDict()
        self._semaphore = asyncio.Semaphore(settings.encode_concurrency)
        self.vector_index = VectorIndex.load(settings.index_path, settings.ids_path)
        self._load_model()

    def _load_model(self) -> None:
        s = self.settings
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model, _, _ = open_clip.create_model_and_transforms(
            s.embed_model_name, pretrained=s.embed_pretrained, device=self.device
        )
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(s.embed_model_name)

    @property
    def num_images(self) -> int:
        return self.vector_index.num_images

    def has_id(self, image_id: str) -> bool:
        return self.vector_index.has_id(image_id)

    def _encode_text_sync(self, query: str) -> np.ndarray:
        tokens = self.tokenizer([query]).to(self.device)
        with torch.no_grad():
            feats = self.model.encode_text(tokens)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return np.ascontiguousarray(feats.cpu().numpy().astype("float32"))

    async def encode_text(self, query: str) -> np.ndarray:
        async with self._semaphore:
            return await asyncio.to_thread(self._encode_text_sync, query)

    def _cache_get(self, key: tuple[str, int]) -> list[dict] | None:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key: tuple[str, int], value: list[dict]) -> None:
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self.settings.search_cache_size:
                self._cache.popitem(last=False)

    async def search(self, query: str, k: int) -> tuple[list[dict], int]:
        key = (query, k)
        cached = self._cache_get(key)
        if cached is not None:
            return cached, 0

        t0 = time.perf_counter()
        vec = await self.encode_text(query)
        results = self.vector_index.search_vector(vec, k)
        took_ms = int((time.perf_counter() - t0) * 1000)

        self._cache_put(key, results)
        return results, took_ms

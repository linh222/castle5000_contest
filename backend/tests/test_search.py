import numpy as np
import pytest

from app.search import IndexNotBuiltError, VectorIndex


def _make_index(vectors: np.ndarray):
    import faiss

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors.astype("float32"))
    return index


def _unit(v: list[float]) -> np.ndarray:
    arr = np.array(v, dtype="float32")
    return arr / np.linalg.norm(arr)


def test_search_vector_orders_by_score_desc():
    ids = ["a.jpg", "b.jpg", "c.jpg"]
    # b is closest to the query direction, then a, then c (orthogonal-ish)
    vectors = np.stack([_unit([1, 0.2]), _unit([1, 0]), _unit([0, 1])])
    index = VectorIndex(_make_index(vectors), ids)

    query = _unit([1, 0]).reshape(1, -1)
    results = index.search_vector(query, k=3)

    assert [r["id"] for r in results] == ["b.jpg", "a.jpg", "c.jpg"]
    # scores should be non-increasing
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_vector_respects_k_limit():
    ids = [f"{i}.jpg" for i in range(10)]
    vectors = np.stack([_unit([1, i * 0.01]) for i in range(10)])
    index = VectorIndex(_make_index(vectors), ids)

    query = _unit([1, 0]).reshape(1, -1)
    results = index.search_vector(query, k=3)

    assert len(results) == 3


def test_search_vector_k_larger_than_corpus_is_capped():
    ids = ["a.jpg", "b.jpg"]
    vectors = np.stack([_unit([1, 0]), _unit([0, 1])])
    index = VectorIndex(_make_index(vectors), ids)

    query = _unit([1, 0]).reshape(1, -1)
    results = index.search_vector(query, k=100)

    assert len(results) == 2


def test_has_id():
    ids = ["x.jpg", "y.jpg"]
    vectors = np.stack([_unit([1, 0]), _unit([0, 1])])
    index = VectorIndex(_make_index(vectors), ids)

    assert index.has_id("x.jpg")
    assert not index.has_id("z.jpg")


def test_mismatched_index_and_ids_raises():
    ids = ["x.jpg"]
    vectors = np.stack([_unit([1, 0]), _unit([0, 1])])
    with pytest.raises(IndexNotBuiltError):
        VectorIndex(_make_index(vectors), ids)


def test_load_missing_files_raises(tmp_path):
    with pytest.raises(IndexNotBuiltError):
        VectorIndex.load(tmp_path / "index.faiss", tmp_path / "ids.json")

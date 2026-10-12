#!/usr/bin/env python3
"""Offline pipeline: images -> CLIP embeddings -> FAISS index + ids.json + thumbnails.

Usage:
    python tools/build_index.py --images-dir /path/to/Castle_5000 --out-dir data

Run this once offline; the backend only ever reads the files this produces
(index.faiss, ids.json) plus the thumbnails directory at startup.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# See backend/app/search.py for why this must be set before importing
# faiss/torch together on macOS (silent abort fix alone isn't enough; it
# segfaults under real load without also pinning OpenMP to 1 thread).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import faiss
import numpy as np
import open_clip
import torch
from PIL import Image

faiss.omp_set_num_threads(1)
torch.set_num_threads(1)

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--images-dir", required=True, type=Path)
    p.add_argument("--out-dir", default=Path("data"), type=Path)
    p.add_argument("--model", default="ViT-B-32")
    p.add_argument("--pretrained", default="laion2b_s34b_b79k")
    p.add_argument("--batch-size", default=64, type=int)
    p.add_argument("--thumb-size", default=320, type=int, help="long edge, px")
    p.add_argument("--device", default=None, help="cpu | mps | cuda (default: auto)")
    p.add_argument(
        "--expected-count",
        default=5000,
        type=int,
        help="warn (not fail) if the number of images differs",
    )
    return p.parse_args()


def pick_device(requested: str | None) -> str:
    if requested:
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def make_thumbnail(src_path: Path, dst_path: Path, long_edge: int) -> None:
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = long_edge / max(w, h)
        if scale < 1:
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst_path, format="JPEG", quality=85, optimize=True)


def main() -> int:
    args = parse_args()

    images_dir: Path = args.images_dir
    if not images_dir.is_dir():
        print(f"ERROR: images dir not found: {images_dir}", file=sys.stderr)
        return 1

    files = sorted(
        p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not files:
        print(f"ERROR: no images found under {images_dir}", file=sys.stderr)
        return 1

    if len(files) != args.expected_count:
        print(
            f"WARNING: found {len(files)} images, expected {args.expected_count}. Continuing.",
            file=sys.stderr,
        )

    device = pick_device(args.device)
    print(f"Loading {args.model} ({args.pretrained}) on {device} ...")
    model, _, preprocess = open_clip.create_model_and_transforms(
        args.model, pretrained=args.pretrained, device=device
    )
    model.eval()

    out_dir: Path = args.out_dir
    thumbs_dir = out_dir / "thumbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    ids: list[str] = []
    embeddings: list[np.ndarray] = []
    errors: list[tuple[str, str]] = []

    t0 = time.time()
    batch_imgs: list[torch.Tensor] = []
    batch_ids: list[str] = []

    def flush_batch() -> None:
        if not batch_imgs:
            return
        batch = torch.stack(batch_imgs).to(device)
        with torch.no_grad():
            feats = model.encode_image(batch)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        embeddings.append(feats.cpu().numpy().astype("float32"))
        ids.extend(batch_ids)
        batch_imgs.clear()
        batch_ids.clear()

    for i, path in enumerate(files, 1):
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                tensor = preprocess(im)
            make_thumbnail(path, thumbs_dir / path.name, args.thumb_size)
        except Exception as exc:  # noqa: BLE001 - keep going on corrupt images
            errors.append((path.name, str(exc)))
            continue

        batch_imgs.append(tensor)
        batch_ids.append(path.name)
        if len(batch_imgs) >= args.batch_size:
            flush_batch()

        if i % 500 == 0 or i == len(files):
            print(f"  {i}/{len(files)} processed ({len(errors)} errors)")

    flush_batch()

    if not embeddings:
        print("ERROR: no embeddings produced", file=sys.stderr)
        return 1

    matrix = np.concatenate(embeddings, axis=0)
    dim = matrix.shape[1]

    index = faiss.IndexFlatIP(dim)
    index.add(matrix)

    np.save(out_dir / "embeddings.npy", matrix)
    (out_dir / "ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=0))
    faiss.write_index(index, str(out_dir / "index.faiss"))

    stats = {
        "num_scanned": len(files),
        "num_indexed": len(ids),
        "num_errors": len(errors),
        "errors": errors[:50],
        "dim": dim,
        "model": args.model,
        "pretrained": args.pretrained,
        "device": device,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out_dir / "build_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))

    print("---")
    print(f"Scanned: {stats['num_scanned']}  Indexed: {stats['num_indexed']}  Errors: {stats['num_errors']}")
    print(f"Index dim: {dim}  Elapsed: {stats['elapsed_s']}s")
    if errors:
        print(f"First errors: {errors[:5]}")
    if len(ids) != args.expected_count:
        print(
            f"WARNING: indexed {len(ids)} images, expected {args.expected_count}.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

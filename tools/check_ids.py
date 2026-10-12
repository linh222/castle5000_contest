#!/usr/bin/env python3
"""Compare our ids.json against the media items DRES actually created.

Per the technical note (section 3): the ID we index images under must match
exactly what DRES calls the item in `mediaItemName` -- no missing items, no
extra items, no case mismatches.

Usage:
    python tools/check_ids.py \\
        --dres-base-url http://localhost:8080 \\
        --username admin --password admin \\
        --collection-name Castle5000 \\
        --ids-path data/ids.json
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

import httpx


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dres-base-url", default="http://localhost:8080")
    p.add_argument("--username", required=True)
    p.add_argument("--password", default=None, help="omit to be prompted")
    p.add_argument("--collection-id", default=None)
    p.add_argument("--collection-name", default=None)
    p.add_argument("--ids-path", default=Path("data/ids.json"), type=Path)
    p.add_argument("--timeout", default=10.0, type=float)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.collection_id and not args.collection_name:
        print("ERROR: provide --collection-id or --collection-name", file=sys.stderr)
        return 1

    password = args.password or getpass.getpass("DRES password: ")
    local_ids: list[str] = json.loads(args.ids_path.read_text())

    with httpx.Client(base_url=args.dres_base_url, timeout=args.timeout) as client:
        resp = client.post(
            "/api/v2/login", json={"username": args.username, "password": password}
        )
        if resp.status_code != 200:
            print(f"ERROR: login failed: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        session_id = resp.json()["sessionId"]

        collection_id = args.collection_id
        if not collection_id:
            resp = client.get("/api/v2/collection/list", params={"session": session_id})
            resp.raise_for_status()
            matches = [c for c in resp.json() if c["name"] == args.collection_name]
            if not matches:
                print(
                    f"ERROR: no collection named {args.collection_name!r} on this DRES instance",
                    file=sys.stderr,
                )
                return 1
            collection_id = matches[0]["id"]

        resp = client.get(
            f"/api/v2/collection/{collection_id}", params={"session": session_id}
        )
        resp.raise_for_status()
        dres_items = resp.json()["items"]

    dres_names = [item["name"] for item in dres_items]
    local_set = set(local_ids)
    dres_set = set(dres_names)

    missing = sorted(local_set - dres_set)  # we index it, DRES doesn't have it
    extra = sorted(dres_set - local_set)  # DRES has it, we don't index it
    case_mismatches = sorted(
        n for n in local_set
        if n not in dres_set and n.lower() in {d.lower() for d in dres_set}
    )

    print(f"Local ids: {len(local_set)}  DRES items: {len(dres_set)}")
    print(f"Missing on DRES (indexed locally but not on DRES): {len(missing)}")
    for name in missing[:20]:
        print(f"  - {name}")
    print(f"Extra on DRES (on DRES but not indexed locally): {len(extra)}")
    for name in extra[:20]:
        print(f"  - {name}")
    print(f"Case mismatches: {len(case_mismatches)}")
    for name in case_mismatches[:20]:
        print(f"  - {name}")

    if missing or extra or case_mismatches:
        print("\nFAIL: ids do not match DRES media collection 1:1.", file=sys.stderr)
        return 1

    print("\nOK: ids.json matches DRES media collection exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

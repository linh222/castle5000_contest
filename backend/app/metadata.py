from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger("retrieval")


class ImageMetadata(NamedTuple):
    owner: str
    day: str
    hour: str
    frame: str
    classes: list[str]
    class_count: dict[str, int]
    description: str


class MetadataStore:
    """Loads per-image metadata keyed by served filename (e.g. "08_1002.jpg").

    The source CSV's imageID column uses "day{N}_{Owner}_{hour}_{frame}",
    which does not match the served filenames. The real filenames use a
    zero-padded hour, so the join key is derived as f"{int(hour):02d}_{frame}.jpg".
    """

    def __init__(self, path: Path):
        self._by_id: dict[str, ImageMetadata] = {}
        if not path.exists():
            logger.warning("Metadata file not found at %s; metadata lookups will be empty", path)
            return
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    filename = f"{int(row['hour']):02d}_{row['frame']}.jpg"
                    classes = json.loads(row["class"])
                    class_count = json.loads(row["class_count"])
                except (KeyError, ValueError) as exc:
                    logger.warning("Skipping malformed metadata row %r: %s", row.get("imageID"), exc)
                    continue
                self._by_id[filename] = ImageMetadata(
                    owner=row["owner"],
                    day=row["day"],
                    hour=row["hour"],
                    frame=row["frame"],
                    classes=classes,
                    class_count=class_count,
                    description=row["description"],
                )
        logger.info("Loaded metadata for %d images from %s", len(self._by_id), path)

    def get(self, image_id: str) -> ImageMetadata | None:
        return self._by_id.get(image_id)

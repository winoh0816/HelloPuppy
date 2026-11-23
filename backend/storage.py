"""Photo storage: uploads are re-encoded without metadata and kept as files outside the database.

- Privacy: phone photos carry EXIF/XMP (GPS position, device, owner name). Every stored copy is re-encoded from pixels
  only, so nothing but the picture leaves the server through the image endpoints. Callers that need the capture time
  (walk/feeding verification) read it from the original bytes *before* calling save_image().
- Size: files go to HELLOPUPPY_MEDIA_DIR (default backend/data/media/) as YYYY/MM/<random>.<ext>; the database keeps
  only `images.storage_path`. Very old SQLite databases kept photos in an `image_data` BLOB column:
  tools/migrate_sqlite_to_postgres.py moves those to files with save_legacy_photo().
"""

from __future__ import annotations

import io
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

DEFAULT_MEDIA_DIR = Path(__file__).parent / "data" / "media"
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def media_dir() -> Path:
    configured = os.getenv("HELLOPUPPY_MEDIA_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_MEDIA_DIR


def strip_metadata(data: bytes, mime: str) -> bytes:
    """Re-encode the pixels only (orientation applied first, so the picture still looks the same)."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    keep_alpha = mime != "image/jpeg" and (image.mode in ("RGBA", "LA") or "transparency" in image.info)
    image = image.convert("RGBA" if keep_alpha else "RGB")
    out = io.BytesIO()
    options = {"JPEG": {"quality": 90, "optimize": True}, "PNG": {"optimize": True}, "WEBP": {"quality": 90}}[FORMATS[mime]]
    # No exif=/icc_profile=/pnginfo= arguments: Pillow then writes no metadata blocks at all.
    image.save(out, FORMATS[mime], **options)
    return out.getvalue()


def _write(data: bytes, mime: str) -> str:
    now = datetime.now(timezone.utc)
    relative = Path(f"{now:%Y}") / f"{now:%m}" / f"{secrets.token_hex(16)}.{EXTENSIONS[mime]}"
    target = media_dir() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".part")
    temporary.write_bytes(data)
    temporary.replace(target)  # never leave a half-written photo under the final name
    return relative.as_posix()


def save_image(data: bytes, mime: str) -> str:
    """Strip metadata, write the file and return the path to store in images.storage_path."""
    return _write(strip_metadata(data, mime), mime)


def read_image(storage_path: str) -> bytes:
    path = (media_dir() / storage_path).resolve()
    if media_dir().resolve() not in path.parents:  # storage_path only ever comes from _write, but never escape media_dir
        raise FileNotFoundError(storage_path)
    return path.read_bytes()


def save_legacy_photo(data: bytes, mime: str) -> str:
    """Like save_image() for a photo taken out of an old database: an unreadable one is kept as it was, not lost."""
    try:
        cleaned = strip_metadata(data, mime)
    except Exception:
        cleaned = data
    return _write(cleaned, mime)

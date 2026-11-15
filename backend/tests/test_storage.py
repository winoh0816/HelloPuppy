from __future__ import annotations

import io
import sqlite3

from fastapi.testclient import TestClient
from PIL import Image

from backend import database, storage
from backend.app import app

GPS_IFD = 0x8825


def _photo_with_gps(rotated: bool = False) -> bytes:
    """A phone-like JPEG: GPS position, camera model and (optionally) 'rotate 90°' orientation in EXIF."""
    image = Image.new("RGB", (160, 100), (200, 30, 30))
    image.paste((30, 30, 200), (0, 0, 80, 100))  # left half blue, to check the orientation is kept
    exif = Image.Exif()
    exif[0x0110] = "Test Phone"  # Model
    exif[0x0112] = 6 if rotated else 1  # Orientation
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (37.0, 33.0, 59.0), 3: "E", 4: (126.0, 58.0, 41.0)})
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def _assert_no_metadata(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    exif = image.getexif()
    assert len(exif) == 0 and not exif.get_ifd(GPS_IFD)
    assert "exif" not in image.info and "xmp" not in image.info
    return image


def test_strip_metadata_removes_gps_and_keeps_orientation():
    original = _photo_with_gps(rotated=True)
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(GPS_IFD)  # the fixture really has GPS
    cleaned = _assert_no_metadata(storage.strip_metadata(original, "image/jpeg"))
    assert cleaned.size == (100, 160)  # rotation applied to the pixels, so it still displays upright


def test_uploaded_photo_is_served_without_gps_and_kept_outside_the_database(tmp_path, monkeypatch):
    db_path = tmp_path / "storage.sqlite3"
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(db_path))
    with TestClient(app) as client:
        token = client.post("/api/auth/register", json={"email": "gps@example.test", "password": "correct horse battery staple",
                                                        "display_name": "위치"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        upload = client.post("/api/uploads?purpose=community", headers=headers,
                             files={"photo": ("walk.jpg", _photo_with_gps(), "image/jpeg")})
        assert upload.status_code == 200
        served = client.get(f"/api/images/{upload.json()['image_id']}", headers=headers)
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    _assert_no_metadata(served.content)

    row = sqlite3.connect(db_path).execute("SELECT length(image_data), storage_path FROM images").fetchone()
    assert row[0] == 0 and row[1]
    stored = (tmp_path / "media" / row[1])
    assert stored.is_file() and stored.read_bytes() == served.content


def test_startup_moves_old_database_photos_to_files_without_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "old.sqlite3"
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(db_path))
    # A database from before photos were files: the original upload, GPS included, sits in image_data.
    old = sqlite3.connect(db_path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash BLOB NOT NULL, password_salt BLOB NOT NULL, display_name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE images (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL, mime_type TEXT NOT NULL, original_name TEXT NOT NULL DEFAULT '', image_data BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
    """)
    old.execute("INSERT INTO users(email,password_hash,password_salt,display_name) VALUES('old@example.test',x'00',x'00','예전')")
    old.execute("INSERT INTO images(user_id,purpose,mime_type,image_data) VALUES(1,'community','image/jpeg',?)", (_photo_with_gps(),))
    old.commit()
    old.close()

    database.init_db()
    database.init_db()  # running again (every server start) must not move anything twice

    db = sqlite3.connect(db_path)
    rows = db.execute("SELECT length(image_data), storage_path FROM images").fetchall()
    assert len(rows) == 1 and rows[0][0] == 0 and rows[0][1]
    assert len(list((tmp_path / "media").rglob("*.jpg"))) == 1
    _assert_no_metadata(storage.read_image(rows[0][1]))


def test_read_image_never_leaves_the_media_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HELLOPUPPY_MEDIA_DIR", str(tmp_path / "media"))
    (tmp_path / "secret.txt").write_text("x")
    try:
        storage.read_image("../secret.txt")
    except FileNotFoundError:
        return
    raise AssertionError("path outside the media folder was read")

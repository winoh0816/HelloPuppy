from __future__ import annotations

import io

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


def test_uploaded_photo_is_served_without_gps_and_kept_outside_the_database(postgres, tmp_path):
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

    with database.db_connection() as db:
        storage_path = db.execute("SELECT storage_path FROM images").fetchone()["storage_path"]
    assert storage_path
    stored = (tmp_path / "media" / storage_path)
    assert stored.is_file() and stored.read_bytes() == served.content


def test_read_image_never_leaves_the_media_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HELLOPUPPY_MEDIA_DIR", str(tmp_path / "media"))
    (tmp_path / "secret.txt").write_text("x")
    try:
        storage.read_image("../secret.txt")
    except FileNotFoundError:
        return
    raise AssertionError("path outside the media folder was read")

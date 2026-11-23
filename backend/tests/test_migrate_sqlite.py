from __future__ import annotations

import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import backend.app as api_module
from backend import database
from backend.app import app
from backend.tools.migrate_sqlite_to_postgres import MigrationError, migrate

GPS_IFD = 0x8825
PASSWORD = "correct horse battery staple"


def _photo_with_gps() -> bytes:
    image = Image.new("RGB", (160, 100), (200, 30, 30))
    exif = Image.Exif()
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (37.0, 33.0, 59.0), 3: "E", 4: (126.0, 58.0, 41.0)})
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def _old_sqlite(path) -> None:
    """A SQLite database as an older HelloPuppy left it: photo bytes inside the DB, no map columns, mixed-case email."""
    salt, digest = api_module.hash_password(PASSWORD)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL, password_salt BLOB NOT NULL, password_hash BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE pets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '',
            breed TEXT NOT NULL DEFAULT '', weight_kg REAL, updated_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE points_accounts (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE images (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, purpose TEXT NOT NULL,
            mime_type TEXT NOT NULL, original_name TEXT NOT NULL DEFAULT '', image_data BLOB NOT NULL DEFAULT X'',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE community_posts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, pet_id INTEGER,
            category TEXT NOT NULL DEFAULT 'daily', title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL, image_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
    """)
    db.execute("INSERT INTO users(id,email,display_name,password_salt,password_hash) VALUES(7,'Old@Example.test','예전 보호자',?,?)",
               (salt, digest))
    db.execute("INSERT INTO pets(id,user_id,name,breed,weight_kg) VALUES(3,7,'초코','말티즈',3.85)")
    db.execute("INSERT INTO points_accounts(user_id,balance) VALUES(7,450)")
    db.execute("INSERT INTO images(id,user_id,purpose,mime_type,image_data) VALUES(5,7,'community','image/jpeg',?)", (_photo_with_gps(),))
    db.execute("INSERT INTO community_posts(id,user_id,pet_id,title,body,image_id) VALUES(9,7,3,'예전 글','옮겨져야 해요',5)")
    db.commit()
    db.close()


def test_old_sqlite_database_moves_to_postgres_with_photos_as_files(postgres, tmp_path):
    source = tmp_path / "old.sqlite3"
    _old_sqlite(source)

    counts = migrate(source)
    assert counts == {"users": 1, "pets": 1, "images": 1, "points_accounts": 1, "community_posts": 1}
    with pytest.raises(MigrationError):  # never copied twice on top of itself
        migrate(source)

    with database.db_connection() as db:
        image = db.execute("SELECT storage_path FROM images WHERE id=5").fetchone()
    assert image["storage_path"] and len(list((tmp_path / "media").rglob("*.jpg"))) == 1

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "old@example.test", "password": PASSWORD})
        assert login.status_code == 200 and login.json()["user"]["id"] == 7
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/points", headers=headers).json()["balance"] == 450
        pet = client.get("/api/pet/profile", headers=headers).json()["profile"]
        assert pet["name"] == "초코" and pet["weight_kg"] == 3.85 and pet["species"] == "dog"  # new column took its default
        post = client.get("/api/community/posts", headers=headers).json()["items"][0]
        assert post["title"] == "예전 글" and post["location_name"] == "" and post["latitude"] is None

        photo = client.get("/api/images/5", headers=headers)
        assert photo.status_code == 200
        assert not Image.open(io.BytesIO(photo.content)).getexif().get_ifd(GPS_IFD)  # GPS removed on the way out

        # ids keep counting after the copied rows, and the old mixed-case email still blocks a duplicate sign-up
        assert client.post("/api/auth/register", json={"email": "OLD@example.test", "password": PASSWORD,
                                                       "display_name": "중복"}).status_code == 409
        new = client.post("/api/auth/register", json={"email": "new@example.test", "password": PASSWORD, "display_name": "새"})
        assert new.status_code == 200 and new.json()["user"]["id"] > 7  # (the refused sign-up above used up a number)

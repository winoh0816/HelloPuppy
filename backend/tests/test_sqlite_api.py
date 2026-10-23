from __future__ import annotations

import io
import sqlite3

from fastapi.testclient import TestClient
from PIL import Image

from backend import database
import backend.app as api_module
from backend.app import app


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 100), (90, 150, 100)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_account_pet_health_photos_community_and_points(tmp_path, monkeypatch):
    db_path = tmp_path / "api-test.sqlite3"
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(db_path))
    monkeypatch.setenv("HELLOPUPPY_AUTH_SECRET", "test-secret-that-is-at-least-thirty-two-characters-long")

    with TestClient(app) as client:
        registration = client.post("/api/auth/register", json={
            "email": "guardian@example.test",
            "password": "correct horse battery staple",
            "display_name": "보호자"
        })
        assert registration.status_code == 200
        token = registration.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert registration.json()["points"] == 0
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.get("/api/points").status_code == 401

        profile = client.put("/api/pet/profile", headers=headers, json={"name": "초코", "breed": "믹스견"})
        assert profile.status_code == 200
        assert profile.json()["profile"]["name"] == "초코"
        food = client.put("/api/pet/food", headers=headers, json={"food_name": "연어 사료", "meals_per_day": 2})
        assert food.status_code == 200
        assert food.json()["food"]["food_name"] == "연어 사료"

        record = client.post("/api/health/records", headers=headers, json={
            "record_type": "vaccination", "record_date": "2026-10-23", "title": "종합백신"
        })
        assert record.status_code == 200
        assert len(client.get("/api/health/records", headers=headers).json()["items"]) == 1

        api_module._activity_model = None
        api_module._activity_transform = None
        api_module._runtime_error = None
        unavailable = client.post("/api/verify/walk", headers=headers,
                      files={"photo": ("walk.jpg", _jpeg_bytes(), "image/jpeg")})
        assert unavailable.status_code == 503

        upload = client.post("/api/uploads?purpose=community", headers=headers,
                             files={"photo": ("post.jpg", _jpeg_bytes(), "image/jpeg")})
        assert upload.status_code == 200
        image_id = upload.json()["image_id"]
        assert client.get(f"/api/images/{image_id}", headers=headers).status_code == 200

        post = client.post("/api/community/posts", headers=headers, json={
            "category": "daily", "title": "산책 기록", "body": "오늘 공원에 다녀왔어요", "image_id": image_id
        })
        post_id = post.json()["post"]["id"]
        assert post.status_code == 200
        assert client.post(f"/api/community/posts/{post_id}/like", headers=headers).json()["liked"] is True
        comment = client.post(f"/api/community/posts/{post_id}/comments", headers=headers, json={"body": "좋은 하루네요"})
        assert comment.status_code == 200
        assert len(client.get("/api/community/posts", headers=headers).json()["items"]) == 1

        second = client.post("/api/auth/register", json={
            "email": "other@example.test", "password": "another secure battery staple", "display_name": "다른 보호자"
        })
        second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
        assert client.get("/api/pet/profile", headers=second_headers).json()["profile"]["name"] == ""
        assert client.get("/api/health/records", headers=second_headers).json()["items"] == []
        assert client.get(f"/api/images/{image_id}", headers=second_headers).status_code == 200
        with database.db_connection() as db:
            verification_image_id = db.execute("SELECT id FROM images WHERE purpose='verification_walk'").fetchone()["id"]
        assert client.get(f"/api/images/{verification_image_id}", headers=second_headers).status_code == 404

        with database.transaction() as db:
            db.execute("UPDATE points_accounts SET balance=2000 WHERE user_id=1")
        redemption = client.post("/api/shop/redeem", headers=headers, json={"product_id": "snack-001"})
        assert redemption.status_code == 200
        assert redemption.json()["balance"] == 1500
        assert client.get("/api/points", headers=headers).json()["balance"] == 1500
        assert len(client.get("/api/points/ledger", headers=headers).json()["items"]) == 1
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 401

    assert db_path.is_file()
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM community_posts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 1
        assert db.execute("SELECT status FROM activity_logs").fetchone()[0] == "unavailable"

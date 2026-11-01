from __future__ import annotations

import io
import os
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


def test_community_upload_accepts_photos_over_12mb(tmp_path, monkeypatch):
    db_path = tmp_path / "large-community-photo.sqlite3"
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(db_path))
    pixels = os.urandom(2200 * 2000 * 3)
    image = Image.frombytes("RGB", (2200, 2000), pixels)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=0)
    photo = buffer.getvalue()
    assert len(photo) > 12 * 1024 * 1024

    with TestClient(app) as client:
        registration = client.post("/api/auth/register", json={
            "email": "large-photo@example.test",
            "password": "correct horse battery staple",
            "display_name": "사진 테스트"
        })
        headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        upload = client.post("/api/uploads?purpose=community", headers=headers,
                             files={"photo": ("portrait.png", photo, "image/png")})

    assert upload.status_code == 200


class _UnavailableVerifier:
    ready = False

    def status(self):
        return {"ready": False, "message": "테스트: 모델 없음", "trained_classifier": False, "object_detector": None}


def _register(client, email: str) -> dict[str, str]:
    registration = client.post("/api/auth/register", json={
        "email": email, "password": "correct horse battery staple", "display_name": "보호자"
    })
    return {"Authorization": f"Bearer {registration.json()['access_token']}"}


def test_structured_health_record_questionnaire_and_fhir_export(tmp_path, monkeypatch):
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(tmp_path / "health.sqlite3"))

    with TestClient(app) as client:
        headers = _register(client, "health@example.test")
        profile = client.put("/api/pet/profile", headers=headers, json={
            "name": "초코", "breed": "말티즈", "sex": "female", "neutered": "yes", "birth_date": "2021-03-01",
            "birth_date_estimated": True, "microchip_id": "410123456789012", "registration_type": "internal",
            "coat_features": "흰색, 왼쪽 귀 갈색 반점", "living_environment": "indoor", "guardian_name": "지보호"
        })
        assert profile.status_code == 200
        assert profile.json()["profile"]["registration_type"] == "internal"
        assert client.put("/api/pet/profile", headers=headers, json={"name": "초코", "species": "lizard"}).status_code == 422
        food = client.put("/api/pet/food", headers=headers, json={
            "food_name": "연어 사료", "amount_per_meal": "40g", "treats": "고구마 말랭이", "diet_changed_date": "2026-10-01"
        })
        assert food.json()["food"]["treats"] == "고구마 말랭이"

        vaccine = client.post("/api/health/records", headers=headers, json={
            "record_type": "vaccination", "record_date": "2026-10-01", "clinic": "1번 동물병원",
            "details": {"vaccine_type": "rabies", "next_due_date": "2027-10-01"}
        })
        assert vaccine.status_code == 200
        assert vaccine.json()["record"]["details"] == {"vaccine_type": "rabies", "next_due_date": "2027-10-01"}
        assert vaccine.json()["record"]["source"] == "guardian"
        assert client.post("/api/health/records", headers=headers, json={
            "record_type": "vaccination", "record_date": "2026-10-01", "details": {"vaccine_type": "unknown-vaccine"}
        }).status_code == 422
        assert client.post("/api/health/records", headers=headers, json={
            "record_type": "medication", "record_date": "2026-10-01", "details": {"dose": "1정"}
        }).status_code == 422
        assert client.post("/api/health/records", headers=headers, json={
            "record_type": "allergy", "record_date": "2026-10-01", "details": {"substance": "닭고기", "unexpected": "x"}
        }).status_code == 422

        weight = client.post("/api/health/records", headers=headers, json={
            "record_type": "weight", "record_date": "2026-10-20", "details": {"weight_kg": "3.85", "body_condition_score": "5"}
        })
        assert weight.json()["record"]["details"] == {"weight_kg": 3.85, "body_condition_score": 5}
        client.post("/api/health/records", headers=headers, json={
            "record_type": "weight", "record_date": "2026-09-01", "details": {"weight_kg": 3.5}
        })
        assert client.get("/api/pet/profile", headers=headers).json()["profile"]["weight_kg"] == 3.85

        upload = client.post("/api/uploads?purpose=health", headers=headers,
                             files={"photo": ("lab.jpg", _jpeg_bytes(), "image/jpeg")})
        lab = client.post("/api/health/records", headers=headers, json={
            "record_type": "lab", "record_date": "2026-10-20", "image_id": upload.json()["image_id"],
            "details": {"test_name": "혈액검사(CBC)", "abnormal_findings": "ALT 경도 상승"}
        })
        assert lab.status_code == 200

        questionnaire = client.post("/api/health/questionnaires", headers=headers, json={
            "visit_date": "2026-11-02", "clinic": "2번 동물병원", "chief_complaint": "이틀째 설사",
            "progression": "worse", "systems": {"stool": "abnormal", "appetite": "decreased", "water": "normal"}
        })
        assert questionnaire.status_code == 200
        assert questionnaire.json()["questionnaire"]["systems"]["stool"] == "abnormal"
        assert client.post("/api/health/questionnaires", headers=headers, json={
            "visit_date": "2026-11-02", "chief_complaint": "x", "systems": {"stool": "very-bad"}
        }).status_code == 422

        summary = client.get("/api/health/summary", headers=headers).json()["summary"]
        assert summary["pet"]["birth_date_estimated"] is True
        assert len(summary["records"]) == 4
        assert len(summary["questionnaires"]) == 1

        bundle = client.get("/api/health/export/fhir", headers=headers).json()
        assert bundle["resourceType"] == "Bundle" and bundle["type"] == "collection"
        resources = [entry["resource"] for entry in bundle["entry"]]
        types = [resource["resourceType"] for resource in resources]
        patient = resources[0]
        assert patient["resourceType"] == "Patient"
        assert patient["identifier"][0]["value"] == "410123456789012"
        animal = {item["url"]: item for item in patient["extension"][0]["extension"]}
        assert animal["species"]["valueCodeableConcept"]["coding"][0]["code"] == "448771007"
        assert animal["genderStatus"]["valueCodeableConcept"]["coding"][0]["code"] == "neutered"
        assert {"Immunization", "Observation", "DiagnosticReport", "QuestionnaireResponse"} <= set(types)
        weights = [r for r in resources if r["resourceType"] == "Observation" and r.get("valueQuantity")]
        assert sorted(r["valueQuantity"]["value"] for r in weights) == [3.5, 3.85]
        assert all(entry["fullUrl"].startswith("urn:uuid:") for entry in bundle["entry"])


def test_clinic_share_links_scope_revocation_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(tmp_path / "share.sqlite3"))

    with TestClient(app) as client:
        headers = _register(client, "owner@example.test")
        other_headers = _register(client, "stranger@example.test")
        client.put("/api/pet/profile", headers=headers, json={"name": "초코", "guardian_phone": "010-0000-0000"})
        upload = client.post("/api/uploads?purpose=health", headers=headers,
                             files={"photo": ("cert.jpg", _jpeg_bytes(), "image/jpeg")})
        image_id = upload.json()["image_id"]
        client.post("/api/health/records", headers=headers, json={
            "record_type": "visit", "record_date": "2026-10-10", "clinic": "1번 동물병원", "image_id": image_id,
            "details": {"reason": "구토", "diagnosis": "급성 위장염"}
        })
        assert client.post("/api/health/records", headers=other_headers, json={
            "record_type": "other", "record_date": "2026-10-10", "image_id": image_id
        }).status_code == 404

        assert client.post("/api/health/shares", headers=headers, json={"clinic_name": "병원", "hours": 100}).status_code == 422
        assert client.post("/api/health/shares", headers=headers, json={"clinic_name": "병원", "scope": "admin"}).status_code == 422
        read_share = client.post("/api/health/shares", headers=headers, json={"clinic_name": "2번 동물병원", "scope": "read", "hours": 24})
        assert read_share.status_code == 200
        read_token = {"X-Health-Share-Token": read_share.json()["token"]}
        write_share = client.post("/api/health/shares", headers=headers, json={"clinic_name": "1번 동물병원", "scope": "read_write", "hours": 1})
        write_token = {"X-Health-Share-Token": write_share.json()["token"]}

        assert client.get("/api/shared/health").status_code == 404
        assert client.get("/api/shared/health", headers={"X-Health-Share-Token": "x" * 43}).status_code == 404
        shared = client.get("/api/shared/health", headers=read_token)
        assert shared.status_code == 200
        assert shared.json()["share"]["clinic_name"] == "2번 동물병원"
        assert shared.json()["summary"]["pet"]["name"] == "초코"
        assert "user_id" not in shared.json()["summary"]["pet"]
        assert client.get(f"/api/shared/health/images/{image_id}", headers=read_token).status_code == 200
        assert client.get("/api/shared/health/fhir", headers=read_token).json()["resourceType"] == "Bundle"

        clinic_record = {"record_type": "medication", "record_date": "2026-11-01", "author_name": "김수의",
                         "author_license": "12345", "details": {"drug_name": "메트로니다졸", "dose": "1/2정", "frequency": "1일 2회"}}
        assert client.post("/api/shared/health/records", headers=read_token, json=clinic_record).status_code == 403
        written = client.post("/api/shared/health/records", headers=write_token, json={**clinic_record, "clinic": "위조 병원"})
        assert written.status_code == 200
        assert written.json()["record"]["source"] == "clinic"
        assert written.json()["record"]["clinic"] == "1번 동물병원"
        assert client.post("/api/shared/health/records", headers=write_token, json={**clinic_record, "image_id": image_id}).status_code == 422

        # 2번 병원은 1번 병원이 입력한 처방을 같은 링크 화면에서 바로 확인한다.
        records = client.get("/api/shared/health", headers=read_token).json()["summary"]["records"]
        assert any(r["source"] == "clinic" and r["author_name"] == "김수의" for r in records)
        assert client.get("/api/health/shares", headers=other_headers).json()["items"] == []

        shares = {item["id"]: item for item in client.get("/api/health/shares", headers=headers).json()["items"]}
        assert shares[read_share.json()["share"]["id"]]["access_count"] == 3
        share_id = read_share.json()["share"]["id"]
        assert client.delete(f"/api/health/shares/{share_id}", headers=other_headers).status_code == 404
        assert client.delete(f"/api/health/shares/{share_id}", headers=headers).status_code == 200
        assert client.get("/api/shared/health", headers=read_token).status_code == 404
        assert client.get("/api/health/shares", headers=headers).json()["items"][-1]["status"] == "revoked"

        with database.transaction() as db:
            db.execute("UPDATE health_shares SET expires_at='2000-01-01T00:00:00.000Z' WHERE id=?", (write_share.json()["share"]["id"],))
        assert client.get("/api/shared/health", headers=write_token).status_code == 404


def test_account_pet_health_photos_community_and_points(tmp_path, monkeypatch):
    db_path = tmp_path / "api-test.sqlite3"
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(db_path))
    monkeypatch.setenv("HELLOPUPPY_AUTH_SECRET", "test-secret-that-is-at-least-thirty-two-characters-long")

    with sqlite3.connect(db_path) as legacy_db:
        legacy_db.execute("""CREATE TABLE community_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pet_id INTEGER,
            category TEXT NOT NULL DEFAULT 'daily',
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL,
            image_id INTEGER,
            created_at TEXT NOT NULL DEFAULT ''
        )""")

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

        renamed = client.put("/api/auth/display-name", headers=headers, json={"display_name": "초코 보호자"})
        assert renamed.status_code == 200
        assert renamed.json()["user"]["display_name"] == "초코 보호자"
        bad_email_change = client.put("/api/auth/email", headers=headers, json={
            "email": "new-guardian@example.test", "current_password": "incorrect password"
        })
        assert bad_email_change.status_code == 401
        email_change = client.put("/api/auth/email", headers=headers, json={
            "email": "new-guardian@example.test", "current_password": "correct horse battery staple"
        })
        assert email_change.status_code == 200
        assert email_change.json()["user"]["email"] == "new-guardian@example.test"
        other_session = client.post("/api/auth/login", json={
            "email": "new-guardian@example.test", "password": "correct horse battery staple"
        })
        other_headers = {"Authorization": f"Bearer {other_session.json()['access_token']}"}
        password_change = client.put("/api/auth/password", headers=headers, json={
            "current_password": "correct horse battery staple", "new_password": "a newer secure battery staple"
        })
        assert password_change.status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.get("/api/auth/me", headers=other_headers).status_code == 401
        assert client.post("/api/auth/login", json={
            "email": "new-guardian@example.test", "password": "correct horse battery staple"
        }).status_code == 401
        assert client.post("/api/auth/login", json={
            "email": "new-guardian@example.test", "password": "a newer secure battery staple"
        }).status_code == 200

        profile = client.put("/api/pet/profile", headers=headers, json={"name": "초코", "breed": "믹스견"})
        assert profile.status_code == 200
        assert profile.json()["profile"]["name"] == "초코"
        food = client.put("/api/pet/food", headers=headers, json={"food_name": "연어 사료", "meals_per_day": 2})
        assert food.status_code == 200
        assert food.json()["food"]["food_name"] == "연어 사료"

        record = client.post("/api/health/records", headers=headers, json={
            "record_type": "vaccination", "record_date": "2026-10-23", "title": "종합백신",
            "details": {"vaccine_type": "dhppl"}
        })
        assert record.status_code == 200
        assert len(client.get("/api/health/records", headers=headers).json()["items"]) == 1

        monkeypatch.setattr(api_module.verification, "verifier", _UnavailableVerifier())
        unavailable = client.post("/api/verify/walk", headers=headers,
                      files={"photo": ("walk.jpg", _jpeg_bytes(), "image/jpeg")})
        assert unavailable.status_code == 503

        monkeypatch.setenv("HELLOPUPPY_DEMO_MODE", "1")
        demo = client.post("/api/verify/walk", headers=headers,
                   files={"photo": ("walk-demo.jpg", _jpeg_bytes(), "image/jpeg")})
        assert demo.status_code == 200
        assert demo.json()["demo"] is True
        assert demo.json()["verified"] is False
        assert demo.json()["points_awarded"] == 0
        assert demo.json()["balance"] == 0
        monkeypatch.delenv("HELLOPUPPY_DEMO_MODE")

        upload = client.post("/api/uploads?purpose=community", headers=headers,
                             files={"photo": ("post.jpg", _jpeg_bytes(), "image/jpeg")})
        assert upload.status_code == 200
        image_id = upload.json()["image_id"]
        assert client.get(f"/api/images/{image_id}", headers=headers).status_code == 200

        post = client.post("/api/community/posts", headers=headers, json={
            "category": "walk", "title": "산책 기록", "body": "오늘 공원에 다녀왔어요", "image_id": image_id,
            "location_name": "한강공원", "latitude": 37.5283, "longitude": 126.9326
        })
        post_id = post.json()["post"]["id"]
        assert post.status_code == 200
        saved_post = client.get("/api/community/posts", headers=headers).json()["items"][0]
        assert saved_post["location_name"] == "한강공원"
        assert saved_post["latitude"] == 37.5283
        assert saved_post["longitude"] == 126.9326
        public_map = client.get("/api/community/walk-map")
        assert public_map.status_code == 200
        assert public_map.json()["items"][0]["location_name"] == "한강공원"
        assert public_map.json()["items"][0]["image_id"] == image_id
        assert public_map.json()["items"][0]["recommendation_count"] == 0
        public_map_image = client.get(f"/api/community/walk-map/images/{image_id}")
        assert public_map_image.status_code == 200
        assert public_map_image.headers["content-type"] == "image/jpeg"
        assert client.get(f"/api/community/posts/{post_id}/recommendation").status_code == 401
        first_recommendation = client.post(f"/api/community/posts/{post_id}/recommendation", headers=headers)
        assert first_recommendation.json() == {"recommended": True, "count": 1}
        repeated_recommendation = client.post(f"/api/community/posts/{post_id}/recommendation", headers=headers)
        assert repeated_recommendation.json() == {"recommended": True, "count": 1}
        invalid_location = client.post("/api/community/posts", headers=headers, json={
            "body": "좌표 검증", "latitude": 37.5
        })
        assert invalid_location.status_code == 422
        assert client.post(f"/api/community/posts/{post_id}/like", headers=headers).json()["liked"] is True
        comment = client.post(f"/api/community/posts/{post_id}/comments", headers=headers, json={"body": "좋은 하루네요"})
        assert comment.status_code == 200
        assert len(client.get("/api/community/posts", headers=headers).json()["items"]) == 1

        second = client.post("/api/auth/register", json={
            "email": "other@example.test", "password": "another secure battery staple", "display_name": "다른 보호자"
        })
        second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
        second_recommendation = client.post(f"/api/community/posts/{post_id}/recommendation", headers=second_headers)
        assert second_recommendation.json() == {"recommended": True, "count": 2}
        assert client.get("/api/community/walk-map").json()["items"][0]["recommendation_count"] == 2
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
        assert db.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM community_posts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM activity_logs WHERE status='unavailable'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM activity_logs WHERE status='demo'").fetchone()[0] == 1

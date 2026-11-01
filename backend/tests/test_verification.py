from __future__ import annotations

import io
import random
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from PIL import Image

import backend.app as api_module
from backend import verification
from backend.app import app
from backend.verification import Analysis, Detection, Settings, decide

SETTINGS = Settings()
DOG = Detection("dog", 0.9, (0.30, 0.30, 0.60, 0.80))


def _analysis(walk=0.1, feeding=0.1, outdoor=0.9, leash=0.5, detections=(DOG,)):
    other = max(0.0, 1 - walk - feeding)
    return Analysis({"walk": walk, "feeding": feeding, "other": other}, outdoor, leash, list(detections) if detections is not None else None)


def test_walk_requires_dog_scene_outdoor_and_leash():
    assert decide("walk", _analysis(walk=0.8), SETTINGS).verified
    assert not decide("walk", _analysis(walk=0.8, leash=0.0), SETTINGS).verified
    assert not decide("walk", _analysis(walk=0.8, outdoor=0.1), SETTINGS).verified
    assert not decide("walk", _analysis(walk=0.2, feeding=0.7), SETTINGS).verified
    no_dog = decide("walk", _analysis(walk=0.8, detections=[Detection("cat", 0.9, DOG.box)]), SETTINGS)
    assert not no_dog.verified
    assert "고양이" in next(c["detail"] for c in no_dog.checks if c["key"] == "dog")
    # 탐지 모델이 없으면 장면 점수로만 판단한다.
    assert decide("walk", _analysis(walk=0.8, detections=None), SETTINGS).verified


def test_feeding_requires_bowl_near_dog_unless_scene_is_very_strong():
    near_bowl = Detection("bowl", 0.6, (0.55, 0.70, 0.70, 0.85))
    far_bowl = Detection("bowl", 0.6, (0.90, 0.02, 0.99, 0.10))
    assert decide("feeding", _analysis(feeding=0.6, detections=[DOG, near_bowl]), SETTINGS).verified
    assert not decide("feeding", _analysis(feeding=0.6, detections=[DOG, far_bowl]), SETTINGS).verified
    assert not decide("feeding", _analysis(feeding=0.6, detections=[DOG]), SETTINGS).verified
    assert decide("feeding", _analysis(feeding=0.85, detections=[DOG]), SETTINGS).verified
    # 그릇만 있고 개가 없으면 실패
    assert not decide("feeding", _analysis(feeding=0.85, detections=[near_bowl]), SETTINGS).verified


def _noise_jpeg(seed: int, exif_time: datetime | None = None) -> bytes:
    rng = random.Random(seed)
    image = Image.new("RGB", (160, 120))
    image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(160 * 120)])
    image = image.resize((640, 480), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    if exif_time:
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = exif_time.strftime("%Y:%m:%d %H:%M:%S")
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_difference_hash_survives_recompression_and_exif_time_is_read():
    original = Image.open(io.BytesIO(_noise_jpeg(1)))
    buffer = io.BytesIO()
    original.resize((320, 240)).save(buffer, format="JPEG", quality=60)
    recompressed = Image.open(io.BytesIO(buffer.getvalue()))
    other = Image.open(io.BytesIO(_noise_jpeg(2)))
    first = verification.difference_hash(original)
    assert verification.hamming_distance(first, verification.difference_hash(recompressed)) <= 6
    assert verification.hamming_distance(first, verification.difference_hash(other)) > 6
    when = datetime(2026, 10, 30, 8, 15, 0)
    assert verification.photo_taken_at(Image.open(io.BytesIO(_noise_jpeg(3, when)))) == when
    assert verification.photo_taken_at(original) is None


class _FakeVerifier:
    """Deterministic stand-in for CLIP + YOLO: every photo looks like a clear walk."""
    ready = True

    def status(self):
        return {"ready": True, "message": None, "trained_classifier": False, "object_detector": "fake", "clip_model": "fake", "prompt_version": "test"}

    def verify(self, activity, image):
        analysis = _analysis(walk=0.9, feeding=0.05)
        return decide(activity, analysis, SETTINGS), analysis


def test_verify_endpoint_points_duplicates_daily_limit_and_old_photos(tmp_path, monkeypatch):
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(tmp_path / "verify.sqlite3"))
    monkeypatch.setattr(api_module.verification, "verifier", _FakeVerifier())
    monkeypatch.setitem(api_module.DAILY_REWARD_LIMITS, "walk", 2)

    with TestClient(app) as client:
        token = client.post("/api/auth/register", json={
            "email": "walker@example.test", "password": "correct horse battery staple", "display_name": "산책러"
        }).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        send = lambda activity, data: client.post(f"/api/verify/{activity}", headers=headers, files={"photo": ("p.jpg", data, "image/jpeg")}).json()

        first = send("walk", _noise_jpeg(10, datetime.now() - timedelta(minutes=5)))
        assert first["verified"] is True and first["points_awarded"] == 100 and first["balance"] == 100
        assert {c["key"] for c in first["checks"]} >= {"dog", "scene", "outdoor", "leash", "duplicate", "taken_at"}

        again = send("walk", _noise_jpeg(10))
        assert again["verified"] is False and again["points_awarded"] == 0
        assert next(c for c in again["checks"] if c["key"] == "duplicate")["passed"] is False

        old = send("walk", _noise_jpeg(11, datetime.now() - timedelta(days=3)))
        assert old["verified"] is False and "24시간" in old["message"]

        assert send("walk", _noise_jpeg(12))["points_awarded"] == 100
        capped = send("walk", _noise_jpeg(13))
        assert capped["verified"] is True and capped["points_awarded"] == 0 and capped["balance"] == 200

        feeding = send("feeding", _noise_jpeg(14))
        assert feeding["verified"] is False and feeding["points_awarded"] == 0

        logs = client.get("/api/activity/logs", headers=headers).json()["items"]
        assert [log["status"] for log in logs].count("verified") == 3
        assert client.get("/health").json()["ready"] is True

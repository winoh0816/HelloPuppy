from __future__ import annotations

import io
import json
import random
from datetime import datetime, timedelta

import pytest
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


def _walk_only_model(threshold=0.5):
    """A walk model that only looks at the full-image walk score: probability = sigmoid(10 * (walk - 0.5))."""
    count = len(verification.WALK_FEATURES)
    weights = [10.0 if name == "walk" else 0.0 for name in verification.WALK_FEATURES]
    mean = [0.5 if name == "walk" else 0.0 for name in verification.WALK_FEATURES]
    return verification.WalkModel(mean, [1.0] * count, weights, 0.0, threshold, verification.PROMPT_VERSION)


def test_subject_box_joins_people_and_bowls_touching_the_dog():
    near_person = Detection("person", 0.8, (0.55, 0.10, 0.80, 0.90))
    far_person = Detection("person", 0.8, (0.95, 0.00, 1.00, 0.10))
    x1, y1, x2, y2 = verification.subject_box([DOG, near_person, far_person])
    assert x1 < 0.30 and x2 > 0.80 and y1 < 0.10 and y2 > 0.90
    assert verification.subject_box([DOG, far_person])[2] < 0.70
    assert verification.subject_box([near_person]) is None


def test_walk_model_decides_walk_and_falls_back_to_rules_without_detector():
    model = _walk_only_model()
    passed = decide("walk", _analysis(walk=0.8, leash=0.0, outdoor=0.1), SETTINGS, model)
    assert passed.verified  # 목줄·야외는 모델 안에서만 반영되고 단독으로 탈락시키지 않는다
    assert {c["key"] for c in passed.checks} >= {"dog", "scene", "outdoor", "leash", "person"}
    assert not decide("walk", _analysis(walk=0.3), SETTINGS, model).verified
    assert not decide("walk", _analysis(walk=0.8, detections=[]), SETTINGS, model).verified
    # 탐지 결과가 없으면 특징을 만들 수 없어 기존 규칙으로 판단한다.
    assert not decide("walk", _analysis(walk=0.8, leash=0.0, detections=None), SETTINGS, model).verified
    # 급여는 모델과 상관없이 규칙으로 판단한다.
    assert not decide("feeding", _analysis(feeding=0.6), SETTINGS, model).verified


def test_walk_model_file_round_trip_and_prompt_check(tmp_path):
    path = tmp_path / "walk_model.json"
    path.write_text(json.dumps(_walk_only_model(0.7).to_json()), encoding="utf-8")
    assert verification.WalkModel.load(path).threshold == 0.7
    stale = {**_walk_only_model().to_json(), "prompt_version": "old"}
    path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(ValueError):
        verification.WalkModel.load(path)
    assert verification.WalkModel.load(tmp_path / "missing.json") is None
    # 저장소에 포함된 모델은 현재 CLIP 문장과 특징 목록에 맞아야 한다.
    if verification.WALK_MODEL_PATH.is_file():
        assert verification.WalkModel.load() is not None


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

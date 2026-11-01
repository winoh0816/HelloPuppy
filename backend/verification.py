"""Walk / feeding photo verification.

학습된 행동 데이터셋이 없는 상태에서 동작하도록 다음을 결합한다.
1. CLIP 제로샷 장면 분류: 산책·급여·기타 장면을 여러 문장(prompt)으로 비교한다.
2. COCO 사전학습 YOLO 객체 탐지: 개·사람·그릇 위치를 찾는다. (LVIS·Open Images 등 공개 데이터에
   '목줄' 클래스는 없어서 목줄은 CLIP 문장으로 판단한다.)
3. 규칙: 개가 실제로 보이는지, 산책은 야외인지, 급여는 그릇이 개 가까이에 있는지 확인한다.
4. (선택) backend/models/activity_classifier.pt 가 학습돼 있으면 CLIP 점수와 평균한다.

부정 사용 방지(중복 사진·촬영 시각·하루 보상 횟수)는 app.py 에서 이 모듈의 도우미로 처리한다.
점수는 정확도 보장이 아니며 임계값은 backend/tools/evaluate_verifier.py 결과로 보정한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

MODEL_DIR = Path(os.getenv("HELLOPUPPY_MODEL_DIR", Path(__file__).parent / "models"))
ACTIVITY_MODEL_PATH = MODEL_DIR / "activity_classifier.pt"
YOLO_MODEL_PATH = Path(os.getenv("HELLOPUPPY_YOLO_MODEL", MODEL_DIR / "yolo11s.pt"))
CLIP_CACHE_DIR = MODEL_DIR / "clip"
CLIP_MODEL = os.getenv("HELLOPUPPY_CLIP_MODEL", "ViT-B-32")
CLIP_PRETRAINED = os.getenv("HELLOPUPPY_CLIP_PRETRAINED", "laion2b_s34b_b79k")

ACTIVITY_PROMPTS: dict[str, list[str]] = {
    "walk": [
        "a photo of a person walking a dog on a leash outdoors",
        "a dog on a leash walking on a street",
        "a dog walking on a sidewalk with its owner",
        "a dog taking a walk in a park",
        "a photo taken while walking a dog, with the leash visible",
        "a dog walking on a trail outside",
    ],
    "feeding": [
        "a photo of a dog eating food from a bowl",
        "a dog eating kibble from a food bowl",
        "a dog with its head in a food bowl",
        "a person feeding a dog dog food",
        "a dog eating its meal next to a bowl on the floor",
        "a dog eating from a feeder",
    ],
    "other": [
        "a photo of a dog sleeping",
        "a dog lying on a bed or sofa indoors",
        "a close-up portrait of a dog's face",
        "a dog playing with a toy",
        "a dog sitting indoors",
        "a dog in a car",
        "a photo of a cat",
        "a bowl of dog food with no dog",
        "an empty dog bowl",
        "a leash with no dog",
        "a street with no animals",
        "a person without a dog",
        "a screenshot of a phone screen",
        "a stuffed toy dog",
        "a drawing or cartoon of a dog",
        "a dog standing on the grass posing for a photo",
        "a dog sitting on the grass in a backyard",
        "a dog playing fetch with a frisbee or a ball",
        "a dog running off leash in a field",
        "a dog chewing a bone or a toy",
        "a dog sitting on a chair or a bench",
        "a person eating food with a dog nearby",
        "a dog being given a treat by hand",
    ],
}
# 두 가지 중 어느 쪽에 가까운지 보는 보조 판단. 첫 번째 키의 확률을 사용한다.
BINARY_PROMPTS: dict[str, dict[str, list[str]]] = {
    "outdoor": {
        "yes": ["a photo taken outdoors", "a photo of a street, park or trail outside"],
        "no": ["a photo taken indoors", "a photo inside a house or apartment"],
    },
    # 동물보호법상 산책 시 목줄·가슴줄 착용이 의무라 산책 근거로 쓴다. 공개 탐지 데이터셋에 목줄 클래스가 없어 CLIP으로 판단.
    "leash": {
        "yes": ["a dog on a leash", "a person holding a dog's leash", "a dog wearing a harness attached to a leash"],
        "no": ["a dog without a leash", "a dog running free off leash", "a dog posing for a photo without a leash"],
    },
}
PROMPT_VERSION = hashlib.sha256(json.dumps([ACTIVITY_PROMPTS, BINARY_PROMPTS], sort_keys=True).encode("utf-8")).hexdigest()[:12]
# COCO class ids used by the pretrained YOLO model
COCO_LABELS = {0: "person", 15: "cat", 16: "dog", 45: "bowl"}
ACTIVITY_LABELS = {"walk": "산책", "feeding": "급여"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # 기본값은 evaluate_verifier.py 로 COCO 실장면 + Oxford Pet 에서 보정한 값 (실장면 오인증률 약 3% 목표)
    walk_threshold: float = 0.35
    feeding_threshold: float = 0.25
    margin: float = 0.05
    strong_feeding: float = 0.80
    outdoor_threshold: float = 0.30
    leash_threshold: float = 0.05
    dog_confidence: float = 0.30
    bowl_confidence: float = 0.20
    trained_model_weight: float = 0.5

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            walk_threshold=_env_float("HELLOPUPPY_WALK_THRESHOLD", cls.walk_threshold),
            feeding_threshold=_env_float("HELLOPUPPY_FEEDING_THRESHOLD", cls.feeding_threshold),
            margin=_env_float("HELLOPUPPY_ACTIVITY_MARGIN", cls.margin),
            strong_feeding=_env_float("HELLOPUPPY_STRONG_FEEDING", cls.strong_feeding),
            outdoor_threshold=_env_float("HELLOPUPPY_OUTDOOR_THRESHOLD", cls.outdoor_threshold),
            leash_threshold=_env_float("HELLOPUPPY_LEASH_THRESHOLD", cls.leash_threshold),
            dog_confidence=_env_float("HELLOPUPPY_DOG_CONFIDENCE", cls.dog_confidence),
            bowl_confidence=_env_float("HELLOPUPPY_BOWL_CONFIDENCE", cls.bowl_confidence),
            trained_model_weight=_env_float("HELLOPUPPY_TRAINED_MODEL_WEIGHT", cls.trained_model_weight),
        )


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 normalised to 0..1

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "confidence": round(self.confidence, 4), "box": [round(v, 4) for v in self.box]}


@dataclass
class Analysis:
    """Raw model outputs for one photo, independent of the requested activity."""
    activity_scores: dict[str, float]
    outdoor: float
    leash: float
    detections: list[Detection] | None  # None when the detector is unavailable
    sources: list[str] = field(default_factory=list)


@dataclass
class Decision:
    verified: bool
    predicted: str
    confidence: float
    margin: float
    checks: list[dict[str, Any]]
    message: str
    dog_confidence: float | None


def bowl_near_dog(dog: Detection, bowl: Detection) -> bool:
    """A bowl counts when its centre lies inside the dog box expanded by 35% of its size, or the boxes overlap."""
    dx1, dy1, dx2, dy2 = dog.box
    width, height = dx2 - dx1, dy2 - dy1
    ex1, ey1, ex2, ey2 = dx1 - 0.35 * width, dy1 - 0.35 * height, dx2 + 0.35 * width, dy2 + 0.35 * height
    bx1, by1, bx2, by2 = bowl.box
    cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
    overlaps = bx1 < dx2 and bx2 > dx1 and by1 < dy2 and by2 > dy1
    return overlaps or (ex1 <= cx <= ex2 and ey1 <= cy <= ey2)


def decide(activity: str, analysis: Analysis, settings: Settings) -> Decision:
    """Combine scene scores, detections and rules into a verification decision with readable checks."""
    scores = analysis.activity_scores
    predicted = max(scores, key=scores.get)
    expected = scores[activity]
    margin = expected - max(score for label, score in scores.items() if label != activity)
    threshold = settings.walk_threshold if activity == "walk" else settings.feeding_threshold
    checks: list[dict[str, Any]] = []

    def check(key: str, label: str, passed: bool | None, detail: str) -> None:
        checks.append({"key": key, "label": label, "passed": passed, "detail": detail})

    dogs: list[Detection] = []
    dog_confidence: float | None = None
    if analysis.detections is None:
        dog_ok: bool | None = None
        check("dog", "강아지 확인", None, "객체 탐지 모델이 없어 장면 점수로만 판단했어요.")
    else:
        dogs = sorted((d for d in analysis.detections if d.label == "dog" and d.confidence >= settings.dog_confidence),
                      key=lambda d: d.confidence, reverse=True)
        dog_confidence = max((d.confidence for d in analysis.detections if d.label == "dog"), default=0.0)
        dog_ok = bool(dogs)
        cat_only = not dogs and any(d.label == "cat" and d.confidence >= settings.dog_confidence for d in analysis.detections)
        check("dog", "강아지 확인", dog_ok,
              f"강아지 {len(dogs)}마리 탐지 (신뢰도 {dog_confidence:.0%})" if dog_ok
              else ("고양이로 보여요. 강아지 사진으로 인증해 주세요." if cat_only else "사진에서 강아지를 찾지 못했어요."))

    scene_ok = expected >= threshold and margin >= settings.margin
    label = ACTIVITY_LABELS[activity]
    check("scene", f"{label} 장면", scene_ok,
          f"{label} 장면 점수 {expected:.0%} (기준 {threshold:.0%}), 다른 장면보다 {margin:+.0%}"
          + ("" if scene_ok else f" · 가장 비슷한 장면: {ACTIVITY_LABELS.get(predicted, '기타')}"))

    if activity == "walk":
        outdoor_ok = analysis.outdoor >= settings.outdoor_threshold
        check("outdoor", "야외 촬영", outdoor_ok, f"야외 점수 {analysis.outdoor:.0%}")
        leash_ok = analysis.leash >= settings.leash_threshold
        check("leash", "목줄·가슴줄", leash_ok,
              f"목줄 점수 {analysis.leash:.0%}" + ("" if leash_ok else " · 목줄이 보이게 찍어 주세요"))
        if analysis.detections is not None:
            people = [d for d in analysis.detections if d.label == "person" and d.confidence >= 0.3]
            check("person", "보호자 동행 (참고)", None, f"사람 {len(people)}명 탐지" if people else "사람은 보이지 않아요 (보호자 시점 촬영도 괜찮아요)")
        verified = dog_ok is not False and scene_ok and outdoor_ok and leash_ok
    else:
        strong = expected >= settings.strong_feeding and margin >= settings.margin
        if analysis.detections is None:
            bowl_ok: bool | None = None
            check("bowl", "밥그릇 위치", None, "객체 탐지 모델이 없어 확인하지 못했어요.")
        else:
            bowls = [d for d in analysis.detections if d.label == "bowl" and d.confidence >= settings.bowl_confidence]
            bowl_ok = any(bowl_near_dog(dog, bowl) for dog in dogs for bowl in bowls)
            detail = ("강아지 가까이에 그릇이 있어요" if bowl_ok
                      else ("그릇이 강아지와 떨어져 있어요" if bowls else "그릇을 찾지 못했어요"))
            if not bowl_ok and strong:
                detail += " · 급여 장면 점수가 높아 통과"
            check("bowl", "강아지 옆 밥그릇", bowl_ok or strong, detail)
        verified = dog_ok is not False and scene_ok and (bowl_ok is not False or strong)

    if verified:
        message = f"{label} 인증에 성공했어요."
    else:
        failed = [item["label"] for item in checks if item["passed"] is False]
        message = f"{label} 장면을 충분히 확인하지 못했어요. 확인 필요: {', '.join(failed)}"
    return Decision(verified, predicted, expected, margin, checks, message, dog_confidence)


class ActivityVerifier:
    """Lazily loads CLIP (required), COCO YOLO (recommended) and the optional trained classifier."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self.error: str | None = None
        self._clip: Any = None
        self._preprocess: Any = None
        self._text_features: dict[str, Any] = {}
        self._yolo: Any = None
        self._trained: Any = None
        self._trained_transform: Any = None
        self._trained_classes: list[str] = []

    @property
    def ready(self) -> bool:
        self.load()
        return self._clip is not None

    def status(self) -> dict[str, Any]:
        self.load()
        return {
            "ready": self._clip is not None,
            "clip_model": f"{CLIP_MODEL}/{CLIP_PRETRAINED}" if self._clip is not None else None,
            "prompt_version": PROMPT_VERSION,
            "object_detector": YOLO_MODEL_PATH.name if self._yolo is not None else None,
            "trained_classifier": self._trained is not None,
            "message": self.error,
        }

    def load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                self._load_clip()
            except Exception as error:  # missing package or weights: fail closed
                self.error = f"CLIP 모델을 불러오지 못했습니다. backend/tools/download_verification_models.py 를 실행하세요. ({error})"
            try:
                self._load_yolo()
            except Exception as error:
                self.error = (self.error + " / " if self.error else "") + f"객체 탐지 모델 로딩 실패: {error}"
            try:
                self._load_trained()
            except Exception as error:
                self.error = (self.error + " / " if self.error else "") + f"학습 분류기 로딩 실패: {error}"
            self._loaded = True

    def _load_clip(self) -> None:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(CLIP_MODEL, pretrained=CLIP_PRETRAINED, cache_dir=str(CLIP_CACHE_DIR))
        model.eval()
        tokenizer = open_clip.get_tokenizer(CLIP_MODEL)
        groups = {f"activity:{key}": prompts for key, prompts in ACTIVITY_PROMPTS.items()}
        for name, options in BINARY_PROMPTS.items():
            groups.update({f"binary:{name}:{option}": prompts for option, prompts in options.items()})
        features = {}
        with torch.inference_mode():
            for group, prompts in groups.items():
                encoded = model.encode_text(tokenizer(prompts))
                features[group] = encoded / encoded.norm(dim=-1, keepdim=True)
        self._clip, self._preprocess, self._text_features = model, preprocess, features

    def _load_yolo(self) -> None:
        if not YOLO_MODEL_PATH.is_file():
            raise FileNotFoundError(f"{YOLO_MODEL_PATH} 이 없습니다")
        from ultralytics import YOLO
        self._yolo = YOLO(str(YOLO_MODEL_PATH))

    def _load_trained(self) -> None:
        if not ACTIVITY_MODEL_PATH.is_file():
            return
        import torch
        from torchvision import transforms
        from .model import IMAGE_SIZE, create_activity_model

        checkpoint = torch.load(ACTIVITY_MODEL_PATH, map_location="cpu", weights_only=True)
        classes = checkpoint.get("classes")
        if not isinstance(classes, list) or set(classes) != {"walk", "feeding", "other"}:
            raise ValueError("모델의 클래스 정보가 올바르지 않습니다.")
        model = create_activity_model(num_classes=len(classes))
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        self._trained, self._trained_classes = model, classes
        self._trained_transform = transforms.Compose([
            transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)), transforms.ToTensor(),
            transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
        ])

    def analyze(self, image: Image.Image) -> Analysis:
        import torch

        if self._clip is None:
            raise RuntimeError(self.error or "CLIP 모델이 준비되지 않았습니다.")
        # 정사각형으로 여백을 채워 가장자리의 목줄·그릇이 잘리지 않게 한다.
        square = ImageOps.pad(image, (max(image.size),) * 2, color=(0, 0, 0))
        with torch.inference_mode():
            features = self._clip.encode_image(self._preprocess(square).unsqueeze(0))
            features = features / features.norm(dim=-1, keepdim=True)
            scale = self._clip.logit_scale.exp()

            def group_probs(prefix: str) -> dict[str, float]:
                keys = [key for key in self._text_features if key.startswith(prefix)]
                logits = torch.cat([scale * features @ self._text_features[key].T for key in keys], dim=-1)[0]
                probabilities = logits.softmax(dim=-1)
                result, offset = {}, 0
                for key in keys:
                    count = self._text_features[key].shape[0]
                    result[key[len(prefix):]] = float(probabilities[offset:offset + count].sum())
                    offset += count
                return result

            activity = group_probs("activity:")
            outdoor = group_probs("binary:outdoor:")["yes"]
            leash = group_probs("binary:leash:")["yes"]
            sources = ["clip"]
            if self._trained is not None:
                logits = self._trained(self._trained_transform(image).unsqueeze(0))[0]
                trained = {label: float(p) for label, p in zip(self._trained_classes, logits.softmax(dim=0))}
                weight = Settings.from_env().trained_model_weight
                activity = {key: (1 - weight) * activity[key] + weight * trained[key] for key in activity}
                sources.append("trained_classifier")

        detections = None
        if self._yolo is not None:
            result = self._yolo.predict(source=image, verbose=False, conf=0.15, classes=list(COCO_LABELS))[0]
            width, height = image.size
            detections = [
                Detection(COCO_LABELS[int(box.cls.item())], float(box.conf.item()),
                          tuple(float(v) for v in (box.xyxy[0][0] / width, box.xyxy[0][1] / height, box.xyxy[0][2] / width, box.xyxy[0][3] / height)))
                for box in result.boxes
            ]
            sources.append("yolo_coco")
        return Analysis(activity, outdoor, leash, detections, sources)

    def verify(self, activity: str, image: Image.Image, settings: Settings | None = None) -> tuple[Decision, Analysis]:
        analysis = self.analyze(image)
        return decide(activity, analysis, settings or Settings.from_env()), analysis


# ---------------------------------------------------------------------------
# 부정 사용 방지 도우미
# ---------------------------------------------------------------------------

def difference_hash(image: Image.Image, size: int = 8) -> str:
    """64-bit dHash: robust to re-compression and resizing, used to spot re-submitted photos."""
    grey = ImageOps.exif_transpose(image).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = grey.tobytes()
    bits = 0
    for row in range(size):
        for col in range(size):
            left, right = pixels[row * (size + 1) + col], pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | int(left > right)
    return f"{bits:016x}"


def hamming_distance(first: str, second: str) -> int:
    return bin(int(first, 16) ^ int(second, 16)).count("1")


def photo_taken_at(image: Image.Image) -> datetime | None:
    """Read EXIF DateTimeOriginal (local camera time). Many browsers strip EXIF, so None is common."""
    try:
        exif = image.getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        return datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S") if raw else None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


verifier = ActivityVerifier()

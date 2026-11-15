"""Download the pretrained models used by photo verification into backend/models.

- CLIP (open_clip, 기본 ViT-B-32 / laion2b_s34b_b79k, 약 600MB) -> backend/models/clip/
- COCO 사전학습 YOLO (기본 yolo11s.pt, 약 19MB) -> backend/models/yolo11s.pt
- 영수증 OCR RapidOCR PP-OCRv5 검출 + 한국어 인식 모델 (약 20MB) -> backend/models/ocr/

Run from the repository root:
    .venv-backend\\Scripts\\python.exe -m backend.tools.download_verification_models
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from backend.receipt import OCR_MODEL_DIR, reader
from backend.verification import CLIP_CACHE_DIR, CLIP_MODEL, CLIP_PRETRAINED, YOLO_MODEL_PATH, verifier


def main() -> None:
    CLIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"CLIP {CLIP_MODEL}/{CLIP_PRETRAINED} 내려받는 중 -> {CLIP_CACHE_DIR}")
    import open_clip
    open_clip.create_model_and_transforms(CLIP_MODEL, pretrained=CLIP_PRETRAINED, cache_dir=str(CLIP_CACHE_DIR))

    if not YOLO_MODEL_PATH.is_file():
        print(f"YOLO {YOLO_MODEL_PATH.name} 내려받는 중 -> {YOLO_MODEL_PATH}")
        from ultralytics import YOLO
        # Ultralytics는 현재 폴더에 가중치를 받으므로 임시 폴더에서 받은 뒤 옮긴다.
        with tempfile.TemporaryDirectory() as temp:
            model = YOLO(str(Path(temp) / YOLO_MODEL_PATH.name))
            downloaded = Path(model.ckpt_path)
            YOLO_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(downloaded, YOLO_MODEL_PATH)

    print(f"영수증 OCR (RapidOCR PP-OCRv5 한국어) 내려받는 중 -> {OCR_MODEL_DIR}")
    ocr_ready = reader.ready

    status = verifier.status()
    print("상태:", status, "| OCR:", "준비됨" if ocr_ready else reader.error)
    if not status["ready"] or not status["object_detector"] or not ocr_ready:
        sys.exit(1)


if __name__ == "__main__":
    main()

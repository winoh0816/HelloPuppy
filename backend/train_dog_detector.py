"""Fine-tune a YOLO dog detector from the supplied Roboflow dog-breed dataset."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "Dataset" / "Dog Breeds.v3i.yolov8"
OUTPUT = Path(__file__).parent / "models" / "dog_detector.pt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="", help="For example: 0 (GPU) or cpu")
    args = parser.parse_args()

    source_yaml = DATASET / "data.yaml"
    if not source_yaml.is_file():
        raise SystemExit(f"YOLO 데이터 설명 파일을 찾지 못했습니다: {source_yaml}")
    if not (DATASET / "train" / "images").is_dir():
        raise SystemExit("train/images 폴더가 없습니다.")
    validation_dir = DATASET / "valid" / "images"
    if not validation_dir.is_dir():
        validation_dir = DATASET / "test" / "images"
    if not validation_dir.is_dir():
        raise SystemExit("valid/images 또는 test/images 검증 폴더가 없습니다.")

    config = yaml.safe_load(source_yaml.read_text(encoding="utf-8"))
    config.update({
        "path": str(DATASET.resolve()),
        "train": "train/images",
        "val": str(validation_dir.resolve()),
        "test": "test/images"
    })
    with tempfile.TemporaryDirectory(prefix="hellopuppy-yolo-") as temp_dir:
        config_path = Path(temp_dir) / "dog-breeds.yaml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        model = YOLO("yolov8n.pt")
        result = model.train(
            data=str(config_path),
            epochs=args.epochs,
            batch=args.batch,
            imgsz=640,
            device=args.device or None,
            project=str(Path(__file__).parent / "runs"),
            name="dog-breed-detector",
            exist_ok=True
        )
        best = Path(result.save_dir) / "weights" / "best.pt"
        if not best.is_file():
            raise SystemExit(f"학습된 최적 가중치를 찾지 못했습니다: {best}")
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, OUTPUT)
        print(f"Dog detector saved: {OUTPUT}")
        print("Class labels are 100 dog breeds; this model checks dog presence, not walking/feeding actions.")


if __name__ == "__main__":
    main()

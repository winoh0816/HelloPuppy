"""Fine-tune an activity classifier using manually labeled photos.

Expected folders:
  Dataset/activity/{train,val}/{feeding,other,walk}/image.jpg
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from model import ACTIVITY_CLASSES, IMAGE_SIZE, create_activity_model

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "Dataset" / "activity"
MODEL_OUT = Path(__file__).parent / "models" / "activity_classifier.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--no-pretrained", action="store_true", help="Do not download ImageNet initialization weights")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_dir = args.data / "train"
    val_dir = args.data / "val"
    if not train_dir.is_dir() or not val_dir.is_dir():
        raise SystemExit(
            f"학습 폴더가 없습니다: {args.data}\n"
            "train/val 아래에 feeding, other, walk 폴더를 만들고 사진을 넣어 주세요."
        )

    train_transform = transforms.Compose([
        transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(10),
        transforms.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.12),
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
    ])
    eval_transform = transforms.Compose([
        transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
    ])
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    for split_dir in (train_dir, val_dir):
        missing = [
            label for label in ACTIVITY_CLASSES
            if not any(
                file.is_file() and file.suffix.lower() in image_extensions
                for file in (split_dir / label).glob("*")
            )
        ]
        if missing:
            raise SystemExit(
                f"{split_dir}에 사진이 없는 클래스: {', '.join(missing)}. "
                "사람이 확인한 학습/검증 사진을 각 클래스 폴더에 추가해 주세요."
            )

    train_set = datasets.ImageFolder(train_dir, transform=train_transform)
    val_set = datasets.ImageFolder(val_dir, transform=eval_transform)
    if set(train_set.classes) != set(ACTIVITY_CLASSES) or set(val_set.classes) != set(ACTIVITY_CLASSES):
        raise SystemExit(f"두 폴더 모두 클래스 폴더가 필요합니다: {', '.join(ACTIVITY_CLASSES)}")
    if min(train_set.targets.count(train_set.class_to_idx[name]) for name in ACTIVITY_CLASSES) < 10:
        raise SystemExit("각 학습 클래스에 최소 10장의 사진을 준비해 주세요.")
    if min(val_set.targets.count(val_set.class_to_idx[name]) for name in ACTIVITY_CLASSES) < 3:
        raise SystemExit("각 검증 클래스에 최소 3장의 사진을 준비해 주세요.")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True, num_workers=args.workers)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False, num_workers=args.workers)
    model = create_activity_model(
        num_classes=len(train_set.classes),
        pretrained=not args.no_pretrained
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    criterion = nn.CrossEntropyLoss()
    best_accuracy = -1.0

    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * labels.size(0)

        model.eval()
        correct = 0
        total = 0
        with torch.inference_mode():
            for images, labels in val_loader:
                logits = model(images.to(device))
                correct += int((logits.argmax(1).cpu() == labels).sum().item())
                total += labels.size(0)
        accuracy = correct / max(total, 1)
        average_loss = train_loss / max(len(train_set), 1)
        print(f"epoch {epoch + 1}/{args.epochs}: train_loss={average_loss:.4f}, val_accuracy={accuracy:.3f}")

        if accuracy > best_accuracy:
            best_accuracy = accuracy
            MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
                "classes": train_set.classes,
                "image_size": IMAGE_SIZE,
                "validation_accuracy": accuracy,
                "dataset_counts": {
                    "train": len(train_set),
                    "val": len(val_set)
                }
            }, MODEL_OUT)

    print(json.dumps({"model": str(MODEL_OUT), "best_val_accuracy": best_accuracy}, ensure_ascii=False))


if __name__ == "__main__":
    main()

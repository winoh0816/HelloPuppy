"""Prepare MPDD dog images as weakly labeled walk examples.

MPDD exposes image-level dog identity/camera-style splits, not keypoint or
walking-action annotations. This utility requires explicit opt-in and splits by
dog identity so the same dog cannot occur in both train and validation.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "Dataset" / "MPDD" / "pytorch"
DEFAULT_OUTPUT = ROOT / "Dataset" / "activity"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def dog_identity(image_path: Path) -> str:
    """Read the leading identity token used by MPDD filenames."""
    identity = image_path.stem.split("_", maxsplit=1)[0]
    if not identity.isdigit():
        raise ValueError(f"MPDD 파일명에 숫자 identity가 없습니다: {image_path.name}")
    return identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validation-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--assume-walk-labels",
        action="store_true",
        help="Explicitly treat MPDD images as weak walk positives despite absent action annotations.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace only the generated MPDD-prefixed images in activity train/val walk folders.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.assume_walk_labels:
        raise SystemExit(
            "MPDD는 산책 행동/키포인트 라벨 데이터가 아니라 개 identity 중심 이미지입니다. "
            "약한 walk 양성 라벨로 사용하려면 --assume-walk-labels 옵션을 명시하세요."
        )
    if not 0.05 <= args.validation_ratio <= 0.5:
        raise SystemExit("--validation-ratio는 0.05~0.5 범위여야 합니다.")

    split_images: dict[str, list[Path]] = {}
    for source_split in ("train", "val"):
        folder = args.source / source_split
        if not folder.is_dir():
            raise SystemExit(f"MPDD split 폴더가 없습니다: {folder}")
        split_images[source_split] = sorted(
            path for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
    images = split_images["train"] + split_images["val"]
    if not images:
        raise SystemExit(f"MPDD train/val 폴더에서 이미지를 찾지 못했습니다: {args.source}")

    by_identity: dict[str, list[Path]] = defaultdict(list)
    for image in images:
        by_identity[dog_identity(image)].append(image)
    identities = sorted(by_identity)
    if len(identities) < 2:
        raise SystemExit("개체 identity가 2개 미만이라 누수 없는 학습/검증 분리가 불가능합니다.")

    rng = random.Random(args.seed)
    shuffled = identities[:]
    rng.shuffle(shuffled)
    validation_identity_count = min(
        len(identities) - 1,
        max(1, round(len(identities) * args.validation_ratio)),
    )
    validation_identities = set(shuffled[:validation_identity_count])

    destination_dirs = {
        "train": args.output / "train" / "walk",
        "val": args.output / "val" / "walk",
    }
    if not args.replace_existing:
        conflicts = [
            str(path)
            for destination in destination_dirs.values()
            for path in destination.glob("mpdd_*")
        ]
        if conflicts:
            raise SystemExit(
                "MPDD 출력 파일이 이미 있습니다. 덮어쓰려면 --replace-existing 옵션을 쓰세요."
            )

    for destination in destination_dirs.values():
        destination.mkdir(parents=True, exist_ok=True)
        if args.replace_existing:
            for previous in destination.glob("mpdd_*"):
                previous.unlink()

    manifest_path = args.output / "mpdd_walk_manifest.csv"
    args.output.mkdir(parents=True, exist_ok=True)
    counts = {"train": 0, "val": 0}
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as manifest_file:
        writer = csv.DictWriter(
            manifest_file,
            fieldnames=["output_split", "identity", "source_split", "source_file", "output_file", "label_quality"],
        )
        writer.writeheader()
        for image in images:
            identity = dog_identity(image)
            output_split = "val" if identity in validation_identities else "train"
            output_name = f"mpdd_{output_split}_{image.name}"
            output_path = destination_dirs[output_split] / output_name
            shutil.copy2(image, output_path)
            writer.writerow({
                "output_split": output_split,
                "identity": identity,
                "source_split": image.parent.name,
                "source_file": str(image.relative_to(args.source)),
                "output_file": str(output_path.relative_to(args.output)),
                "label_quality": "weak_walk_assumption_requires_manual_audit",
            })
            counts[output_split] += 1

    print(f"MPDD walk candidates copied: train={counts['train']}, val={counts['val']}")
    print(f"Identity-disjoint split: train={len(identities) - validation_identity_count}, val={validation_identity_count} identities")
    print(f"Manifest: {manifest_path}")
    print("IMPORTANT: MPDD does not provide walk-action/keypoint labels; audit the copied images before treating them as ground truth.")
    print("The activity model still also needs verified feeding and other images in their respective train/val folders.")


if __name__ == "__main__":
    main()

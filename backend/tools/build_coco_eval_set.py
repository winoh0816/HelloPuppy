"""Build a real-scene evaluation set for walk / feeding / other from COCO 2017 captions.

보유 데이터(MPDD·Oxford Pet)는 개만 잘라낸 사진·인물 사진이라 실제 인증 사진과 다르다. 그래서 COCO의
사람이 쓴 캡션 5개 중 2개 이상이 같은 행동을 말하는 사진을 골라 '실제 장면' 검증 세트를 만든다.
캡션 기반 약한 라벨이므로 결과 해석 전 contact sheet로 검수할 것. 평가 전용이며 학습에 쓰지 않는다.
COCO 주석은 CC BY 4.0, 이미지는 Flickr 원저작자의 라이선스를 따른다.

    .venv-backend\\Scripts\\python.exe -m backend.tools.build_coco_eval_set --per-class 120
"""

from __future__ import annotations

import argparse
import json
import random
import re
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "Dataset" / "activity_eval" / "coco"
CACHE = ROOT / "Dataset" / "activity_eval" / "_cache"
ANNOTATION_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
IMAGE_URL = "http://images.cocodataset.org/{split}/{file_name}"

HOT_DOG = re.compile(r"\bhot ?dogs?\b|\bcorn ?dogs?\b|\bchili ?dogs?\b")
DOG = re.compile(r"\b(dog|dogs|puppy|puppies|pup)\b")
WALK = re.compile(r"\b(walk|walks|walking|walked|leash|leashed|leashes)\b")
FEED = re.compile(r"\b(eat|eats|eating|ate|feeding|fed|feed|chewing|drinking)\b|\b(food|water) (bowl|dish)\b")
OTHER_HINT = re.compile(r"\b(lay|lays|laying|lying|sleep|sleeps|sleeping|sit|sits|sitting|couch|sofa|bed|frisbee|car|window|toy|blanket)\b")


def caption_label(captions: list[str]) -> str | None:
    texts = [caption.lower() for caption in captions]
    if any(HOT_DOG.search(text) for text in texts):
        return None
    dog_mentions = sum(bool(DOG.search(text)) for text in texts)
    if dog_mentions < 2:
        return None
    walk = sum(bool(DOG.search(text) and WALK.search(text)) for text in texts)
    feed = sum(bool(DOG.search(text) and FEED.search(text)) for text in texts)
    if walk >= 2 and feed == 0:
        return "walk"
    if feed >= 2 and walk == 0:
        return "feeding"
    if walk == 0 and feed == 0 and sum(bool(OTHER_HINT.search(text)) for text in texts) >= 2:
        return "other"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-class", type=int, default=120)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / "annotations_trainval2017.zip"
    if not archive.is_file():
        print("COCO 캡션 주석 내려받는 중 (약 241MB)...")
        urllib.request.urlretrieve(ANNOTATION_URL, archive)

    candidates: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    with zipfile.ZipFile(archive) as bundle:
        for split in ("train2017", "val2017"):
            data = json.loads(bundle.read(f"annotations/captions_{split}.json"))
            captions = defaultdict(list)
            for item in data["annotations"]:
                captions[item["image_id"]].append(item["caption"])
            for image in data["images"]:
                label = caption_label(captions[image["id"]])
                if label:
                    candidates[label].append((split, {**image, "captions": captions[image["id"]]}))
    print({label: len(items) for label, items in candidates.items()})

    random.seed(args.seed)
    manifest = []
    for label, items in candidates.items():
        target = OUTPUT / label
        target.mkdir(parents=True, exist_ok=True)
        for split, image in random.sample(items, min(args.per_class, len(items))):
            path = target / image["file_name"]
            if not path.is_file():
                urllib.request.urlretrieve(IMAGE_URL.format(split=split, file_name=image["file_name"]), path)
            manifest.append({"label": label, "file": f"{label}/{image['file_name']}", "split": split,
                             "license": image.get("license"), "flickr_url": image.get("flickr_url"), "captions": image["captions"]})
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(manifest)}장 저장 -> {OUTPUT}")


if __name__ == "__main__":
    main()

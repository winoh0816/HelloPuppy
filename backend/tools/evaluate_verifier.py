"""Evaluate walk / feeding verification on the local datasets and suggest thresholds.

평가 세트 (있는 것만 사용)
- coco: Dataset/activity_eval/coco (build_coco_eval_set.py + curation.json 검수 결과) - 실제 장면
- mpdd_walk: Dataset/activity/{train,val}/walk - 보유 MPDD 약한 산책 라벨 (개만 잘라낸 사진, 참고용)
- oxford_dogs: Dataset/TheOxford-IIIT_Pet_Dataset/images 의 개 사진(소문자 파일명) - 산책·급여가 아닌 반려견 사진
- user: Dataset/activity/test/{walk,feeding,other} - 직접 촬영해 넣은 사진 (가장 중요한 최종 테스트)

    .venv-backend\\Scripts\\python.exe -m backend.tools.evaluate_verifier --limit 150
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from dataclasses import asdict, replace
from pathlib import Path

from PIL import Image, ImageOps

from backend.verification import Analysis, Detection, Settings, decide, verifier

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "Dataset" / "activity_eval" / "_cache" / "analysis_cache.json"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def images_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES) if folder.is_dir() else []


def collect(limit: int, seed: int) -> list[tuple[str, str, Path]]:
    """Return (set_name, expected_label, path)."""
    rng = random.Random(seed)
    sample = lambda items: rng.sample(items, min(limit, len(items)))
    items: list[tuple[str, str, Path]] = []
    coco = ROOT / "Dataset" / "activity_eval" / "coco"
    curation_file = coco / "curation.json"
    curation = json.loads(curation_file.read_text(encoding="utf-8")) if curation_file.is_file() else {}
    if coco.is_dir():
        noise = set(curation.get("walk_noise", []))
        items += [("coco", "walk", p) for p in images_in(coco / "walk") if p.name not in noise]
        if curation:
            items += [("coco", "feeding", coco / "feeding" / name) for name in curation["feeding_positive"]]
            items += [("coco", "other", coco / "feeding" / name) for name in curation["feeding_not"]]
        else:
            items += [("coco", "feeding", p) for p in images_in(coco / "feeding")]
        items += [("coco", "other", p) for p in images_in(coco / "other")]
    activity = ROOT / "Dataset" / "activity"
    mpdd = images_in(activity / "train" / "walk") + images_in(activity / "val" / "walk")
    items += [("mpdd_walk", "walk", p) for p in sample(mpdd)]
    oxford = [p for p in images_in(ROOT / "Dataset" / "TheOxford-IIIT_Pet_Dataset" / "images") if p.name[:1].islower()]
    items += [("oxford_dogs", "other", p) for p in sample(oxford)]
    for label in ("walk", "feeding", "other"):
        items += [("user", label, p) for p in images_in(activity / "test" / label)]
    return items


def analysis_from_dict(data: dict) -> Analysis:
    detections = None if data["detections"] is None else [Detection(d["label"], d["confidence"], tuple(d["box"])) for d in data["detections"]]
    return Analysis(data["activity_scores"], data["outdoor"], data["leash"], detections, data.get("sources", []))


def analyse_all(items: list[tuple[str, str, Path]]) -> dict[str, Analysis]:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}
    status = verifier.status()
    model_key = f"{status['clip_model']}|{status['prompt_version']}|{status['object_detector']}|{status['trained_classifier']}"
    results: dict[str, Analysis] = {}
    started, computed = time.time(), 0
    for _, _, path in items:
        key = f"{model_key}|{path.relative_to(ROOT).as_posix()}"
        if key not in cache:
            image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            analysis = verifier.analyze(image)
            cache[key] = {**asdict(analysis), "detections": None if analysis.detections is None else [d.to_dict() for d in analysis.detections]}
            computed += 1
            if computed % 50 == 0:
                print(f"  분석 {computed}장 ({time.time() - started:.0f}초)")
        results[str(path)] = analysis_from_dict(cache[key])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    if computed:
        print(f"새로 분석 {computed}장, 장당 평균 {(time.time() - started) / computed:.2f}초")
    return results


def score(items, analyses, activity: str, settings: Settings, sets: set[str] | None = None) -> dict[str, float]:
    tp = fp = fn = tn = 0
    for set_name, label, path in items:
        if sets and set_name not in sets:
            continue
        verified = decide(activity, analyses[str(path)], settings).verified
        positive = label == activity
        tp += verified and positive
        fn += (not verified) and positive
        fp += verified and not positive
        tn += (not verified) and not positive
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"positives": tp + fn, "negatives": fp + tn, "recall": recall, "precision": precision,
            "false_accept_rate": fp / (fp + tn) if fp + tn else 0.0, "tp": tp, "fp": fp}


def report(items, analyses, settings: Settings) -> None:
    sets = sorted({set_name for set_name, _, _ in items})
    for activity in ("walk", "feeding"):
        print(f"\n[{activity}] 인증 요청 기준 (양성 = {activity} 사진, 음성 = 나머지)")
        print(f"{'세트':<12}{'양성':>5}{'음성':>5}{'재현율':>8}{'정밀도':>8}{'오인증률':>9}")
        for name in sets + ["ALL(실장면)"]:
            chosen = {s for s in sets if s != "mpdd_walk"} if name.startswith("ALL") else {name}
            m = score(items, analyses, activity, settings, chosen)
            if m["positives"] + m["negatives"] == 0:
                continue
            print(f"{name:<12}{m['positives']:>5}{m['negatives']:>5}{m['recall']:>8.1%}{m['precision']:>8.1%}{m['false_accept_rate']:>9.1%}")


def sweep(items, analyses, base: Settings, max_false_accept: float) -> Settings:
    """Pick per-activity thresholds that maximise recall while keeping the false-accept rate on real scenes low."""
    real = {s for s, _, _ in items if s != "mpdd_walk"}
    thresholds = [0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]
    grids = {
        "walk": [{"walk_threshold": t, "leash_threshold": l, "outdoor_threshold": o}
                 for t in thresholds for l in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3) for o in (0.3, 0.5)],
        "feeding": [{"feeding_threshold": t, "strong_feeding": s} for t in thresholds for s in (0.8, 0.9, 1.01)],
    }
    best = base
    for activity, grid in grids.items():
        candidates = []
        for values in grid:
            trial = replace(best, **values)
            m = score(items, analyses, activity, trial, real)
            if m["false_accept_rate"] <= max_false_accept:
                candidates.append((m["recall"], m["precision"], values))
        if not candidates:
            print(f"추천 {activity}: 오인증률 {max_false_accept:.0%} 이하를 만족하는 조합이 없습니다.")
            continue
        recall, precision, values = max(candidates, key=lambda c: c[:2])
        best = replace(best, **values)
        print(f"추천 {activity}: {values} → 재현율 {recall:.1%}, 정밀도 {precision:.1%}")
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=150, help="MPDD·Oxford 에서 뽑을 최대 장수")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-false-accept", type=float, default=0.05, help="추천 임계값 탐색 시 허용할 실장면 오인증률")
    args = parser.parse_args()

    if not verifier.ready:
        raise SystemExit(verifier.status()["message"])
    items = collect(args.limit, args.seed)
    print(f"평가 사진 {len(items)}장: " + ", ".join(f"{s}/{l}={sum(1 for x in items if x[0] == s and x[1] == l)}"
                                               for s, l in sorted({(s, l) for s, l, _ in items})))
    analyses = analyse_all(items)
    current = Settings.from_env()
    print("\n=== 현재 설정 ===", current)
    report(items, analyses, current)
    print("\n=== 임계값 탐색 ===")
    suggested = sweep(items, analyses, current, args.max_false_accept)
    print("\n=== 추천 설정 적용 시 ===", suggested)
    report(items, analyses, suggested)


if __name__ == "__main__":
    main()

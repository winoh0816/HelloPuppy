"""Train the walk decision model (logistic regression over verification.WALK_FEATURES).

CLIP 장면 점수(전체 + 강아지 주변 확대)와 YOLO 탐지 결과 17개를 하나의 산책 점수로 결합한다.
평가 세트는 evaluate_verifier.py 와 같은 실장면 사진(COCO 검수본 + Oxford 반려견, + 직접 촬영한 사진)을 쓴다.
MPDD 는 강아지만 잘라낸 약한 라벨이라 학습·평가에서 뺀다.

- 5겹 교차검증으로 성능을 보고한다. 임계값도 학습 겹 안에서 다시 교차검증해 고르므로 시험 겹은 한 번도 보지 않는다.
- 최종 모델은 전체 사진으로 학습하고, 교차검증 점수에서 오인증률 목표를 만족하는 임계값을 저장한다.

    .venv-backend\\Scripts\\python.exe -m backend.tools.train_walk_model
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

import torch

from backend.tools.evaluate_verifier import analyse_all, collect
from backend.verification import PROMPT_VERSION, WALK_FEATURES, WALK_MODEL_PATH, Settings, WalkModel, verifier, walk_features


def fit(x: torch.Tensor, y: torch.Tensor, weight_decay: float):
    """Class-balanced L2 logistic regression on standardised features (LBFGS, deterministic)."""
    mean, std = x.mean(0), x.std(0).clamp_min(1e-6)
    xs = (x - mean) / std
    weights = torch.zeros(x.shape[1], requires_grad=True)
    bias = torch.zeros(1, requires_grad=True)
    positive_weight = (1 - y.mean()) / y.mean()
    optimiser = torch.optim.LBFGS([weights, bias], max_iter=200)

    def closure():
        optimiser.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(xs @ weights + bias, y, pos_weight=positive_weight)
        loss = loss + weight_decay * (weights * weights).sum()
        loss.backward()
        return loss

    optimiser.step(closure)
    weights, bias = weights.detach(), bias.detach()
    return mean, std, weights, float(bias), lambda z: torch.sigmoid(((z - mean) / std) @ weights + bias)


def folds(count: int, k: int, seed: int) -> list[list[int]]:
    order = list(range(count))
    random.Random(seed).shuffle(order)
    return [order[i::k] for i in range(k)]


def out_of_fold(x, y, weight_decay, k=5, seed=1) -> torch.Tensor:
    scores = torch.zeros(len(y))
    for test in folds(len(y), k, seed):
        train = sorted(set(range(len(y))) - set(test))
        scores[test] = fit(x[train], y[train], weight_decay)[4](x[test])
    return scores


def threshold_for(scores: torch.Tensor, y: torch.Tensor, max_false_accept: float) -> float:
    """Lowest threshold whose false-accept rate on negatives stays within the target."""
    negatives = scores[y == 0].sort(descending=True).values
    allowed = int(max_false_accept * len(negatives))
    return float(negatives[allowed]) + 1e-6 if allowed < len(negatives) else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-false-accept", type=float, default=0.02, help="실장면 사진 기준 허용 오인증률")
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if not verifier.ready:
        raise SystemExit(verifier.status()["message"])
    items = [item for item in collect(args.limit, args.seed) if item[0] != "mpdd_walk"]
    analyses = analyse_all(items)
    settings = Settings.from_env()
    x = torch.tensor([walk_features(analyses[str(path)]) for _, _, path in items])
    y = torch.tensor([float(label == "walk") for _, label, _ in items])
    # 강아지가 탐지되지 않은 사진은 decide() 에서 어차피 실패하므로 임계값 계산에서도 0점으로 둔다.
    dog = torch.tensor([float(any(d.label == "dog" and d.confidence >= settings.dog_confidence for d in analyses[str(path)].detections or []))
                        for _, _, path in items])
    print(f"학습 사진 {len(items)}장 (산책 {int(y.sum())}장, 그 외 {int(len(y) - y.sum())}장), 특징 {len(WALK_FEATURES)}개")

    tp = fp = fn = tn = 0
    for test in folds(len(y), 5, 0):
        train = sorted(set(range(len(y))) - set(test))
        threshold = threshold_for(out_of_fold(x[train], y[train], args.weight_decay) * dog[train], y[train], args.max_false_accept)
        accepted = fit(x[train], y[train], args.weight_decay)[4](x[test]) * dog[test] >= threshold
        positive = y[test] == 1
        tp += int((accepted & positive).sum()); fp += int((accepted & ~positive).sum())
        fn += int((~accepted & positive).sum()); tn += int((~accepted & ~positive).sum())
    cv = {"recall": tp / (tp + fn), "precision": tp / max(1, tp + fp), "false_accept_rate": fp / (fp + tn), "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    print(f"5겹 교차검증: 재현율 {cv['recall']:.1%}, 정밀도 {cv['precision']:.1%}, 오인증률 {cv['false_accept_rate']:.1%}")

    mean, std, weights, bias, _ = fit(x, y, args.weight_decay)
    threshold = threshold_for(out_of_fold(x, y, args.weight_decay) * dog, y, args.max_false_accept)
    model = WalkModel(mean.tolist(), std.tolist(), weights.tolist(), bias, threshold, PROMPT_VERSION, {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "photos": {"walk": int(y.sum()), "not_walk": int(len(y) - y.sum())},
        "sets": sorted({s for s, _, _ in items}),
        "target_false_accept": args.max_false_accept, "weight_decay": args.weight_decay, "cross_validation": cv,
    })
    WALK_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    WALK_MODEL_PATH.write_text(json.dumps(model.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {WALK_MODEL_PATH} (임계값 {threshold:.3f})")
    print("특징별 가중치 (표준화 기준, 클수록 산책 쪽):")
    for name, weight in sorted(zip(WALK_FEATURES, weights.tolist()), key=lambda item: -abs(item[1])):
        print(f"  {name:<16}{weight:+.2f}")


if __name__ == "__main__":
    main()

"""Evaluate receipt OCR + field extraction on Dataset/receipt/ocrReceipt1000 (built by build_receipt_dataset.py).

OCR output is cached per preset in <dataset>/cache/<preset>.jsonl, so changing only parse_receipt() re-scores in
seconds (`--parse-only`). Labelled KORIE receipts are scored against their transcriptions:
total / date / time exact match (time5: within 5 minutes), store name fuzzy match (similarity >= 0.6 or containment after removing spaces and
punctuation), and "id-ready" = total and date both right (what the duplicate fingerprint needs).
With the KORIE item labels downloaded, item_recall / item_prec score item amounts and item_name the names (similarity >= 0.6).
A random sample of the team photos was labelled by hand (manual_labels.csv: total and date; split "manual").
Unlabelled and non-Korean ("foreign") photos are scored by coverage: how often each field was found at all.

    python -m backend.tools.evaluate_receipt_ocr --preset baseline --split train
    python -m backend.tools.evaluate_receipt_ocr --preset baseline --parse-only --split test --errors 20
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

from backend import receipt

ROOT = Path(__file__).resolve().parents[2]

# Reader settings to compare. "current" is whatever receipt.py ships with.
PRESETS: dict[str, dict] = {
    "baseline": {"engine": {}, "min_side": 0},                       # settings before the dataset work
    "upscale1600": {"engine": {}, "min_side": 1600},
    "det_server": {"engine": {"Det.model_type": "server"}, "min_side": 0},
    "det_server_up": {"engine": {"Det.model_type": "server"}, "min_side": 1600},
    "det_v6": {"engine": {"Det.ocr_version": "PP-OCRv6", "Det.model_type": "small"}, "min_side": 0},
    "det_v6_up": {"engine": {"Det.ocr_version": "PP-OCRv6", "Det.model_type": "small"}, "min_side": 1600},
    "det_960_up": {"engine": {"Det.limit_side_len": 960}, "min_side": 1600},
    "current": None,
}


def make_reader(preset: str) -> receipt.ReceiptReader:
    config = PRESETS[preset]
    if config is None:
        return receipt.ReceiptReader()
    engine = {}
    for key, value in config["engine"].items():  # turn strings into rapidocr enums
        from rapidocr import ModelType, OCRVersion
        engine[key] = OCRVersion(value) if key.endswith("ocr_version") else ModelType(value) if key.endswith("model_type") else value
    return receipt.ReceiptReader(engine_params=engine, min_side=config["min_side"])


def squash(text: str | None) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text or "")).lower()


def store_match(gt: str, pred: str | None) -> bool:
    a, b = squash(gt), squash(pred)
    if not a or not b:
        return False
    if (len(b) >= 2 and b in a) or a in b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.6


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def load_rows(dataset: Path, split: str, source: str, limit: int) -> list[dict]:
    with open(dataset / "manifest.csv", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if split != "all":
        rows = [r for r in rows if r["split"] == split or (split == "labeled" and r["split"] not in ("unlabeled", "foreign"))]
    if source != "all":
        rows = [r for r in rows if r["source"] == source]
    return rows[:limit] if limit else rows


def run_ocr(dataset: Path, preset: str, rows: list[dict]) -> dict[str, dict]:
    cache_path = dataset / "cache" / f"{preset}.jsonl"
    cache_path.parent.mkdir(exist_ok=True)
    cache: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            cache[item["id"]] = item
    todo = [r for r in rows if r["id"] not in cache]
    if todo:
        reader = make_reader(preset)
        if not reader.ready:
            sys.exit(reader.error)
        started = time.perf_counter()
        with open(cache_path, "a", encoding="utf-8") as handle:
            for index, row in enumerate(todo, 1):
                lines, meta = reader.read(Image.open(dataset / row["file"]))
                item = {"id": row["id"], "lines": [l.text for l in lines], "scores": [round(l.score, 3) for l in lines], **meta}
                cache[row["id"]] = item
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                if index % 25 == 0 or index == len(todo):
                    rate = (time.perf_counter() - started) / index
                    print(f"  [{preset}] {index}/{len(todo)} OCR  {rate:.2f}s/img", file=sys.stderr, flush=True)
    return cache


def load_item_labels(raw_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """KORIE item labels (Dataset/receipt/external_raw/korie_items/items_*.csv): (name, line total) per receipt."""
    labels: dict[str, list[tuple[str, int]]] = {}
    for path in sorted(raw_dir.glob("items_*.csv")):
        with open(path, encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                try:
                    amount = int(float(row["Total Price"]))
                except ValueError:
                    continue
                name = receipt.LEADING_CODE.sub("", row["Item_Name"].split(",")[0]).strip(" •*")
                labels.setdefault(f"korie/{row['image_name']}", []).append((name, amount))
    return labels


ITEM_GT: dict[str, list[tuple[str, int]]] = {}


def score(rows: list[dict], cache: dict[str, dict], show_errors: int) -> dict:
    stats: dict[str, dict[str, list[int]]] = {}
    errors: list[str] = []
    for row in rows:
        result = cache[row["id"]]
        fields = receipt.parse_receipt(result["lines"])
        group = row["source"] if row["split"] == "unlabeled" else f"{row['source']}-{row['split']}"
        s = stats.setdefault(group, {})
        add = lambda key, ok: s.setdefault(key, []).append(int(bool(ok)))
        s.setdefault("seconds", []).append(result.get("seconds", 0))
        if row["split"] in ("unlabeled", "foreign"):
            add("found_total", fields.total_amount)
            add("found_date", fields.purchased_date)
            add("found_time", fields.purchased_time)
            add("found_store", fields.store_name)
            add("id_ready", fields.fingerprint())
            continue
        checks = {}
        if row["gt_total"]:
            checks["total"] = fields.total_amount == int(row["gt_total"])
        if row["gt_date"]:
            checks["date"] = fields.purchased_date == row["gt_date"]
        if row["gt_time"]:
            checks["time"] = fields.purchased_time == row["gt_time"]
            # KORIE often labels the card-approval time printed a minute or two after the sale time
            checks["time5"] = fields.purchased_time is not None and abs(_minutes(fields.purchased_time) - _minutes(row["gt_time"])) <= 5
        if row["gt_store"]:
            checks["store"] = store_match(row["gt_store"], fields.store_name)
        if row["gt_total"] and row["gt_date"]:
            checks["id_ready"] = checks["total"] and checks["date"]
        for key, ok in checks.items():
            add(key, ok)
        if row["id"] in ITEM_GT:  # purchase log: item amounts (recall / precision) and names of the matched items
            left = list(ITEM_GT[row["id"]])
            for item in fields.items:
                same = [g for g in left if g[1] == item["amount"]]
                add("item_prec", same)
                if same:
                    best = max(same, key=lambda g: SequenceMatcher(None, squash(g[0]), squash(item["name"])).ratio())
                    left.remove(best)
                    add("item_name", SequenceMatcher(None, squash(best[0]), squash(item["name"])).ratio() >= 0.6)
            for _ in range(len(ITEM_GT[row["id"]]) - len(left)):
                add("item_recall", True)
            for _ in left:
                add("item_recall", False)
        if len(errors) < show_errors and not all(checks.values()):
            wrong = {k: (row.get(f"gt_{k}"), getattr(fields, {"total": "total_amount", "date": "purchased_date",
                                                              "time": "purchased_time", "store": "store_name"}[k]))
                     for k, ok in checks.items() if not ok and k not in ("id_ready", "time5")}
            errors.append(f"{row['id']}: {wrong}")
    summary = {}
    for group, values in sorted(stats.items()):
        n = len(values["seconds"])
        summary[group] = {"n": n, **{k: round(100 * sum(v) / len(v), 1) for k, v in values.items() if k != "seconds"},
                          "sec/img": round(sum(values["seconds"]) / n, 2)}
    return {"summary": summary, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=ROOT / "Dataset" / "receipt" / "ocrReceipt1000")
    parser.add_argument("--preset", default="current", choices=list(PRESETS))
    parser.add_argument("--split", default="all", help="train | val | test | unlabeled | labeled | all")
    parser.add_argument("--source", default="all", help="own | korie | humynlabs | all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--parse-only", action="store_true", help="score cached OCR output only (no OCR run)")
    parser.add_argument("--errors", type=int, default=0, help="print this many failed receipts")
    parser.add_argument("--json", type=Path, help="also write the summary to this file")
    args = parser.parse_args()

    rows = load_rows(args.dataset, args.split, args.source, args.limit)
    ITEM_GT.update(load_item_labels(args.dataset.parent / "external_raw" / "korie_items"))
    if args.parse_only:
        cache_path = args.dataset / "cache" / f"{args.preset}.jsonl"
        cache = {json.loads(l)["id"]: json.loads(l) for l in cache_path.read_text(encoding="utf-8").splitlines()}
        rows = [r for r in rows if r["id"] in cache]
    else:
        cache = run_ocr(args.dataset, args.preset, rows)
    result = score(rows, cache, args.errors)
    print(f"preset={args.preset} split={args.split} source={args.source} images={len(rows)}")
    for group, values in result["summary"].items():
        print(f"  {group:18s} " + "  ".join(f"{k}={v}" for k, v in values.items()))
    for line in result["errors"]:
        print("  x", line)
    if args.json:
        args.json.write_text(json.dumps({"preset": args.preset, "split": args.split, **result}, ensure_ascii=False, indent=2),
                             encoding="utf-8")


if __name__ == "__main__":
    main()

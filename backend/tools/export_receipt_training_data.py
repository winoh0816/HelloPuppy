"""Export receipt photos that users agreed to share (dataset_consent=1) as an OCR training / evaluation set.

    python -m backend.tools.export_receipt_training_data                 # -> Dataset/receipt/user_uploads/
    python -m backend.tools.export_receipt_training_data --corrected-only # only receipts whose items a user fixed

Output (git-ignored, it holds user photos):
    images/<receipt_id>.<ext>   the stored copy (EXIF/GPS already removed when it was uploaded)
    labels.jsonl                OCR lines and boxes, parsed store/date/total and items; items_corrected=true means a
                                person checked the item names and amounts, otherwise everything is the OCR's own guess
    manifest.csv                one row per receipt, same columns as Dataset/receipt/ocrReceipt1000/manifest.csv where
                                they apply, so evaluate_receipt_ocr.py can run on it (split=unlabeled: it reports how often each field is found)

Only receipts whose consent is still on are exported, and the output folder is rebuilt from scratch on every run, so a
withdrawn photo drops out of the training set the next time it is exported.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

from backend import purchases, storage
from backend.database import db_connection

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "Dataset" / "receipt" / "user_uploads")
    parser.add_argument("--corrected-only", action="store_true")
    args = parser.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)  # a fresh export: withdrawn photos must not survive from an earlier run
    (args.out / "images").mkdir(parents=True)
    with db_connection() as db:
        rows = db.execute("""SELECT r.*, i.storage_path, i.mime_type FROM receipts r JOIN images i ON i.id=r.image_id
            WHERE r.dataset_consent=1 AND i.storage_path<>'' ORDER BY r.id""").fetchall()
        items = purchases.items_of(db, [row["id"] for row in rows])

    exported = 0
    with open(args.out / "labels.jsonl", "w", encoding="utf-8") as labels, \
            open(args.out / "manifest.csv", "w", newline="", encoding="utf-8-sig") as manifest_file:
        manifest = csv.writer(manifest_file)
        manifest.writerow(["id", "file", "source", "split", "gt_total", "gt_date", "gt_time", "gt_store", "items_corrected", "consented_at"])
        for row in rows:
            if args.corrected_only and not row["items_corrected"]:
                continue
            record = purchases.training_record(row, items.get(row["id"], []))
            ext = {"image/png": "png", "image/webp": "webp"}.get(row["mime_type"], "jpg")
            relative = f"images/{row['id']}.{ext}"
            try:
                (args.out / relative).write_bytes(storage.read_image(row["storage_path"]))
            except FileNotFoundError:
                continue
            record["file"] = relative
            labels.write(json.dumps(record, ensure_ascii=False) + "\n")
            # OCR's own fields are pseudo labels: kept for reference, not as ground truth (no gt_* unless a person checked)
            manifest.writerow([f"user/{row['id']}", relative, "user", "unlabeled", "", "", "", "", int(row["items_corrected"]),
                               row["dataset_consent_at"] or ""])
            exported += 1
    print(f"{exported} consented receipts -> {args.out}")


if __name__ == "__main__":
    main()

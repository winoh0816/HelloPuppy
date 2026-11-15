"""Build the 1,000-image Korean receipt OCR dataset (Dataset/receipt/ocrReceipt1000).

Sources
- own        : Dataset/receipt/team_photos (collected by the team; byte-identical duplicates removed). No labels.
- korie      : KORIE benchmark (Korean retail receipts, https://github.com/MahmoudSalah/KORIE). Full-receipt images from the
               "Key Information Detection" zips + per-field transcriptions from the "OCR Dataset" zips
               (files like IMG00640_Total.txt). Receipts that have transcriptions are taken first.
- humynlabs  : HumynLabs/Korean_Receipts_Dataset on Hugging Face (CC BY 4.0). No labels.

Every image is re-encoded as JPEG (longest side <= 2000 px, the size receipt.ReceiptReader works at) with EXIF
orientation applied and all metadata dropped (the HumynLabs photos carry GPS tags).

Download the sources first (see backend/README.md) and run:
    python -m backend.tools.build_receipt_dataset --target 1000
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
MAX_SIDE = 2000
LABEL_FIELDS = ["Total", "TransactionDate", "PaymentDate", "TransactionTime", "MerchantName", "Subtotal", "TotalTax",
                "ReceiptNumber", "MerchantPhoneNumber"]


def save_jpeg(data: bytes, out: Path) -> tuple[int, int]:
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "JPEG", quality=92, optimize=True)  # no exif= argument -> metadata is dropped
    return image.size


def norm_amount(text: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits and len(digits) <= 9 else None


def norm_date(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"(20\d{2}|\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    if not match:
        return None
    year = int(match.group(1)) + (2000 if len(match.group(1)) == 2 else 0)
    try:
        return date(year, int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def norm_time(text: str | None) -> str | None:
    match = re.search(r"(\d{1,2})\s*:\s*(\d{2})", text or "")
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return None
    hour = int(match.group(1))
    if re.search(r"오후|PM", text or "", re.I) and hour < 12:
        hour += 12
    return f"{hour:02d}:{match.group(2)}"


def korie_labels(raw_dir: Path) -> dict[str, dict[str, list[str]]]:
    labels: dict[str, dict[str, list[str]]] = {}
    for zip_path in sorted((raw_dir / "korie_ocr").glob("*.zip")):
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                if not name.endswith(".txt"):
                    continue
                image_id, field = Path(name).stem.split("_", 1)
                labels.setdefault(image_id, {}).setdefault(field, []).append(archive.read(name).decode("utf-8").strip())
    return labels


def korie_row(image_id: str, split: str, fields: dict[str, list[str]]) -> dict[str, object]:
    first = lambda key: (fields.get(key) or [None])[0]
    raw = {key: first(key) for key in LABEL_FIELDS if first(key)}
    return {
        "gt_total": norm_amount(first("Total")),
        "gt_date": norm_date(first("TransactionDate")) or norm_date(first("PaymentDate")),
        "gt_time": norm_time(first("TransactionTime")) or norm_time(first("PaymentDate")),
        "gt_store": first("MerchantName"),
        "raw_labels": json.dumps(raw, ensure_ascii=False) if raw else "",
        "split": split,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--own", type=Path, default=ROOT / "Dataset" / "receipt" / "team_photos")
    parser.add_argument("--raw", type=Path, default=ROOT / "Dataset" / "receipt" / "external_raw")
    parser.add_argument("--out", type=Path, default=ROOT / "Dataset" / "receipt" / "ocrReceipt1000")
    parser.add_argument("--target", type=int, default=1000)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    seen: set[str] = set()

    def add(source: str, name: str, data: bytes, original: str, license_: str, **extra: object) -> bool:
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            return False
        seen.add(digest)
        rel = Path("images") / source / f"{name}.jpg"
        width, height = save_jpeg(data, args.out / rel)
        rows.append({"id": f"{source}/{name}", "file": rel.as_posix(), "source": source, "original": original,
                     "license": license_, "width": width, "height": height, "sha256": digest[:16],
                     **{"split": "unlabeled", "gt_total": None, "gt_date": None, "gt_time": None, "gt_store": None,
                        "raw_labels": ""}, **extra})
        return True

    natural = lambda p: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.name)]
    for path in sorted(args.own.glob("*.jpg"), key=natural):
        add("own", path.stem, path.read_bytes(), f"Dataset/receipt/team_photos/{path.name}", "team-collected")
    for path in sorted((args.raw / "humynlabs").glob("*.jpeg"), key=natural):
        add("humynlabs", path.stem, path.read_bytes(), f"HumynLabs/Korean_Receipts_Dataset:{path.name}", "CC-BY-4.0")

    labels = korie_labels(args.raw)
    korie: list[tuple[bool, str, str, Path, str]] = []
    for split in ("train", "val", "test"):
        zip_path = args.raw / f"korie_{split}" / f"{split}.zip"
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                if "/images/" in name and not name.endswith("/"):
                    image_id = Path(name).stem
                    korie.append((image_id not in labels, image_id, split, zip_path, name))
    korie.sort()  # labelled receipts first, then by id
    need = args.target - len(rows)
    archives: dict[Path, zipfile.ZipFile] = {}
    for unlabeled, image_id, split, zip_path, name in korie:
        if need <= 0:
            break
        archive = archives.setdefault(zip_path, zipfile.ZipFile(zip_path))
        extra = korie_row(image_id, split, labels.get(image_id, {}))
        if unlabeled:
            extra["split"] = "unlabeled"
        if add("korie", image_id, archive.read(name), f"KORIE {split}/{Path(name).name}", "KORIE (research benchmark)", **extra):
            need -= 1
    for archive in archives.values():
        archive.close()

    # Hand labels for a random sample of the team photos (total/date read off the image; unreadable ones left out).
    # foreign = receipt that is not Korean (JP/TW/TH/ES ...): kept in the set, excluded from Korean accuracy numbers.
    manual_path = args.out / "manual_labels.csv"
    if manual_path.exists():
        with open(manual_path, encoding="utf-8") as handle:
            manual = {row["id"]: row for row in csv.DictReader(handle)}
        for row in rows:
            if label := manual.get(str(row["id"])):
                row["split"] = "foreign" if label["foreign"] else "manual"
                row["gt_total"] = label["gt_total"] or None
                row["gt_date"] = label["gt_date"] or None

    columns = ["id", "file", "source", "split", "gt_total", "gt_date", "gt_time", "gt_store", "width", "height", "license",
               "original", "sha256", "raw_labels"]
    with open(args.out / "manifest.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['source']}:{row['split']}"
        counts[key] = counts.get(key, 0) + 1
    print(f"{len(rows)} images -> {args.out}", counts)


if __name__ == "__main__":
    main()

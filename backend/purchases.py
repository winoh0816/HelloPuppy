"""Pet-supply purchase log built from receipt OCR (tables receipts + receipt_items).

A receipt goes into the log when it is a pet purchase (pet keywords on the receipt, or the user marked items as pet
supplies), has an amount, and is not a second copy of a receipt already in this user's log. Whether it earned reward
points is a separate question (date window, daily limit): an old receipt is still a real purchase.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date
from typing import Any

from . import receipt
from .database import Connection

CATEGORY_NAMES = receipt.CATEGORY_NAMES
NOT_PET = receipt.NOT_PET
UNKNOWN_ITEMS = "품목 미확인"


def log_state(pet_ok: bool, pet_amount: int | None, duplicate: bool) -> tuple[int, str]:
    """(in_log, log_reason)."""
    if duplicate:
        return 0, "duplicate"
    if not pet_ok:
        return 0, "not_pet"
    if not pet_amount:
        return 0, "no_amount"
    return 1, ""


def is_logged_duplicate(db: Connection, user_id: int, fingerprint: str | None, exclude_id: int | None = None) -> bool:
    if not fingerprint:
        return False
    row = db.execute("SELECT 1 FROM receipts WHERE user_id=%s AND fingerprint=%s AND in_log=1 AND id<>%s",
                     (user_id, fingerprint, exclude_id or 0)).fetchone()
    return row is not None


def save_items(db: Connection, receipt_id: int, user_id: int, items: list[dict[str, Any]]) -> None:
    db.execute("DELETE FROM receipt_items WHERE receipt_id=%s", (receipt_id,))
    db.cursor().executemany(
        "INSERT INTO receipt_items(receipt_id,user_id,position,name,quantity,unit_price,amount,category) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        [(receipt_id, user_id, index, item["name"], item.get("quantity"), item.get("unit_price"), int(item["amount"]),
          item.get("category") or "기타 용품") for index, item in enumerate(items)])


def items_of(db: Connection, receipt_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not receipt_ids:
        return {}
    rows = db.execute("""SELECT receipt_id,name,quantity,unit_price,amount,category FROM receipt_items
        WHERE receipt_id = ANY(%s) ORDER BY receipt_id, position""", (list(receipt_ids),)).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["receipt_id"]].append({key: row[key] for key in ("name", "quantity", "unit_price", "amount", "category")})
    return grouped


def _month(row: dict[str, Any]) -> str:
    return (row["purchased_date"] or row["created_at"][:10])[:7]


def _name_key(name: str) -> str:
    """Group the same product written slightly differently ('로얄캐닌 미니 3kg' / '로얄캐닌미니3kg')."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", name)).lower()


def summary(db: Connection, user_id: int, months: int = 6, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    receipts = db.execute("""SELECT id,store_name,purchased_date,created_at,pet_amount FROM receipts
        WHERE user_id=%s AND in_log=1 ORDER BY COALESCE(purchased_date, substr(created_at,1,10))""", (user_id,)).fetchall()
    items = items_of(db, [row["id"] for row in receipts])

    total = sum(int(row["pet_amount"] or 0) for row in receipts)
    by_month: dict[str, int] = defaultdict(int)
    categories: dict[str, dict[str, int]] = defaultdict(lambda: {"amount": 0, "count": 0})
    products: dict[str, dict[str, Any]] = {}
    item_count = 0
    for row in receipts:
        by_month[_month(row)] += int(row["pet_amount"] or 0)
        pet_items = [item for item in items.get(row["id"], []) if item["category"] != NOT_PET]
        if not pet_items:
            categories[UNKNOWN_ITEMS]["amount"] += int(row["pet_amount"] or 0)
            categories[UNKNOWN_ITEMS]["count"] += 1
            continue
        for item in pet_items:
            item_count += 1
            quantity = int(item["quantity"] or 1)
            categories[item["category"]]["amount"] += int(item["amount"])
            categories[item["category"]]["count"] += quantity
            entry = products.setdefault(_name_key(item["name"]), {"name": item["name"], "category": item["category"],
                                                                   "count": 0, "purchases": 0, "amount": 0})
            entry["count"] += quantity
            entry["purchases"] += 1
            entry["amount"] += int(item["amount"])
            entry["last_date"] = row["purchased_date"] or row["created_at"][:10]

    month_keys = []
    year, month = today.year, today.month
    for _ in range(months):
        month_keys.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    month_keys.reverse()
    category_total = sum(value["amount"] for value in categories.values()) or 1
    active_months = len([key for key, value in by_month.items() if value]) or 1
    dates = [row["purchased_date"] or row["created_at"][:10] for row in receipts]
    return {
        "receipt_count": len(receipts),
        "item_count": item_count,
        "total_spent": total,
        "average_per_receipt": round(total / len(receipts)) if receipts else 0,
        "average_per_month": round(total / active_months) if receipts else 0,
        "this_month_spent": by_month.get(month_keys[-1], 0),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "monthly": [{"month": key, "amount": by_month.get(key, 0)} for key in month_keys],
        "categories": sorted(({"category": name, **value, "share": round(value["amount"] / category_total, 3)}
                              for name, value in categories.items()), key=lambda c: -c["amount"]),
        "top_items": sorted(products.values(), key=lambda p: (-p["purchases"], -p["count"], -p["amount"]))[:8],
    }


def backfill(db: Connection) -> int:
    """Receipts saved before the purchase log existed: rebuild items from the OCR text kept in raw_text."""
    rows = db.execute("SELECT id,user_id,raw_text,fingerprint FROM receipts WHERE log_reason IS NULL ORDER BY id").fetchall()
    for row in rows:
        fields = receipt.parse_receipt(row["raw_text"].split("\n"))
        save_items(db, row["id"], row["user_id"], fields.items)
        duplicate = is_logged_duplicate(db, row["user_id"], row["fingerprint"], row["id"])
        in_log, reason = log_state(bool(fields.pet_keywords) or fields.pet_store, fields.pet_amount, duplicate)
        db.execute("UPDATE receipts SET pet_store=%s, pet_amount=%s, in_log=%s, log_reason=%s WHERE id=%s",
                   (int(fields.pet_store), fields.pet_amount, in_log, reason, row["id"]))
    return len(rows)


def training_record(row: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """One consented receipt as an OCR training sample: OCR output is a pseudo label, user-corrected items are checked."""
    details = json.loads(row["details_json"] or "{}")
    return {
        "receipt_id": row["id"], "storage_path": row["storage_path"], "mime_type": row["mime_type"],
        "consented_at": row["dataset_consent_at"], "uploaded_at": row["created_at"],
        "store_name": row["store_name"], "purchased_date": row["purchased_date"], "purchased_time": row["purchased_time"],
        "total_amount": row["total_amount"], "items": items, "items_corrected": bool(row["items_corrected"]),
        "ocr_lines": [line.get("text") for line in details.get("lines", [])],
        "ocr_boxes": [line.get("box") for line in details.get("lines", [])],
    }

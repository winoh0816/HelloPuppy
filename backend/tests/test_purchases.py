from __future__ import annotations

import csv
import io
import json
import random
import sys
from datetime import date

from fastapi.testclient import TestClient
from PIL import Image

import backend.app as api_module
from backend import receipt
from backend.app import app
from backend.receipt import OcrLine, parse_receipt
from backend.tools import export_receipt_training_data


def test_items_are_read_with_name_quantity_and_amount():
    # 실제 KORIE 영수증의 OCR 결과 그대로: 이름 다음 줄에 바코드·가격, 끝의 면세(#)·할인(*) 표시, 쉼표 뒤 공백
    fields = parse_receipt([
        "주)한국마트", "판매일:23-11-17 20:45, 금요일 계산대:004", "NO.상품명 단가 수량 금액",
        "001큐원)하얀설탕 5kg", "8801013113136 7,990 1 7,990K",
        "002 참고을)콤식용유1.8", "8809056511988 5, 990 1 5,990*",
        "004 신)재사용봉투20L", "22002662 600 1 600#",
        "(*) 할인금액: -2, 350", "합 계: 15,570",
    ])
    assert [(i["name"], i["amount"], i["quantity"]) for i in fields.items] == [
        ("큐원)하얀설탕 5kg", 7990, 1), ("참고을)콤식용유1.8", 5990, 1), ("신)재사용봉투20L", 600, 1)]
    # 마트 영수증의 일반 식품은 반려용품이 아니다
    assert not fields.pet_store and {i["category"] for i in fields.items} == {receipt.NOT_PET} and fields.pet_amount is None


def test_pet_shop_items_are_categorised_and_paid_total_is_logged():
    fields = parse_receipt([
        "[상호] 해피독 애견용품", "판매일 24.11.03 14:05", "상품명 수량 금액",
        "로얄캐닌 미니 어덜트 3kg 1 42,000", "덴탈껌 30P 2 25,000", "배변패드 100매 1 15,900",
        "할인금액 -5,000", "합계 77,900",
    ])
    assert fields.pet_store
    assert [(i["name"], i["category"]) for i in fields.items] == [
        ("로얄캐닌 미니 어덜트 3kg", "사료"), ("덴탈껌 30P", "간식"), ("배변패드 100매", "배변/위생")]
    assert fields.items[1]["quantity"] == 2 and fields.items[1]["unit_price"] == 12500
    assert fields.pet_amount == 77900  # 할인 후 실제 낸 돈
    # 마트에서 산 강아지 간식은 그 줄만 반려용품
    mart = parse_receipt(["GS25 역삼점", "2026-11-01 08:10", "자일리톨껌 1 1,500", "강아지 육포 1 3,000", "합계 4,500"])
    assert [(i["name"], i["category"]) for i in mart.items] == [("자일리톨껌", receipt.NOT_PET), ("강아지 육포", "간식")]
    assert mart.pet_amount == 3000


class _FakeReader:
    ready = True
    error = None
    lines: list[str] = []

    def status(self):
        return {"ocr_engine": "fake", "ocr_loaded": True, "ocr_message": None}

    def read(self, image):
        return [OcrLine(text, 0.95, (0, 30 * i, 300, 30 * i + 20)) for i, text in enumerate(self.lines)], {"rotation": 0, "seconds": 0.0}


def _photo(seed: int) -> bytes:
    rng = random.Random(seed)
    image = Image.new("RGB", (80, 120))
    image.putdata([(rng.randrange(256),) * 3 for _ in range(80 * 120)])
    buffer = io.BytesIO()
    image.resize((400, 600), Image.Resampling.NEAREST).save(buffer, format="JPEG")
    return buffer.getvalue()


def _pet_receipt(day: date, approval: str, food_price: str = "42,000", total: str = "67,000") -> list[str]:
    return ["멍멍펫샵", "사업자번호 123-45-67890", f"거래일시 {day.isoformat()} 10:15", "상품명 수량 금액",
            f"로얄캐닌 미니 어덜트 3kg 1 {food_price}", "덴탈껌 30P 2 25,000", f"합계 금액 {total}원", f"승인번호 {approval}"]


def test_purchase_log_summary_editing_consent_and_export(tmp_path, monkeypatch):
    db_path = tmp_path / "purchases.sqlite3"
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(db_path))
    reader = _FakeReader()
    monkeypatch.setattr(api_module.receipt, "reader", reader)
    today = date.today()

    with TestClient(app) as client:
        token = client.post("/api/auth/register", json={"email": "log@example.test", "password": "correct horse battery staple",
                                                        "display_name": "기록"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        def send(lines, seed, consent=False):
            reader.lines = lines
            return client.post("/api/receipts", headers=headers, data={"dataset_consent": "true" if consent else "false"},
                               files={"photo": ("r.jpg", _photo(seed), "image/jpeg")}).json()

        first = send(_pet_receipt(today, "11112222"), 1, consent=True)
        assert first["verified"] and first["log"] == {"in_log": True, "reason": "", "pet_amount": 67000}
        assert [i["category"] for i in first["fields"]["items"]] == ["사료", "간식"]
        # 기간이 지나 리워드는 못 받아도 구매 기록에는 남는다
        old = send(_pet_receipt(date(today.year - 1, 1, 15), "33334444", "39,000", "64,000"), 2)
        assert not old["verified"] and old["log"]["in_log"]
        # 같은 영수증을 다시 올리면 기록에 두 번 들어가지 않는다
        again = send(_pet_receipt(today, "11112222"), 3)
        assert again["log"] == {"in_log": False, "reason": "duplicate", "pet_amount": 67000}
        # 반려용품이 없는 영수증은 기록하지 않는다
        food = send(["김밥천국", f"{today.isoformat()} 12:00", "참치김밥 1 4,500", "합계 4,500원"], 4)
        assert food["log"]["reason"] == "not_pet"

        summary = client.get("/api/receipts/summary", headers=headers).json()
        assert summary["receipt_count"] == 2 and summary["total_spent"] == 131000
        assert summary["this_month_spent"] == 67000 and summary["monthly"][-1]["amount"] == 67000
        assert {c["category"]: c["amount"] for c in summary["categories"]} == {"사료": 81000, "간식": 50000}
        # 두 상품 모두 두 번 샀고, 덴탈껌은 한 번에 2개씩이라 개수가 더 많다
        assert [(t["name"], t["purchases"], t["count"]) for t in summary["top_items"]] == [
            ("덴탈껌 30P", 2, 4), ("로얄캐닌 미니 어덜트 3kg", 2, 2)]

        receipts = client.get("/api/receipts", headers=headers).json()
        assert len(receipts["items"]) == 4 and "반려용품 아님" in receipts["categories"]
        logged = client.get("/api/receipts?logged_only=true", headers=headers).json()["items"]
        assert [r["id"] for r in logged] == [first["id"], old["id"]]

        # OCR 이 틀린 이름·금액을 고치면 기록과 통계가 바뀐다
        fixed = client.put(f"/api/receipts/{first['id']}/items", headers=headers, json={"items": [
            {"name": "로얄캐닌 미니 어덜트 3kg", "amount": 42000, "quantity": 1, "category": "사료"},
            {"name": "그리니즈 덴탈껌", "amount": 25000, "quantity": 2, "category": "간식"},
            {"name": "봉투", "amount": 100, "quantity": 1, "category": "반려용품 아님"}]}).json()["receipt"]
        assert fixed["items_corrected"] == 1 and fixed["in_log"] == 1 and fixed["pet_amount"] == 67000
        assert client.put(f"/api/receipts/{first['id']}/items", headers=headers,
                          json={"items": [{"name": "x", "amount": 1, "category": "없는 분류"}]}).status_code == 422
        # 김밥 영수증의 품목을 반려용품으로 고치면 기록에 들어간다 / 전부 '반려용품 아님'이면 빠진다
        moved = client.put(f"/api/receipts/{food['id']}/items", headers=headers,
                           json={"items": [{"name": "강아지 김밥 간식", "amount": 4500, "category": "간식"}]}).json()["receipt"]
        assert moved["in_log"] == 1
        removed = client.put(f"/api/receipts/{old['id']}/items", headers=headers,
                             json={"items": [{"name": "사람 간식", "amount": 39000, "category": "반려용품 아님"}]}).json()["receipt"]
        assert removed["in_log"] == 0 and removed["log_reason"] == "not_pet"
        assert client.get("/api/receipts/summary", headers=headers).json()["total_spent"] == 67000 + 4500

        # 다른 사람의 영수증은 고칠 수 없다
        other = client.post("/api/auth/register", json={"email": "other@example.test", "password": "correct horse battery staple",
                                                        "display_name": "남"}).json()["access_token"]
        assert client.put(f"/api/receipts/{first['id']}/dataset-consent", headers={"Authorization": f"Bearer {other}"},
                          json={"consent": True}).status_code == 404

        # 학습 데이터 동의: 동의한 것만 내보내고, 철회하면 다음 내보내기에서 빠진다
        assert client.put(f"/api/receipts/{old['id']}/dataset-consent", headers=headers, json={"consent": True}).status_code == 200

        out = tmp_path / "export"
        monkeypatch.setattr(sys, "argv", ["export", "--out", str(out)])
        export_receipt_training_data.main()
        labels = [json.loads(line) for line in (out / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
        assert sorted(r["receipt_id"] for r in labels) == sorted([first["id"], old["id"]])
        sample = next(r for r in labels if r["receipt_id"] == first["id"])
        assert sample["items_corrected"] and sample["items"][1]["name"] == "그리니즈 덴탈껌" and sample["ocr_lines"][0] == "멍멍펫샵"
        assert (out / sample["file"]).is_file()
        assert len(list(csv.DictReader(open(out / "manifest.csv", encoding="utf-8-sig")))) == 2

        client.put(f"/api/receipts/{first['id']}/dataset-consent", headers=headers, json={"consent": False})
        export_receipt_training_data.main()
        labels = [json.loads(line) for line in (out / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [r["receipt_id"] for r in labels] == [old["id"]] and len(list((out / "images").iterdir())) == 1

        missions = client.get("/api/missions/today", headers=headers).json()
        by_key = {m["key"]: m for m in missions["missions"]}
        assert by_key["receipt"]["rewarded_today"] == 1 and by_key["receipt"]["done"]
        assert by_key["walk"] == {**by_key["walk"], "rewarded_today": 0, "done": False, "daily_limit": 2, "points": 100}
        assert missions["points_today"] == 30

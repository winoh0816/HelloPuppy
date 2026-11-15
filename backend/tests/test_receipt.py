from __future__ import annotations

import io
import random
from datetime import date, timedelta

from fastapi.testclient import TestClient
from PIL import Image

import backend.app as api_module
from backend.app import app
from backend.receipt import OcrLine, group_lines, parse_receipt


def test_parse_receipt_reads_core_fields_and_skips_discount_and_tax_lines():
    fields = parse_receipt([
        "[상호] 해피독 애견용품", "사업자번호 214-86-12345", "TEL 02-555-1234", "판매일 24.11.03 14:05",
        "로얄캐닌 미니 어덜트 3kg   1   42,000", "덴탈껌 30P   2   25,000", "할인금액 -5,000",
        "부가세 5,636", "합계", "62,000", "신용카드 62,000", "승인번호: 30012345",
    ])
    assert fields.store_name == "해피독 애견용품"
    assert fields.business_number == "214-86-12345"
    assert (fields.purchased_date, fields.purchased_time) == ("2024-11-03", "14:05")
    assert fields.total_amount == 62000
    assert fields.approval_number == "30012345"
    assert "로얄캐닌" in fields.pet_keywords and len(fields.items) == 2
    assert fields.fingerprint() == parse_receipt(["해피독 애견용품", "사업자번호 214-86-12345", "2024.11.03 14:05",
                                                   "합계 62,000", "승인번호 30012345"]).fingerprint()


def test_parse_receipt_without_pet_words_or_total():
    fields = parse_receipt(["김밥천국 역삼점", "2026-11-01 12:30", "참치김밥 4,500", "라면 5,000"])
    assert fields.pet_keywords == [] and fields.total_amount is None and fields.fingerprint() is None
    # 편의점의 껌·캔커피·과자 간식은 반려동물 구매가 아니다.
    store = parse_receipt(["GS25 역삼점", "2026-11-01 08:10", "자일리톨껌 1,500", "캔커피 1,200", "츄파춥스 300", "간식 세트 3,000", "합계 6,000"])
    assert store.pet_keywords == [] and store.total_amount == 6000


def test_parse_receipt_handles_ocr_quirks_seen_in_real_receipts():
    # 실제 영수증(KORIE) 평가에서 나온 OCR 결과 그대로
    glued = parse_receipt(["천사(1004)마트", "판매일:23-10-2421:49,화요일계산대:001", "과세물품: 3,273", "합계: 3,600"])
    assert (glued.purchased_date, glued.purchased_time, glued.total_amount) == ("2023-10-24", "21:49", 3600)
    long_glued = parse_receipt(["[P0S 1068431] 2023.11.0220:53:00"])
    assert (long_glued.purchased_date, long_glued.purchased_time) == ("2023-11-02", "20:53")
    # 쉼표 뒤 공백, '과세'를 '관세'로 잘못 읽은 줄
    spaced = parse_receipt(["2023-11-02 10:21", "관세물품간액 10,181", "결제금액 11, 200"])
    assert spaced.total_amount == 11200
    # 'B,600'(8,600 오인식)의 600 이나 승인번호 숫자를 합계로 잡지 않는다
    assert parse_receipt(["신용카드지불: 8,600", "승인금액: B,600 [일시불]"]).total_amount == 8600
    assert parse_receipt(["판매합계 B,00000", "증인번호09800246(0) 승인금액8,000"]).total_amount == 8000
    # 금액 없는 합계 줄 다음의 공급가액 줄 금액을 집지 않는다
    assert parse_receipt(["주문총액: 84,00", "공급가액: 76, 364", "합계 84,000원"]).total_amount == 84000
    assert parse_receipt(["내신금액: 7,800"]).total_amount is None and parse_receipt(["내실금액: 7,800"]).total_amount == 7800
    assert parse_receipt(["2022-10-14 오후 1:28:24"]).purchased_time == "13:28"
    assert parse_receipt(["합계 W157,600"]).total_amount == 157600  # ₩ 를 W 로 읽은 경우


def test_store_name_skips_slogans_and_card_slip_numbers():
    daiso = parse_receipt(['"국민가게, 다이소"', "(주)아성다이소_청주산남2호점", "전화:043-283-6016", "합계 5,000"])
    assert daiso.store_name == "(주)아성다이소_청주산남2호점"
    assert parse_receipt(["[고객용]", "N0: 151700635", "오지 식당", "합계 9,000"]).store_name == "오지 식당"
    # '가맹점번호' 는 가맹점명이 아니다
    assert parse_receipt(["멍멍마트", "가맹점번호: 0107717308", "합계 9,000"]).store_name == "멍멍마트"


def test_group_lines_joins_name_and_price_on_the_same_row():
    lines = group_lines([OcrLine("42,000", 0.9, (300, 102, 360, 122)), OcrLine("사료 3kg", 0.9, (10, 100, 120, 124)),
                         OcrLine("합계 42,000", 0.9, (10, 140, 200, 164))])
    assert [line.text for line in lines] == ["사료 3kg 42,000", "합계 42,000"]


class _FakeReader:
    """Returns whatever lines the test sets, instead of running the OCR models."""
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


def _receipt(day: date, total: str, approval: str, store: str = "멍멍펫샵") -> list[str]:
    return [store, "사업자번호 123-45-67890", f"거래일시 {day.isoformat()} 10:15", "강아지 간식 1 " + total, f"합계 금액 {total}원",
            f"승인번호 {approval}"]


def test_receipt_endpoint_rewards_once_and_blocks_reuse(tmp_path, monkeypatch):
    monkeypatch.setenv("HELLOPUPPY_DB_PATH", str(tmp_path / "receipt.sqlite3"))
    reader = _FakeReader()
    monkeypatch.setattr(api_module.receipt, "reader", reader)
    today = date.today()

    with TestClient(app) as client:
        def account(email):
            token = client.post("/api/auth/register", json={"email": email, "password": "correct horse battery staple",
                                                            "display_name": "영수증"}).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}

        def send(headers, lines, seed):
            reader.lines = lines
            return client.post("/api/receipts", headers=headers, files={"photo": ("r.jpg", _photo(seed), "image/jpeg")}).json()

        first_user, second_user = account("first@example.test"), account("second@example.test")
        first = send(first_user, _receipt(today, "15,800", "11112222"), 1)
        assert first["verified"] is True and first["points_awarded"] == 30 and first["balance"] == 30
        assert first["fields"]["total_amount"] == 15800 and first["fields"]["store_name"] == "멍멍펫샵"

        # 같은 영수증을 다른 계정이 다른 사진으로 올려도 거절
        reused = send(second_user, _receipt(today, "15,800", "11112222"), 2)
        assert reused["verified"] is False and reused["points_awarded"] == 0
        assert next(c for c in reused["checks"] if c["key"] == "duplicate")["passed"] is False

        # 하루 1회: 두 번째 영수증은 확인되지만 포인트는 0
        second = send(first_user, _receipt(today, "9,900", "33334444"), 3)
        assert second["verified"] is True and second["points_awarded"] == 0 and second["balance"] == 30

        not_pet = send(second_user, ["김밥천국", f"{today.isoformat()} 12:00", "합계 9,000원"], 4)
        assert not_pet["verified"] is False
        assert next(c for c in not_pet["checks"] if c["key"] == "pet")["passed"] is False

        old = send(second_user, _receipt(today - timedelta(days=30), "20,000", "55556666"), 5)
        assert old["verified"] is False and next(c for c in old["checks"] if c["key"] == "date")["passed"] is False

        history = client.get("/api/receipts", headers=first_user).json()["items"]
        assert [item["status"] for item in history] == ["verified", "verified"]

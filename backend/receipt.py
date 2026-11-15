"""Receipt OCR and field extraction for the receipt reward.

OCR 엔진: RapidOCR (Apache-2.0) + PaddleOCR PP-OCRv5 한국어 인식 모델을 ONNX Runtime 으로 CPU 에서 실행한다.
- 글줄 방향 분류기(cls)는 끈다. 똑바로 찍힌 영수증 줄을 180도로 뒤집어 읽는 경우가 많아 정확도가 크게 떨어졌다
  (합성 영수증 평가: 줄 단위 일치 83% -> 99%). 사진 자체의 회전은 EXIF 와 아래 회전 재시도로 처리한다.
- 모델 파일(약 20MB)은 처음 실행할 때 backend/models/ocr/ 에 내려받는다.

인식된 글자 조각을 같은 줄끼리 묶은 뒤 매장명·사업자번호·거래일시·합계 금액·승인번호·반려동물 관련 품목을 뽑는다.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image

OCR_MODEL_DIR = Path(os.getenv("HELLOPUPPY_OCR_MODEL_DIR", Path(__file__).parent / "models" / "ocr"))
MAX_SIDE = 2000

# 합계 금액을 찾을 때 볼 단어. 앞에 있을수록 우선한다 (공백을 지운 뒤 비교).
TOTAL_KEYWORDS = ["총결제금액", "결제금액", "받을금액", "내실금액", "청구금액", "합계금액", "총합계", "판매합계", "총금액", "총액",
                  "주문금액", "합계", "판매금액", "총구매액", "승인금액", "카드결제", "신용카드", "현금결제", "결제", "지불", "TOTAL"]
# 합계 줄처럼 보여도 최종 결제액이 아닌 줄. '관세'는 '과세'를 잘못 읽은 것 (실제 영수증 평가에서 자주 나옴).
NOT_TOTAL_WORDS = ["부가세", "과세", "관세", "면세", "세액", "가액", "할인", "포인트", "거스름", "잔액", "공급가", "봉사료", "적립",
                   "받은금액", "현금영수증", "물품"]
# 반려동물 영수증인지 판단할 단어 (매장명·품목에서 찾는다).
# '껌', '캔', '츄', '간식'처럼 편의점·마트 영수증에도 흔한 짧은 단어는 넣지 않는다 (일반 영수증 오인증 방지).
PET_KEYWORDS = [
    "애견", "애완", "반려", "펫", "pet", "강아지", "멍멍", "댕댕", "퍼피", "puppy", "dog", "고양이", "캣", "동물병원", "동물",
    "사료", "개껌", "덴탈껌", "배변패드", "배변봉투", "고양이모래", "하네스", "목줄", "리드줄", "가슴줄", "켄넬", "이동장", "스크래쳐",
    "로얄캐닌", "로얄캐닝", "오리젠", "아카나", "내추럴코어", "ANF", "하림펫푸드", "뉴트로", "힐스", "그리니즈", "시저",
]
HEADER_WORDS = ["영수증", "사업자", "대표", "주소", "TEL", "전화", "거래일시", "일시", "POS", "포스", "상품명", "단가", "수량", "금액"]


@dataclass
class OcrLine:
    text: str
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "score": round(self.score, 4), "box": [round(v, 1) for v in self.box]}


@dataclass
class ReceiptFields:
    store_name: str | None = None
    business_number: str | None = None
    purchased_date: str | None = None  # YYYY-MM-DD
    purchased_time: str | None = None  # HH:MM
    total_amount: int | None = None
    approval_number: str | None = None
    items: list[str] = field(default_factory=list)
    pet_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str | None:
        """Same receipt -> same value, whoever uploads it. None when there is not enough to identify it."""
        if not (self.total_amount and self.purchased_date):
            return None
        shop = self.business_number or _compact(self.store_name or "")
        key = "|".join([shop, self.purchased_date, self.purchased_time or "", str(self.total_amount), self.approval_number or ""])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def group_lines(pieces: list[OcrLine]) -> list[OcrLine]:
    """Merge text boxes that sit on the same row (e.g. item name on the left, price on the right)."""
    rows: list[list[OcrLine]] = []
    for piece in sorted(pieces, key=lambda p: (p.box[1] + p.box[3]) / 2):
        centre = (piece.box[1] + piece.box[3]) / 2
        height = piece.box[3] - piece.box[1]
        if rows:
            last = rows[-1]
            top, bottom = min(p.box[1] for p in last), max(p.box[3] for p in last)
            last_centre, last_height = (top + bottom) / 2, bottom - top
            if abs(centre - last_centre) < 0.5 * min(height, last_height):
                last.append(piece)
                continue
        rows.append([piece])
    merged = []
    for row in rows:
        row.sort(key=lambda p: p.box[0])
        merged.append(OcrLine(" ".join(p.text for p in row), min(p.score for p in row),
                              (min(p.box[0] for p in row), min(p.box[1] for p in row), max(p.box[2] for p in row), max(p.box[3] for p in row))))
    return merged


# 쉼표 뒤에 공백이 끼어 읽히는 경우("11, 200")도 한 금액으로 본다. "B,600"(8,600 오인식)의 600 처럼 쉼표·글자 뒤에 붙은
# 조각은 금액으로 보지 않고(₩ 를 W 로 읽은 "W157,600"은 예외), 구분자 없는 숫자는 6자리까지만 본다 (승인번호·카드번호 같은 긴 숫자 제외).
AMOUNT = re.compile(r"(?<![\d,.A-VX-Za-z-])(\d{1,3}(?:[,.] ?\d{3})+|\d{3,6})(?:\s*원)?(?![\d-])")
# 날짜 바로 뒤에 시간이 공백 없이 붙어 읽히는 경우("23-10-2421:49", "2023.11.0220:53")도 날짜로 본다.
_DATE_END = r"(?=\d{1,2}\s*:|\D|$)"
DATE_LONG = re.compile(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})" + _DATE_END)
DATE_SHORT = re.compile(r"(?<!\d)(\d{2})\s?[-./]\s?(\d{2})\s?[-./]\s?(\d{2})" + _DATE_END)
TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*:\s*([0-5]\d)(?::[0-5]\d)?(?!\d)")
PM = re.compile(r"오후|PM", re.I)
BUSINESS = re.compile(r"(?<!\d)(\d{3})\s*-\s*(\d{2})\s*-\s*(\d{5})(?!\d)")
APPROVAL = re.compile(r"승인\s*(?:번호|No\.?)?\s*[:.]?\s*(\d{6,12})")


def _amounts(text: str) -> list[int]:
    values = []
    for match in AMOUNT.finditer(text):
        value = int(re.sub(r"[,. ]", "", match.group(1)))
        if 100 <= value <= 10_000_000:
            values.append(value)
    return values


def _find_date(text: str) -> tuple[str, int, int] | None:
    """(YYYY-MM-DD, start, end) of the first plausible date in text."""
    for pattern, century in ((DATE_LONG, ""), (DATE_SHORT, "20")):
        for match in pattern.finditer(text):
            try:
                found = date(int(century + match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
            if 2000 <= found.year <= date.today().year + 1:
                return found.isoformat(), match.start(), match.end()
    return None


def _find_time(text: str) -> str | None:
    if match := TIME.search(text):
        hour = int(match.group(1))
        if PM.search(text[:match.start()][-6:]) and hour < 12:  # "오후 1:28"
            hour += 12
        return f"{hour:02d}:{match.group(2)}"
    return None


def _find_total(texts: list[str], compact: list[str], approval: str | None) -> int | None:
    """Amount on the line with the highest-priority total keyword (largest one if several)."""
    candidates: list[tuple[int, int]] = []
    for index, text in enumerate(compact):
        if any(word in text for word in NOT_TOTAL_WORDS):
            continue
        # '합 계'의 '합'이 빠지거나 틀리게 읽힌 줄("일 계: 62,000", "계 #5,200")도 합계로 본다. 소계는 제외.
        fuzzy_total = TOTAL_KEYWORDS.index("합계") if FUZZY_TOTAL.match(text) else None
        for priority, keyword in enumerate(TOTAL_KEYWORDS):
            if keyword.lower() in text.lower() or priority == fuzzy_total:
                values = _amounts(texts[index].replace(approval or "\0", ""))
                # 금액이 다음 줄로 넘어간 경우. 다음 줄이 숫자뿐일 때만 본다 (공급가액·부가세 줄 금액을 집지 않도록).
                if not values and index + 1 < len(texts) and not re.search(r"[가-힣A-Za-z]{2}", texts[index + 1]):
                    values = _amounts(texts[index + 1])
                if values:
                    candidates.append((priority, max(values)))
                break
    return min(candidates, key=lambda c: (c[0], -c[1]))[1] if candidates else None


FUZZY_TOTAL = re.compile(r"^[^\d소]?계[:：]?[#₩W]?\d")
STORE_LABEL = re.compile(r"(?:상호명?|가맹점명|매장명|점포명)\s*[\]\)】:.]*\s*(.+)")
STORE_HINT = re.compile(r"\(주\)|㈜|주식회사|[가-힣A-Za-z0-9]점(?:$|[\s(\[])")
STORE_SKIP = ["고객용", "주문번호", "주문서", "감사합니다", "어서오세요", "환영", "여신금융", "영수증", "no:", "no.", "n0:"]


def _find_store(texts: list[str]) -> str | None:
    """'상호/가맹점명' 표기가 있으면 그 값. 없으면 위쪽 8줄 중 머리글·주소·번호 줄을 빼고 (주)·○○점 줄을 우선한다."""
    for text in texts:
        if (match := STORE_LABEL.search(text)) and len(re.findall(r"[가-힣A-Za-z]", match.group(1))) >= 2:
            return match.group(1).strip()[:60]
    best: tuple[float, str] | None = None
    for index, text in enumerate(texts[:8]):
        small = _compact(text).lower()
        hangul = len(re.findall(r"[가-힣]", text))
        if hangul < 2 or len(re.findall(r"\d", text)) > hangul or re.search(r"(시|도|구|군|로|길)\s*\d", text) \
                or any(word.lower() in small for word in HEADER_WORDS + STORE_SKIP):
            continue
        score = (2 if STORE_HINT.search(text) else 0) - (1 if re.match(r"^[\"'“‘\[]", text) else 0) - 0.25 * index
        if best is None or score > best[0]:
            best = (score, text)
    return best[1][:60] if best else None


def parse_receipt(lines: list[str]) -> ReceiptFields:
    fields = ReceiptFields()
    texts = [unicodedata.normalize("NFKC", line).strip() for line in lines if line.strip()]
    compact = [_compact(text) for text in texts]
    whole = "\n".join(texts)

    if match := BUSINESS.search(whole):
        fields.business_number = "-".join(match.groups())
    if match := APPROVAL.search(whole.replace(" ", "")):
        fields.approval_number = match.group(1)
    # 거래일시처럼 날짜·시간이 함께 있는 줄을 먼저 본다.
    dated = sorted(texts, key=lambda t: not any(word in _compact(t) for word in ("거래일시", "판매일", "일시", "거래일", "결제일")))
    for text in dated:
        if found := _find_date(text):
            fields.purchased_date = found[0]
            # 날짜 뒤에 붙은 시간을 먼저 본다 ("23-10-2421:49" 처럼 붙어 읽혀도 21:49 를 찾도록 남은 부분만 검사).
            fields.purchased_time = _find_time(text[found[2]:].lstrip()) or _find_time(text[:found[1]])
            break
    if fields.purchased_date and not fields.purchased_time:
        fields.purchased_time = _find_time(whole)

    fields.total_amount = _find_total(texts, compact, fields.approval_number)
    fields.store_name = _find_store(texts)

    lower = whole.lower()
    fields.pet_keywords = sorted({word for word in PET_KEYWORDS if word.lower() in lower}, key=PET_KEYWORDS.index)
    # 품목: 반려동물 단어가 들어 있고 머리글·합계 줄이 아닌 줄
    for text, small in zip(texts, compact):
        if any(word.lower() in small.lower() for word in PET_KEYWORDS) and _compact(fields.store_name or "\0") not in small \
                and not any(word.lower() in small.lower() for word in TOTAL_KEYWORDS + NOT_TOTAL_WORDS + HEADER_WORDS):
            fields.items.append(text[:80])
    fields.items = fields.items[:12]
    return fields


DEFAULT_ENGINE_PARAMS: dict[str, Any] = {}
# 긴 변이 이보다 짧은 사진은 키워서 읽는다. 블로그·메신저로 줄어든 사진(가로 340px 등)은 글자 높이가 8px 남짓이라
# 인식이 크게 떨어진다 (직접 라벨링한 실사진 44장: 합계 35.0% -> 47.5%, 날짜 55.6% -> 66.7%, 장당 0.9초 -> 1.9초).
MIN_TEXT_SIDE = int(os.getenv("HELLOPUPPY_OCR_MIN_SIDE", "1600"))


class ReceiptReader:
    """Lazily loads RapidOCR; thread-safe because ONNX sessions are shared across requests.

    engine_params override the RapidOCR settings below (used by tools/evaluate_receipt_ocr.py to compare settings);
    min_side upscales photos whose longest side is shorter than this before OCR.
    """

    def __init__(self, engine_params: dict[str, Any] | None = None, min_side: int | None = None) -> None:
        self._lock = threading.Lock()
        self._engine: Any = None
        self._loaded = False
        self.error: str | None = None
        self.engine_params = {**DEFAULT_ENGINE_PARAMS, **(engine_params or {})}
        self.min_side = MIN_TEXT_SIDE if min_side is None else min_side

    @property
    def ready(self) -> bool:
        self.load()
        return self._engine is not None

    def status(self) -> dict[str, Any]:
        """Cheap status for /health: does not load the models (they load on the first receipt)."""
        import importlib.util

        installed = importlib.util.find_spec("rapidocr") is not None
        return {"ocr_engine": "RapidOCR PP-OCRv5 korean" if installed else None,
                "ocr_loaded": self._engine is not None, "ocr_message": self.error if installed else "rapidocr 가 설치되지 않았습니다."}

    def load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

                OCR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
                self._engine = RapidOCR(params={
                    "Global.use_cls": False, "Global.log_level": "error", "Global.model_root_dir": str(OCR_MODEL_DIR),
                    "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
                    "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE, "Rec.lang_type": LangRec.KOREAN,
                    **self.engine_params,
                })
            except Exception as error:  # package missing or model download failed
                self.error = f"OCR 엔진을 불러오지 못했습니다. requirements-detection.txt 설치와 인터넷 연결(첫 실행 시 모델 다운로드)을 확인하세요. ({error})"
            self._loaded = True

    def _run(self, image: Image.Image) -> list[OcrLine]:
        import numpy as np

        result = self._engine(np.asarray(image)[:, :, ::-1].copy())  # RapidOCR expects BGR like OpenCV
        if result.boxes is None or result.txts is None:
            return []
        pieces = []
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            pieces.append(OcrLine(str(text), float(score), (min(xs), min(ys), max(xs), max(ys))))
        return group_lines(pieces)

    def read(self, image: Image.Image) -> tuple[list[OcrLine], dict[str, Any]]:
        if not self.ready:
            raise RuntimeError(self.error or "OCR 엔진이 준비되지 않았습니다.")
        started = time.perf_counter()
        image = image.convert("RGB")
        if max(image.size) > MAX_SIDE:
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        elif self.min_side and max(image.size) < self.min_side:
            scale = self.min_side / max(image.size)
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        best, rotation = self._run(image), 0
        # 거의 읽히지 않으면 옆으로 누운 사진일 수 있어 회전해 다시 읽고, 글자가 가장 많이 읽힌 쪽을 쓴다.
        weight = lambda lines: sum(len(line.text) * line.score for line in lines)
        if len(best) < 4 or _amounts(" ".join(line.text for line in best)) == []:
            for angle in (90, 270, 180):
                lines = self._run(image.rotate(angle, expand=True))
                if weight(lines) > weight(best) * 1.3:
                    best, rotation = lines, angle
        return best, {"rotation": rotation, "seconds": round(time.perf_counter() - started, 2)}


reader = ReceiptReader()

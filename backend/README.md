# 안녕멍뭉 사진 인증 백엔드

## 데이터셋 조사 결과와 적용 범위

| 데이터셋 | 현재 폴더 내용 / 라벨 | 이 프로젝트에서의 사용 |
|---|---|---|
| `Dataset/public/MPDD/pytorch` | `train`, `val`, `query`, `gallery` 이미지 폴더. train/val에서 1,032장, 95개 숫자 identity를 확인했으며 pose/keypoint, walk-action annotation 파일은 없음 | `backend/tools/prepare_mpdd_walk.py --assume-walk-labels`가 train+val을 identity 기준으로 재분할해 약한 walk 후보로 준비합니다. 현재 train 819장/76 identities, val 213장/19 identities. 수동 검수 후에만 행동 정답으로 보세요. query/gallery는 학습에 넣지 않습니다. |
| `Dataset/public/DogBreeds-yolov8` | 9,951장, YOLO 바운딩박스 형식, 100개 견종, CC BY 4.0 표기 | `train_dog_detector.py`로 반려견 존재를 확인하는 보조 객체 탐지 모델을 학습합니다. 견종 라벨은 산책/급여 행동 라벨이 아니므로 행동 판별로 오해하지 않습니다. |
| `Dataset/public/Oxford-IIIT-Pet` | 7,390장, 고양이/개 종, 품종 라벨, 머리 박스, 분할 정보 | 개/고양이 구분 연구 데이터입니다. 원본 웹사이트 이미지의 이용 조건을 확인해야 하며, 행동 레이블이 없어 행동 분류 학습에는 자동 편입하지 않습니다. |
| `Dataset/public/AP-10K` | 동물 키포인트 추정 코드, 설정과 일부 자료. README는 AP-10K 10,015장/동물 17개 키포인트를 설명하며 데이터셋 사용은 비상업적 조건을 명시합니다. | 동물 자세/키포인트 연구 자료입니다. 걷기, 급여 행동 레이블은 없으며 폴더에는 공식 `data/ap10k` 학습 이미지 번들이 없습니다. 현재 액션 모델 학습에는 사용하지 않습니다. |
| `Dataset/public/OpenImages-tools` | Open Images V3 도구, 설명 및 일부 메타데이터. README의 원본 이미지 라이선스 안내는 이미지별 검증을 요구합니다. | 현재 폴더에 행동별 이미지 레이블 데이터셋 자체가 없어 자동 학습하지 않습니다. |

MPDD에는 견종 이미지와 식별 ID가 있지만 pose/keypoint 또는 산책 행동 정답 라벨이 없습니다. 요청에 맞춰 identity가 겹치지 않는 약한 walk 후보 이미지를 준비했지만, 이 약한 라벨이 실제 산책 동작을 보장하지 않으며 별도 수동 검수가 필요합니다. 급여 및 비산책 `other` 정답 이미지는 현재 없으므로 세 클래스 활동 분류기는 별도 데이터 수집 후에야 학습할 수 있습니다. 그래서 현재 인증은 학습 없이 동작하는 사전학습 모델 조합(아래 **사진 인증 로직**)을 쓰고, 보유 데이터는 임계값 보정과 오판 측정에 사용합니다. 사전학습 모델 파일이 없으면 인증 API는 `503`으로 fail-closed 동작을 하고 포인트를 지급하지 않습니다.

## 사진 인증 로직 (산책, 급여)

`backend/verification.py`가 다음을 결합합니다. 사진 한 장당 CPU에서 약 0.25초 걸립니다.

1. **CLIP 제로샷 장면 분류** (open_clip ViT-B-32 / laion2b): 산책, 급여, 기타 장면을 여러 영어 문장과 비교한 확률. 정사각형 여백을 채워 가장자리의 목줄, 그릇이 잘리지 않게 합니다. 같은 방식으로 야외 여부, 목줄 여부도 판단합니다. (LVIS, Open Images에 목줄 클래스가 없어 목줄은 CLIP으로 판단합니다.)
2. **COCO 사전학습 YOLO (yolo11s)**: 개, 사람, 고양이, 그릇 위치.
3. **강아지 주변 확대 판별**: 가장 확실한 개 박스에 붙어 있는 사람, 그릇까지 합친 영역(15% 여유)을 잘라 CLIP 점수를 한 번 더 계산합니다(`Analysis.subject`). 개, 목줄이 작게 찍힌 사진에서 신호가 묻히는 문제를 줄입니다.
4. **산책 판정 모델** (`backend/models/walk_model.json`): 전체, 확대 장면 점수, 야외, 목줄 점수, 개 크기, 신뢰도, 사람, 그릇 위치 등 17개 특징을 로지스틱 회귀로 묶어 산책 점수 하나로 판단합니다. 목줄, 야외는 단독 탈락 조건이 아니라 모델의 입력이 되고, 화면에는 참고 항목으로 보여 줍니다. 파일이 없거나 CLIP 문장이 바뀌면 자동으로 아래 규칙으로 돌아갑니다.
5. **규칙**
   - 산책(모델이 없을 때): 개 탐지 + 산책 장면 점수 + 야외 + 목줄(동물보호법상 산책 시 목줄 의무). 사람은 참고 정보입니다.
   - 급여: 개 탐지 + 급여 장면 점수 + **개 박스 주변(35% 확장)에 그릇**. 그릇이 안 잡혀도 급여 장면 점수가 매우 높으면(기본 0.8) 통과합니다. 급여 양성 사진이 21장뿐이라 학습형 판정이 규칙보다 낫지 않아 규칙을 유지합니다.
6. **부정 사용 방지** (`app.py`): 이미 포인트를 받은 사진과 dHash 거리 6 이하면 거절, EXIF 촬영 시각이 24시간을 넘으면 거절(EXIF가 없으면 기록만), 하루 포인트 횟수 제한(산책 2회, 급여 3회).
7. (선택) `backend/models/activity_classifier.pt`를 학습해 두면 CLIP 점수와 평균합니다.

응답의 `checks` 배열에 항목별 통과/실패와 근거가 담기고, `activity_logs.details_json`에 점수, 탐지 결과가 저장됩니다.

### 준비

```powershell
uv pip install --python .venv-backend\Scripts\python.exe -r backend\requirements-detection.txt
.venv-backend\Scripts\python.exe -m backend.tools.download_verification_models   # CLIP 약 600MB + yolo11s.pt
```

### 평가와 임계값 보정

```powershell
.venv-backend\Scripts\python.exe -m backend.tools.build_coco_eval_set --per-class 120   # COCO 캡션 기반 실제 장면 평가 세트
.venv-backend\Scripts\python.exe -m backend.tools.evaluate_verifier --limit 150
```

평가 세트는 `Dataset/activity_eval/`에 저장되고 git에는 올라가지 않습니다.
- `coco/curation.json`: 사람이 검수한 결과입니다. 급여 후보 82장 중 그릇, 접시의 음식을 먹는 장면 21장만 급여 양성으로 쓰고, 급여가 아닌 29장은 어려운 오답으로 씁니다.
- MPDD walk(개만 잘라낸 사진)와 Oxford Pet 개 사진은 참고용, 오답용으로 함께 평가합니다.
- 직접 찍은 사진을 `Dataset/activity/test/{walk,feeding,other}/`에 넣으면 `user` 세트로 따로 집계합니다. 이 결과가 최종 정확도에 가장 가깝습니다.

### 산책 판정 모델 학습

```powershell
.venv-backend\Scripts\python.exe -m backend.tools.train_walk_model --max-false-accept 0.02
```

평가 세트(COCO 실장면 + Oxford + `user` 세트, MPDD 제외)로 학습하고 `backend/models/walk_model.json`을 덮어씁니다. 5겹 교차검증으로 성능을 보고하며, 임계값도 학습 겹 안에서 다시 교차검증해 고르므로 시험 겹의 사진은 한 번도 보지 않습니다. CLIP 문장(`ACTIVITY_PROMPTS`, `BINARY_PROMPTS`)을 고치면 다시 학습해야 합니다.

### 측정값 (COCO 실장면 + Oxford, 정확도 보장 아님)

임계값을 고른 사진으로 다시 채점하면 수치가 부풀려지므로, 아래는 모두 **5겹 교차검증** 수치입니다(2026-11-08).

| 요청 | 방식 | 재현율 | 정밀도 | 실장면 오인증률 |
|---|---|---|---|---|
| 산책 | 이전 규칙 (전체 사진만) | 38% | 80% | 3.4% |
| 산책 | 규칙 + 강아지 주변 확대 | 48% | 81% | 4.1% |
| 산책 | **산책 판정 모델 (현재)** | **63%** | **92%** | **1.9%** |
| 급여 | 규칙 (현재, 임계값도 교차검증으로 선택) | 81% (21장) | 90% | 0.5% |

- 이전 문서의 산책 50% / 86%는 같은 사진으로 임계값을 고르고 채점한 값이었습니다.
- 산책 모델의 향상분 상당 부분은 "개가 화면을 크게 차지하면 산책이 아닐 가능성이 높다", "사람이 함께 보이면 산책일 가능성이 높다" 같은 구도 특징에서 나옵니다. 사람 없이 찍은 산책 사진(34장)에서는 이전 규칙과 같은 재현율(35%)이고, 같은 조건의 오답 사진 오인증률은 3.0% → 0.7%로 줄었습니다.
- COCO 산책 사진은 대부분 멀리서 찍은 사진이라 **보호자 시점에서 내려다본 휴대폰 사진이 부족**합니다. 실제 사진을 `Dataset/activity/test/{walk,other}/`에 넣고 다시 학습하면 이 편향이 줄어듭니다.
- 급여는 양성 표본이 21장뿐이라 신뢰구간이 넓습니다.

임계값은 환경 변수로 바꿀 수 있습니다.
- `HELLOPUPPY_WALK_MODEL`(산책 판정 모델 경로, 기본 `backend/models/walk_model.json`. 없는 경로를 주면 규칙으로 판단)
- `HELLOPUPPY_WALK_THRESHOLD`(0.35), `HELLOPUPPY_FEEDING_THRESHOLD`(0.25), `HELLOPUPPY_ACTIVITY_MARGIN`(0.05)
- `HELLOPUPPY_LEASH_THRESHOLD`(0.05), `HELLOPUPPY_OUTDOOR_THRESHOLD`(0.3), `HELLOPUPPY_STRONG_FEEDING`(0.8) — 산책 세 값은 모델이 없을 때만 씁니다
- `HELLOPUPPY_DOG_CONFIDENCE`(0.3), `HELLOPUPPY_BOWL_CONFIDENCE`(0.2)
- `HELLOPUPPY_WALK_DAILY_LIMIT`(2), `HELLOPUPPY_FEEDING_DAILY_LIMIT`(3), `HELLOPUPPY_MAX_PHOTO_AGE_HOURS`(24)

## 영수증 리워드 (OCR)

`backend/receipt.py`, `backend/purchases.py` + `POST /api/receipts` (사진 업로드), `GET /api/receipts`, `GET /api/receipts/summary`, `PUT /api/receipts/{id}/items`, `PUT /api/receipts/{id}/dataset-consent`. 화면은 `frontend/receipt.html`(인증)과 `frontend/purchases.html`(구매 기록)입니다.

- **OCR 엔진**: [RapidOCR](https://github.com/RapidAI/RapidOCR) (Apache-2.0) + PaddleOCR **PP-OCRv5 한국어 인식 모델**을 ONNX Runtime으로 CPU에서 실행합니다. 장당 약 1~2초. 모델(약 20MB)은 첫 실행 때 `backend/models/ocr/`에 받습니다(`download_verification_models`도 함께 받음).
- **엔진을 고른 근거** (합성 한국어 영수증 6장 × 촬영본, 저화질 촬영본, 줄 단위 문자 일치율): RapidOCR 99.9% / 98.0%, EasyOCR 91.5% / 83.7%(2~3배 느림). 글줄 방향 분류기(cls)를 켜면 똑바른 줄을 180도로 뒤집어 읽어 83%까지 떨어져 끕니다. 사진이 옆으로 누워 거의 읽히지 않으면 90/270/180도로 돌려 다시 읽습니다.
- **추출 항목**: 같은 줄의 글자 조각(품목명, 가격)을 묶은 뒤 매장명, 사업자번호, 거래일시, 합계 금액(합계, 결제금액 등 우선순위, 부가세, 할인 줄 제외), 승인번호, 반려동물 품목을 뽑습니다. 실제 영수증에서 자주 나온 OCR 오류도 처리합니다: 날짜, 시간이 붙어 읽힘(`23-10-2421:49`), 쉼표 뒤 공백(`11, 200`), 키워드 오자(`관세`=과세, `일 계`=합계), `₩`→`W`, 금액 없는 합계 줄 다음의 공급가액 줄, 승인번호처럼 긴 숫자.
- **작은 사진 확대**: 긴 변이 `HELLOPUPPY_OCR_MIN_SIDE`(1600)px보다 작은 사진은 키워서 읽습니다. 메신저, 블로그로 줄어든 사진(가로 340px)에서 효과가 가장 컸습니다.
- **실측 (한국 영수증 1,000장, [Dataset/receipt/ocrReceipt1000](../Dataset/receipt/ocrReceipt1000/README.md))**: `python -m backend.tools.evaluate_receipt_ocr --split test`

  | 평가 셋 | 합계 | 거래일 | 거래시각(±5분) | 매장명 | 중복 확인 가능(합계+날짜) | 초/장 |
  |---|---|---|---|---|---|---|
  | KORIE test 131장 (규칙 개발에 안 씀), 개선 전 → 후 | 70.6 → **94.4%** | 74.0 → **96.2%** | 70.5 → **89.1%** | 60.2 → **86.2%** | 52.4 → **91.3%** | 1.3 |
  | 팀 수집 실사진 44장 (직접 라벨링, 저해상도), 전 → 후 | 20.0 → **47.5%** | 51.9 → **66.7%** | – | – | 13.0 → **34.8%** | 0.9 → 1.9 |

  검출 모델은 PP-OCRv5 mobile을 그대로 씁니다. 실사진 44장에서 v5 server는 합계 +1장, 날짜 −2장에 2.3배 느렸고, v6 small은 합계가 더 낮았습니다.
- **리워드 조건** (모두 통과해야 `HELLOPUPPY_RECEIPT_POINTS`=30P): 글자 3줄 이상, 반려동물 관련 단어(펫샵, 사료, 배변패드, 브랜드 등. '껌', '캔'처럼 편의점에도 흔한 단어는 제외), 합계 금액, 최근 `HELLOPUPPY_RECEIPT_MAX_AGE_DAYS`(7)일 이내 거래일, 처음 제출한 영수증.
- **품목 추출 (구매 기록)**: 품목 머리글(상품명, 단가, 수량) 아래부터 합계, 과세 줄 전까지에서 상품명, 수량, 단가, 금액을 뽑습니다. 이름과 가격이 한 줄에 있는 형태와, 이름 다음 줄에 바코드, 가격이 오는 형태를 모두 읽고, 행사, 에누리 할인 줄과 면세(#), 할인(*) 표시, 6~14자리 상품코드는 건너뜁니다. KORIE 품목 정답으로 측정(규칙 개발은 train, 보고는 test 130장, 품목 565개): **품목 금액 재현율 95.2%, 정밀도 95.9%, 상품명 유사(0.6 이상) 84%**. `evaluate_receipt_ocr.py`가 `item_recall`, `item_prec`, `item_name`으로 함께 보고합니다.
- **분류**: 사료, 간식, 배변/위생, 미용/목욕, 건강/영양제, 병원/진료, 장난감, 산책/외출, 생활용품, 기타 용품, 반려용품 아님. 펫샵, 동물병원 영수증은 모든 품목이 반려용품이고, 마트, 편의점 영수증은 반려동물 단어가 있는 품목만 반려용품으로 셉니다(자일리톨껌은 제외, 강아지 육포는 포함). 펫샵 여부는 거래일, 품목 머리글 위의 매장 정보로만 판단합니다.
- **구매 기록**: 반려용품이 있고 금액을 읽었으며 내 기록에 같은 영수증(지문 또는 같은 사진)이 없으면 `receipt_items`와 함께 기록합니다. 리워드 조건(7일 이내, 하루 1회)과 별개라 지난 영수증도 기록됩니다. 반려용품 지출은 펫샵이면 실제 결제액(할인 후), 마트면 반려용품 품목 금액의 합입니다. 사용자는 품목 이름, 수량, 금액, 분류를 고칠 수 있고, 모든 품목을 ‘반려용품 아님’으로 바꾸면 기록에서 빠지며 반려용품으로 바꾸면 기록에 들어갑니다. 고친 영수증은 `items_corrected=1`로 표시되어 사람이 확인한 학습 정답이 됩니다. 이 기능 이전에 저장된 영수증은 서버 시작 때 저장해 둔 OCR 원문으로 품목을 다시 만듭니다.
- **통계** (`/api/receipts/summary`): 총 지출, 이번 달, 월평균, 영수증당 평균, 최근 6개월 월별 지출, 분류별 금액, 비율(품목 금액 기준), 자주 산 물품(같은 이름을 공백, 기호 무시하고 묶음).
- **OCR 학습 데이터 (선택 동의)**: 영수증 인증 화면에서 동의(기본 해제)한 경우에만 `dataset_consent=1`로 표시합니다. 동의하지 않아도 리워드와 구매 기록은 똑같이 쓸 수 있고, 구매 기록 화면에서 영수증마다 철회할 수 있습니다. `python -m backend.tools.export_receipt_training_data`가 동의가 켜져 있는 영수증만 `Dataset/receipt/user_uploads/`(git 제외)에 사진, OCR 줄과 위치, 품목 라벨로 내보냅니다. 폴더는 매번 새로 만들어 철회한 사진은 다음 내보내기부터 빠집니다. 사진은 업로드 때 이미 GPS 등 메타데이터를 지운 사본입니다. 실제 서비스에서는 개인정보 처리방침에 수집 항목, 목적, 보관 기간을 적어야 합니다.
- **재사용 방지**: 사업자번호(없으면 매장명), 거래일시, 금액, 승인번호로 만든 지문이 같은 영수증은 다른 계정이 올려도 거절하고, 같은 사용자가 이미 쓴 사진(dHash)도 거절합니다. 하루 `HELLOPUPPY_RECEIPT_DAILY_LIMIT`(1)회까지 적립합니다.
- 한계: 저해상도 실사진은 합계를 절반 정도만 맞힙니다. 남은 오류 대부분은 OCR이 금액, 키워드 자체를 깨뜨린 경우(`18,30`, `B,00000`)입니다. 다음 단계는 KORIE OCR 크롭(약 1.7만 개)으로 한국어 인식 모델을 미세조정하는 것입니다. 이때 영수증 단위로 train/test를 나눠야 합니다(KORIE OCR 분할은 크롭 단위라 같은 영수증이 양쪽에 섞여 있음). 원문을 화면에 함께 보여 주는 것은 그대로 둡니다.

## 학습 데이터 준비

실제 촬영 사진을 아래처럼 직접 검수하고 분류해 주세요. `other`에는 산책/급여가 아닌 사진(예: 실내 휴식, 장난감, 풍경, 고양이, 잘못된 사진)을 넣습니다. 개인정보와 원본 출처/동의를 관리하고, 연속 촬영 프레임이나 같은 장면이 학습/검증 폴더에 동시에 들어가지 않게 합니다.

```text
Dataset/activity/
├── train/
│   ├── walk/
│   ├── feeding/
│   └── other/
└── val/
    ├── walk/
    ├── feeding/
    └── other/
```

각 클래스에 학습 사진 10장 이상, 검증 사진 3장 이상이 필요합니다. 이는 단지 실행을 위한 최저 조건이며 신뢰할 만한 모델에는 훨씬 많은 다양하고 독립적인 사진과 별도 테스트 세트가 필요합니다. 충분한 촬영 조건/견종/실내외/각도를 확보하고, 오분류를 검토한 뒤 포인트 지급 기능을 실제 사용자에게 공개하세요.

## Windows 개발 환경

Python 3.11 또는 3.12 권장. 필요한 것만 설치할 수 있게 종속성 파일을 나눴습니다.

| 파일 | 내용 |
|---|---|
| `requirements.txt` | API 서버 핵심 (계정, 포인트, 건강기록, 커뮤니티, 사진, PostgreSQL 드라이버 psycopg). AI 판별 없이 동작 |
| `requirements-detection.txt` | + 사진 인증(CLIP, YOLO), 영수증 OCR. torch 포함 |
| `requirements-train.txt` | + `train_activity.py` 학습용 torch, torchvision. GPU가 있으면 PyTorch 공식 안내의 CUDA 빌드를 먼저 설치 |
| `requirements-dev.txt` | + pytest, httpx (CI와 같은 테스트 환경) |

```powershell
uv venv .venv-backend --python 3.12
uv pip install --python .venv-backend\Scripts\python.exe -r backend\requirements-detection.txt -r backend\requirements-dev.txt
```

## PostgreSQL 계정, 앱 데이터 API

데이터는 **PostgreSQL**(오픈소스, PostgreSQL License, 상업적 이용 포함 무료)에 저장합니다. 백엔드는 시작할 때 필요한 테이블과 인덱스를 자동으로 만듭니다. 접속 주소는 `HELLOPUPPY_DATABASE_URL`로 정하며, 없으면 `postgresql://hellopuppy:hellopuppy@127.0.0.1:5432/hellopuppy`에 접속합니다. 가입 시 기본 포인트는 0P이며, 판별된 미션 성공만 서버 트랜잭션으로 포인트를 지급합니다. 포인트를 주거나 쓰는 요청은 그 사용자의 포인트 행을 잠그고(`SELECT ... FOR UPDATE`) 처리하므로, 같은 사용자의 요청이 동시에 와도 하루 적립 횟수를 넘기거나 잔액보다 많이 쓰지 않습니다.

### 로컬 PostgreSQL 준비 (둘 중 하나)

- **Docker**: 아래 명령으로 PostgreSQL 컨테이너만 띄웁니다.
  ```powershell
  docker run -d --name hellopuppy-db -e POSTGRES_DB=hellopuppy -e POSTGRES_USER=hellopuppy -e POSTGRES_PASSWORD=hellopuppy -p 5432:5432 -v hellopuppy-db:/var/lib/postgresql/data postgres:17-alpine
  ```
- **Windows 설치**: [PostgreSQL 공식 설치 파일](https://www.postgresql.org/download/windows/)로 설치한 뒤 SQL Shell(psql)에서 계정과 DB를 만듭니다.
  ```sql
  CREATE USER hellopuppy WITH PASSWORD 'hellopuppy';
  CREATE DATABASE hellopuppy OWNER hellopuppy;
  ```

다른 주소나 비밀번호를 쓰면 PowerShell 세션에 지정합니다. 개발 중 프론트엔드와 API의 주소가 다르면 CORS 허용 주소도 지정합니다. 운영 환경에서는 와일드카드 대신 실제 프론트엔드 origin만 허용해야 합니다.

```powershell
$env:HELLOPUPPY_DATABASE_URL = "postgresql://hellopuppy:hellopuppy@127.0.0.1:5432/hellopuppy"
$env:HELLOPUPPY_FRONTEND_ORIGIN = "http://127.0.0.1:5500"
```

`HELLOPUPPY_FRONTEND_ORIGIN`은 실제 프론트엔드 주소로 설정합니다. Live Server 포트가 다르면 값을 바꾸세요. 연결 풀 크기는 `HELLOPUPPY_DB_POOL_SIZE`(기본 10)로 바꿉니다.

### 예전 SQLite 데이터 옮기기

SQLite(`backend/data/hellopuppy.sqlite3`)로 쓰던 데이터는 한 번만 옮기면 됩니다. 빈 PostgreSQL DB에만 옮기며(이미 계정이 있으면 멈춤), SQLite 파일은 읽기만 합니다. id는 그대로 유지되고, 사진 파일 폴더(`backend/data/media`)는 그대로 씁니다. 사진이 DB 안(BLOB)에 들어 있던 아주 예전 DB는 메타데이터를 지운 파일로 꺼냅니다.

```powershell
$env:HELLOPUPPY_DATABASE_URL = "postgresql://hellopuppy:hellopuppy@127.0.0.1:5432/hellopuppy"
.venv-backend\Scripts\python.exe -m backend.tools.migrate_sqlite_to_postgres --sqlite backend\data\hellopuppy.sqlite3
```

**사진 저장**: 업로드 사진은 EXIF, XMP(GPS 위치, 기기 정보 등)를 지우고 다시 인코딩해 `backend/data/media/YYYY/MM/`에 파일로 저장합니다(`HELLOPUPPY_MEDIA_DIR`). DB에는 경로만 남깁니다. 산책 인증의 촬영 시각은 저장 전에 원본에서 읽습니다. 백업할 것은 PostgreSQL(`pg_dump`)과 `media/` 폴더 두 가지입니다.

**로그인 시도 제한**: 15분 안에 같은 이메일로 5번, 같은 IP에서 20번 실패하면 남은 시간만큼 `429`(`Retry-After`)로 막습니다. 없는 이메일도 같은 비용으로 계산하고 실패로 세서, 가입 여부를 응답으로 알 수 없게 했습니다. 기록은 DB `login_failures` 테이블에 남겨 서버를 재시작해도 유지됩니다. `HELLOPUPPY_LOGIN_WINDOW_MINUTES`, `HELLOPUPPY_LOGIN_MAX_FAILURES_PER_EMAIL`, `HELLOPUPPY_LOGIN_MAX_FAILURES_PER_IP`로 조정합니다. 리버스 프록시 뒤에서는 `HELLOPUPPY_TRUST_PROXY=1`로 `X-Forwarded-For`를 믿게 합니다. 이때 프록시가 이 헤더를 덮어써야 합니다(`deploy/nginx.conf`).

로그인 토큰은 충분히 긴 무작위 bearer token이며 서버에는 토큰 원문이 아닌 SHA-256 해시와 만료 시각만 DB `sessions` 테이블에 보관합니다. 로그아웃하면 서버 세션도 삭제되어 토큰을 즉시 폐기합니다. 비밀번호는 PBKDF2-HMAC-SHA256으로 해시합니다.

### 계정 및 저장 데이터

- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`: 가입, 로그인, 현재 계정. 비밀번호는 PBKDF2-HMAC-SHA256 해시로 저장되며 평문은 DB에 저장하지 않습니다.
- `POST /api/auth/logout`: 현재 로그인 세션 폐기.
- `GET /api/points`, `GET /api/points/ledger`: 계정 잔액 및 모든 지급/차감 원장.
- `GET/PUT /api/pet/profile`, `GET/PUT /api/pet/food`: 계정별 반려견, 사료 정보.
- `GET/POST/DELETE /api/health/records`: 계정별 건강 기록. 기록 종류는 `visit`(SOAP 진료), `vaccination`, `parasite`, `medication`, `condition`, `allergy`, `surgery`, `lab`, `weight`, `symptom`, `other`입니다. 종류별 상세 항목은 `details`로 받고 `backend/health.py`의 `RECORD_TYPES` 규칙으로 검증합니다. `purpose=health`로 올린 사진(`image_id`)을 첨부할 수 있습니다.
- `GET /api/health/summary`: 병원에 보여줄 기본 정보, 식이, 기록, 문진표, 30일 활동을 한 번에 반환합니다.
- `GET/POST/DELETE /api/health/questionnaires`: 방문 전 문진표(주 증상, 경과, 계통별 상태).
- `GET /api/health/export/fhir`: HL7 FHIR R4 collection Bundle 내보내기.
- `POST/GET/DELETE /api/health/shares`: 병원별 기한부 공유 링크 발급, 목록(열람 횟수 포함), 취소. 권한은 `read` 또는 `read_write`이고 최대 72시간입니다. 토큰 원문은 발급 응답에서 한 번만 반환하며 DB에는 SHA-256 해시만 저장합니다.
- `GET /api/shared/health`, `GET /api/shared/health/fhir`, `POST /api/shared/health/records`, `GET /api/shared/health/images/{id}`: 동물병원용 API입니다. 로그인 대신 `X-Health-Share-Token` 헤더로 인증합니다. 기록 입력은 `read_write` 링크에서만 가능하고, 입력된 기록은 `source=clinic`, 링크의 병원명, 수의사 이름, 면허번호와 함께 저장됩니다. 만료, 취소된 링크는 404를 반환합니다. 열람, 내보내기, 입력은 `audit_logs`에 남습니다.
- `POST /api/verify/walk`, `POST /api/verify/feeding`: 로그인 사용자 사진 인증. 사진 파일(메타데이터 제거), 판정 결과와 활동 로그가 기록됩니다. 인증 성공 포인트 지급과 원장은 한 DB 트랜잭션으로 처리됩니다.
- `POST /api/uploads?purpose=community`, `GET /api/images/{id}`: 로그인한 사용자의 사진을 메타데이터를 지운 파일로 저장/조회. 커뮤니티 게시글에 첨부된 사진은 로그인 사용자에게 공개되며, 인증/건강 용도 사진은 업로드한 계정만 읽을 수 있습니다.
- `GET/POST /api/community/posts`, `POST /api/community/posts/{id}/like`, `GET/POST /api/community/posts/{id}/comments`: 글, 좋아요, 댓글을 저장합니다.
- `POST /api/shop/redeem`, `GET /api/shop/redemptions`: 서버 카탈로그를 기준으로 포인트 차감과 교환 원장을 저장합니다. 클라이언트가 제출한 가격은 사용하지 않습니다.

프론트엔드에는 bearer token만 `localStorage`에 저장합니다. 포인트, 프로필, 활동, 건강 로그, 커뮤니티 글/사진 등 업무 데이터는 API로 저장합니다. 로그인 전 계정이 필요한 화면은 `account.html`로 보냅니다. 신규 계정은 기본 0P로 시작하고, 기존 브라우저 localStorage 포인트/프로필은 클라이언트가 조작할 수 있어 자동 이관하지 않습니다. 영수증은 OCR로 확인한 뒤에만 포인트를 주고, 판별 모델 파일이 없어 `503`이 나는 사진도 보상 없이 거절됩니다.

저장 흐름의 통합 테스트는 프로젝트 루트에서 실행합니다. AI 모델 없이 돌아가며, GitHub Actions(`.github/workflows/tests.yml`)가 push, PR마다 PostgreSQL 컨테이너를 띄워 Python 3.11/3.12로 같은 테스트와 프론트 JS 문법 검사를 실행합니다. DB가 필요한 테스트는 `HELLOPUPPY_TEST_DATABASE_URL`의 PostgreSQL에 테스트마다 빈 스키마를 만들어 쓰고 지웁니다(DB의 다른 데이터는 건드리지 않음). 주소가 없으면 그 테스트만 건너뜁니다.

```powershell
$env:HELLOPUPPY_TEST_DATABASE_URL = "postgresql://hellopuppy:hellopuppy@127.0.0.1:5432/hellopuppy"
.venv-backend\Scripts\python.exe -m pytest backend\tests -q
```

사진 폴더는 서버를 여러 대로 늘릴 때 오브젝트 스토리지(S3 등)로 옮기는 것을 권장합니다(`storage.py`의 저장, 읽기 함수만 바꾸면 됩니다). 정기 백업, 복구 테스트, 만료된 세션 정리, HTTPS, 운영 CORS, 사용자 동의/데이터 삭제 정책 및 개인정보 보관 정책을 별도로 마련하세요. 현재 만료 토큰은 요청에서 거절되며 DB 행 자동 정리는 아직 없습니다.

프로젝트에 포함된 견종 YOLO 데이터를 이용해 보조 개 탐지기를 학습하려면 추가 종속성과 Ultralytics의 초기 가중치 다운로드가 필요합니다.

```powershell
.venv-backend\Scripts\python.exe backend\train_dog_detector.py --epochs 30 --device cpu
```

GPU 예시: `--device 0`. 완료된 보조 모델은 `backend/models/dog_detector.pt`에 저장됩니다. 학습된 견종 클래스들은 개 존재 확인에만 쓰며, 산책, 급여 판단에는 쓰지 않습니다.

MPDD 산책 후보를 준비하려면 다음 스크립트를 실행합니다. 기존 train/val을 합친 뒤 개체 identity별로 다시 나누어 같은 개가 양쪽에 섞이지 않게 합니다. 원본 데이터에는 walk-action 라벨이 없으므로 실제 산책 장면인지 직접 검수해야 합니다.

```powershell
.venv-backend\Scripts\python.exe backend\tools\prepare_mpdd_walk.py --assume-walk-labels
```

실제 행동 판별기를 학습하려면 검수된 walk 후보와 feeding/other 사진을 준비한 뒤 실행합니다. `--no-pretrained`를 주지 않는 한 MobileNetV3-Small ImageNet 초기 가중치를 내려받아 전이 학습합니다.

```powershell
.venv-backend\Scripts\python.exe backend\train_activity.py --epochs 12
```

완료되면 `backend/models/activity_classifier.pt`가 생성되고, 서버를 재시작하면 CLIP 점수와 평균해 사용합니다(`HELLOPUPPY_TRAINED_MODEL_WEIGHT`, 기본 0.5). `/health`의 `trained_classifier`로 확인합니다.

## 서버/API

```powershell
.venv-backend\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

- `GET /health`: 판별 모델 준비 상태(`ready`, `clip_model`, `object_detector`, `trained_classifier`)
- `POST /api/verify/walk`: multipart/form-data의 `photo`로 산책 사진 판별
- `POST /api/verify/feeding`: multipart/form-data의 `photo`로 급여 사진 판별

중간 발표에서 화면 흐름만 시연해야 하고 판별 모델을 내려받지 못한 상태라면, 개발용 서버를 시작하기 전에 PowerShell 세션에서 `$env:HELLOPUPPY_DEMO_MODE = "1"`을 설정하세요. 모델이 없는 동안 유효한 이미지 업로드에 더미 결과를 반환하지만, 응답은 `demo: true`이며 실제 인증으로 기록하거나 포인트를 지급하지 않습니다. 시연 모드를 끄려면 `$env:HELLOPUPPY_DEMO_MODE = "0"`으로 바꾸고 서버를 재시작하세요. 운영 환경에서는 이 옵션을 활성화하지 마세요.

판정 기준은 위 **사진 인증 로직**을 참고하세요. 모델 점수는 검증된 정확도 보장이 아니므로 부정 사용 방지의 단독 근거로 삼지 마세요. 인증 사진은 메타데이터를 지운 파일로 저장됩니다.

프론트엔드는 기본적으로 `http://127.0.0.1:8000`에 요청합니다. 다른 호스트/배포 환경에서는 HTML에서 `window.HELLOPUPPY_API_BASE`를 API 주소로 설정해야 합니다. 현재 인증 요청은 브라우저 카메라/파일 선택 사진을 실제로 서버에 보내며, 성공 응답을 받은 경우에만 시연용 브라우저 포인트를 올립니다. 서버 응답이 거절/미준비/오류인 경우 포인트는 적립하지 않습니다.

## Docker 배포

저장소 루트의 `docker-compose.yml`은 세 컨테이너로 구성됩니다.
- `db`: PostgreSQL 17. `api`가 준비 상태(`pg_isready`)를 확인한 뒤 시작합니다.
- `api`: `backend/Dockerfile`, FastAPI + AI 판별, CPU torch
- `web`: nginx. `frontend/`를 서빙하고 `/api`를 `api`로 넘깁니다. 같은 주소에서 서비스되므로 프론트 설정은 필요 없습니다.

DB와 API 포트는 바깥에 열지 않습니다. 실제 서버에서는 `docker-compose.yml`과 같은 폴더의 `.env` 파일(git 제외)에 `POSTGRES_PASSWORD=길고-무작위인-값`을 넣어 기본 비밀번호를 바꾸세요. 이 값은 DB 접속 주소에 들어가므로 영문, 숫자, `-`, `_`만 씁니다. 비밀번호는 DB 볼륨을 처음 만들 때 정해지므로, 이미 만든 볼륨의 비밀번호를 바꾸려면 PostgreSQL에서 `ALTER USER`로 바꿉니다.

```bash
docker compose up -d --build                    # http://localhost:8080
docker compose run --rm api python -m backend.tools.download_verification_models   # 처음 한 번, AI 모델 약 650MB
```

- 데이터는 볼륨 세 개에 남습니다. `hellopuppy-db`에는 PostgreSQL 데이터가, `hellopuppy-data`에는 사진이, `hellopuppy-models`에는 CLIP, YOLO, OCR 모델이 들어갑니다. 백업 대상은 `hellopuppy-db`(`docker compose exec db pg_dump -U hellopuppy hellopuppy > backup.sql`)와 `hellopuppy-data`입니다.
- 예전 SQLite 볼륨 데이터를 옮기려면 SQLite 파일을 `api` 컨테이너에서 읽을 수 있게 한 뒤 `docker compose run --rm api python -m backend.tools.migrate_sqlite_to_postgres --sqlite /data/hellopuppy.sqlite3`를 실행합니다. 사진은 같은 `hellopuppy-data` 볼륨에 그대로 있습니다.
- 학습한 산책 판정 모델(`backend/models/walk_model.json`)은 이미지에 포함됩니다.
- HTTPS는 compose 앞단의 리버스 프록시(Caddy, 클라우드 로드밸런서 등)에서 처리하세요. 병원 공유 링크를 다른 기기에서 열려면 HTTPS 주소가 필요합니다.
- 포트는 `HELLOPUPPY_PORT`로, 허용할 프론트 주소는 `HELLOPUPPY_FRONTEND_ORIGIN`으로 바꿉니다.

## 배포 전 필수 보완

이 코드는 로컬 개발용 시작점입니다. 사진 분류만으로 촬영 시점/위치/실제 행위를 증명할 수 없고, 브라우저의 bearer token은 XSS 등에 노출될 수 있습니다. 상용 공개 전에 HTTPS, 짧은 세션, 토큰 보호, 요청 제한, 업로드 보관, 삭제 정책, 엄격한 CORS, 정기 백업, 별도 보안/정확도 검증을 수행하세요. 임계값은 학습된 별도 검증 세트에서 보정해야 하며 모델의 신뢰도 수치 자체를 정확도라고 해석하면 안 됩니다.

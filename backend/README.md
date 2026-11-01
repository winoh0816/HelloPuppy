# 안녕멍뭉 사진 인증 백엔드

## 데이터셋 조사 결과와 적용 범위

| 데이터셋 | 현재 폴더 내용 / 라벨 | 이 프로젝트에서의 사용 |
|---|---|---|
| `Dataset/MPDD/pytorch` | `train`, `val`, `query`, `gallery` 이미지 폴더. train/val에서 1,032장, 95개 숫자 identity를 확인했으며 pose/keypoint·walk-action annotation 파일은 없음 | `backend/tools/prepare_mpdd_walk.py --assume-walk-labels`가 train+val을 identity 기준으로 재분할해 약한 walk 후보로 준비합니다. 현재 train 819장/76 identities, val 213장/19 identities. 수동 검수 후에만 행동 정답으로 보세요. query/gallery는 학습에 넣지 않습니다. |
| `Dataset/Dog Breeds.v3i.yolov8` | 9,951장, YOLO 바운딩박스 형식, 100개 견종, CC BY 4.0 표기 | `train_dog_detector.py`로 반려견 존재를 확인하는 보조 객체 탐지 모델을 학습합니다. 견종 라벨은 산책/급여 행동 라벨이 아니므로 행동 판별로 오해하지 않습니다. |
| `Dataset/TheOxford-IIIT_Pet_Dataset` | 7,390장, 고양이/개 종·품종 라벨, 머리 박스·분할 정보 | 개/고양이 구분 연구 데이터입니다. 원본 웹사이트 이미지의 이용 조건을 확인해야 하며, 행동 레이블이 없어 행동 분류 학습에는 자동 편입하지 않습니다. |
| `Dataset/AP-10K-main` | 동물 키포인트 추정 코드·설정과 일부 자료. README는 AP-10K 10,015장/동물 17개 키포인트를 설명하며 데이터셋 사용은 비상업적 조건을 명시합니다. | 동물 자세/키포인트 연구 자료입니다. 걷기·급여 행동 레이블은 없으며 폴더에는 공식 `data/ap10k` 학습 이미지 번들이 없습니다. 현재 액션 모델 학습에는 사용하지 않습니다. |
| `Dataset/dataset-main` | Open Images V3 도구, 설명 및 일부 메타데이터. README의 원본 이미지 라이선스 안내는 이미지별 검증을 요구합니다. | 현재 폴더에 행동별 이미지 레이블 데이터셋 자체가 없어 자동 학습하지 않습니다. |

MPDD에는 견종 이미지와 식별 ID가 있지만 pose/keypoint 또는 산책 행동 정답 라벨이 없습니다. 요청에 맞춰 identity가 겹치지 않는 약한 walk 후보 이미지를 준비했지만, 이 약한 라벨이 실제 산책 동작을 보장하지 않으며 별도 수동 검수가 필요합니다. 급여 및 비산책 `other` 정답 이미지는 현재 없으므로 세 클래스 활동 분류기는 별도 데이터 수집 후에야 학습할 수 있습니다. 그래서 현재 인증은 학습 없이 동작하는 사전학습 모델 조합(아래 **사진 인증 로직**)을 쓰고, 보유 데이터는 임계값 보정과 오판 측정에 사용합니다. 사전학습 모델 파일이 없으면 인증 API는 `503`으로 fail-closed 동작을 하고 포인트를 지급하지 않습니다.

## 사진 인증 로직 (산책·급여)

`backend/verification.py`가 다음을 결합합니다. 사진 한 장당 CPU에서 약 0.15초 걸립니다.

1. **CLIP 제로샷 장면 분류** (open_clip ViT-B-32 / laion2b): 산책·급여·기타 장면을 여러 영어 문장과 비교한 확률. 정사각형 여백을 채워 가장자리의 목줄·그릇이 잘리지 않게 합니다. 같은 방식으로 야외 여부, 목줄 여부도 판단합니다. (LVIS·Open Images에 목줄 클래스가 없어 목줄은 CLIP으로 판단합니다.)
2. **COCO 사전학습 YOLO (yolo11s)**: 개·사람·고양이·그릇 위치.
3. **규칙**
   - 산책: 개 탐지 + 산책 장면 점수 + 야외 + 목줄(동물보호법상 산책 시 목줄 의무). 사람은 참고 정보입니다.
   - 급여: 개 탐지 + 급여 장면 점수 + **개 박스 주변(35% 확장)에 그릇**. 그릇이 안 잡혀도 급여 장면 점수가 매우 높으면(기본 0.8) 통과합니다.
4. **부정 사용 방지** (`app.py`): 이미 포인트를 받은 사진과 dHash 거리 6 이하면 거절, EXIF 촬영 시각이 24시간을 넘으면 거절(EXIF가 없으면 기록만), 하루 포인트 횟수 제한(산책 2회, 급여 3회).
5. (선택) `backend/models/activity_classifier.pt`를 학습해 두면 CLIP 점수와 평균합니다.

응답의 `checks` 배열에 항목별 통과/실패와 근거가 담기고, `activity_logs.details_json`에 점수·탐지 결과가 저장됩니다.

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
- `coco/curation.json`: 사람이 검수한 결과입니다. 급여 후보 82장 중 그릇·접시의 음식을 먹는 장면 21장만 급여 양성으로 쓰고, 급여가 아닌 29장은 어려운 오답으로 씁니다.
- MPDD walk(개만 잘라낸 사진)와 Oxford Pet 개 사진은 참고용·오답용으로 함께 평가합니다.
- 직접 찍은 사진을 `Dataset/activity/test/{walk,feeding,other}/`에 넣으면 `user` 세트로 따로 집계합니다. 이 결과가 최종 정확도에 가장 가깝습니다.

2026-11-01 기본 설정 측정값 (COCO 실장면 + Oxford, 정확도 보장 아님):

| 요청 | 재현율 | 정밀도 | 실장면 오인증률 | 비고 |
|---|---|---|---|---|
| 산책 | 50% | 86% (COCO만 98%) | 2.8% (Oxford 5.3%) | COCO 산책 라벨은 캡션 기반이라 약 20%가 잡음 |
| 급여 | 76% (21장) | 94% | 0.2% | 양성 표본이 적어 신뢰구간이 넓음 |

임계값은 환경 변수로 바꿀 수 있습니다.
- `HELLOPUPPY_WALK_THRESHOLD`(0.35), `HELLOPUPPY_FEEDING_THRESHOLD`(0.25), `HELLOPUPPY_ACTIVITY_MARGIN`(0.05)
- `HELLOPUPPY_LEASH_THRESHOLD`(0.05), `HELLOPUPPY_OUTDOOR_THRESHOLD`(0.3), `HELLOPUPPY_STRONG_FEEDING`(0.8)
- `HELLOPUPPY_DOG_CONFIDENCE`(0.3), `HELLOPUPPY_BOWL_CONFIDENCE`(0.2)
- `HELLOPUPPY_WALK_DAILY_LIMIT`(2), `HELLOPUPPY_FEEDING_DAILY_LIMIT`(3), `HELLOPUPPY_MAX_PHOTO_AGE_HOURS`(24)

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

Python 3.11 또는 3.12 권장. GPU가 있으면 PyTorch 공식 설치 안내에서 CUDA에 맞는 명령을 선택하세요. 먼저 `torch`와 `torchvision`을 해당 환경에 설치한 후 기본 API 종속성을 설치합니다.

```powershell
uv venv .venv-backend --python 3.12
uv pip install --python .venv-backend\Scripts\python.exe -r backend\requirements.txt
uv pip install --python .venv-backend\Scripts\python.exe -r backend\requirements-detection.txt
```

## SQLite 계정·앱 데이터 API

백엔드는 첫 시작 때 `backend/data/hellopuppy.sqlite3`를 만들고 필요한 테이블을 자동 생성합니다. DB 파일은 `.gitignore` 대상이며 버전 관리에 포함되지 않습니다. 다른 위치를 쓰려면 `HELLOPUPPY_DB_PATH`를 지정합니다. 가입 시 기본 포인트는 0P이며, 판별된 미션 성공만 서버 트랜잭션으로 포인트를 지급합니다.

개발 중 프런트엔드와 API의 주소가 다르면 CORS 허용 주소를 PowerShell 세션에 지정합니다. 운영 환경에서는 와일드카드 대신 실제 프런트엔드 origin만 허용해야 합니다.

```powershell
$env:HELLOPUPPY_DB_PATH = "backend/data/hellopuppy.sqlite3"
$env:HELLOPUPPY_FRONTEND_ORIGIN = "http://127.0.0.1:5500"
```

`HELLOPUPPY_FRONTEND_ORIGIN`은 실제 프런트엔드 주소로 설정합니다. Live Server 포트가 다르면 값을 바꾸세요. 같은 API 프로세스와 DB 파일을 계속 사용해야 데이터가 유지됩니다.

로그인 토큰은 충분히 긴 무작위 bearer token이며 서버에는 토큰 원문이 아닌 SHA-256 해시와 만료 시각만 SQLite `sessions` 테이블에 보관합니다. 로그아웃하면 서버 세션도 삭제되어 토큰을 즉시 폐기합니다. 비밀번호는 PBKDF2-HMAC-SHA256으로 해시합니다.

### 계정 및 저장 데이터

- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`: 가입·로그인·현재 계정. 비밀번호는 PBKDF2-HMAC-SHA256 해시로 저장되며 평문은 DB에 저장하지 않습니다.
- `POST /api/auth/logout`: 현재 로그인 세션 폐기.
- `GET /api/points`, `GET /api/points/ledger`: 계정 잔액 및 모든 지급/차감 원장.
- `GET/PUT /api/pet/profile`, `GET/PUT /api/pet/food`: 계정별 반려견·사료 정보.
- `GET/POST/DELETE /api/health/records`: 계정별 건강 기록. 기록 종류는 `visit`(SOAP 진료), `vaccination`, `parasite`, `medication`, `condition`, `allergy`, `surgery`, `lab`, `weight`, `symptom`, `other`입니다. 종류별 상세 항목은 `details`로 받고 `backend/health.py`의 `RECORD_TYPES` 규칙으로 검증합니다. `purpose=health`로 올린 사진(`image_id`)을 첨부할 수 있습니다.
- `GET /api/health/summary`: 병원에 보여줄 기본 정보·식이·기록·문진표·30일 활동을 한 번에 반환합니다.
- `GET/POST/DELETE /api/health/questionnaires`: 방문 전 문진표(주 증상, 경과, 계통별 상태).
- `GET /api/health/export/fhir`: HL7 FHIR R4 collection Bundle 내보내기.
- `POST/GET/DELETE /api/health/shares`: 병원별 기한부 공유 링크 발급·목록(열람 횟수 포함)·취소. 권한은 `read` 또는 `read_write`이고 최대 72시간입니다. 토큰 원문은 발급 응답에서 한 번만 반환하며 DB에는 SHA-256 해시만 저장합니다.
- `GET /api/shared/health`, `GET /api/shared/health/fhir`, `POST /api/shared/health/records`, `GET /api/shared/health/images/{id}`: 동물병원용 API입니다. 로그인 대신 `X-Health-Share-Token` 헤더로 인증합니다. 기록 입력은 `read_write` 링크에서만 가능하고, 입력된 기록은 `source=clinic`, 링크의 병원명, 수의사 이름·면허번호와 함께 저장됩니다. 만료·취소된 링크는 404를 반환합니다. 열람·내보내기·입력은 `audit_logs`에 남습니다.
- `POST /api/verify/walk`, `POST /api/verify/feeding`: 로그인 사용자 사진 인증. 사진 BLOB, 판정 결과와 활동 로그가 SQLite에 기록됩니다. 인증 성공 포인트 지급과 원장은 한 DB 트랜잭션으로 처리됩니다.
- `POST /api/uploads?purpose=community`, `GET /api/images/{id}`: 로그인한 사용자의 사진을 SQLite BLOB으로 저장/조회. 커뮤니티 게시글에 첨부된 사진은 로그인 사용자에게 공개되며, 인증/건강 용도 사진은 업로드한 계정만 읽을 수 있습니다.
- `GET/POST /api/community/posts`, `POST /api/community/posts/{id}/like`, `GET/POST /api/community/posts/{id}/comments`: 글·좋아요·댓글을 저장합니다.
- `POST /api/shop/redeem`, `GET /api/shop/redemptions`: 서버 카탈로그를 기준으로 포인트 차감과 교환 원장을 저장합니다. 클라이언트가 제출한 가격은 사용하지 않습니다.

프런트엔드에는 bearer token만 `localStorage`에 저장합니다. 포인트, 프로필, 활동·건강 로그, 커뮤니티 글/사진 등 업무 데이터는 API로 저장합니다. 로그인 전 계정이 필요한 화면은 `account.html`로 보냅니다. 신규 계정은 기본 0P로 시작하고, 기존 브라우저 localStorage 포인트/프로필은 클라이언트가 조작할 수 있어 자동 이관하지 않습니다. 현재 영수증 OCR은 데모라 포인트를 지급하지 않으며, 판별 모델 파일이 없어 `503`이 나는 사진도 보상 없이 거절됩니다.

저장 흐름의 통합 테스트는 프로젝트 루트에서 실행합니다.

```powershell
.venv-backend\Scripts\python.exe -m pytest backend\tests -q
```

SQLite는 단일 서버/개발 단계용입니다. 다중 서버 배포나 동시 쓰기가 많아지면 PostgreSQL/Supabase로 옮기고, 이미지 BLOB은 오브젝트 스토리지로 이전하는 것을 권장합니다. 정기 백업, 복구 테스트, 만료된 세션 정리, rate limit, HTTPS, 운영 CORS, 사용자 동의/데이터 삭제 정책 및 개인정보 보관 정책을 별도로 마련하세요. 현재 만료 토큰은 요청에서 거절되며 DB 행 자동 정리는 아직 없습니다.

프로젝트에 포함된 견종 YOLO 데이터를 이용해 보조 개 탐지기를 학습하려면 추가 종속성과 Ultralytics의 초기 가중치 다운로드가 필요합니다.

```powershell
.venv-backend\Scripts\python.exe backend\train_dog_detector.py --epochs 30 --device cpu
```

GPU 예시: `--device 0`. 완료된 보조 모델은 `backend/models/dog_detector.pt`에 저장됩니다. 학습된 견종 클래스들은 개 존재 확인에만 쓰며, 산책·급여 판단에는 쓰지 않습니다.

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

판정 기준은 위 **사진 인증 로직**을 참고하세요. 모델 점수는 검증된 정확도 보장이 아니므로 부정 사용 방지의 단독 근거로 삼지 마세요. 인증 사진은 디스크 파일이 아니라 SQLite BLOB으로 저장됩니다.

프런트엔드는 기본적으로 `http://127.0.0.1:8000`에 요청합니다. 다른 호스트/배포 환경에서는 HTML에서 `window.HELLOPUPPY_API_BASE`를 API 주소로 설정해야 합니다. 현재 인증 요청은 브라우저 카메라/파일 선택 사진을 실제로 서버에 보내며, 성공 응답을 받은 경우에만 시연용 브라우저 포인트를 올립니다. 서버 응답이 거절/미준비/오류인 경우 포인트는 적립하지 않습니다.

## 배포 전 필수 보완

이 코드는 로컬 개발용 시작점입니다. 사진 분류만으로 촬영 시점/위치/실제 행위를 증명할 수 없고, 브라우저의 bearer token은 XSS 등에 노출될 수 있습니다. 상용 공개 전에 HTTPS, 짧은 세션·토큰 보호, 요청 제한, 업로드 보관·삭제 정책, 엄격한 CORS, 정기 백업, 별도 보안/정확도 검증을 수행하세요. 임계값은 학습된 별도 검증 세트에서 보정해야 하며 모델의 신뢰도 수치 자체를 정확도라고 해석하면 안 됩니다.

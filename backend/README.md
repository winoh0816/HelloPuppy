# 안녕멍뭉 사진 인증 백엔드

## 데이터셋 조사 결과와 적용 범위

| 데이터셋 | 현재 폴더 내용 / 라벨 | 이 프로젝트에서의 사용 |
|---|---|---|
| `Dataset/MPDD/pytorch` | `train`, `val`, `query`, `gallery` 이미지 폴더. train/val에서 1,032장, 95개 숫자 identity를 확인했으며 pose/keypoint·walk-action annotation 파일은 없음 | `backend/tools/prepare_mpdd_walk.py --assume-walk-labels`가 train+val을 identity 기준으로 재분할해 약한 walk 후보로 준비합니다. 현재 train 819장/76 identities, val 213장/19 identities. 수동 검수 후에만 행동 정답으로 보세요. query/gallery는 학습에 넣지 않습니다. |
| `Dataset/Dog Breeds.v3i.yolov8` | 9,951장, YOLO 바운딩박스 형식, 100개 견종, CC BY 4.0 표기 | `train_dog_detector.py`로 반려견 존재를 확인하는 보조 객체 탐지 모델을 학습합니다. 견종 라벨은 산책/급여 행동 라벨이 아니므로 행동 판별로 오해하지 않습니다. |
| `Dataset/TheOxford-IIIT_Pet_Dataset` | 7,390장, 고양이/개 종·품종 라벨, 머리 박스·분할 정보 | 개/고양이 구분 연구 데이터입니다. 원본 웹사이트 이미지의 이용 조건을 확인해야 하며, 행동 레이블이 없어 행동 분류 학습에는 자동 편입하지 않습니다. |
| `Dataset/AP-10K-main` | 동물 키포인트 추정 코드·설정과 일부 자료. README는 AP-10K 10,015장/동물 17개 키포인트를 설명하며 데이터셋 사용은 비상업적 조건을 명시합니다. | 동물 자세/키포인트 연구 자료입니다. 걷기·급여 행동 레이블은 없으며 폴더에는 공식 `data/ap10k` 학습 이미지 번들이 없습니다. 현재 액션 모델 학습에는 사용하지 않습니다. |
| `Dataset/dataset-main` | Open Images V3 도구, 설명 및 일부 메타데이터. README의 원본 이미지 라이선스 안내는 이미지별 검증을 요구합니다. | 현재 폴더에 행동별 이미지 레이블 데이터셋 자체가 없어 자동 학습하지 않습니다. |

MPDD에는 견종 이미지와 식별 ID가 있지만 pose/keypoint 또는 산책 행동 정답 라벨이 없습니다. 요청에 맞춰 identity가 겹치지 않는 약한 walk 후보 이미지를 준비했지만, 이 약한 라벨이 실제 산책 동작을 보장하지 않으며 별도 수동 검수가 필요합니다. 급여 및 비산책 `other` 정답 이미지는 현재 없으므로 세 클래스 활동 분류기는 별도 데이터 수집 후에야 학습할 수 있습니다. 활동 모델이 준비되기 전 인증 API는 `503`으로 fail-closed 동작을 하고 UI도 포인트를 지급하지 않습니다.

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
- `GET/POST/DELETE /api/health/records`: 계정별 건강 기록.
- `POST /api/verify/walk`, `POST /api/verify/feeding`: 로그인 사용자 사진 인증. 사진 BLOB, 판정 결과와 활동 로그가 SQLite에 기록됩니다. 인증 성공 포인트 지급과 원장은 한 DB 트랜잭션으로 처리됩니다.
- `POST /api/uploads?purpose=community`, `GET /api/images/{id}`: 로그인한 사용자의 사진을 SQLite BLOB으로 저장/조회. 커뮤니티 게시글에 첨부된 사진은 로그인 사용자에게 공개되며, 인증/건강 용도 사진은 업로드한 계정만 읽을 수 있습니다.
- `GET/POST /api/community/posts`, `POST /api/community/posts/{id}/like`, `GET/POST /api/community/posts/{id}/comments`: 글·좋아요·댓글을 저장합니다.
- `POST /api/shop/redeem`, `GET /api/shop/redemptions`: 서버 카탈로그를 기준으로 포인트 차감과 교환 원장을 저장합니다. 클라이언트가 제출한 가격은 사용하지 않습니다.

프런트엔드에는 bearer token만 `localStorage`에 저장합니다. 포인트, 프로필, 활동·건강 로그, 커뮤니티 글/사진 등 업무 데이터는 API로 저장합니다. 로그인 전 계정이 필요한 화면은 `account.html`로 보냅니다. 신규 계정은 기본 0P로 시작하고, 기존 브라우저 localStorage 포인트/프로필은 클라이언트가 조작할 수 있어 자동 이관하지 않습니다. 현재 영수증 OCR은 데모라 포인트를 지급하지 않으며, 인증 모델이 없어 판별이 `503`인 사진도 보상 없이 거절됩니다.

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

완료되면 `backend/models/activity_classifier.pt`가 생성됩니다. 서버를 재시작한 후 `http://127.0.0.1:8000/health`에서 `ready: true`인지 확인합니다.

## 서버/API

```powershell
.venv-backend\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

- `GET /health`: 모델 준비 상태
- `POST /api/verify/walk`: multipart/form-data의 `photo`로 산책 사진 판별
- `POST /api/verify/feeding`: multipart/form-data의 `photo`로 급여 사진 판별

활동 점수와 클래스 간 여유 폭이 환경 변수 기준을 모두 넘고, 견종 탐지기가 설치되어 있으면 개도 탐지되어야 인증됩니다. 점수 기준은 `HELLOPUPPY_ACTIVITY_THRESHOLD`(기본 0.70), 간격은 `HELLOPUPPY_ACTIVITY_MARGIN`(기본 0.15)입니다. 모델 점수는 검증된 정확도 보장이 아니므로 부정 사용 방지의 단독 근거로 삼지 마세요. API는 업로드 사진을 디스크에 저장하지 않습니다.

프런트엔드는 기본적으로 `http://127.0.0.1:8000`에 요청합니다. 다른 호스트/배포 환경에서는 HTML에서 `window.HELLOPUPPY_API_BASE`를 API 주소로 설정해야 합니다. 현재 인증 요청은 브라우저 카메라/파일 선택 사진을 실제로 서버에 보내며, 성공 응답을 받은 경우에만 시연용 브라우저 포인트를 올립니다. 서버 응답이 거절/미준비/오류인 경우 포인트는 적립하지 않습니다.

## 배포 전 필수 보완

이 코드는 로컬 개발용 시작점입니다. 사진 분류만으로 촬영 시점/위치/실제 행위를 증명할 수 없고, 브라우저의 bearer token은 XSS 등에 노출될 수 있습니다. 상용 공개 전에 HTTPS, 짧은 세션·토큰 보호, 요청 제한, 업로드 보관·삭제 정책, 엄격한 CORS, 정기 백업, 별도 보안/정확도 검증을 수행하세요. 임계값은 학습된 별도 검증 세트에서 보정해야 하며 모델의 신뢰도 수치 자체를 정확도라고 해석하면 안 됩니다.

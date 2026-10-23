# HelloPuppy · 안녕멍뭉

반려견과 보호자를 위한 산책·급여 인증, 커뮤니티, 동물병원 방문용 건강 요약 프로젝트입니다.

## 폴더 구조

```text
HelloPuppy/
├── frontend/                 # 정적 웹 프런트엔드
│   ├── index.html             # 홈 진입점
│   ├── auth.html              # 산책 인증
│   ├── feeding.html           # 급여 인증
│   ├── health.html            # 동물병원 건강 요약
│   └── assets/                # CSS, JavaScript, 이미지
├── backend/                  # FastAPI 사진 판별 API와 모델 학습 코드
├── Dataset/                  # 제공 데이터셋 및 직접 준비할 활동 사진
├── design/                   # 앱 원본 로고·화면 기획 이미지
├── docs/archive/             # 이전 중복 프로젝트 메타데이터 보관
├── LICENSE
└── README.md
```

## 프런트엔드 실행

먼저 아래 백엔드 서버를 실행한 뒤 VS Code Live Server 같은 정적 웹 서버를 `frontend/` 폴더에 실행합니다. `index.html`에서 시작하고 `mypage.html` 또는 `account.html`에서 계정을 생성/로그인합니다. 페이지 및 정적 자산 경로는 `frontend/` 기준 상대 경로입니다.

## 백엔드 실행

Python 환경 구성, SQLite 데이터 저장, 계정 API, 활동 분류 학습 및 백엔드 실행 방법은 [backend/README.md](backend/README.md)를 참고하세요. 백엔드 명령은 저장소 루트에서 실행합니다. 기본 DB는 `backend/data/hellopuppy.sqlite3`에 생성됩니다.

## 프로젝트 정보

캡스톤 디자인 프로젝트 · 20221378 지승오 · 20242446 김보금

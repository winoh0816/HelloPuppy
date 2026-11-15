# Dataset

용도별로 나눠 둡니다. 외부에서 받은 원본은 `public/`에 그대로 두고 고치지 않습니다. 학습·평가용으로 가공한 데이터는 기능별 폴더(`activity*`, `receipt/`)에 둡니다.

```
Dataset/
├── public/                    # 외부 공개 데이터셋 원본 (수정하지 않음)
│   ├── AP-10K/                #   동물 키포인트 코드·설정 (비상업 조건)
│   ├── DogBreeds-yolov8/      #   견종 100종 YOLO 박스 9,951장 (Roboflow, CC BY 4.0) → train_dog_detector.py
│   ├── MPDD/                  #   반려견 identity 이미지 → tools/prepare_mpdd_walk.py
│   ├── OpenImages-tools/      #   Open Images 도구·메타데이터 (이미지 없음)
│   └── Oxford-IIIT-Pet/       #   개·고양이 품종 7,390장 → tools/evaluate_verifier.py
├── activity/                  # 산책·급여 인증: 학습 사진 train/val/test/{walk,feeding,other}
├── activity_eval/             # 산책·급여 인증: COCO 실장면 평가 세트와 캐시 (git 제외)
└── receipt/                   # 영수증 OCR
    ├── team_photos/           #   팀이 모은 영수증 사진 원본 308장
    ├── external_raw/          #   KORIE·HumynLabs 원본 다운로드 zip (git 제외, 약 1.8GB)
    └── ocrReceipt1000/        #   통합 평가 데이터셋 1,000장 → tools/build_receipt_dataset.py, evaluate_receipt_ocr.py
```

| 폴더 | 크기 | git |
|---|---:|---|
| `public/Oxford-IIIT-Pet` | 815MB | 추적 |
| `public/DogBreeds-yolov8` | 276MB | 추적 |
| `public/MPDD` | 33MB | 추적 |
| `public/AP-10K` | 24MB | 추적 |
| `public/OpenImages-tools` | 3.5MB | 추적 |
| `activity` | 19MB | README·manifest만 |
| `activity_eval` | 290MB | 제외 |
| `receipt/team_photos` | 8MB | 제외 |
| `receipt/external_raw` | 1.8GB | 제외 |
| `receipt/ocrReceipt1000` | 281MB | README·manifest·manual_labels만 |

각 데이터셋의 출처·라이선스·사용 방법은 [backend/README.md](../backend/README.md)와 폴더별 README에 있습니다.

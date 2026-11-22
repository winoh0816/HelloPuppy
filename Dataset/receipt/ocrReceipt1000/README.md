# ocrReceipt1000: 한국 영수증 OCR 평가 데이터셋 (1,000장)

영수증 리워드 OCR(`backend/receipt.py`)을 실제 영수증 사진으로 측정하고 개선하려고 만든 데이터셋입니다.
이미지(`images/`, 약 280MB)는 git에 올리지 않습니다. 아래 순서로 다시 만들 수 있습니다.
`manifest.csv`와 `manual_labels.csv`만 저장소에 들어 있습니다.

## 구성

| 출처 | 장수 | 정답 라벨 | 라이선스 |
|---|---:|---|---|
| `own`: `Dataset/receipt/team_photos` (팀 수집) | 304 | 무작위 54장을 사람이 직접 라벨링 (`manual_labels.csv`) | 팀 수집 |
| `korie`: [KORIE](https://github.com/MahmoudSalah/KORIE) 한국 소매 영수증 벤치마크 | 676 | 674장: 합계, 거래일, 거래시각, 가맹점명 (KORIE OCR 전사) | 아래 주의 참고 |
| `humynlabs`: [HumynLabs/Korean_Receipts_Dataset](https://huggingface.co/datasets/HumynLabs/Korean_Receipts_Dataset) | 20 | 없음 | CC BY 4.0 |

- `own`: 원래 `ocrTest/`에 있던 616개 파일 중 308개는 바이트 단위로 같은 복사본이라 지웠고(2026-11 정리), 남은 308개(`team_photos/`) 중 4개도 서로 중복이라 **고유 이미지는 304장**입니다.
  그중 10장은 일본, 대만, 태국, 스페인 영수증이라 `split=foreign`으로 따로 표시했습니다. 한국어 정확도 계산에서는 빼고, 데이터셋에는 남겨 둡니다.
- `korie`: 774장 중 정답이 있는 674장을 모두 넣고, 1,000장을 채우려고 정답 없는 2장을 더했습니다. 원래 분할(train 408 / val 135 / test 131)을 그대로 씁니다.
  **파서 규칙은 train으로만 만들고, val, test는 최종 확인에만 썼습니다.**
- 모든 이미지는 JPEG로 다시 저장했습니다. EXIF 회전을 적용하고, 긴 변은 최대 2000px로 줄이고, 메타데이터는 모두 지웠습니다.
  HumynLabs 사진의 iPhone EXIF에는 GPS 정보가 들어 있었습니다.

## manifest.csv 열

`id, file, source, split(train|val|test|manual|foreign|unlabeled), gt_total(원), gt_date(YYYY-MM-DD), gt_time(HH:MM), gt_store, width, height, license, original, sha256, raw_labels(KORIE 원문 JSON)`

## 다시 만들기

```bash
# 1) 원본 받기 (Dataset/receipt/external_raw/, git 제외, 약 1.8GB)
cd Dataset/receipt/external_raw
mkdir -p korie_train korie_val korie_test korie_ocr korie_items humynlabs
gd(){ curl -sL -o "$2" "https://drive.usercontent.google.com/download?id=$1&export=download&confirm=t"; }
gd 1M3C_xG8Vg47DIbPP2fYpXs6mv5t6YOVq korie_train/train.zip
gd 15wXqZUzWaYEJu-rWZwCPuMvHFMZgWQOD korie_val/val.zip
gd 1UJZIcTX38FnMa8PZHYj--5OJ8-deSMRI korie_test/test.zip
gd 1I4BzOqKgF7zbNPlNeood4f7g8pi2xh26 korie_ocr/ocr_train.zip
gd 1v_0iGpBjB5WdWOeKI4C903eeqkRBjTsM korie_ocr/ocr_val.zip
gd 1GtEzSUA2wTNfOujO67-JEZ_PLpJOdBhg korie_ocr/ocr_test.zip
# 품목 정답 (CSV, 품목 추출 평가용)
gd 1W6XYnRtsQ2E8UZlo-MGwxQ0SkByTsdQV korie_items/items_train.csv
gd 1ff3z44tfhkeba-CvKv7fQp7EliFQ8EGu korie_items/items_val.csv
gd 107ckPQ59gda7172Ls_iiEg5JomWhLtVA korie_items/items_test.csv
for i in $(seq 1 20); do curl -sL -o humynlabs/kgen_$i.jpeg \
  "https://huggingface.co/datasets/HumynLabs/Korean_Receipts_Dataset/resolve/main/Kgen_Korean%20Receipts_1005_$i.JPEG"; done
cd ../../..
# 2) 통합 (manual_labels.csv 를 읽어 반영)
python -m backend.tools.build_receipt_dataset --target 1000
# 3) 평가
python -m backend.tools.evaluate_receipt_ocr --split test
```

## 라벨 기준

- KORIE `TransactionTime`은 영수증 아래쪽 카드 승인 시각(판매 시각보다 1~2분 뒤)인 경우가 많습니다. 그래서 평가에 `time5`(±5분 일치) 지표를 함께 둡니다.
- KORIE `Total`은 할인 전 금액인 경우가 있습니다(예: IMG00020은 88,700 정답에 실제 결제 44,350). 라벨 오류로 보이는 것도 있습니다(IMG00082는 영수증에 176,000원이 찍혀 있는데 정답은 17,600).
  이런 라벨은 고치지 않고 원본 그대로 둡니다.
- `manual_labels.csv`: 축소된 사진을 사람이 눈으로 읽어 단 라벨입니다. 확실히 읽히는 값만 적었고, 읽을 수 없는 6장은 뺐습니다.
  합계는 최종 결제 대상 금액입니다(할인 후, 쿠폰 포함).

## 라이선스와 출처 표기

- **HumynLabs/Korean_Receipts_Dataset**: CC BY 4.0. 출처: HumynLabs (KGeN), Hugging Face.
- **KORIE**: 저장소에 LICENSE 파일이 없고 README에도 라이선스가 적혀 있지 않습니다(2026-11 확인). 논문은 MDPI *Mathematics* 14(1):187에 실렸습니다.
  연구용 공개 벤치마크로 배포되지만 이용 조건은 확인되지 않았으므로 **재배포(이미지를 저장소, 서비스에 올리는 것)는 하지 말고**, 평가, 연구용으로만 내부에서 쓰세요.
  상업적으로 쓰려면 저자에게 먼저 확인해야 합니다.
- **own**: 웹에서 모은 사진으로 보이며(블로그 워터마크 포함), 원 게시자의 권리가 있을 수 있습니다. 평가용으로만 쓰세요.

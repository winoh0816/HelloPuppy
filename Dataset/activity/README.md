# 산책·급여 행동 분류용 사진

기존 제공 데이터셋은 견종, 동물 자세, 개/고양이 종, 일반 객체를 주로 라벨링하며 산책/급여 행동을 직접 라벨링하지 않습니다. MPDD는 아래 절차로 약한 산책 후보로만 활용하고, 나머지 데이터를 임의로 walk/feeding 정답으로 오분류하지 마세요.

## MPDD 사용 안내

`Dataset/MPDD/pytorch`는 `train`, `val`, `query`, `gallery` 이미지 폴더로 구성되어 있습니다. 확인한 이미지 파일명에는 숫자 identity와 카메라/시퀀스 유사 토큰이 있지만 별도의 keypoint/pose annotation이나 walk-action label 파일은 없습니다. 따라서 MPDD는 정식 pose/keypoint 정답 데이터로 볼 수 없습니다. 프로젝트 요청에 따라 `train`+`val` 이미지 1,032장을 **약한 walk 후보**로 준비했으며, 실제 산책 장면인지 사람이 검수한 뒤에만 학습 정답으로 취급하세요.

`backend/tools/prepare_mpdd_walk.py`는 같은 identity가 학습과 검증에 동시에 들어가지 않도록 기존 train/val을 합쳐 identity 단위로 다시 나눕니다. 현재 생성 결과는 학습 819장(76 identities), 검증 213장(19 identities)입니다. 출처와 약한 라벨임은 `mpdd_walk_manifest.csv`에 남깁니다. 이 검증 분리는 개 identity 누수를 줄일 뿐 실제 walk-action 정답 라벨을 보증하지 않습니다.

```powershell
.venv-backend\Scripts\python.exe backend\tools\prepare_mpdd_walk.py --assume-walk-labels
```

이 명령은 MPDD train/val 이미지를 `train/walk`, `val/walk`에 복사합니다. `--assume-walk-labels`는 원본에 행동 라벨이 없다는 점을 알고 약한 walk 양성 라벨로 쓰겠다는 명시적 선택입니다. MPDD 라이선스는 현재 폴더에서 확인되지 않았으므로 원본 출처의 사용 조건을 확인하고 이미지 원본을 공개 저장소에 올리지 마세요.

실제 인증용으로 별도 권한을 확보하고 사람이 검수한 촬영 사진을 다음 디렉터리에 분류해 넣습니다. `feeding` 및 `other` 예시는 별도로 수집해야 합니다.

- `train/walk`, `val/walk`: 산책 중인 반려견이 보이는 사진
- `train/feeding`, `val/feeding`: 반려견에게 사료를 주거나 사료를 먹는 장면이 보이는 사진
- `train/other`, `val/other`: 관련 없는 사진, 활동이 모호한 사진, 다른 동물/물체 사진

학습/검증은 서로 다른 촬영 세션으로 나누고, 같은 연속 촬영 장면을 양쪽에 섞지 않습니다. MPDD 후보도 산책 장면인지 확인해 오분류 이미지를 제외하세요. 얼굴·위치 같은 민감정보, 사진 출처 및 동의 조건을 확인하고 공개 전 별도 테스트 데이터에서 오탐률을 확인해야 합니다.

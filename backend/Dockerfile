# HelloPuppy API (FastAPI + AI 판별, CPU). 빌드는 저장소 루트에서: docker compose build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # 사진과 내려받는 모델은 볼륨에 둔다. DB 주소(HELLOPUPPY_DATABASE_URL)는 docker-compose.yml 에서 넘긴다.
    HELLOPUPPY_MEDIA_DIR=/data/media \
    HELLOPUPPY_MODEL_DIR=/models \
    HELLOPUPPY_OCR_MODEL_DIR=/models/ocr \
    # 학습해 둔 산책 판정 모델은 이미지에 포함된 것을 쓴다
    HELLOPUPPY_WALK_MODEL=/app/backend/models/walk_model.json \
    YOLO_CONFIG_DIR=/tmp/ultralytics

# OpenCV(ultralytics·rapidocr)가 쓰는 시스템 라이브러리
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements*.txt backend/
# GPU 없는 서버용 CPU 빌드 torch (CUDA 빌드보다 수 GB 작다)
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r backend/requirements-detection.txt

COPY backend/ backend/
RUN useradd --create-home --uid 1000 app && mkdir -p /data /models && chown app:app /data /models
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
# 모델을 프로세스마다 올리므로 워커는 1개. 리버스 프록시(nginx) 뒤에서 X-Forwarded-For 를 믿는다.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

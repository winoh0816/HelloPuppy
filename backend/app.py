"""Authenticated HelloPuppy API backed by SQLite."""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .database import db_connection, init_db, transaction

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(os.getenv("HELLOPUPPY_MODEL_DIR", Path(__file__).parent / "models"))
ACTIVITY_MODEL_PATH = MODEL_DIR / "activity_classifier.pt"
DOG_MODEL_PATH = MODEL_DIR / "dog_detector.pt"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
ACTIVITY_LABELS = {"walk": "산책", "feeding": "급여"}
STARTING_POINTS = int(os.getenv("HELLOPUPPY_STARTING_POINTS", "0"))
TOKEN_TTL_DAYS = int(os.getenv("HELLOPUPPY_TOKEN_TTL_DAYS", "30"))
PBKDF2_ITERATIONS = 310_000

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="HelloPuppy SQLite API", version="2.0.0", lifespan=lifespan)
_frontend_origin = os.getenv("HELLOPUPPY_FRONTEND_ORIGIN", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _frontend_origin.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"]
)

_activity_model: Any = None
_activity_transform: Any = None
_activity_classes: list[str] = []
_dog_model: Any = None
_dog_model_loaded = False
_runtime_error: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt, PBKDF2_ITERATIONS)
    return actual_salt, digest


def create_session(db: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = (utc_now() + timedelta(days=TOKEN_TTL_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (token_hash, user_id, expires_at))
    return token


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token = authorization[7:]
    if len(token) < 40 or len(token) > 256:
        raise HTTPException(status_code=401, detail="로그인 토큰이 올바르지 않습니다.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db_connection() as db:
        user = db.execute("""SELECT u.id,u.email,u.display_name,u.created_at,s.token_hash
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>?""", (token_hash, utc_iso())).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="로그인 토큰이 만료되었거나 로그아웃되었습니다.")
    return dict(user)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class PetProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(default="", max_length=80)
    breed: str = Field(default="", max_length=120)
    birth_date: str = Field(default="", max_length=10)
    sex: str = Field(default="", max_length=20)
    weight_kg: float | None = Field(default=None, ge=0, le=150)
    neutered: str = Field(default="unknown", max_length=20)
    guardian_name: str = Field(default="", max_length=80)
    guardian_phone: str = Field(default="", max_length=40)
    microchip_id: str = Field(default="", max_length=80)
    allergies: str = Field(default="", max_length=4000)
    medical_notes: str = Field(default="", max_length=6000)


class FoodProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    food_name: str = Field(default="", max_length=160)
    meals_per_day: int | None = Field(default=None, ge=1, le=12)
    feeding_schedule: str = Field(default="", max_length=200)
    food_notes: str = Field(default="", max_length=1000)


class HealthRecordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    record_type: str = Field(min_length=1, max_length=40)
    record_date: str = Field(min_length=10, max_length=10)
    clinic: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=6000)


class CommunityPostRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    category: str = Field(default="daily", max_length=40)
    title: str = Field(default="", max_length=160)
    body: str = Field(min_length=1, max_length=10000)
    image_id: int | None = Field(default=None, ge=1)


class ProductRedeemRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)


class CommentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)


def _load_runtime() -> None:
    global _activity_model, _activity_transform, _activity_classes
    global _dog_model, _dog_model_loaded, _runtime_error
    if _activity_model is not None or _runtime_error is not None:
        return
    if not ACTIVITY_MODEL_PATH.is_file():
        _runtime_error = "활동 분류 모델이 아직 학습되지 않았습니다."
        return
    try:
        import torch
        from torchvision import transforms
        from .model import IMAGE_SIZE, create_activity_model

        checkpoint = torch.load(ACTIVITY_MODEL_PATH, map_location="cpu", weights_only=True)
        classes = checkpoint.get("classes")
        if not isinstance(classes, list) or set(classes) != {"walk", "feeding", "other"}:
            raise ValueError("모델의 클래스 정보가 올바르지 않습니다.")
        model = create_activity_model(num_classes=len(classes))
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        _activity_model = model
        _activity_classes = classes
        _activity_transform = transforms.Compose([
            transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
        ])
    except Exception as error:
        _runtime_error = f"모델 로딩 실패: {error}"
        return
    if DOG_MODEL_PATH.is_file():
        try:
            from ultralytics import YOLO
            _dog_model = YOLO(str(DOG_MODEL_PATH))
            _dog_model_loaded = True
        except Exception:
            _dog_model = None
            _dog_model_loaded = False


def _decode_image(data: bytes) -> tuple[Image.Image, str]:
    if not data:
        raise HTTPException(status_code=400, detail="사진 파일이 비어 있습니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="사진은 12MB 이하로 올려 주세요.")
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in ALLOWED_FORMATS:
            raise HTTPException(status_code=415, detail="JPEG, PNG, WEBP 사진만 지원합니다.")
        if image.width < 64 or image.height < 64 or image.width * image.height > 30_000_000:
            raise HTTPException(status_code=400, detail="사진 크기가 지원 범위를 벗어났습니다.")
        mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[image.format]
        image.verify()
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        return image, mime
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="올바른 이미지 파일이 아닙니다.") from error


def _store_image(db: sqlite3.Connection, user_id: int, purpose: str, filename: str, mime: str, data: bytes) -> int:
    cursor = db.execute(
        "INSERT INTO images(user_id,purpose,mime_type,original_name,image_data) VALUES(?,?,?,?,?)",
        (user_id, purpose, mime, Path(filename).name[:255], data)
    )
    return int(cursor.lastrowid)


def _award_points(db: sqlite3.Connection, user_id: int, delta: int, reason: str, reference: str) -> int:
    account = db.execute("SELECT balance FROM points_accounts WHERE user_id=?", (user_id,)).fetchone()
    if account is None:
        raise HTTPException(status_code=404, detail="포인트 계정을 찾을 수 없습니다.")
    new_balance = int(account["balance"]) + delta
    if new_balance < 0:
        raise HTTPException(status_code=409, detail="포인트가 부족합니다.")
    db.execute(
        "UPDATE points_accounts SET balance=?, updated_at=? WHERE user_id=?",
        (new_balance, utc_iso(), user_id)
    )
    db.execute(
        "INSERT INTO points_ledger(user_id,delta,balance_after,reason,reference) VALUES(?,?,?,?,?)",
        (user_id, delta, new_balance, reason, reference)
    )
    return new_balance


@app.get("/health")
def health() -> dict[str, Any]:
    _load_runtime()
    with db_connection() as db:
        db.execute("SELECT 1")
    return {
        "status": "ok",
        "database": "sqlite",
        "database_path": str(Path(os.getenv("HELLOPUPPY_DB_PATH", Path(__file__).parent / "data" / "hellopuppy.sqlite3")).resolve()),
        "ready": _activity_model is not None,
        "activity_model": ACTIVITY_MODEL_PATH.is_file(),
        "dog_detector": _dog_model_loaded,
        "message": _runtime_error
    }


@app.post("/api/auth/register")
def register(request: RegisterRequest) -> dict[str, Any]:
    email = request.email.lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="올바른 이메일 주소를 입력하세요.")
    salt, digest = hash_password(request.password)
    try:
        with transaction() as db:
            cursor = db.execute(
                "INSERT INTO users(email,display_name,password_salt,password_hash) VALUES(?,?,?,?)",
                (email, request.display_name, salt, digest)
            )
            user_id = int(cursor.lastrowid)
            db.execute("INSERT INTO pets(user_id) VALUES(?)", (user_id,))
            db.execute("INSERT INTO points_accounts(user_id,balance) VALUES(?,?)", (user_id, STARTING_POINTS))
            if STARTING_POINTS:
                db.execute(
                    "INSERT INTO points_ledger(user_id,delta,balance_after,reason,reference) VALUES(?,?,?,?,?)",
                    (user_id, STARTING_POINTS, STARTING_POINTS, "신규 가입 기본 포인트", f"signup:{user_id}")
                )
            access_token = create_session(db, user_id)
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (user_id, "register", "user", user_id))
            user = db.execute("SELECT id,email,display_name,created_at FROM users WHERE id=?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as error:
        if "users.email" in str(error).lower() or "unique" in str(error).lower():
            raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다.") from error
        raise
    return {"access_token": access_token, "token_type": "bearer", "user": dict(user), "points": STARTING_POINTS}


@app.post("/api/auth/login")
def login(request: LoginRequest) -> dict[str, Any]:
    with db_connection() as db:
        user = db.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (request.email.lower(),)).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    _, supplied = hash_password(request.password, bytes(user["password_salt"]))
    if not hmac.compare_digest(supplied, bytes(user["password_hash"])):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    public_user = {key: user[key] for key in ("id", "email", "display_name", "created_at")}
    with transaction() as db:
        access_token = create_session(db, int(user["id"]))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (user["id"], "login", "user", user["id"]))
    return {"access_token": access_token, "token_type": "bearer", "user": public_user}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        points = db.execute("SELECT balance FROM points_accounts WHERE user_id=?", (user["id"],)).fetchone()
    public_user = {key: user[key] for key in ("id", "email", "display_name", "created_at")}
    return {"user": public_user, "points": int(points["balance"]) if points else 0}


@app.post("/api/auth/logout")
def logout(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, bool]:
    with transaction() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (user["id"], "logout", "user", user["id"]))
    return {"logged_out": True}


@app.get("/api/points")
def get_points(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, int]:
    with db_connection() as db:
        row = db.execute("SELECT balance FROM points_accounts WHERE user_id=?", (user["id"],)).fetchone()
    return {"balance": int(row["balance"]) if row else 0}


@app.get("/api/points/ledger")
def get_points_ledger(limit: int = 100, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 300))
    with db_connection() as db:
        rows = db.execute(
            "SELECT id,delta,balance_after,reason,reference,created_at FROM points_ledger WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user["id"], safe_limit)
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/pet/profile")
def get_pet_profile(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        row = db.execute("SELECT * FROM pets WHERE user_id=?", (user["id"],)).fetchone()
    return {"profile": dict(row) if row else None}


@app.put("/api/pet/profile")
def save_pet_profile(request: PetProfileRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if request.birth_date:
        try:
            date.fromisoformat(request.birth_date)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="생년월일은 YYYY-MM-DD 형식이어야 합니다.") from error
    data = request.model_dump()
    if data["sex"] not in {"", "female", "male", "unknown"}:
        raise HTTPException(status_code=422, detail="성별 값이 올바르지 않습니다.")
    if data["neutered"] not in {"yes", "no", "unknown"}:
        raise HTTPException(status_code=422, detail="중성화 값이 올바르지 않습니다.")
    with transaction() as db:
        db.execute("""UPDATE pets SET name=?,breed=?,birth_date=?,sex=?,weight_kg=?,neutered=?,guardian_name=?,guardian_phone=?,microchip_id=?,allergies=?,medical_notes=?,updated_at=? WHERE user_id=?""",
                   (data["name"], data["breed"], data["birth_date"], data["sex"], data["weight_kg"], data["neutered"], data["guardian_name"], data["guardian_phone"], data["microchip_id"], data["allergies"], data["medical_notes"], utc_iso(), user["id"]))
        row = db.execute("SELECT * FROM pets WHERE user_id=?", (user["id"],)).fetchone()
    return {"profile": dict(row)}


@app.get("/api/pet/food")
def get_food(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        row = db.execute("SELECT f.* FROM food_profiles f JOIN pets p ON p.id=f.pet_id WHERE p.user_id=?", (user["id"],)).fetchone()
    return {"food": dict(row) if row else None}


@app.put("/api/pet/food")
def save_food(request: FoodProfileRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with transaction() as db:
        pet = db.execute("SELECT id FROM pets WHERE user_id=?", (user["id"],)).fetchone()
        db.execute("""INSERT INTO food_profiles(pet_id,food_name,meals_per_day,feeding_schedule,food_notes,updated_at) VALUES(?,?,?,?,?,?)
            ON CONFLICT(pet_id) DO UPDATE SET food_name=excluded.food_name,meals_per_day=excluded.meals_per_day,feeding_schedule=excluded.feeding_schedule,food_notes=excluded.food_notes,updated_at=excluded.updated_at""",
            (pet["id"], request.food_name, request.meals_per_day, request.feeding_schedule, request.food_notes, utc_iso()))
        row = db.execute("SELECT * FROM food_profiles WHERE pet_id=?", (pet["id"],)).fetchone()
    return {"food": dict(row)}


@app.get("/api/health/records")
def list_health_records(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        rows = db.execute("SELECT * FROM health_records WHERE user_id=? ORDER BY record_date DESC,id DESC", (user["id"],)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/health/records")
def create_health_record(request: HealthRecordRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    try:
        date.fromisoformat(request.record_date)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="날짜는 YYYY-MM-DD 형식이어야 합니다.") from error
    with transaction() as db:
        pet = db.execute("SELECT id FROM pets WHERE user_id=?", (user["id"],)).fetchone()
        cursor = db.execute("INSERT INTO health_records(user_id,pet_id,record_type,record_date,clinic,title,notes) VALUES(?,?,?,?,?,?,?)",
                            (user["id"], pet["id"], request.record_type, request.record_date, request.clinic, request.title, request.notes))
        row = db.execute("SELECT * FROM health_records WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {"record": dict(row)}


@app.delete("/api/health/records/{record_id}")
def delete_health_record(record_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, bool]:
    with transaction() as db:
        cursor = db.execute("DELETE FROM health_records WHERE id=? AND user_id=?", (record_id, user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="건강 기록을 찾을 수 없습니다.")
    return {"deleted": True}


@app.post("/api/uploads")
async def upload_image(purpose: str, photo: UploadFile = File(...), user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if purpose not in {"community", "health"}:
        raise HTTPException(status_code=422, detail="지원하지 않는 이미지 용도입니다.")
    data = await photo.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="사진은 12MB 이하로 올려 주세요.")
    _, mime = _decode_image(data)
    with transaction() as db:
        image_id = _store_image(db, int(user["id"]), purpose, photo.filename or "upload", mime, data)
    return {"image_id": image_id, "purpose": purpose}


@app.get("/api/images/{image_id}")
def get_image(image_id: int, user: dict[str, Any] = Depends(get_current_user)) -> Any:
    from fastapi.responses import Response
    with db_connection() as db:
        row = db.execute("""SELECT i.mime_type,i.image_data FROM images i
            WHERE i.id=? AND (i.user_id=? OR EXISTS(SELECT 1 FROM community_posts p WHERE p.image_id=i.id))""",
                         (image_id, user["id"])).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    return Response(content=bytes(row["image_data"]), media_type=row["mime_type"], headers={"Cache-Control": "private, no-store"})


@app.get("/api/community/posts")
def list_posts(limit: int = 50, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    with db_connection() as db:
        rows = db.execute("""SELECT p.id,p.user_id,p.pet_id,p.category,p.title,p.body,p.image_id,p.created_at,u.display_name,
            (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
            EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked
            FROM community_posts p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT ?""", (user["id"], safe_limit)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/community/posts")
def create_post(request: CommunityPostRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if request.image_id is not None:
        with db_connection() as db:
            image = db.execute("SELECT id FROM images WHERE id=? AND user_id=? AND purpose='community'", (request.image_id, user["id"])).fetchone()
        if image is None:
            raise HTTPException(status_code=404, detail="업로드한 커뮤니티 사진을 찾을 수 없습니다.")
    with transaction() as db:
        pet = db.execute("SELECT id FROM pets WHERE user_id=?", (user["id"],)).fetchone()
        cursor = db.execute("INSERT INTO community_posts(user_id,pet_id,category,title,body,image_id) VALUES(?,?,?,?,?,?)",
                            (user["id"], pet["id"], request.category, request.title, request.body, request.image_id))
        row = db.execute("SELECT * FROM community_posts WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {"post": dict(row)}


@app.post("/api/community/posts/{post_id}/like")
def toggle_post_like(post_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with transaction() as db:
        post = db.execute("SELECT id FROM community_posts WHERE id=?", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
        existing = db.execute("SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?", (post_id, user["id"])).fetchone()
        if existing:
            db.execute("DELETE FROM post_likes WHERE post_id=? AND user_id=?", (post_id, user["id"]))
            liked = False
        else:
            db.execute("INSERT INTO post_likes(post_id,user_id) VALUES(?,?)", (post_id, user["id"]))
            liked = True
        count = db.execute("SELECT COUNT(*) AS count FROM post_likes WHERE post_id=?", (post_id,)).fetchone()["count"]
    return {"liked": liked, "count": int(count)}


@app.get("/api/community/posts/{post_id}/comments")
def list_post_comments(post_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        rows = db.execute("SELECT c.id,c.post_id,c.body,c.created_at,u.display_name FROM post_comments c JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.id LIMIT 300", (post_id,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/community/posts/{post_id}/comments")
def create_post_comment(post_id: int, request: CommentRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with transaction() as db:
        post = db.execute("SELECT id FROM community_posts WHERE id=?", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
        cursor = db.execute("INSERT INTO post_comments(post_id,user_id,body) VALUES(?,?,?)", (post_id, user["id"], request.body))
        row = db.execute("SELECT c.id,c.post_id,c.body,c.created_at,u.display_name FROM post_comments c JOIN users u ON u.id=c.user_id WHERE c.id=?", (cursor.lastrowid,)).fetchone()
    return {"comment": dict(row)}


@app.delete("/api/community/posts/{post_id}")
def delete_post(post_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, bool]:
    with transaction() as db:
        cursor = db.execute("DELETE FROM community_posts WHERE id=? AND user_id=?", (post_id, user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없거나 삭제 권한이 없습니다.")
    return {"deleted": True}


@app.post("/api/verify/{activity}")
async def verify_photo(activity: str, photo: UploadFile = File(...), user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if activity not in ACTIVITY_LABELS:
        raise HTTPException(status_code=404, detail="지원하지 않는 인증 종류입니다.")
    data = await photo.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="사진은 12MB 이하로 올려 주세요.")
    image, mime = _decode_image(data)
    _load_runtime()
    if _activity_model is None or _activity_transform is None:
        with transaction() as db:
            image_id = _store_image(db, int(user["id"]), f"verification_{activity}", photo.filename or "photo", mime, data)
            db.execute("""INSERT INTO activity_logs(user_id,pet_id,activity,status,predicted,image_id)
                SELECT ?,id,?,'unavailable','',? FROM pets WHERE user_id=?""",
                (user["id"], activity, image_id, user["id"]))
        raise HTTPException(status_code=503, detail=_runtime_error or "사진 판별 모델을 사용할 수 없습니다.")

    import torch
    tensor = _activity_transform(image).unsqueeze(0)
    with torch.inference_mode():
        probabilities = torch.softmax(_activity_model(tensor)[0], dim=0)
    scores = {label: float(probabilities[index].item()) for index, label in enumerate(_activity_classes)}
    predicted = max(scores, key=scores.get)
    expected_score = scores[activity]
    margin = expected_score - max(score for label, score in scores.items() if label != activity)
    threshold = float(os.getenv("HELLOPUPPY_ACTIVITY_THRESHOLD", "0.70"))
    min_margin = float(os.getenv("HELLOPUPPY_ACTIVITY_MARGIN", "0.15"))

    dog_detected: bool | None = None
    dog_confidence: float | None = None
    if _dog_model_loaded and _dog_model is not None:
        results = _dog_model.predict(source=image, verbose=False, conf=0.25)
        dog_confidence = max((float(box.conf.item()) for box in results[0].boxes), default=0.0)
        dog_detected = dog_confidence >= 0.25
    verified = predicted == activity and expected_score >= threshold and margin >= min_margin and dog_detected is not False

    with transaction() as db:
        image_id = _store_image(db, int(user["id"]), f"verification_{activity}", photo.filename or "photo", mime, data)
        cursor = db.execute("""INSERT INTO activity_logs(user_id,pet_id,activity,status,predicted,confidence,margin,image_id)
            SELECT ?,id,?,?,?,?,?,? FROM pets WHERE user_id=?""",
            (user["id"], activity, "verified" if verified else "rejected", predicted, expected_score, margin, image_id, user["id"]))
        if verified:
            points = 100 if activity == "walk" else 50
            balance = _award_points(db, int(user["id"]), points, f"{ACTIVITY_LABELS[activity]} 인증", f"activity:{cursor.lastrowid}")
        else:
            balance = None

    return {
        "verified": verified, "activity": activity, "activity_label": ACTIVITY_LABELS[activity],
        "predicted": predicted, "confidence": round(expected_score, 4), "margin": round(margin, 4),
        "dog_detected": dog_detected, "dog_confidence": round(dog_confidence, 4) if dog_confidence is not None else None,
        "scores": {key: round(value, 4) for key, value in scores.items()}, "points_awarded": (100 if activity == "walk" else 50) if verified else 0,
        "balance": balance, "message": "인증되었습니다." if verified else "사진에서 요청한 활동을 충분히 확인하지 못했습니다."
    }


@app.get("/api/activity/logs")
def list_activity_logs(days: int = 30, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    safe_days = max(1, min(days, 365))
    cutoff = (utc_now() - timedelta(days=safe_days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with db_connection() as db:
        rows = db.execute("SELECT id,activity,status,predicted,confidence,margin,created_at FROM activity_logs WHERE user_id=? AND created_at>=? ORDER BY id DESC",
                          (user["id"], cutoff)).fetchall()
    return {"items": [dict(row) for row in rows]}


SHOP_CATALOG = {
    "snack-001": ("조인트 덴탈 츄 샘플팩", 500, "assets/images/brand/icon-bone.png"),
    "food-001": ("프리미엄 연어 화식 100g", 1000, "assets/images/brand/emoji-drink.png"),
    "snack-002": ("수제 트릿 체험팩", 300, "assets/images/brand/emoji-best.png"),
    "food-002": ("소형견 맞춤 사료 샘플", 700, "assets/images/brand/emoji-start.png"),
    "health-001": ("반려견 영양 케어 샘플", 800, "assets/images/brand/icon-paw.png"),
    "goods-001": ("산책 배변봉투 세트", 400, "assets/images/brand/icon-bone.png"),
}


@app.post("/api/shop/redeem")
def redeem_product(request: ProductRedeemRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    product = SHOP_CATALOG.get(request.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
    product_name, cost, image_path = product
    reference = secrets.token_urlsafe(24)
    with transaction() as db:
        balance = _award_points(db, int(user["id"]), -cost, f"상품 교환: {product_name}", f"redeem:{reference}")
        cursor = db.execute("INSERT INTO shop_redemptions(user_id,product_id,product_name,image_path,cost) VALUES(?,?,?,?,?)",
                    (user["id"], request.product_id, product_name, image_path[:500], cost))
        redemption = db.execute("SELECT * FROM shop_redemptions WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {"redemption": dict(redemption), "balance": balance}


@app.get("/api/shop/redemptions")
def list_redemptions(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        rows = db.execute("SELECT * FROM shop_redemptions WHERE user_id=? ORDER BY id DESC LIMIT 200", (user["id"],)).fetchall()
    return {"items": [dict(row) for row in rows]}

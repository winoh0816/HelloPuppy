"""Authenticated HelloPuppy API backed by SQLite."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from . import verification
from .database import db_connection, init_db, transaction
from .health import (
    LIVING_ENVIRONMENTS, PROGRESSIONS, REGISTRATION_TYPES, SHARE_SCOPES, SPECIES,
    HealthValidationError, build_summary, questionnaire_row_to_dict, record_row_to_dict, to_fhir_bundle,
    validate_choice, validate_details, validate_iso_date, validate_systems,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_COMMUNITY_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
ACTIVITY_LABELS = verification.ACTIVITY_LABELS
ACTIVITY_POINTS = {"walk": 100, "feeding": 50}
# 하루 포인트 지급 횟수 (산책 1일 2회, 급여 1일 3회). 초과분도 인증 기록은 남지만 포인트는 0
DAILY_REWARD_LIMITS = {
    "walk": int(os.getenv("HELLOPUPPY_WALK_DAILY_LIMIT", "2")),
    "feeding": int(os.getenv("HELLOPUPPY_FEEDING_DAILY_LIMIT", "3")),
}
MAX_PHOTO_AGE_HOURS = int(os.getenv("HELLOPUPPY_MAX_PHOTO_AGE_HOURS", "24"))
DUPLICATE_HASH_DISTANCE = 6
STARTING_POINTS = int(os.getenv("HELLOPUPPY_STARTING_POINTS", "0"))
TOKEN_TTL_DAYS = int(os.getenv("HELLOPUPPY_TOKEN_TTL_DAYS", "30"))
PBKDF2_ITERATIONS = 310_000
MAX_SHARE_HOURS = 72

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
    allow_headers=["Authorization", "Content-Type", "X-Health-Share-Token"]
)

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


class DisplayNameRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    display_name: str = Field(min_length=1, max_length=80)


class EmailChangeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)
    current_password: str = Field(min_length=1, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


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
    species: str = Field(default="dog", max_length=20)
    birth_date_estimated: bool = False
    coat_features: str = Field(default="", max_length=300)
    registration_type: str = Field(default="", max_length=20)
    blood_type: str = Field(default="", max_length=40)
    living_environment: str = Field(default="", max_length=20)
    other_pets: str = Field(default="", max_length=300)


class FoodProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    food_name: str = Field(default="", max_length=160)
    meals_per_day: int | None = Field(default=None, ge=1, le=12)
    feeding_schedule: str = Field(default="", max_length=200)
    food_notes: str = Field(default="", max_length=1000)
    amount_per_meal: str = Field(default="", max_length=80)
    treats: str = Field(default="", max_length=500)
    supplements: str = Field(default="", max_length=500)
    diet_changed_date: str = Field(default="", max_length=10)


class HealthRecordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    record_type: str = Field(min_length=1, max_length=40)
    record_date: str = Field(min_length=10, max_length=10)
    clinic: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=6000)
    details: dict[str, Any] = Field(default_factory=dict)
    image_id: int | None = Field(default=None, ge=1)


class ClinicRecordRequest(HealthRecordRequest):
    """A record written by a veterinarian through a guardian's read_write share link."""
    author_name: str = Field(min_length=1, max_length=80)
    author_license: str = Field(default="", max_length=40)


class QuestionnaireRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    visit_date: str = Field(min_length=10, max_length=10)
    clinic: str = Field(default="", max_length=160)
    chief_complaint: str = Field(min_length=1, max_length=1000)
    onset_date: str = Field(default="", max_length=10)
    frequency: str = Field(default="", max_length=300)
    progression: str = Field(default="", max_length=20)
    home_care: str = Field(default="", max_length=1000)
    recent_changes: str = Field(default="", max_length=1000)
    concerns: str = Field(default="", max_length=1000)
    systems: dict[str, Any] = Field(default_factory=dict)
    image_id: int | None = Field(default=None, ge=1)


class HealthShareRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    clinic_name: str = Field(min_length=1, max_length=160)
    scope: str = Field(default="read", max_length=20)
    hours: int = Field(default=24, ge=1, le=MAX_SHARE_HOURS)


class CommunityPostRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    category: str = Field(default="daily", max_length=40)
    title: str = Field(default="", max_length=160)
    body: str = Field(min_length=1, max_length=10000)
    location_name: str = Field(default="", max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    image_id: int | None = Field(default=None, ge=1)


class ProductRedeemRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)


class CommentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)


def _decode_image(data: bytes, max_bytes: int = MAX_UPLOAD_BYTES) -> tuple[Image.Image, str]:
    if not data:
        raise HTTPException(status_code=400, detail="사진 파일이 비어 있습니다.")
    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"사진은 {limit_mb}MB 이하로 올려 주세요.")
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


def _store_image(db: sqlite3.Connection, user_id: int, purpose: str, filename: str, mime: str, data: bytes, perceptual_hash: str = "") -> int:
    cursor = db.execute(
        "INSERT INTO images(user_id,purpose,mime_type,original_name,image_data,perceptual_hash) VALUES(?,?,?,?,?,?)",
        (user_id, purpose, mime, Path(filename).name[:255], data, perceptual_hash)
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
    with db_connection() as db:
        db.execute("SELECT 1")
    status = verification.verifier.status()
    return {
        "status": "ok",
        "database": "sqlite",
        "database_path": str(Path(os.getenv("HELLOPUPPY_DB_PATH", Path(__file__).parent / "data" / "hellopuppy.sqlite3")).resolve()),
        **status,
        "activity_model": status["trained_classifier"],
        "dog_detector": status["object_detector"] is not None,
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


@app.put("/api/auth/display-name")
def update_display_name(
    request: DisplayNameRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with transaction() as db:
        db.execute("UPDATE users SET display_name=? WHERE id=?", (request.display_name, user["id"]))
        db.execute(
            "INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)",
            (user["id"], "update_display_name", "user", user["id"]),
        )
        updated = db.execute(
            "SELECT id,email,display_name,created_at FROM users WHERE id=?", (user["id"],)
        ).fetchone()
    return {"user": dict(updated)}


@app.put("/api/auth/email")
def update_email(
    request: EmailChangeRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    email = request.email.lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="올바른 이메일 주소를 입력하세요.")
    with transaction() as db:
        account = db.execute(
            "SELECT password_salt,password_hash FROM users WHERE id=?", (user["id"],)
        ).fetchone()
        _, supplied = hash_password(request.current_password, bytes(account["password_salt"]))
        if not hmac.compare_digest(supplied, bytes(account["password_hash"])):
            raise HTTPException(status_code=401, detail="현재 비밀번호가 올바르지 않습니다.")
        try:
            db.execute("UPDATE users SET email=? WHERE id=?", (email, user["id"]))
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다.") from error
        db.execute(
            "INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)",
            (user["id"], "update_email", "user", user["id"]),
        )
        updated = db.execute(
            "SELECT id,email,display_name,created_at FROM users WHERE id=?", (user["id"],)
        ).fetchone()
    return {"user": dict(updated)}


@app.put("/api/auth/password")
def update_password(
    request: PasswordChangeRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, bool]:
    with transaction() as db:
        account = db.execute(
            "SELECT password_salt,password_hash FROM users WHERE id=?", (user["id"],)
        ).fetchone()
        _, supplied = hash_password(request.current_password, bytes(account["password_salt"]))
        if not hmac.compare_digest(supplied, bytes(account["password_hash"])):
            raise HTTPException(status_code=401, detail="현재 비밀번호가 올바르지 않습니다.")
        salt, digest = hash_password(request.new_password)
        db.execute(
            "UPDATE users SET password_salt=?,password_hash=? WHERE id=?",
            (salt, digest, user["id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], user["token_hash"]))
        db.execute(
            "INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)",
            (user["id"], "update_password", "user", user["id"]),
        )
    return {"password_updated": True}


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
    try:
        validate_choice(data["species"], SPECIES, "동물 종류")
        validate_choice(data["registration_type"], REGISTRATION_TYPES, "동물등록 방식")
        validate_choice(data["living_environment"], LIVING_ENVIRONMENTS, "생활환경")
    except HealthValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with transaction() as db:
        db.execute("""UPDATE pets SET name=?,breed=?,birth_date=?,sex=?,weight_kg=?,neutered=?,guardian_name=?,guardian_phone=?,microchip_id=?,allergies=?,medical_notes=?,
                species=?,birth_date_estimated=?,coat_features=?,registration_type=?,blood_type=?,living_environment=?,other_pets=?,updated_at=? WHERE user_id=?""",
                   (data["name"], data["breed"], data["birth_date"], data["sex"], data["weight_kg"], data["neutered"], data["guardian_name"], data["guardian_phone"], data["microchip_id"], data["allergies"], data["medical_notes"],
                    data["species"], int(data["birth_date_estimated"]), data["coat_features"], data["registration_type"], data["blood_type"], data["living_environment"], data["other_pets"], utc_iso(), user["id"]))
        row = db.execute("SELECT * FROM pets WHERE user_id=?", (user["id"],)).fetchone()
    return {"profile": dict(row)}


@app.get("/api/pet/food")
def get_food(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        row = db.execute("SELECT f.* FROM food_profiles f JOIN pets p ON p.id=f.pet_id WHERE p.user_id=?", (user["id"],)).fetchone()
    return {"food": dict(row) if row else None}


@app.put("/api/pet/food")
def save_food(request: FoodProfileRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    try:
        validate_iso_date(request.diet_changed_date, "사료 변경일")
    except HealthValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with transaction() as db:
        pet = db.execute("SELECT id FROM pets WHERE user_id=?", (user["id"],)).fetchone()
        db.execute("""INSERT INTO food_profiles(pet_id,food_name,meals_per_day,feeding_schedule,food_notes,amount_per_meal,treats,supplements,diet_changed_date,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(pet_id) DO UPDATE SET food_name=excluded.food_name,meals_per_day=excluded.meals_per_day,feeding_schedule=excluded.feeding_schedule,food_notes=excluded.food_notes,
            amount_per_meal=excluded.amount_per_meal,treats=excluded.treats,supplements=excluded.supplements,diet_changed_date=excluded.diet_changed_date,updated_at=excluded.updated_at""",
            (pet["id"], request.food_name, request.meals_per_day, request.feeding_schedule, request.food_notes,
             request.amount_per_meal, request.treats, request.supplements, request.diet_changed_date, utc_iso()))
        row = db.execute("SELECT * FROM food_profiles WHERE pet_id=?", (pet["id"],)).fetchone()
    return {"food": dict(row)}


def _activity_cutoff(days: int = 30) -> str:
    return (utc_now() - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _require_health_image(db: sqlite3.Connection, user_id: int, image_id: int | None) -> None:
    if image_id is None:
        return
    image = db.execute("SELECT id FROM images WHERE id=? AND user_id=? AND purpose='health'", (image_id, user_id)).fetchone()
    if image is None:
        raise HTTPException(status_code=404, detail="업로드한 건강 기록 사진을 찾을 수 없습니다.")


def _insert_health_record(db: sqlite3.Connection, user_id: int, request: HealthRecordRequest, *, source: str = "guardian",
                          clinic: str | None = None, author_name: str = "", author_license: str = "") -> dict[str, Any]:
    try:
        validate_iso_date(request.record_date, "날짜")
        details = validate_details(request.record_type, request.details)
    except HealthValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _require_health_image(db, user_id, request.image_id)
    pet = db.execute("SELECT id FROM pets WHERE user_id=?", (user_id,)).fetchone()
    cursor = db.execute("""INSERT INTO health_records(user_id,pet_id,record_type,record_date,clinic,title,notes,details_json,source,author_name,author_license,image_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, pet["id"], request.record_type, request.record_date, clinic if clinic is not None else request.clinic,
         request.title, request.notes, json.dumps(details, ensure_ascii=False), source, author_name, author_license, request.image_id))
    if request.record_type == "weight":
        # 가장 최근 체중 측정 기록을 기본 정보의 현재 체중으로 반영한다.
        newer = db.execute("""SELECT 1 FROM health_records WHERE user_id=? AND record_type='weight' AND id<>?
            AND record_date>?""", (user_id, cursor.lastrowid, request.record_date)).fetchone()
        if newer is None:
            db.execute("UPDATE pets SET weight_kg=?,updated_at=? WHERE id=?", (details["weight_kg"], utc_iso(), pet["id"]))
    row = db.execute("SELECT * FROM health_records WHERE id=?", (cursor.lastrowid,)).fetchone()
    return record_row_to_dict(row)


@app.get("/api/health/summary")
def get_health_summary(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        summary = build_summary(db, int(user["id"]), _activity_cutoff())
    return {"summary": summary}


@app.get("/api/health/records")
def list_health_records(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        rows = db.execute("SELECT * FROM health_records WHERE user_id=? ORDER BY record_date DESC,id DESC", (user["id"],)).fetchall()
    return {"items": [record_row_to_dict(row) for row in rows]}


@app.post("/api/health/records")
def create_health_record(request: HealthRecordRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with transaction() as db:
        record = _insert_health_record(db, int(user["id"]), request)
    return {"record": record}


@app.delete("/api/health/records/{record_id}")
def delete_health_record(record_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, bool]:
    with transaction() as db:
        cursor = db.execute("DELETE FROM health_records WHERE id=? AND user_id=?", (record_id, user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="건강 기록을 찾을 수 없습니다.")
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (user["id"], "delete_health_record", "health_record", record_id))
    return {"deleted": True}


@app.get("/api/health/questionnaires")
def list_questionnaires(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        rows = db.execute("SELECT * FROM pre_visit_questionnaires WHERE user_id=? ORDER BY visit_date DESC,id DESC", (user["id"],)).fetchall()
    return {"items": [questionnaire_row_to_dict(row) for row in rows]}


@app.post("/api/health/questionnaires")
def create_questionnaire(request: QuestionnaireRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    try:
        validate_iso_date(request.visit_date, "방문일")
        validate_iso_date(request.onset_date, "증상 시작일")
        validate_choice(request.progression, PROGRESSIONS, "경과")
        systems = validate_systems(request.systems)
    except HealthValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with transaction() as db:
        _require_health_image(db, int(user["id"]), request.image_id)
        pet = db.execute("SELECT id FROM pets WHERE user_id=?", (user["id"],)).fetchone()
        cursor = db.execute("""INSERT INTO pre_visit_questionnaires(user_id,pet_id,visit_date,clinic,chief_complaint,onset_date,frequency,progression,home_care,recent_changes,concerns,systems_json,image_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user["id"], pet["id"], request.visit_date, request.clinic, request.chief_complaint, request.onset_date, request.frequency,
             request.progression, request.home_care, request.recent_changes, request.concerns, json.dumps(systems, ensure_ascii=False), request.image_id))
        row = db.execute("SELECT * FROM pre_visit_questionnaires WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {"questionnaire": questionnaire_row_to_dict(row)}


@app.delete("/api/health/questionnaires/{questionnaire_id}")
def delete_questionnaire(questionnaire_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, bool]:
    with transaction() as db:
        cursor = db.execute("DELETE FROM pre_visit_questionnaires WHERE id=? AND user_id=?", (questionnaire_id, user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="문진표를 찾을 수 없습니다.")
    return {"deleted": True}


@app.get("/api/health/export/fhir")
def export_health_fhir(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with transaction() as db:
        summary = build_summary(db, int(user["id"]), _activity_cutoff())
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (user["id"], "export_fhir", "pet", summary["pet"].get("id")))
    return to_fhir_bundle(summary, utc_iso())


# ---------------------------------------------------------------------------
# 병원 공유: 보호자가 병원별로 기한부 링크를 발급하고, 병원은 로그인 없이 링크로 열람(·입력)한다.
# 토큰 원문은 발급 응답에서 한 번만 돌려주고 DB에는 SHA-256 해시만 저장한다.
# ---------------------------------------------------------------------------

def _share_status(row: sqlite3.Row) -> str:
    if row["revoked_at"]:
        return "revoked"
    return "active" if row["expires_at"] > utc_iso() else "expired"


@app.post("/api/health/shares")
def create_health_share(request: HealthShareRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if request.scope not in SHARE_SCOPES:
        raise HTTPException(status_code=422, detail="공유 권한 값이 올바르지 않습니다.")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = (utc_now() + timedelta(hours=request.hours)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with transaction() as db:
        cursor = db.execute("INSERT INTO health_shares(user_id,token_hash,clinic_name,scope,expires_at) VALUES(?,?,?,?,?)",
                            (user["id"], token_hash, request.clinic_name, request.scope, expires_at))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (user["id"], "share_create", "health_share", cursor.lastrowid))
        row = db.execute("SELECT id,clinic_name,scope,expires_at,revoked_at,created_at FROM health_shares WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {"share": {**dict(row), "status": "active", "access_count": 0, "last_accessed_at": None}, "token": token}


@app.get("/api/health/shares")
def list_health_shares(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        rows = db.execute("""SELECT s.id,s.clinic_name,s.scope,s.expires_at,s.revoked_at,s.created_at,
            (SELECT COUNT(*) FROM audit_logs a WHERE a.entity_type='health_share' AND a.entity_id=s.id AND a.action IN ('share_view','share_write','share_export')) AS access_count,
            (SELECT MAX(a.created_at) FROM audit_logs a WHERE a.entity_type='health_share' AND a.entity_id=s.id AND a.action IN ('share_view','share_write','share_export')) AS last_accessed_at
            FROM health_shares s WHERE s.user_id=? ORDER BY s.id DESC LIMIT 50""", (user["id"],)).fetchall()
    return {"items": [{**dict(row), "status": _share_status(row)} for row in rows]}


@app.delete("/api/health/shares/{share_id}")
def revoke_health_share(share_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, bool]:
    with transaction() as db:
        cursor = db.execute("UPDATE health_shares SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL", (utc_iso(), share_id, user["id"]))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="공유 링크를 찾을 수 없거나 이미 취소되었습니다.")
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (user["id"], "share_revoke", "health_share", share_id))
    return {"revoked": True}


def get_health_share(x_health_share_token: str | None = Header(default=None)) -> dict[str, Any]:
    # 만료·취소된 링크도 존재 여부를 드러내지 않도록 모두 404로 응답한다.
    not_found = HTTPException(status_code=404, detail="공유 링크가 없거나 만료·취소되었습니다. 보호자에게 새 링크를 요청하세요.")
    if not x_health_share_token or not 20 <= len(x_health_share_token) <= 128:
        raise not_found
    token_hash = hashlib.sha256(x_health_share_token.encode("utf-8")).hexdigest()
    with db_connection() as db:
        share = db.execute("SELECT * FROM health_shares WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?", (token_hash, utc_iso())).fetchone()
    if share is None:
        raise not_found
    return dict(share)


def _log_share_access(db: sqlite3.Connection, share: dict[str, Any], action: str) -> None:
    db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id) VALUES(?,?,?,?)", (share["user_id"], action, "health_share", share["id"]))


def _public_share(share: dict[str, Any]) -> dict[str, Any]:
    return {key: share[key] for key in ("clinic_name", "scope", "expires_at")}


@app.get("/api/shared/health")
def view_shared_health(share: dict[str, Any] = Depends(get_health_share)) -> dict[str, Any]:
    with transaction() as db:
        summary = build_summary(db, int(share["user_id"]), _activity_cutoff())
        _log_share_access(db, share, "share_view")
    return {"share": _public_share(share), "summary": summary}


@app.get("/api/shared/health/fhir")
def export_shared_health_fhir(share: dict[str, Any] = Depends(get_health_share)) -> dict[str, Any]:
    with transaction() as db:
        summary = build_summary(db, int(share["user_id"]), _activity_cutoff())
        _log_share_access(db, share, "share_export")
    return to_fhir_bundle(summary, utc_iso())


@app.post("/api/shared/health/records")
def create_shared_health_record(request: ClinicRecordRequest, share: dict[str, Any] = Depends(get_health_share)) -> dict[str, Any]:
    if share["scope"] != "read_write":
        raise HTTPException(status_code=403, detail="이 공유 링크는 열람 전용입니다.")
    if request.image_id is not None:
        raise HTTPException(status_code=422, detail="병원 입력 기록에는 사진을 첨부할 수 없습니다.")
    with transaction() as db:
        record = _insert_health_record(db, int(share["user_id"]), request, source="clinic", clinic=share["clinic_name"],
                                       author_name=request.author_name, author_license=request.author_license)
        _log_share_access(db, share, "share_write")
    return {"record": record}


@app.get("/api/shared/health/images/{image_id}")
def get_shared_health_image(image_id: int, share: dict[str, Any] = Depends(get_health_share)) -> Any:
    from fastapi.responses import Response

    with db_connection() as db:
        row = db.execute("""SELECT i.mime_type,i.image_data FROM images i
            WHERE i.id=? AND i.user_id=? AND i.purpose='health' AND (
                EXISTS(SELECT 1 FROM health_records r WHERE r.image_id=i.id AND r.user_id=i.user_id)
                OR EXISTS(SELECT 1 FROM pre_visit_questionnaires q WHERE q.image_id=i.id AND q.user_id=i.user_id))""",
                         (image_id, share["user_id"])).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    return Response(content=bytes(row["image_data"]), media_type=row["mime_type"], headers={"Cache-Control": "private, no-store"})


@app.post("/api/uploads")
async def upload_image(purpose: str, photo: UploadFile = File(...), user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if purpose not in {"community", "health"}:
        raise HTTPException(status_code=422, detail="지원하지 않는 이미지 용도입니다.")
    max_upload_bytes = MAX_COMMUNITY_UPLOAD_BYTES if purpose == "community" else MAX_UPLOAD_BYTES
    data = await photo.read(max_upload_bytes + 1)
    if len(data) > max_upload_bytes:
        limit_mb = max_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"사진은 {limit_mb}MB 이하로 올려 주세요.")
    _, mime = _decode_image(data, max_upload_bytes)
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
        rows = db.execute("""SELECT p.id,p.user_id,p.pet_id,p.category,p.title,p.body,p.location_name,p.latitude,p.longitude,p.image_id,p.created_at,u.display_name,
            (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
            EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked
            FROM community_posts p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT ?""", (user["id"], safe_limit)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/community/walk-map")
def list_public_walk_map_posts(limit: int = 100) -> dict[str, Any]:
    """Return only locations explicitly shared by logged-in community members."""
    safe_limit = max(1, min(limit, 200))
    with db_connection() as db:
        rows = db.execute("""SELECT p.id,p.category,p.title,p.body,p.location_name,p.latitude,p.longitude,p.image_id,p.created_at,u.display_name,
            (SELECT COUNT(*) FROM community_place_recommendations r WHERE r.post_id=p.id) AS recommendation_count
            FROM community_posts p JOIN users u ON u.id=p.user_id
            WHERE p.location_name<>'' AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL
            ORDER BY p.id DESC LIMIT ?""", (safe_limit,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/community/walk-map/images/{image_id}")
def get_public_walk_map_image(image_id: int) -> Any:
    """Serve an image only when it is attached to an explicitly public map post."""
    from fastapi.responses import Response

    with db_connection() as db:
        row = db.execute("""SELECT i.mime_type,i.image_data FROM images i
            JOIN community_posts p ON p.image_id=i.id
            WHERE i.id=? AND i.purpose='community' AND p.location_name<>''
                AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL""", (image_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="공개 지도 게시물의 사진을 찾을 수 없습니다.")
    return Response(content=bytes(row["image_data"]), media_type=row["mime_type"], headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/community/posts/{post_id}/recommendation")
def get_place_recommendation(post_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with db_connection() as db:
        post = db.execute("SELECT id FROM community_posts WHERE id=? AND location_name<>''", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="추천 장소를 찾을 수 없습니다.")
        recommended = db.execute("SELECT 1 FROM community_place_recommendations WHERE post_id=? AND user_id=?", (post_id, user["id"])).fetchone()
        count = db.execute("SELECT COUNT(*) AS count FROM community_place_recommendations WHERE post_id=?", (post_id,)).fetchone()["count"]
    return {"recommended": recommended is not None, "count": int(count)}


@app.post("/api/community/posts/{post_id}/recommendation")
def recommend_place(post_id: int, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    with transaction() as db:
        post = db.execute("SELECT id FROM community_posts WHERE id=? AND location_name<>''", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="추천 장소를 찾을 수 없습니다.")
        db.execute("INSERT OR IGNORE INTO community_place_recommendations(post_id,user_id) VALUES(?,?)", (post_id, user["id"]))
        count = db.execute("SELECT COUNT(*) AS count FROM community_place_recommendations WHERE post_id=?", (post_id,)).fetchone()["count"]
    return {"recommended": True, "count": int(count)}


@app.post("/api/community/posts")
def create_post(request: CommunityPostRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if (request.latitude is None) != (request.longitude is None):
        raise HTTPException(status_code=422, detail="지도 위치는 위도와 경도를 함께 선택해야 합니다.")
    if request.image_id is not None:
        with db_connection() as db:
            image = db.execute("SELECT id FROM images WHERE id=? AND user_id=? AND purpose='community'", (request.image_id, user["id"])).fetchone()
        if image is None:
            raise HTTPException(status_code=404, detail="업로드한 커뮤니티 사진을 찾을 수 없습니다.")
    with transaction() as db:
        pet = db.execute("SELECT id FROM pets WHERE user_id=?", (user["id"],)).fetchone()
        cursor = db.execute("INSERT INTO community_posts(user_id,pet_id,category,title,body,location_name,latitude,longitude,image_id) VALUES(?,?,?,?,?,?,?,?,?)",
                    (user["id"], pet["id"], request.category, request.title, request.body, request.location_name, request.latitude, request.longitude, request.image_id))
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
    if not verification.verifier.ready:
        demo_mode = os.getenv("HELLOPUPPY_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
        with transaction() as db:
            image_id = _store_image(db, int(user["id"]), f"verification_{activity}", photo.filename or "photo", mime, data)
            if demo_mode:
                db.execute("""INSERT INTO activity_logs(user_id,pet_id,activity,status,predicted,confidence,margin,image_id)
                    SELECT ?,id,?,'demo',?,1.0,1.0,? FROM pets WHERE user_id=?""",
                    (user["id"], activity, activity, image_id, user["id"]))
                balance_row = db.execute("SELECT balance FROM points_accounts WHERE user_id=?", (user["id"],)).fetchone()
                balance = int(balance_row["balance"]) if balance_row else 0
            else:
                db.execute("""INSERT INTO activity_logs(user_id,pet_id,activity,status,predicted,image_id)
                    SELECT ?,id,?,'unavailable','',? FROM pets WHERE user_id=?""",
                    (user["id"], activity, image_id, user["id"]))
        if demo_mode:
            return {
                "verified": False, "demo": True, "activity": activity,
                "activity_label": ACTIVITY_LABELS[activity], "predicted": activity,
                "confidence": 1.0, "margin": 1.0, "dog_detected": None,
                "dog_confidence": None, "scores": {activity: 1.0},
                "points_awarded": 0, "balance": balance,
                "message": "시연 모드: 더미 판정이 완료되었습니다. 실제 AI 인증 및 포인트 적립은 아닙니다."
            }
        raise HTTPException(status_code=503, detail=verification.verifier.status()["message"] or "사진 판별 모델을 사용할 수 없습니다.")

    user_id = int(user["id"])
    label = ACTIVITY_LABELS[activity]
    photo_hash = verification.difference_hash(image)
    taken_at = verification.photo_taken_at(Image.open(io.BytesIO(data)))
    fraud_checks: list[dict[str, Any]] = []

    # 1) 이미 포인트를 받은 사진(재압축·크기 변경 포함)을 다시 올렸는지
    with db_connection() as db:
        used_hashes = [row["perceptual_hash"] for row in db.execute("""SELECT i.perceptual_hash FROM activity_logs a JOIN images i ON i.id=a.image_id
            WHERE a.user_id=? AND a.status='verified' AND i.perceptual_hash<>''""", (user_id,)).fetchall()]
    duplicate = any(verification.hamming_distance(photo_hash, used) <= DUPLICATE_HASH_DISTANCE for used in used_hashes)
    fraud_checks.append({"key": "duplicate", "label": "새로운 사진", "passed": not duplicate,
                         "detail": "이미 인증에 사용한 사진이에요." if duplicate else "처음 제출한 사진이에요."})
    # 2) 촬영 시각. 브라우저가 EXIF를 지우는 경우가 많아 정보가 없으면 통과시키고 기록만 남긴다.
    stale = taken_at is not None and datetime.now() - taken_at > timedelta(hours=MAX_PHOTO_AGE_HOURS)
    fraud_checks.append({"key": "taken_at", "label": f"최근 {MAX_PHOTO_AGE_HOURS}시간 내 촬영", "passed": None if taken_at is None else not stale,
                         "detail": "촬영 시각 정보가 없어요." if taken_at is None else f"촬영 {taken_at:%Y-%m-%d %H:%M}"})

    if duplicate or stale:
        decision, analysis = None, None
        verified = False
        checks = fraud_checks
        message = "이미 인증에 사용한 사진이에요. 새로 촬영해 주세요." if duplicate else f"{MAX_PHOTO_AGE_HOURS}시간 이내에 촬영한 사진만 인증할 수 있어요."
    else:
        decision, analysis = await run_in_threadpool(verification.verifier.verify, activity, image)
        verified = decision.verified
        checks = decision.checks + fraud_checks
        message = decision.message

    # 3) 하루 보상 횟수 (서버 현지 날짜 기준)
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = local_midnight.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    details = {
        "checks": checks,
        "scores": analysis.activity_scores if analysis else None,
        "outdoor": analysis.outdoor if analysis else None,
        "leash": analysis.leash if analysis else None,
        "detections": [d.to_dict() for d in analysis.detections] if analysis and analysis.detections is not None else None,
        "sources": analysis.sources if analysis else [],
        "photo_taken_at": taken_at.isoformat() if taken_at else None,
    }
    points_awarded = 0
    with transaction() as db:
        image_id = _store_image(db, user_id, f"verification_{activity}", photo.filename or "photo", mime, data, photo_hash)
        rewarded_today = db.execute("""SELECT COUNT(*) AS count FROM points_ledger WHERE user_id=? AND reason=? AND delta>0 AND created_at>=?""",
                                    (user_id, f"{label} 인증", day_start)).fetchone()["count"]
        cursor = db.execute("""INSERT INTO activity_logs(user_id,pet_id,activity,status,predicted,confidence,margin,image_id,details_json)
            SELECT ?,id,?,?,?,?,?,?,? FROM pets WHERE user_id=?""",
            (user_id, activity, "verified" if verified else "rejected", decision.predicted if decision else "",
             decision.confidence if decision else None, decision.margin if decision else None, image_id,
             json.dumps(details, ensure_ascii=False), user_id))
        if verified and rewarded_today < DAILY_REWARD_LIMITS[activity]:
            points_awarded = ACTIVITY_POINTS[activity]
            balance = _award_points(db, user_id, points_awarded, f"{label} 인증", f"activity:{cursor.lastrowid}")
        else:
            row = db.execute("SELECT balance FROM points_accounts WHERE user_id=?", (user_id,)).fetchone()
            balance = int(row["balance"]) if row else 0
    if verified and not points_awarded:
        message += f" 오늘 {label} 포인트는 {DAILY_REWARD_LIMITS[activity]}회 모두 받았어요."

    return {
        "verified": verified, "activity": activity, "activity_label": label,
        "predicted": decision.predicted if decision else None,
        "confidence": round(decision.confidence, 4) if decision else None,
        "margin": round(decision.margin, 4) if decision else None,
        "dog_detected": None if not decision or decision.dog_confidence is None else any(c["key"] == "dog" and c["passed"] for c in decision.checks),
        "dog_confidence": round(decision.dog_confidence, 4) if decision and decision.dog_confidence is not None else None,
        "scores": {key: round(value, 4) for key, value in analysis.activity_scores.items()} if analysis else {},
        "checks": checks, "points_awarded": points_awarded, "balance": balance, "message": message,
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

"""SQLite persistence for HelloPuppy accounts, health, points, photos and community."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import storage

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(__file__).parent / "data" / "hellopuppy.sqlite3"


def database_path() -> Path:
    configured = os.getenv("HELLOPUPPY_DB_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with transaction() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            -- 로그인 실패 기록 (이메일·IP별 시도 제한). 하루 지난 기록은 로그인 때 지운다.
            CREATE TABLE IF NOT EXISTS login_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE INDEX IF NOT EXISTS idx_login_failures_key ON login_failures(key, created_at);

            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL DEFAULT '',
                breed TEXT NOT NULL DEFAULT '',
                birth_date TEXT NOT NULL DEFAULT '',
                sex TEXT NOT NULL DEFAULT '',
                weight_kg REAL,
                neutered TEXT NOT NULL DEFAULT 'unknown',
                guardian_name TEXT NOT NULL DEFAULT '',
                guardian_phone TEXT NOT NULL DEFAULT '',
                microchip_id TEXT NOT NULL DEFAULT '',
                allergies TEXT NOT NULL DEFAULT '',
                medical_notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS food_profiles (
                pet_id INTEGER PRIMARY KEY REFERENCES pets(id) ON DELETE CASCADE,
                food_name TEXT NOT NULL DEFAULT '',
                meals_per_day INTEGER,
                feeding_schedule TEXT NOT NULL DEFAULT '',
                food_notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                purpose TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                original_name TEXT NOT NULL DEFAULT '',
                image_data BLOB NOT NULL DEFAULT X'',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pet_id INTEGER REFERENCES pets(id) ON DELETE SET NULL,
                activity TEXT NOT NULL CHECK(activity IN ('walk','feeding')),
                status TEXT NOT NULL,
                predicted TEXT NOT NULL DEFAULT '',
                confidence REAL,
                margin REAL,
                image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS points_accounts (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS points_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                delta INTEGER NOT NULL CHECK(delta <> 0),
                balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
                reason TEXT NOT NULL,
                reference TEXT UNIQUE,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS health_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pet_id INTEGER REFERENCES pets(id) ON DELETE SET NULL,
                record_type TEXT NOT NULL,
                record_date TEXT NOT NULL,
                clinic TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS community_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pet_id INTEGER REFERENCES pets(id) ON DELETE SET NULL,
                category TEXT NOT NULL DEFAULT 'daily',
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                location_name TEXT NOT NULL DEFAULT '',
                latitude REAL,
                longitude REAL,
                image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS post_likes (
                post_id INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(post_id,user_id)
            );

            CREATE TABLE IF NOT EXISTS community_place_recommendations (
                post_id INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(post_id,user_id)
            );

            CREATE TABLE IF NOT EXISTS post_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS shop_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                image_path TEXT NOT NULL DEFAULT '',
                cost INTEGER NOT NULL CHECK(cost > 0),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS pre_visit_questionnaires (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pet_id INTEGER REFERENCES pets(id) ON DELETE SET NULL,
                visit_date TEXT NOT NULL,
                clinic TEXT NOT NULL DEFAULT '',
                chief_complaint TEXT NOT NULL,
                onset_date TEXT NOT NULL DEFAULT '',
                frequency TEXT NOT NULL DEFAULT '',
                progression TEXT NOT NULL DEFAULT '',
                home_care TEXT NOT NULL DEFAULT '',
                recent_changes TEXT NOT NULL DEFAULT '',
                concerns TEXT NOT NULL DEFAULT '',
                systems_json TEXT NOT NULL DEFAULT '{}',
                image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE TABLE IF NOT EXISTS health_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                clinic_name TEXT NOT NULL,
                scope TEXT NOT NULL CHECK(scope IN ('read','read_write')),
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            -- 영수증 리워드: OCR 원문과 추출 항목. fingerprint 는 같은 영수증 재사용(다른 계정 포함) 검사용
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
                status TEXT NOT NULL CHECK(status IN ('verified','rejected')),
                store_name TEXT NOT NULL DEFAULT '',
                business_number TEXT NOT NULL DEFAULT '',
                purchased_date TEXT,
                purchased_time TEXT,
                total_amount INTEGER,
                approval_number TEXT NOT NULL DEFAULT '',
                fingerprint TEXT,
                raw_text TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            -- 영수증에서 읽은 품목 (구매 기록). 사용자가 고친 내용으로 덮어쓴다.
            CREATE TABLE IF NOT EXISTS receipt_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                position INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                quantity INTEGER,
                unit_price INTEGER,
                amount INTEGER NOT NULL,
                category TEXT NOT NULL DEFAULT '기타 용품'
            );
            CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt ON receipt_items(receipt_id, position);
            CREATE INDEX IF NOT EXISTS idx_receipt_items_user ON receipt_items(user_id);
            CREATE INDEX IF NOT EXISTS idx_receipts_user_created ON receipts(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_receipts_fingerprint ON receipts(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_activity_user_created ON activity_logs(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_questionnaires_user_date ON pre_visit_questionnaires(user_id, visit_date DESC);
            CREATE INDEX IF NOT EXISTS idx_health_shares_user ON health_shares(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_health_user_date ON health_records(user_id, record_date DESC);
            CREATE INDEX IF NOT EXISTS idx_posts_created ON community_posts(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_comments_post ON post_comments(post_id,created_at);
            CREATE INDEX IF NOT EXISTS idx_place_recommendations_post ON community_place_recommendations(post_id);
            CREATE INDEX IF NOT EXISTS idx_points_user_created ON points_ledger(user_id, created_at DESC);
            """
        )
        # 인증 사진 재사용 검사용 dHash, 판정 근거(점수·탐지·체크 결과)
        _add_missing_columns(db, "images", {"perceptual_hash": "TEXT NOT NULL DEFAULT ''"})
        # 사진은 파일로 저장한다 (storage.py). image_data 는 예전 DB 호환용으로 남겨 두고 비워 둔다.
        _add_missing_columns(db, "images", {"storage_path": "TEXT NOT NULL DEFAULT ''"})
        moved = storage.migrate_blobs(db)
        _add_missing_columns(db, "activity_logs", {"details_json": "TEXT NOT NULL DEFAULT '{}'"})
        # 구매 기록: log_reason NULL = 아직 계산 안 함(예전 행), '' = 기록에 포함, 'not_pet'/'duplicate'/'no_amount' = 제외 이유
        # dataset_consent: 사진을 OCR 학습 데이터로 쓰는 데 동의(선택)했는지
        _add_missing_columns(db, "receipts", {
            "pet_store": "INTEGER NOT NULL DEFAULT 0",
            "pet_amount": "INTEGER",
            "in_log": "INTEGER NOT NULL DEFAULT 0",
            "log_reason": "TEXT",
            "items_corrected": "INTEGER NOT NULL DEFAULT 0",
            "dataset_consent": "INTEGER NOT NULL DEFAULT 0",
            "dataset_consent_at": "TEXT",
        })
        _add_missing_columns(db, "community_posts", {
            "location_name": "TEXT NOT NULL DEFAULT ''",
            "latitude": "REAL",
            "longitude": "REAL",
        })
        # 수의 진료부 기재사항(품종·성별·특징·연령, 동물등록번호)과 문진 항목을 위한 확장 컬럼
        _add_missing_columns(db, "pets", {
            "species": "TEXT NOT NULL DEFAULT 'dog'",
            "birth_date_estimated": "INTEGER NOT NULL DEFAULT 0",
            "coat_features": "TEXT NOT NULL DEFAULT ''",
            "registration_type": "TEXT NOT NULL DEFAULT ''",
            "blood_type": "TEXT NOT NULL DEFAULT ''",
            "living_environment": "TEXT NOT NULL DEFAULT ''",
            "other_pets": "TEXT NOT NULL DEFAULT ''",
        })
        _add_missing_columns(db, "food_profiles", {
            "amount_per_meal": "TEXT NOT NULL DEFAULT ''",
            "treats": "TEXT NOT NULL DEFAULT ''",
            "supplements": "TEXT NOT NULL DEFAULT ''",
            "diet_changed_date": "TEXT NOT NULL DEFAULT ''",
        })
        # source: guardian(보호자 입력) / clinic(공유 링크로 동물병원이 입력)
        _add_missing_columns(db, "health_records", {
            "details_json": "TEXT NOT NULL DEFAULT '{}'",
            "source": "TEXT NOT NULL DEFAULT 'guardian'",
            "author_name": "TEXT NOT NULL DEFAULT ''",
            "author_license": "TEXT NOT NULL DEFAULT ''",
            "image_id": "INTEGER REFERENCES images(id) ON DELETE SET NULL",
        })
    if moved:  # give the space the photo BLOBs used back to the disk (VACUUM cannot run inside a transaction)
        with db_connection() as db:
            db.execute("VACUUM")


def _add_missing_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

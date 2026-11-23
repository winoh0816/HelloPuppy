"""Copy an existing HelloPuppy SQLite database into PostgreSQL (one time, when switching databases).

    $env:HELLOPUPPY_DATABASE_URL = "postgresql://hellopuppy:비밀번호@127.0.0.1:5432/hellopuppy"
    .venv-backend\\Scripts\\python.exe -m backend.tools.migrate_sqlite_to_postgres --sqlite backend\\data\\hellopuppy.sqlite3

- PostgreSQL 에 표를 만들고, 표마다 두 DB 에 모두 있는 컬럼만 옮긴다. id 는 그대로 두고 다음 번호를 그 뒤로 맞춘다.
  예전 SQLite 에 없던 컬럼은 기본값으로 채워진다.
- 사진이 아직 DB 안(image_data BLOB)에 있는 아주 예전 DB 는 메타데이터를 지운 파일로 HELLOPUPPY_MEDIA_DIR 에 꺼낸다.
  이미 파일로 저장된 사진은 경로만 옮기므로, 서버가 지금까지 쓰던 사진 폴더(기본 backend/data/media)를 그대로 써야 한다.
- 전부 한 트랜잭션이다. 중간에 실패하면 PostgreSQL 에는 아무것도 들어가지 않는다 (꺼낸 사진 파일만 남을 수 있다).
- 대상 DB 에 계정이 하나라도 있으면 덮어쓰지 않도록 멈춘다. SQLite 파일은 읽기 전용으로 열어 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from psycopg import sql

from backend import storage
from backend.database import TABLES, init_db, transaction

DEFAULT_SQLITE = Path(__file__).resolve().parents[1] / "data" / "hellopuppy.sqlite3"


class MigrationError(RuntimeError):
    pass


def migrate(sqlite_path: Path) -> dict[str, int]:
    """Copy every table and return how many rows each one got."""
    if not sqlite_path.is_file():
        raise MigrationError(f"SQLite 파일이 없습니다: {sqlite_path}")
    source = sqlite3.connect(f"file:{sqlite_path.resolve().as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        source_tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        init_db()
        counts: dict[str, int] = {}
        with transaction() as db:
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise MigrationError("PostgreSQL 에 이미 계정이 있습니다. 덮어쓰지 않도록 빈 DB 에만 옮길 수 있어요.")
            for table in TABLES:
                if table not in source_tables:
                    continue
                target_columns = {row["column_name"] for row in db.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s",
                    (table,)).fetchall()}
                source_columns = [row["name"] for row in source.execute(f'PRAGMA table_info("{table}")')]
                columns = [name for name in source_columns if name in target_columns]
                if table == "images" and "storage_path" not in columns:
                    columns.append("storage_path")  # a database from before photos were files
                rows = [_row_values(table, row, columns) for row in source.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                if rows:
                    insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.SQL(",").join(sql.Placeholder() * len(columns)))
                    db.cursor().executemany(insert, rows)
                if "id" in target_columns:  # new rows continue after the copied ids
                    db.execute(sql.SQL("SELECT setval(pg_get_serial_sequence({}, 'id'), COALESCE((SELECT MAX(id) FROM {}), 0) + 1, false)")
                               .format(sql.Literal(table), sql.Identifier(table)))
                counts[table] = len(rows)
        return counts
    finally:
        source.close()


def _row_values(table: str, row: sqlite3.Row, columns: list[str]) -> list:
    keys = row.keys()
    values = {name: row[name] if name in keys else "" for name in columns}
    if table == "images" and not values["storage_path"] and "image_data" in keys and row["image_data"]:
        values["storage_path"] = storage.save_legacy_photo(bytes(row["image_data"]), row["mime_type"])
    return [values[name] for name in columns]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE, help="옮길 SQLite 파일")
    args = parser.parse_args()
    try:
        counts = migrate(args.sqlite)
    except MigrationError as error:
        raise SystemExit(str(error)) from error
    for table, count in counts.items():
        print(f"{table:34} {count:>8}")
    print(f"완료: {sum(counts.values())}행을 PostgreSQL 로 옮겼습니다. 사진 폴더: {storage.media_dir()}")


if __name__ == "__main__":
    main()

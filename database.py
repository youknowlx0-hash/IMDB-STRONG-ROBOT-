import sqlite3
import os
from contextlib import contextmanager

DB_FILE = os.getenv("DB_FILE", "bot.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_name TEXT,
                file_type TEXT DEFAULT 'document',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)


def add_user(user_id, username=None, first_name=None):
    with get_db() as db:
        db.execute("""
            INSERT OR IGNORE INTO users
            (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (user_id, username, first_name))


def get_users():
    with get_db() as db:
        return db.execute("""
            SELECT user_id
            FROM users
            WHERE is_blocked = 0
        """).fetchall()


def add_file(tmdb_id, file_id, file_name="", file_type="document"):
    with get_db() as db:
        db.execute("""
            INSERT INTO files
            (tmdb_id, file_id, file_name, file_type)
            VALUES (?, ?, ?, ?)
        """, (tmdb_id, file_id, file_name, file_type))


def get_files(tmdb_id):
    with get_db() as db:
        return db.execute("""
            SELECT *
            FROM files
            WHERE tmdb_id = ?
            ORDER BY id DESC
        """, (tmdb_id,)).fetchall()


def set_setting(key, value):
    with get_db() as db:
        db.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
        """, (key, value))


def get_setting(key, default=None):
    with get_db() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        ).fetchone()

    return row["value"] if row else default


def get_user_count():
    with get_db() as db:
        row = db.execute(
            "SELECT COUNT(*) AS count FROM users"
        ).fetchone()

    return row["count"]

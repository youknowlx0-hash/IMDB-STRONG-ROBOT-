import sqlite3
from contextlib import contextmanager

from config import DB_FILE


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
                blocked INTEGER DEFAULT 0
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER,
                title TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT DEFAULT 'document',
                file_name TEXT,
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
            INSERT INTO users (
                user_id,
                username,
                first_name
            )
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (
            user_id,
            username,
            first_name
        ))


def block_user(user_id):
    with get_db() as db:
        db.execute(
            "UPDATE users SET blocked = 1 WHERE user_id = ?",
            (user_id,)
        )


def get_all_users():
    with get_db() as db:
        return db.execute("""
            SELECT user_id
            FROM users
            WHERE blocked = 0
        """).fetchall()


def user_count():
    with get_db() as db:
        row = db.execute("""
            SELECT COUNT(*) AS total
            FROM users
        """).fetchone()

        return row["total"]


def add_media(
    tmdb_id,
    title,
    file_id,
    file_type="document",
    file_name=""
):
    with get_db() as db:
        cursor = db.execute("""
            INSERT INTO media (
                tmdb_id,
                title,
                file_id,
                file_type,
                file_name
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            tmdb_id,
            title,
            file_id,
            file_type,
            file_name
        ))

        return cursor.lastrowid


def get_media(tmdb_id):
    with get_db() as db:
        return db.execute("""
            SELECT *
            FROM media
            WHERE tmdb_id = ?
            ORDER BY id DESC
        """, (
            tmdb_id,
        )).fetchall()


def get_media_by_id(media_id):
    with get_db() as db:
        return db.execute("""
            SELECT *
            FROM media
            WHERE id = ?
        """, (
            media_id,
        )).fetchone()


def delete_media(media_id):
    with get_db() as db:
        db.execute(
            "DELETE FROM media WHERE id = ?",
            (media_id,)
        )


def set_setting(key, value):
    with get_db() as db:
        db.execute("""
            INSERT INTO settings (
                key,
                value
            )
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
        """, (
            key,
            value
        ))


def get_setting(key, default=None):
    with get_db() as db:
        row = db.execute("""
            SELECT value
            FROM settings
            WHERE key = ?
        """, (
            key,
        )).fetchone()

        return row["value"] if row else default

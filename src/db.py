"""Simple SQLite store so we never process the same notice twice."""

import os
import sqlite3
from datetime import datetime

from src.config import DB_PATH


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_notices (
            notice_id   TEXT PRIMARY KEY,
            title       TEXT,
            published   TEXT,
            processed   TEXT
        )
        """
    )
    conn.commit()
    return conn


def is_notice_processed(notice_id: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM processed_notices WHERE notice_id = ?", (notice_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def mark_notice_processed(notice_id: str, title: str, published: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO processed_notices (notice_id, title, published, processed)
            VALUES (?, ?, ?, ?)
            """,
            (notice_id, title, published, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

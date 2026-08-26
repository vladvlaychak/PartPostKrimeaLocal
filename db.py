import re
import sqlite3
from config import DB_PATH


def normalize_search_text(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())


def normalize_shpi(value):
    if value is None:
        return ""
    return re.sub(r"[^A-ZА-ЯЁ0-9]+", "", str(value).strip().upper())


def normalize_internal_number(value):
    if value is None:
        return ""
    return re.sub(r"[^A-ZА-ЯЁ0-9]+", "", str(value).strip().upper())


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_columns(cursor, table_name):
    return {row["name"] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}


def add_column_if_missing(cursor, table_name, column_name, definition):
    if column_name not in get_columns(cursor, table_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
        print(f"[DB] Добавлена колонка: {table_name}.{column_name}")


def init_db():
    print("[DB] Инициализация базы данных...")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shpi TEXT NOT NULL,
            shpi_normalized TEXT,
            mass REAL,
            shipping_cost REAL,
            recipient TEXT,
            recipient_normalized TEXT,
            phone TEXT,
            index_code TEXT,
            address TEXT,
            address_normalized TEXT,
            internal_number TEXT,
            internal_number_normalized TEXT,
            comment TEXT,
            comment_normalized TEXT,
            uploaded_at TEXT
        )
    """)

    migrations = [
        ("uploaded_at", "TEXT"),
        ("shpi_normalized", "TEXT"),
        ("recipient_normalized", "TEXT"),
        ("address_normalized", "TEXT"),
        ("internal_number_normalized", "TEXT"),
        ("comment_normalized", "TEXT"),
    ]
    for column, definition in migrations:
        add_column_if_missing(cur, "shipments", column, definition)

    rows = cur.execute("""
        SELECT id, shpi, recipient, address, internal_number, comment
        FROM shipments
    """).fetchall()

    if rows:
        cur.executemany("""
            UPDATE shipments
            SET shpi_normalized = ?,
                recipient_normalized = ?,
                address_normalized = ?,
                internal_number_normalized = ?,
                comment_normalized = ?
            WHERE id = ?
        """, [
            (
                normalize_shpi(row["shpi"]),
                normalize_search_text(row["recipient"]),
                normalize_search_text(row["address"]),
                normalize_internal_number(row["internal_number"]),
                normalize_search_text(row["comment"]),
                row["id"],
            )
            for row in rows
        ])

    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_shpi ON shipments(shpi)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shpi_normalized ON shipments(shpi_normalized)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_internal_number_normalized ON shipments(internal_number_normalized)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_at ON shipments(uploaded_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipient_normalized ON shipments(recipient_normalized)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_index_code ON shipments(index_code)")

    conn.commit()
    conn.close()
    print("[DB] База данных готова.")

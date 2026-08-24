import sqlite3
from config import DB_PATH

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    print("Инициализация базы данных...")
    conn = get_db_connection()
    cur = conn.cursor()

    # Безопасная миграция: добавляем колонку, если её нет
    try:
        cur.execute("ALTER TABLE shipments ADD COLUMN uploaded_at TEXT")
        print("Колонка uploaded_at добавлена.")
    except sqlite3.OperationalError:
        # Колонка уже есть — это нормально
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shpi TEXT NOT NULL,
            mass REAL,
            shipping_cost REAL,
            recipient TEXT,
            phone TEXT,
            index_code TEXT,
            address TEXT,
            internal_number TEXT,
            comment TEXT,
            uploaded_at TEXT
        )
    """)

    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_shpi ON shipments(shpi)")
    conn.commit()
    conn.close()
    print("База данных готова.")

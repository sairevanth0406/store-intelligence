"""
Async SQLite database with WAL mode for concurrent read/write.
Purplle Store Intelligence System.
"""
import os
import aiosqlite
import structlog
from pathlib import Path

log = structlog.get_logger()

DB_PATH = os.environ.get("DB_PATH", "data/store_intelligence.db")


async def get_db() -> aiosqlite.Connection:
    """Get a database connection with WAL mode and busy timeout."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA busy_timeout = 30000")
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def init_db():
    """Initialize all database tables."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA foreign_keys = ON")
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            event_id       TEXT PRIMARY KEY,
            store_id       TEXT NOT NULL,
            camera_id      TEXT NOT NULL,
            event_type     TEXT NOT NULL,
            person_id      TEXT NOT NULL,
            is_staff       INTEGER NOT NULL DEFAULT 0,
            zone_id        TEXT,
            timestamp      TEXT NOT NULL,
            dwell_seconds  REAL,
            confidence     REAL DEFAULT 1.0,
            metadata       TEXT,
            ingested_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_events_store_ts
            ON events(store_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_zone
            ON events(store_id, zone_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_person
            ON events(store_id, person_id, timestamp);

        CREATE TABLE IF NOT EXISTS sessions (
            session_id     TEXT PRIMARY KEY,
            store_id       TEXT NOT NULL,
            person_id      TEXT NOT NULL,
            camera_id      TEXT NOT NULL,
            entry_time     TEXT NOT NULL,
            exit_time      TEXT,
            is_staff       INTEGER NOT NULL DEFAULT 0,
            converted      INTEGER NOT NULL DEFAULT 0,
            zones_visited  TEXT,
            total_dwell_s  REAL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_store
            ON sessions(store_id, entry_time);

        CREATE TABLE IF NOT EXISTS pos_transactions (
            order_id       TEXT PRIMARY KEY,
            store_id       TEXT NOT NULL,
            order_time     TEXT NOT NULL,
            gmv            REAL,
            nmv            REAL,
            product_name   TEXT,
            brand          TEXT,
            category       TEXT,
            salesperson_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pos_store_ts
            ON pos_transactions(store_id, order_time);

        CREATE TABLE IF NOT EXISTS brand_engagements (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id       TEXT NOT NULL,
            zone_id        TEXT NOT NULL,
            brand          TEXT,
            category       TEXT,
            person_id      TEXT NOT NULL,
            session_id     TEXT,
            dwell_seconds  REAL NOT NULL,
            converted      INTEGER DEFAULT 0,
            timestamp      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_brand_store_zone
            ON brand_engagements(store_id, zone_id, timestamp);
    """)
    await db.commit()
    await db.close()
    log.info("database.init", path=DB_PATH)

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "app.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                weight_g REAL NOT NULL,
                received_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                issued_at TEXT NOT NULL,
                weight_before REAL,
                weight_after REAL,
                device_reported TEXT,
                verdict TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                result_timeout INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_state (
                device_id TEXT PRIMARY KEY,
                halted INTEGER NOT NULL DEFAULT 0,
                halted_at TEXT
            )
            """
        )


def insert_telemetry(device_id: str, weight_g: float, received_at: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO telemetry (device_id, weight_g, received_at) VALUES (?, ?, ?)",
            (device_id, weight_g, received_at),
        )
        return cur.lastrowid


def get_latest_weight(device_id: str) -> float | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT weight_g FROM telemetry WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
        return row["weight_g"] if row else None


def insert_command(
    device_id: str,
    duration_ms: int,
    issued_at: str,
    weight_before: float | None,
    created_at: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO commands
                (device_id, duration_ms, issued_at, weight_before, retry_count, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (device_id, duration_ms, issued_at, weight_before, created_at),
        )
        return cur.lastrowid


def update_device_reported(command_id: int, device_reported: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE commands SET device_reported = ? WHERE id = ?",
            (device_reported, command_id),
        )
        return cur.rowcount > 0


def update_command_result(
    command_id: int,
    weight_before: float | None,
    weight_after: float | None,
    verdict: str | None,
    retry_count: int,
    result_timeout: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE commands
            SET weight_before = ?, weight_after = ?, verdict = ?, retry_count = ?, result_timeout = ?
            WHERE id = ?
            """,
            (weight_before, weight_after, verdict, retry_count, int(result_timeout), command_id),
        )


def is_halted(device_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT halted FROM device_state WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        return bool(row["halted"]) if row else False


def set_halted(device_id: str, halted_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO device_state (device_id, halted, halted_at) VALUES (?, 1, ?)
            ON CONFLICT(device_id) DO UPDATE SET halted = 1, halted_at = excluded.halted_at
            """,
            (device_id, halted_at),
        )


def clear_halt(device_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO device_state (device_id, halted, halted_at) VALUES (?, 0, NULL)
            ON CONFLICT(device_id) DO UPDATE SET halted = 0, halted_at = NULL
            """,
            (device_id,),
        )


def list_recent_commands(limit: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM commands ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_latest_telemetry() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.device_id, t.weight_g, t.received_at
            FROM telemetry t
            INNER JOIN (
                SELECT device_id, MAX(id) AS max_id FROM telemetry GROUP BY device_id
            ) latest ON t.device_id = latest.device_id AND t.id = latest.max_id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def list_device_states() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT device_id, halted, halted_at FROM device_state").fetchall()
        return [dict(row) for row in rows]

import json
import sqlite3

from app.clock import now_iso


def record(conn: sqlite3.Connection, action: str, target: str | None, detail: dict | None) -> int:
    cur = conn.execute(
        "INSERT INTO activity_log (ts, action, target, detail) VALUES (?,?,?,?)",
        (now_iso(), action, target, json.dumps(detail) if detail is not None else None),
    )
    return int(cur.lastrowid)


def recent(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, action, target, detail FROM activity_log"
        " ORDER BY ts DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "action": r["action"],
            "target": r["target"],
            "detail": json.loads(r["detail"]) if r["detail"] else None,
        }
        for r in rows
    ]

"""SQLite storage. Each table keeps the full object as JSON plus a few columns for lookups."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import settings

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY, group_id TEXT, data TEXT NOT NULL, loaded_at TEXT);
CREATE TABLE IF NOT EXISTS checklists (
  checklist_id TEXT, version INTEGER, data TEXT NOT NULL, created_at TEXT,
  PRIMARY KEY (checklist_id, version));
CREATE TABLE IF NOT EXISTS evaluations (
  evaluation_id TEXT PRIMARY KEY, conversation_id TEXT, checklist_id TEXT,
  checklist_version INTEGER, created_at TEXT, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_eval_conv ON evaluations (conversation_id, created_at);
CREATE TABLE IF NOT EXISTS appeals (
  appeal_id TEXT PRIMARY KEY, evaluation_id TEXT, status TEXT, created_at TEXT, data TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False, timeout=30)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def _all(sql: str, args=()):
    with _lock:
        return _db().execute(sql, args).fetchall()


def _run(sql: str, args=()):
    with _lock:
        db = _db()
        db.execute(sql, args)
        db.commit()


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------- conversations ----------
def upsert_conversations(group_id: str, records: list[dict]) -> None:
    with _lock:
        db = _db()
        db.executemany(
            "INSERT OR REPLACE INTO conversations VALUES (?,?,?,?)",
            [(r["conversation_id"], group_id, _dump({**r, "group_id": group_id}), now()) for r in records],
        )
        db.commit()


def get_conversation(conversation_id: str) -> dict | None:
    rows = _all("SELECT data FROM conversations WHERE conversation_id=?", (conversation_id,))
    return json.loads(rows[0]["data"]) if rows else None


def list_conversations(group_id: str | None = None) -> list[dict]:
    if group_id:
        rows = _all("SELECT data FROM conversations WHERE group_id=? ORDER BY rowid", (group_id,))
    else:
        rows = _all("SELECT data FROM conversations ORDER BY rowid")
    return [json.loads(r["data"]) for r in rows]


def list_groups() -> list[dict]:
    rows = _all("SELECT group_id, COUNT(*) AS n FROM conversations GROUP BY group_id ORDER BY MIN(rowid)")
    return [{"group_id": r["group_id"], "count": r["n"]} for r in rows]


def count_conversations() -> int:
    return _all("SELECT COUNT(*) AS n FROM conversations")[0]["n"]


# ---------- checklists (every save = new version) ----------
def save_checklist(checklist_id: str, data: dict) -> dict:
    with _lock:
        rows = _all("SELECT MAX(version) AS v FROM checklists WHERE checklist_id=?", (checklist_id,))
        version = (rows[0]["v"] or 0) + 1
        data = {**data, "checklist_id": checklist_id, "version": version, "created_at": now()}
        _run("INSERT INTO checklists VALUES (?,?,?,?)", (checklist_id, version, _dump(data), data["created_at"]))
        return data


def get_checklist(checklist_id: str, version: int | None = None) -> dict | None:
    if version:
        rows = _all("SELECT data FROM checklists WHERE checklist_id=? AND version=?", (checklist_id, version))
    else:
        rows = _all("SELECT data FROM checklists WHERE checklist_id=? ORDER BY version DESC LIMIT 1", (checklist_id,))
    return json.loads(rows[0]["data"]) if rows else None


def list_checklists() -> list[dict]:
    rows = _all("SELECT checklist_id, version, created_at, data FROM checklists ORDER BY checklist_id, version")
    out: dict[str, dict] = {}
    for r in rows:
        d = json.loads(r["data"])
        item = out.setdefault(r["checklist_id"], {"checklist_id": r["checklist_id"], "versions": []})
        item["name"] = d.get("name", r["checklist_id"])
        item["latest"] = r["version"]
        item["versions"].append({"version": r["version"], "created_at": r["created_at"],
                                 "criteria": len(d.get("criteria", []))})
    return list(out.values())


def checklist_count() -> int:
    return _all("SELECT COUNT(*) AS n FROM checklists")[0]["n"]


# ---------- evaluations ----------
def save_evaluation(ev: dict) -> dict:
    _run("INSERT OR REPLACE INTO evaluations VALUES (?,?,?,?,?,?)",
         (ev["evaluation_id"], ev["conversation_id"], ev["checklist_id"], ev["checklist_version"],
          ev["created_at"], _dump(ev)))
    return ev


def get_evaluation(evaluation_id: str) -> dict | None:
    rows = _all("SELECT data FROM evaluations WHERE evaluation_id=?", (evaluation_id,))
    return json.loads(rows[0]["data"]) if rows else None


def evaluations_for(conversation_id: str) -> list[dict]:
    rows = _all("SELECT data FROM evaluations WHERE conversation_id=? ORDER BY created_at DESC", (conversation_id,))
    return [json.loads(r["data"]) for r in rows]


def all_evaluations() -> list[dict]:
    rows = _all("SELECT data FROM evaluations ORDER BY created_at")
    return [json.loads(r["data"]) for r in rows]


def has_evaluation(conversation_id: str, checklist_id: str, version: int) -> bool:
    rows = _all("SELECT 1 FROM evaluations WHERE conversation_id=? AND checklist_id=? AND checklist_version=? "
                "AND json_extract(data, '$.usage.provider') != 'mock' LIMIT 1",  # placeholder scores do not count
                (conversation_id, checklist_id, version))
    return bool(rows)


# ---------- appeals ----------
def save_appeal(ap: dict) -> dict:
    _run("INSERT OR REPLACE INTO appeals VALUES (?,?,?,?,?)",
         (ap["appeal_id"], ap["evaluation_id"], ap["status"], ap["created_at"], _dump(ap)))
    return ap


def get_appeal(appeal_id: str) -> dict | None:
    rows = _all("SELECT data FROM appeals WHERE appeal_id=?", (appeal_id,))
    return json.loads(rows[0]["data"]) if rows else None


def list_appeals(status: str | None = None, evaluation_id: str | None = None) -> list[dict]:
    sql, args = "SELECT data FROM appeals WHERE 1=1", []
    if status == "open":
        sql += " AND status='open'"
    elif status == "resolved":
        sql += " AND status!='open'"
    if evaluation_id:
        sql += " AND evaluation_id=?"
        args.append(evaluation_id)
    rows = _all(sql + " ORDER BY created_at DESC", tuple(args))
    return [json.loads(r["data"]) for r in rows]

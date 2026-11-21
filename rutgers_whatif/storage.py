"""Save the audit to JSON and SQLite (both under data/, git-ignored)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .courses import AuditRequirement, TakenCourse

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    source TEXT
);
CREATE TABLE IF NOT EXISTS courses (
    snapshot_id INTEGER REFERENCES snapshots(id),
    code TEXT NOT NULL, title TEXT, credits REAL, grade TEXT, term TEXT, status TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS requirements (
    snapshot_id INTEGER REFERENCES snapshots(id),
    program TEXT, name TEXT, satisfied INTEGER, courses_applied TEXT,
    credits_remaining REAL, raw_status TEXT
);
"""


def save(courses: list[TakenCourse], requirements: list[AuditRequirement], source: str,
         json_path: Path | None = None, db_path: Path | None = None) -> dict:
    json_path = json_path or config.AUDIT_JSON
    db_path = db_path or config.DB_FILE
    json_path.parent.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    audit = {"fetched_at": fetched_at, "source": source,
             "courses": [c.to_dict() for c in courses],
             "requirements": [r.to_dict() for r in requirements]}
    json_path.write_text(json.dumps(audit, indent=2))

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        cur = con.execute("INSERT INTO snapshots (fetched_at, source) VALUES (?, ?)", (fetched_at, source))
        sid = cur.lastrowid
        con.executemany(
            "INSERT INTO courses VALUES (?,?,?,?,?,?,?,?)",
            [(sid, c.code, c.title, c.credits, c.grade, c.term, c.status, c.source) for c in courses])
        con.executemany(
            "INSERT INTO requirements VALUES (?,?,?,?,?,?,?)",
            [(sid, r.program, r.name, None if r.satisfied is None else int(r.satisfied),
              json.dumps(r.courses_applied), r.credits_remaining, r.raw_status) for r in requirements])
        con.commit()
    finally:
        con.close()
    return audit


def load_courses(json_path: Path | None = None) -> list[TakenCourse]:
    json_path = json_path or config.AUDIT_JSON
    if not json_path.exists():
        raise FileNotFoundError(
            "No courses loaded yet. Run Discover and then Scrape (or import a course CSV) first. "
            f"(Looked for {json_path}.)")
    data = json.loads(json_path.read_text())
    return [TakenCourse.from_dict(c) for c in data.get("courses", [])]


def import_courses(path: Path) -> list[TakenCourse]:
    """Read courses from a CSV (code,title,credits,grade,term) or JSON list."""
    import csv

    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text())
        rows = rows.get("courses", rows) if isinstance(rows, dict) else rows
    else:
        with path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        r = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
        if r.get("credits") in ("", None):
            r["credits"] = None
        else:
            r["credits"] = float(r["credits"])
        r["source"] = "import"
        out.append(TakenCourse.from_dict(r))
    return out

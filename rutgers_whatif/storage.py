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


def load_manual() -> list[TakenCourse]:
    """Courses you added by hand (e.g. AP credit). Kept separate so re-scraping never erases them."""
    path = config.MANUAL_FILE
    if not path.exists():
        return []
    return [TakenCourse.from_dict({**c, "source": "manual"}) for c in json.loads(path.read_text())]


def _write_manual(courses: list[TakenCourse]) -> None:
    config.MANUAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.MANUAL_FILE.write_text(json.dumps([c.to_dict() for c in courses], indent=2))


def add_manual(code: str, grade: str = "T", credits: float | None = None, title: str = "",
               term: str | None = "AP", transfer: bool = True) -> TakenCourse:
    from .courses import normalize_code

    norm = normalize_code(code)
    if not norm:
        raise ValueError(f"{code!r} isn't a course code like 01:640:151")
    course = TakenCourse(code=norm, title=title, credits=credits, grade=grade or "T", term=term,
                         source="manual", transfer=transfer)
    rest = [c for c in load_manual() if not (c.code == norm and c.term == term)]
    _write_manual(rest + [course])
    return course


def ap_table() -> dict:
    from .requirements import PROGRAM_DIR
    return json.loads((PROGRAM_DIR / "ap_credit.json").read_text())


def add_ap_exam(exam: str, score: int) -> list[TakenCourse]:
    """Add the Rutgers courses an AP exam + score earns (SAS table)."""
    table = ap_table()
    match = next((e for e in table["exams"] if e["exam"].lower() == exam.strip().lower()), None)
    if match is None:
        raise ValueError(f"Unknown AP exam {exam!r}. Known: {', '.join(e['exam'] for e in table['exams'])}")
    awards = match["awards"].get(str(int(score)))
    if not awards:
        raise ValueError(f"A score of {score} on AP {match['exam']} earns no Rutgers credit (SAS gives credit for 4 and 5).")
    total = match["credits"][str(int(score))]
    each = round(total / len(awards), 2)
    return [add_manual(code, grade="T", credits=each, term=f"AP {match['exam']} ({score})") for code in awards]


def remove_manual(code: str) -> int:
    from .courses import normalize_code

    norm = normalize_code(code) or code
    before = load_manual()
    after = [c for c in before if c.code != norm]
    _write_manual(after)
    return len(before) - len(after)


def load_courses(json_path: Path | None = None) -> list[TakenCourse]:
    """Scraped/imported courses plus anything you added by hand."""
    json_path = json_path or config.AUDIT_JSON
    manual = load_manual()
    if not json_path.exists():
        if manual:
            return manual
        raise FileNotFoundError(
            "No courses loaded yet. Run Discover and then Scrape (or import a course CSV), "
            f"or add AP/transfer credit by hand. (Looked for {json_path}.)")
    data = json.loads(json_path.read_text())
    return [TakenCourse.from_dict(c) for c in data.get("courses", [])] + manual


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

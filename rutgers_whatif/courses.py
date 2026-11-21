"""Course codes, grades and terms: the small vocabulary everything else shares."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# 01:198:111  (school:subject:number). Also accept "198:111" (assumes school 01).
CODE_RE = re.compile(r"\b(\d{2}):(\d{3}):(\d{3}[A-Z]?)\b")
SHORT_CODE_RE = re.compile(r"(?<![:\d])(\d{3}):(\d{3})(?![:\d])")

GRADE_POINTS = {"A": 4.0, "B+": 3.5, "B": 3.0, "C+": 2.5, "C": 2.0, "D": 1.0, "F": 0.0}
PASS_GRADES = {"P", "PA", "S", "T", "TR", "TZ", "CR"}           # pass / transfer / credit by exam
NO_CREDIT = {"F", "W", "NC", "U", "INC", "IN", "WF", "NG", "AU", "R"}
IN_PROGRESS = {"", "IP", "PR", "TBA", "*", "-", "CURRENT", "IN PROGRESS", "REG", "REGISTERED"}

GRADE_TOKEN_RE = re.compile(r"^(A|B\+|B|C\+|C|D|F|P|PA|S|U|W|NC|T|TR|TZ|CR|INC|IP|PR)$")

# Text that marks a row as AP / test / transfer credit rather than a Rutgers class.
TRANSFER_RE = re.compile(
    r"\b(AP|A\.P\.|advanced\s+placement|transfer(?:red)?|test\s+credit|credit\s+by\s+exam(?:ination)?|"
    r"exam\s+credit|IB|international\s+baccalaureate|CLEP|dual\s+enrollment|TR|TZ)\b", re.I)
TRANSFER_GRADES = {"T", "TR", "TZ", "CR"}

TERM_NAMES = {"0": "Winter", "1": "Spring", "7": "Summer", "9": "Fall"}
TERM_RE = re.compile(
    r"\b(?:(Fall|Spring|Summer|Winter)\s*(\d{4})|(\d{4})\s*(Fall|Spring|Summer|Winter)|(\d{4})\s*([0179])\b)",
    re.I,
)


def normalize_code(text: str) -> str | None:
    m = CODE_RE.search(text or "")
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
    m = SHORT_CODE_RE.search(text or "")
    if m:
        return f"01:{m.group(1)}:{m.group(2)}"
    return None


def find_codes(text: str) -> list[str]:
    seen: list[str] = []
    for m in CODE_RE.finditer(text or ""):
        c = f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
        if c not in seen:
            seen.append(c)
    return seen


def normalize_term(text: str) -> str | None:
    m = TERM_RE.search(text or "")
    if not m:
        return None
    if m.group(1):
        return f"{m.group(1).title()} {m.group(2)}"
    if m.group(3):
        return f"{m.group(4).title()} {m.group(3)}"
    return f"{TERM_NAMES[m.group(6)]} {m.group(5)}"


def normalize_grade(text: str | None) -> str:
    g = (text or "").strip().upper()
    return g


def grade_status(grade: str | None) -> str:
    """'passed', 'in_progress' or 'failed' (F/W/NC etc.)."""
    g = normalize_grade(grade)
    if g in IN_PROGRESS:
        return "in_progress"
    if g in NO_CREDIT:
        return "failed"
    if g in GRADE_POINTS or g in PASS_GRADES:
        return "passed"
    return "passed"  # unknown codes: assume earned credit, but keep the raw grade visible


def meets_min_grade(grade: str, min_grade: str | None) -> bool:
    """Letter grades are compared by points; pass/transfer grades meet any minimum."""
    if not min_grade:
        return True
    g = normalize_grade(grade)
    if g in PASS_GRADES:
        return True
    if g not in GRADE_POINTS:
        return True
    return GRADE_POINTS[g] >= GRADE_POINTS[min_grade]


def level(code: str) -> int:
    """Course level, e.g. 01:198:344 -> 300."""
    num = re.match(r"\d+", code.split(":")[2]).group(0)
    return (int(num) // 100) * 100


def subject(code: str) -> str:
    return ":".join(code.split(":")[:2])


@dataclass
class TakenCourse:
    code: str
    title: str = ""
    credits: float | None = None
    grade: str = ""
    term: str | None = None
    source: str = "degree_navigator"
    transfer: bool = False          # AP / test / transfer credit

    def __post_init__(self):
        if normalize_grade(self.grade) in TRANSFER_GRADES:
            self.transfer = True
        if self.transfer and not normalize_grade(self.grade):
            self.grade = "T"        # credit already earned; never "in progress"

    @property
    def status(self) -> str:
        return grade_status(self.grade)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TakenCourse":
        return cls(code=normalize_code(d["code"]) or d["code"], title=d.get("title", ""),
                   credits=d.get("credits"), grade=d.get("grade", "") or "",
                   term=d.get("term"), source=d.get("source", "import"),
                   transfer=bool(d.get("transfer")) or bool(TRANSFER_RE.search(str(d.get("term") or ""))))


@dataclass
class AuditRequirement:
    program: str
    name: str
    satisfied: bool | None
    courses_applied: list[str] = field(default_factory=list)
    credits_remaining: float | None = None
    raw_status: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

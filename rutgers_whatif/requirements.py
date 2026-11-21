"""Program requirement definitions + an evaluator.

Definitions live in ``rutgers_whatif/programs/*.json`` (one file per major or
minor), condensed from the official department pages. Each requirement is
one of:

* ``all``      – every listed course, e.g. the CS core.
* ``choose``   – ``count`` courses from ``from`` selectors, optionally with
                 ``rules`` such as {"min": 2, "from": ["01:198:3xx", "01:198:4xx"]}
                 or {"max": 1, "from": ["01:198:493", "01:198:494"]}.
* ``one_set``  – complete any one of several course sets (e.g. a physics sequence).

Selectors are exact codes ("01:640:250"), wildcards ("01:640:3xx",
"01:198:*"), and may be negated with ``exclude``. Codes listed together in
``equivalents.json`` satisfy each other (e.g. old CS 111 for new CS 121).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .courses import TakenCourse, grade_status, meets_min_grade, normalize_grade

PROGRAM_DIR = Path(__file__).parent / "programs"
GRADE_RANK = {"A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 1}


# ------------------------------------------------------------------ loading

@lru_cache(maxsize=1)
def equivalence_groups() -> dict[str, frozenset[str]]:
    path = PROGRAM_DIR / "equivalents.json"
    groups: dict[str, frozenset[str]] = {}
    if path.exists():
        for grp in json.loads(path.read_text())["groups"]:
            fs = frozenset(grp["codes"])
            for c in fs:
                groups[c] = groups.get(c, frozenset()) | fs
    return groups


def load_programs(directory: Path = PROGRAM_DIR) -> dict[str, dict]:
    progs = {}
    for f in sorted(directory.glob("*.json")):
        if f.name in ("equivalents.json", "ap_credit.json"):
            continue
        p = json.loads(f.read_text())
        progs[p["id"]] = p
    return progs


# ------------------------------------------------------------------ matching

def _pattern_re(sel: str) -> re.Pattern:
    s = re.escape(sel).replace(r"\*", r"[^\s]*")
    s = re.sub(r"x", r"\\d", s)
    return re.compile(f"^{s}[A-Z]?$")


@lru_cache(maxsize=4096)
def _compiled(sel: str) -> re.Pattern:
    return _pattern_re(sel)


def matches(code: str, selector: str) -> bool:
    if "x" in selector or "*" in selector:
        return bool(_compiled(selector).match(code))
    if code == selector:
        return True
    return code in equivalence_groups().get(selector, ())


def matches_any(code: str, selectors: list[str], exclude: list[str] | None = None) -> bool:
    if exclude and any(matches(code, e) for e in exclude):
        return False
    return any(matches(code, s) for s in selectors)


# ------------------------------------------------------------------ results

@dataclass
class ReqResult:
    id: str
    name: str
    satisfied: bool
    satisfied_with_in_progress: bool
    applied: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    still_needed: list[str] = field(default_factory=list)   # human-readable
    missing_courses: list[str] = field(default_factory=list)  # specific codes you still need
    courses_remaining: int = 0
    credits_remaining: float = 0.0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ProgramResult:
    id: str
    name: str
    kind: str
    requirements: list[ReqResult]
    applied: list[str]
    d_grades_used: int

    @property
    def satisfied(self) -> bool:
        return all(r.satisfied for r in self.requirements)

    @property
    def courses_remaining(self) -> int:
        return sum(r.courses_remaining for r in self.requirements)

    @property
    def credits_remaining(self) -> float:
        return sum(r.credits_remaining for r in self.requirements)

    @property
    def met(self) -> int:
        return sum(r.satisfied for r in self.requirements)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "satisfied": self.satisfied,
                "requirements_met": self.met, "requirements_total": len(self.requirements),
                "courses_remaining": self.courses_remaining, "credits_remaining": self.credits_remaining,
                "applied": self.applied, "d_grades_used": self.d_grades_used,
                "requirements": [r.to_dict() for r in self.requirements]}


# ------------------------------------------------------------------ evaluation

def best_attempts(courses: list[TakenCourse]) -> dict[str, TakenCourse]:
    """One record per course code: the best passed attempt, else an in-progress one."""
    best: dict[str, TakenCourse] = {}

    def rank(c: TakenCourse) -> tuple:
        st = c.status
        return ({"passed": 2, "in_progress": 1, "failed": 0}[st], GRADE_RANK.get(normalize_grade(c.grade), 5))

    for c in courses:
        if c.code not in best or rank(c) > rank(best[c.code]):
            best[c.code] = c
    return {k: v for k, v in best.items() if v.status != "failed"}


class _Pool:
    def __init__(self, attempts: dict[str, TakenCourse], policy: dict, include_ip: bool):
        self.attempts = attempts
        self.min_grade = policy.get("min_grade")
        self.max_d = policy.get("max_d", 99)
        self.d_used = 0
        self.used: set[str] = set()
        self.include_ip = include_ip

    def candidates(self, pred, allow_d: bool = True) -> list[TakenCourse]:
        out = []
        for code, c in sorted(self.attempts.items()):
            if code in self.used or not pred(code):
                continue
            if c.status == "in_progress" and not self.include_ip:
                continue
            out.append(c)
        # non-D, completed courses first; in-progress last
        out.sort(key=lambda c: (c.status == "in_progress", self.is_d(c), c.code))
        return [c for c in out if self.usable(c, allow_d)]

    def is_d(self, c: TakenCourse) -> bool:
        return c.status == "passed" and normalize_grade(c.grade) == "D"

    def usable(self, c: TakenCourse, allow_d: bool = True) -> bool:
        if c.status == "in_progress":
            return True
        if self.is_d(c):
            return allow_d and self.d_used < self.max_d
        return meets_min_grade(c.grade, self.min_grade)

    def take(self, c: TakenCourse) -> None:
        self.used.add(c.code)
        if self.is_d(c):
            self.d_used += 1


def _credits(code: str, catalog: dict, default: float) -> float:
    c = catalog.get(code) or {}
    cr = c.get("credits")
    return float(cr) if isinstance(cr, (int, float)) and cr else default


def _eval_req(req: dict, pool: _Pool, catalog: dict, default_cr: float) -> tuple[list[TakenCourse], list[str], list[str], int, float]:
    """Returns (taken, still_needed text, missing codes, courses remaining, credits remaining)."""
    allow_d = not req.get("no_d", False)
    kind = req["type"]

    if kind == "all":
        taken, missing = [], []
        for code in req["courses"]:
            cands = pool.candidates(lambda c, code=code: matches(c, code), allow_d)
            if cands:
                pool.take(cands[0])
                taken.append(cands[0])
            else:
                missing.append(code)
        cr = sum(_credits(c, catalog, default_cr) for c in missing)
        return taken, [f"{c} {(catalog.get(c) or {}).get('title', '')}".strip() for c in missing], missing, len(missing), cr

    if kind == "one_set":
        best = None
        for s in req["sets"]:
            have = [code for code in s if pool.candidates(lambda c, code=code: matches(c, code), allow_d)]
            miss = [code for code in s if code not in have]
            if best is None or len(miss) < len(best[1]):
                best = (s, miss)
        s, miss = best
        taken = []
        for code in s:
            cands = pool.candidates(lambda c, code=code: matches(c, code), allow_d)
            if cands:
                pool.take(cands[0])
                taken.append(cands[0])
        cr = sum(_credits(c, catalog, default_cr) for c in miss)
        need = [f"finish set {', '.join(s)}: still need {', '.join(miss)}"] if miss else []
        return taken, need, miss, len(miss), cr

    if kind == "choose":
        count = req["count"]
        sel, excl = req["from"], req.get("exclude", [])
        rules = req.get("rules", [])
        taken: list[TakenCourse] = []

        def rule_room(code: str) -> bool:
            for r in rules:
                if "max" in r and matches_any(code, r["from"]):
                    if sum(matches_any(t.code, r["from"]) for t in taken) >= r["max"]:
                        return False
            return True

        def pick(pred, n):
            got = 0
            for c in pool.candidates(lambda code: matches_any(code, sel, excl) and pred(code), allow_d):
                if got >= n or len(taken) >= count:
                    break
                if not pool.usable(c, allow_d) or not rule_room(c.code):
                    continue
                pool.take(c)
                taken.append(c)
                got += 1

        for r in rules:
            if "min" in r:
                have = sum(matches_any(t.code, r["from"]) for t in taken)
                pick(lambda code, r=r: matches_any(code, r["from"]), r["min"] - have)
        pick(lambda code: True, count - len(taken))

        need = []
        remaining = count - len(taken)
        rule_short = 0
        for r in rules:
            if "min" in r:
                have = sum(matches_any(t.code, r["from"]) for t in taken)
                if have < r["min"]:
                    rule_short = max(rule_short, r["min"] - have)
                    need.append(f"{r['min'] - have} more from {', '.join(r['from'])}"
                                + (f" ({r['label']})" if r.get("label") else ""))
        remaining = max(remaining, rule_short)
        if count - len(taken) > 0:
            need.insert(0, f"{count - len(taken)} more course(s) from: {req.get('label') or ', '.join(sel)}")
        cr = remaining * req.get("credits_each", default_cr)
        return taken, need, [], remaining, cr

    raise ValueError(f"Unknown requirement type {kind!r}")


def evaluate(program: dict, courses: list[TakenCourse], catalog: dict | None = None) -> ProgramResult:
    catalog = catalog or {}
    attempts = best_attempts(courses)
    policy = program.get("grade_policy", {})
    default_cr = program.get("default_credits", 3)

    results: list[ReqResult] = []
    pool_done = _Pool(attempts, policy, include_ip=False)
    pool_ip = _Pool(attempts, policy, include_ip=True)
    for req in program["requirements"]:
        done, need, missing, n_left, cr_left = _eval_req(req, pool_done, catalog, default_cr)
        with_ip, need_ip, *_ = _eval_req(req, pool_ip, catalog, default_cr)
        results.append(ReqResult(
            id=req["id"], name=req["name"], satisfied=not need, satisfied_with_in_progress=not need_ip,
            applied=[c.code for c in done],
            in_progress=[c.code for c in with_ip if c.status == "in_progress"],
            still_needed=need, missing_courses=missing, courses_remaining=n_left,
            credits_remaining=cr_left))
    applied = sorted({c for r in results for c in r.applied})
    return ProgramResult(program["id"], program["name"], program.get("kind", "major"), results,
                         applied, pool_done.d_used)

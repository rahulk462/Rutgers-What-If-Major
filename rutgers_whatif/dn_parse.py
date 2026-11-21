"""Turn captured Degree Navigator pages (HTML or JSON) into structured data.

Degree Navigator's markup isn't documented, so this parser is deliberately
heuristic: it looks for tables that have course + grade columns, and for
blocks of the audit that look like requirements (a name plus a
complete/incomplete status). If your pages don't parse well, put CSS
selectors in data/dn_selectors.json (see README) and they take priority.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup, Tag

from .courses import (GRADE_TOKEN_RE, TRANSFER_RE, AuditRequirement, TakenCourse, find_codes,
                      normalize_code, normalize_term)

SATISFIED_RE = re.compile(r"\b(complete[d]?|satisfied|fulfilled|met|done)\b", re.I)
UNSATISFIED_RE = re.compile(
    r"\b(not\s+(?:yet\s+)?(?:complete[d]?|satisfied|fulfilled|met)|incomplete|unsatisfied|in\s*progress|still\s+needed|needs?)\b",
    re.I,
)
CREDITS_LEFT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:more\s+)?(?:credits?|cr\.?)\s*(?:are\s+)?(?:remaining|needed|still\s+needed|required|left)", re.I)
NEEDS_CREDITS_RE = re.compile(r"(?:need|needs|remaining)[:\s]+(\d+(?:\.\d+)?)\s*(?:credits?|cr)", re.I)
REQ_NAME_RE = re.compile(r"^\s*(R\d+[A-Za-z]?\b|Requirement\b|Req\.?\s*\d+)", re.I)
CREDIT_CELL_RE = re.compile(r"^\d+(?:\.\d+)?$")


def load_selectors(path: Path | None) -> dict:
    if path and path.exists():
        return json.loads(path.read_text())
    return {}


def _text(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def _block_text(el: Tag | None) -> str:
    """Text plus image alt/title, since status is often shown as an icon."""
    if el is None:
        return ""
    alts = [img.get("alt") or img.get("title") or "" for img in el.find_all("img")]
    return " ".join([_text(el)] + [a for a in alts if a])


def status_from_text(text: str) -> bool | None:
    if UNSATISFIED_RE.search(text):
        return False
    if SATISFIED_RE.search(text):
        return True
    return None


def credits_remaining_from_text(text: str) -> float | None:
    m = CREDITS_LEFT_RE.search(text) or NEEDS_CREDITS_RE.search(text)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------- courses

def _header_map(cells: list[str]) -> dict[str, int]:
    names = {"code": ("course", "number", "course #", "course id", "subject"),
             "title": ("title", "description", "name"),
             "credits": ("credit", "cr", "hours", "units"),
             "grade": ("grade",),
             "term": ("term", "semester", "taken", "year")}
    out: dict[str, int] = {}
    for i, raw in enumerate(cells):
        c = raw.lower()
        for key, words in names.items():
            if key not in out and any(w == c or c.startswith(w) or w in c.split() for w in words):
                out[key] = i
                break
    return out


def _table_context(table: Tag) -> str:
    """Caption / nearest heading above a table, e.g. 'Transfer and Test Credit'."""
    parts = []
    cap = table.find("caption")
    if cap:
        parts.append(_text(cap))
    prev = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6", "legend", "strong", "b", "th"])
    if prev is not None and not (prev.name == "th" and table in prev.parents):
        parts.append(_text(prev))
    return " ".join(parts)


def parse_course_tables(soup: BeautifulSoup) -> list[TakenCourse]:
    found: list[TakenCourse] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = [_text(c) for c in rows[0].find_all(["th", "td"])]
        hmap = _header_map(header_cells)
        context = _table_context(table) + " " + " ".join(header_cells)
        transfer_table = bool(TRANSFER_RE.search(context))
        if "grade" not in hmap and not transfer_table:
            continue
        for row in rows[1:]:
            cells = [_text(c) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            code = normalize_code(cells[hmap["code"]] if "code" in hmap and hmap["code"] < len(cells) else " ".join(cells))
            if not code:
                code = normalize_code(" ".join(cells))
            if not code:
                continue
            grade = cells[hmap["grade"]] if "grade" in hmap and hmap["grade"] < len(cells) else ""
            credits = None
            if "credits" in hmap and hmap["credits"] < len(cells) and CREDIT_CELL_RE.match(cells[hmap["credits"]]):
                credits = float(cells[hmap["credits"]])
            term_cell = cells[hmap["term"]] if "term" in hmap and hmap["term"] < len(cells) else ""
            title = cells[hmap["title"]] if "title" in hmap and hmap["title"] < len(cells) else ""
            other = " ".join(c for i, c in enumerate(cells) if i not in (hmap.get("title"), hmap.get("code")))
            transfer = transfer_table or bool(TRANSFER_RE.search(other)) or grade.strip().upper() in ("T", "TR", "TZ")
            term = normalize_term(term_cell) or (term_cell.strip()[:40] if transfer and term_cell.strip() else None)
            found.append(TakenCourse(code=code, title=title, credits=credits, grade=grade.strip(), term=term,
                                     transfer=transfer))
    return found


def parse_course_lines(text: str) -> list[TakenCourse]:
    """Fallback for non-tabular pages: lines like '01:198:111 INTRO CS 4.0 A Fall 2024'."""
    out: list[TakenCourse] = []
    for line in text.splitlines():
        code = normalize_code(line)
        if not code:
            continue
        tokens = line.replace(code, " ").split()
        grade = next((t for t in reversed(tokens) if GRADE_TOKEN_RE.match(t.upper())), "")
        credits = next((float(t) for t in tokens if CREDIT_CELL_RE.match(t) and float(t) <= 12), None)
        out.append(TakenCourse(code=code, grade=grade, credits=credits, term=normalize_term(line),
                               transfer=bool(TRANSFER_RE.search(line.replace(code, " ")))))
    return out


# ---------------------------------------------------------------- requirements

def _requirement_blocks(soup: BeautifulSoup, sel: dict) -> Iterable[Tag]:
    if sel.get("requirement_block"):
        yield from soup.select(sel["requirement_block"])
        return
    seen: set[int] = set()
    for el in soup.find_all(string=REQ_NAME_RE):
        block = el.parent
        # climb to the smallest ancestor that also contains a status word or course codes
        for _ in range(4):
            if block is None or block.parent is None:
                break
            txt = _block_text(block)
            if (SATISFIED_RE.search(txt) or UNSATISFIED_RE.search(txt)) and len(txt) > len(el.strip()) + 5:
                break
            block = block.parent
        if block is not None and id(block) not in seen:
            seen.add(id(block))
            yield block


def _first_line(block: Tag) -> str:
    for s in block.stripped_strings:
        if REQ_NAME_RE.match(s):
            return s[:120]
    return next(block.stripped_strings, "")[:120]


def parse_requirements(soup: BeautifulSoup, program: str, sel: dict | None = None) -> list[AuditRequirement]:
    sel = sel or {}
    reqs: list[AuditRequirement] = []
    for block in _requirement_blocks(soup, sel):
        name_el = block.select_one(sel["requirement_name"]) if sel.get("requirement_name") else None
        full = _block_text(block)
        name = _text(name_el) if name_el else _first_line(block)
        status_el = block.select_one(sel["status"]) if sel.get("status") else None
        status_text = _text(status_el) if status_el else full
        if status_el is not None and status_el.name == "img":
            status_text = status_el.get("alt", "") or status_el.get("title", "")
        reqs.append(AuditRequirement(
            program=program, name=name, satisfied=status_from_text(status_text),
            courses_applied=find_codes(full), credits_remaining=credits_remaining_from_text(full),
            raw_status=status_text[:200]))
    return reqs


def program_name(soup: BeautifulSoup, fallback: str) -> str:
    for tag in ("h1", "h2", "h3"):
        h = soup.find(tag)
        if h and _text(h):
            return _text(h)[:120]
    return fallback


def parse_html(html: str, source: str = "", selectors: dict | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    courses = parse_course_tables(soup)
    if not courses:
        courses = parse_course_lines(soup.get_text("\n"))
    prog = program_name(soup, source)
    return {"program": prog, "courses": courses, "requirements": parse_requirements(soup, prog, selectors)}


# ---------------------------------------------------------------- JSON

KEY_HINTS = {
    "code": ("coursecode", "coursenumber", "courseid", "coursestring", "course"),
    "grade": ("grade", "finalgrade"),
    "term": ("term", "semester", "termdesc"),
    "credits": ("credits", "credit", "credithours", "units"),
    "title": ("title", "coursetitle", "description"),
    "req_name": ("requirementname", "reqname", "requirement", "name", "title", "description"),
    "status": ("satisfied", "complete", "completed", "status", "met", "isfulfilled", "fulfilled"),
}


def _pick(d: dict, key: str) -> Any:
    lowered = {k.lower().replace("_", ""): v for k, v in d.items()}
    for hint in KEY_HINTS[key]:
        if hint in lowered and not isinstance(lowered[hint], (dict, list)):
            return lowered[hint]
    return None


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def parse_json(payload: Any, program: str = "") -> dict:
    """Generic walk over a JSON payload looking for course rows and requirement rows."""
    courses: list[TakenCourse] = []
    reqs: list[AuditRequirement] = []
    for d in _walk(payload):
        code_val = _pick(d, "code")
        code = normalize_code(str(code_val)) if code_val is not None else None
        grade = _pick(d, "grade")
        if code and grade is not None:
            cr = _pick(d, "credits")
            try:
                cr = float(cr) if cr not in (None, "") else None
            except (TypeError, ValueError):
                cr = None
            term_raw = str(_pick(d, "term") or "")
            courses.append(TakenCourse(code=code, title=str(_pick(d, "title") or ""), credits=cr,
                                       grade=str(grade), term=normalize_term(term_raw) or (term_raw[:40] or None),
                                       transfer=bool(TRANSFER_RE.search(" ".join(
                                           str(v) for k, v in d.items() if not isinstance(v, (dict, list))
                                           and "title" not in k.lower())))))
            continue
        status = _pick(d, "status")
        name = _pick(d, "req_name")
        if status is not None and name and not code:
            sat = status if isinstance(status, bool) else status_from_text(str(status))
            reqs.append(AuditRequirement(program=program, name=str(name)[:120], satisfied=sat,
                                         courses_applied=find_codes(json.dumps(d)),
                                         credits_remaining=credits_remaining_from_text(json.dumps(d)),
                                         raw_status=str(status)[:200]))
    return {"program": program, "courses": courses, "requirements": reqs}


def dedupe_courses(courses: Iterable[TakenCourse]) -> list[TakenCourse]:
    """Keep one row per (code, term); prefer rows that carry more information."""
    best: dict[tuple, TakenCourse] = {}
    for c in courses:
        key = (c.code, c.term)
        cur = best.get(key)
        score = sum(bool(x) for x in (c.title, c.credits, c.grade, c.term))
        if cur is None or score > sum(bool(x) for x in (cur.title, cur.credits, cur.grade, cur.term)):
            best[key] = c
    return list(best.values())

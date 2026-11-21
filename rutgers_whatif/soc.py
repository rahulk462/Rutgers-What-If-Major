"""Public Rutgers Schedule of Classes API: course titles, credits, prerequisites.

    https://sis.rutgers.edu/soc/api/courses.json?year=2026&term=1&campus=NB
    term codes: 0 winter, 1 spring, 7 summer, 9 fall

One request returns every course in the term (~4,500 for NB), so we fetch
each term once, cache it in data/soc/, and keep only the fields we need in
a slim index (data/soc/index.json) that merges all cached terms.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .throttle import Throttle

SLIM_FIELDS = ("courseString", "title", "expandedTitle", "credits", "preReqNotes", "subject",
               "courseNumber", "offeringUnitCode", "coreCodes", "level")


def term_code(term: str | int) -> int:
    if isinstance(term, int) or str(term).isdigit():
        code = int(term)
        if code not in config.TERM_CODES.values():
            raise ValueError(f"Unknown term code {term}; use 0, 1, 7 or 9")
        return code
    return config.TERM_CODES[str(term).lower()]


def cache_path(year: int, term: int, campus: str = "NB") -> Path:
    return config.SOC_DIR / f"{year}_{term}_{campus}.json"


def fetch_term(year: int, term: str | int, campus: str = "NB", force: bool = False,
               throttle: Throttle | None = None) -> Path:
    import httpx

    config.ensure_dirs()
    t = term_code(term)
    path = cache_path(year, t, campus)
    if path.exists() and not force:
        return path
    (throttle or Throttle()).wait()
    resp = httpx.get(config.SOC_API, params={"year": year, "term": t, "campus": campus},
                     headers={"User-Agent": config.USER_AGENT}, timeout=120)
    resp.raise_for_status()
    courses = resp.json()
    slim = [slim_course(c) for c in courses]
    path.write_text(json.dumps(slim))
    build_index()
    return path


def slim_course(c: dict) -> dict:
    out = {k: c.get(k) for k in SLIM_FIELDS}
    out["title"] = (c.get("expandedTitle") or c.get("title") or "").strip() or (c.get("title") or "").strip()
    out["coreCodes"] = sorted({cc.get("code") or cc.get("coreCode") for cc in (c.get("coreCodes") or [])} - {None})
    out.pop("expandedTitle", None)
    return out


def build_index() -> dict:
    """Merge every cached term into one {courseString: course} map (newest term wins)."""
    index: dict[str, dict] = {}
    files = sorted(config.SOC_DIR.glob("*_*_*.json"),
                   key=lambda p: (int(p.stem.split("_")[0]), [0, 1, 7, 9].index(int(p.stem.split("_")[1]))))
    for f in files:
        for c in json.loads(f.read_text()):
            c["lastOffered"] = f.stem
            index[c["courseString"]] = c
    (config.SOC_DIR / "index.json").write_text(json.dumps(index))
    return index


def load_index() -> dict:
    p = config.SOC_DIR / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}

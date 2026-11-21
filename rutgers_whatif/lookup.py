"""Course lookup: what you need before a course, and which programs it counts toward.

Useful whether or not you've declared a major: pick any course and see its
prerequisites, whether you meet them, the shortest chain of courses still
missing, and which majors/minors it would count for.
"""

from __future__ import annotations

from . import prereqs
from .courses import normalize_code
from .requirements import matches, matches_any


def _missing_for(node, passed: set[str], catalog: dict) -> list[str]:
    """Courses you still need to satisfy ``node`` (picks the cheapest OR branch)."""
    if node is None or prereqs.satisfied(node, passed):
        return []
    if isinstance(node, prereqs.Course):
        return [node.code]
    if node.op == "and":
        out: list[str] = []
        for ch in node.children:
            for c in _missing_for(ch, passed, catalog):
                if c not in out:
                    out.append(c)
        return out
    options = [_missing_for(ch, passed, catalog) for ch in node.children]

    def cost(opt):  # fewest courses; prefer ones offered at NB (in the SOC data)
        return (len(opt), sum(c not in catalog for c in opt))
    return min(options, key=cost)


def prerequisite_path(code: str, passed: set[str], catalog: dict, max_depth: int = 6) -> list[str]:
    """All courses to take before ``code``, earliest first (based on the cheapest branches)."""
    order: list[str] = []
    seen: set[str] = set()

    def visit(c: str, depth: int) -> None:
        if depth > max_depth or c in seen:
            return
        seen.add(c)
        tree = prereqs.parse((catalog.get(c) or {}).get("preReqNotes") or "")
        for need in _missing_for(tree, passed, catalog):
            visit(need, depth + 1)
            if need not in order:
                order.append(need)

    visit(code, 0)
    return order


def counts_toward(code: str, programs: dict) -> list[dict]:
    out = []
    for pid, p in programs.items():
        for req in p["requirements"]:
            if req["type"] == "all":
                hit = any(matches(code, c) for c in req["courses"])
            elif req["type"] == "one_set":
                hit = any(matches(code, c) for s in req["sets"] for c in s)
            else:
                hit = matches_any(code, req["from"], req.get("exclude"))
            if hit:
                out.append({"program": pid, "program_name": p["name"], "requirement": req["name"]})
                break
    return out


def describe(code: str, catalog: dict, programs: dict, passed: set[str]) -> dict:
    code = normalize_code(code) or code
    info = catalog.get(code) or {}
    tree = prereqs.parse(info.get("preReqNotes") or "")
    path = prerequisite_path(code, passed, catalog)
    return {
        "code": code,
        "title": info.get("title", ""),
        "credits": info.get("credits"),
        "known": code in catalog,
        "taken": code in passed,
        "prereqs": prereqs.to_text(tree),
        "ready": prereqs.satisfied(tree, passed),
        "path": [{"code": c, "title": (catalog.get(c) or {}).get("title", ""),
                  "ready": prereqs.satisfied(prereqs.parse((catalog.get(c) or {}).get("preReqNotes") or ""), passed)}
                 for c in path],
        "counts_toward": counts_toward(code, programs),
    }


def search(query: str, catalog: dict, limit: int = 20) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    code = normalize_code(query)
    hits = []
    for c, info in catalog.items():
        title = (info.get("title") or "").lower()
        if (code and c == code) or q in c or q in title:
            hits.append({"code": c, "title": info.get("title", "")})
    hits.sort(key=lambda h: (h["code"] != code, not h["code"].startswith("01:"), h["code"]))
    return hits[:limit]

"""Compare what's left across programs, and what changes if you switch or add one."""

from __future__ import annotations

from . import prereqs
from .courses import TakenCourse
from .requirements import ProgramResult, best_attempts, evaluate


def passed_codes(courses: list[TakenCourse], include_in_progress: bool = False) -> set[str]:
    ok = {"passed", "in_progress"} if include_in_progress else {"passed"}
    return {c.code for c in best_attempts(courses).values() if c.status in ok}


def prereq_status(code: str, catalog: dict, passed: set[str]) -> dict:
    notes = (catalog.get(code) or {}).get("preReqNotes") or ""
    tree = prereqs.parse(notes)
    return {"code": code, "ready": prereqs.satisfied(tree, passed),
            "prereqs": prereqs.to_text(tree), "known": code in catalog}


def compare(programs: dict[str, dict], ids: list[str], courses: list[TakenCourse],
            catalog: dict | None = None, current: list[str] | None = None) -> dict:
    """Evaluate each program in ``ids``; if ``current`` is given, add switch/add deltas."""
    catalog = catalog or {}
    passed = passed_codes(courses)
    ids = list(dict.fromkeys((current or []) + ids))
    results: dict[str, ProgramResult] = {pid: evaluate(programs[pid], courses, catalog) for pid in ids}

    current_missing: set[str] = set()
    current_left = 0
    current_cr = 0.0
    for pid in current or []:
        r = results[pid]
        current_missing |= {c for req in r.requirements for c in req.missing_courses}
        current_left += r.courses_remaining
        current_cr += r.credits_remaining

    rows = []
    for pid in ids:
        r = results[pid]
        missing = sorted({c for req in r.requirements for c in req.missing_courses})
        row = r.to_dict()
        row["next_courses"] = [prereq_status(c, catalog, passed) for c in missing]
        if current and pid not in current:
            current_applied = {c for cid in current for c in results[cid].applied}
            row["overlap_with_current"] = sorted(set(r.applied) & current_applied)
            row["switch"] = {"courses_remaining": r.courses_remaining,
                             "credits_remaining": r.credits_remaining,
                             "change_vs_current_courses": r.courses_remaining - current_left,
                             "change_vs_current_credits": r.credits_remaining - current_cr}
            # Adding: specific courses already on your to-do list for the current
            # program count once; open-ended electives are assumed not to overlap.
            shared_todo = set(missing) & current_missing
            row["add"] = {"extra_courses": r.courses_remaining - len(shared_todo),
                          "extra_credits": r.credits_remaining - sum(
                              float((catalog.get(c) or {}).get("credits") or programs[pid].get("default_credits", 3))
                              for c in shared_todo),
                          "shared_todo": sorted(shared_todo)}
        rows.append(row)
    if not current:  # undeclared: show the programs you're closest to finishing first
        rows.sort(key=lambda r: (r["courses_remaining"], r["credits_remaining"]))
    return {"current": current or [], "programs": rows, "courses_considered": len(best_attempts(courses))}


def render(report: dict) -> str:
    out = []
    cur = report["current"]
    out.append(f"Courses considered: {report['courses_considered']}"
               + (f" | Current program(s): {', '.join(cur)}" if cur else ""))
    out.append("")
    header = f"{'program':<16}{'reqs met':>9}{'courses left':>14}{'~credits left':>15}"
    if cur:
        header += f"{'if switch':>12}{'if added':>11}"
    out.append(header)
    out.append("-" * len(header))
    for p in report["programs"]:
        line = (f"{p['id']:<16}{p['requirements_met']:>4}/{p['requirements_total']:<4}"
                f"{p['courses_remaining']:>14}{p['credits_remaining']:>15.0f}")
        if "switch" in p:
            line += f"{p['switch']['change_vs_current_courses']:>+12}{'+' + str(p['add']['extra_courses']):>11}"
        elif cur:
            line += f"{'(current)':>12}{'':>11}"
        out.append(line)
    out.append("")
    for p in report["programs"]:
        out.append(f"== {p['name']} ({p['id']})")
        for r in p["requirements"]:
            mark = "x" if r["satisfied"] else ("~" if r["satisfied_with_in_progress"] else " ")
            out.append(f"  [{mark}] {r['name']}")
            if r["applied"]:
                out.append(f"        applied: {', '.join(r['applied'])}")
            if r["in_progress"] and not r["satisfied"]:
                out.append(f"        in progress: {', '.join(r['in_progress'])}")
            for n in r["still_needed"]:
                out.append(f"        needs: {n}")
        ready = [n for n in p["next_courses"] if n["ready"]]
        blocked = [n for n in p["next_courses"] if not n["ready"]]
        if ready:
            out.append(f"  can take now: {', '.join(n['code'] for n in ready)}")
        for n in blocked:
            out.append(f"  {n['code']} needs first: {n['prereqs']}")
        if p.get("overlap_with_current"):
            out.append(f"  already counts from current program: {', '.join(p['overlap_with_current'])}")
        out.append("")
    out.append("[x] done  [~] done once in-progress courses pass  [ ] open")
    out.append("Credits for open-ended electives are estimates (default credits per course).")
    return "\n".join(out)

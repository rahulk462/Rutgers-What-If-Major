"""Command line entry point: ``python -m rutgers_whatif <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config


def _cmd_login(a):
    from . import auth
    try:
        auth.login()
    except auth.SessionExpired as e:
        print(e)
        return 1


def _cmd_check(a):
    from . import auth
    try:
        ok = auth.check_session()
    except auth.SessionExpired as e:
        print(e)
        return 1
    print("Session is valid." if ok else "Session expired. Run `login` again.")
    return 0 if ok else 1


def _cmd_discover(a):
    from . import discover
    discover.run()


def _cmd_scrape(a):
    from . import scrape
    scrape.run(mode=a.mode)


def _cmd_reparse(a):
    from . import scrape
    scrape.reparse()


def _cmd_import(a):
    from . import storage
    courses = storage.import_courses(Path(a.file))
    storage.save(courses, [], source=f"import:{Path(a.file).name}")
    print(f"Imported {len(courses)} courses -> {config.AUDIT_JSON}")


def _cmd_courses(a):
    from . import storage
    try:
        courses = storage.load_courses()
    except FileNotFoundError as e:
        print(e)
        return 1
    for c in sorted(courses, key=lambda c: c.code):
        tag = " [AP/transfer]" if c.transfer else ""
        tag += " [added by hand]" if c.source == "manual" else ""
        print(f"{c.code}  {c.grade or '-':<3} {c.term or '':<14} {c.title}{tag}")
    print(f"{len(courses)} courses ({sum(c.transfer for c in courses)} AP/transfer)")
    return 0


def _cmd_add_course(a):
    from . import storage
    c = storage.add_manual(a.code, grade=a.grade, credits=a.credits, title=a.title or "", term=a.term)
    print(f"Added {c.code} ({c.term}, grade {c.grade}). It counts as completed in every comparison.")


def _cmd_add_ap(a):
    from . import storage
    if not a.exam:
        for e in storage.ap_table()["exams"]:
            print(f"  {e['exam']}: " + "; ".join(f"score {k} -> {', '.join(v)}" for k, v in e["awards"].items()))
        return 0
    try:
        added = storage.add_ap_exam(a.exam, a.score)
    except ValueError as e:
        print(e)
        return 1
    print(f"Added {', '.join(c.code for c in added)} for AP {a.exam} ({a.score}).")
    return 0


def _cmd_remove_course(a):
    from . import storage
    n = storage.remove_manual(a.code)
    print(f"Removed {n} hand-added entr{'y' if n == 1 else 'ies'} for {a.code}.")


def _cmd_soc(a):
    from . import soc
    terms = a.term or ["spring", "fall"]
    for t in terms:
        path = soc.fetch_term(a.year, t, campus=a.campus, force=a.force)
        print(f"{a.year} {t}: {path}")


def _cmd_programs(a):
    from .requirements import load_programs
    for pid, p in load_programs().items():
        print(f"{pid:<14} {p['kind']:<6} {p['name']}")


def _cmd_whatif(a):
    from . import soc, storage, whatif
    from .requirements import load_programs
    programs = load_programs()
    ids = a.programs or [p for p in programs]
    unknown = [p for p in ids + (a.current or []) if p not in programs]
    if unknown:
        print(f"Unknown program(s): {', '.join(unknown)}. See `programs`.")
        return 2
    courses = storage.import_courses(Path(a.courses)) if a.courses else storage.load_courses()
    report = whatif.compare(programs, ids, courses, soc.load_index(), current=a.current)
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        print(whatif.render(report))
    return 0


def _cmd_prereq(a):
    from . import lookup, soc, storage, whatif
    from .requirements import load_programs
    cat = soc.load_index()
    try:
        passed = whatif.passed_codes(storage.load_courses())
    except FileNotFoundError:
        passed = set()
        print("(No courses loaded yet, so this assumes you haven't taken anything.)")
    d = lookup.describe(a.code, cat, load_programs(), passed)
    if not d["known"]:
        print(f"{d['code']} isn't in the downloaded Schedule of Classes data. Run `soc` for a recent term first.")
    print(f"{d['code']} {d['title']}".rstrip())
    print(f"  prerequisites: {d['prereqs']}")
    print("  you've taken it" if d["taken"] else f"  you can take it now: {'yes' if d['ready'] else 'no'}")
    if d["path"]:
        print("  take these first (in order):")
        for step in d["path"]:
            print(f"    {step['code']} {step['title']}".rstrip() + ("" if step["ready"] else "  (has its own prereqs above)"))
    if d["counts_toward"]:
        print("  counts toward:")
        for c in d["counts_toward"]:
            print(f"    {c['program_name']}: {c['requirement']}")
    return 0


def _cmd_serve(a):
    from . import web
    web.serve(port=a.port, open_browser=not a.no_browser)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rutgers_whatif", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="open a browser, log in yourself (NetID + Duo), save auth.json").set_defaults(f=_cmd_login)
    sub.add_parser("check-session", help="is auth.json still valid?").set_defaults(f=_cmd_check)
    sub.add_parser("discover", help="record what Degree Navigator loads while you click around").set_defaults(f=_cmd_discover)
    s = sub.add_parser("scrape", help="fetch your audit using the discovered pages/endpoints")
    s.add_argument("--mode", choices=["json", "html"], help="override the mode discover picked")
    s.set_defaults(f=_cmd_scrape)
    sub.add_parser("reparse", help="re-run parsing on saved raw pages").set_defaults(f=_cmd_reparse)
    s = sub.add_parser("import-courses", help="load courses from a CSV/JSON instead of scraping")
    s.add_argument("file")
    s.set_defaults(f=_cmd_import)
    sub.add_parser("courses", help="list the courses the tool knows you've taken").set_defaults(f=_cmd_courses)
    s = sub.add_parser("add-course", help="add AP / test / transfer credit by hand (survives re-scraping)")
    s.add_argument("code", help="Rutgers equivalent, e.g. 01:640:151")
    s.add_argument("--term", default="AP", help='where it came from, e.g. "AP", "Transfer" (default AP)')
    s.add_argument("--grade", default="T")
    s.add_argument("--credits", type=float)
    s.add_argument("--title")
    s.set_defaults(f=_cmd_add_course)
    s = sub.add_parser("add-ap", help='add AP credit by exam and score, e.g. add-ap "Calculus BC" 5 (no args: list exams)')
    s.add_argument("exam", nargs="?")
    s.add_argument("score", nargs="?", type=int)
    s.set_defaults(f=_cmd_add_ap)
    s = sub.add_parser("remove-course", help="remove a course you added by hand")
    s.add_argument("code")
    s.set_defaults(f=_cmd_remove_course)
    s = sub.add_parser("soc", help="download public Schedule of Classes data")
    s.add_argument("--year", type=int, required=True)
    s.add_argument("--term", action="append", help="spring/summer/fall/winter or 0/1/7/9 (repeatable)")
    s.add_argument("--campus", default="NB")
    s.add_argument("--force", action="store_true")
    s.set_defaults(f=_cmd_soc)
    sub.add_parser("programs", help="list programs with requirement definitions").set_defaults(f=_cmd_programs)
    s = sub.add_parser("whatif", help="compare remaining requirements across programs")
    s.add_argument("programs", nargs="*", help="program ids (default: all)")
    s.add_argument("--current", action="append", help="your current program id(s) for switch/add deltas")
    s.add_argument("--courses", help="use this CSV/JSON of courses instead of data/audit.json")
    s.add_argument("--json", action="store_true")
    s.set_defaults(f=_cmd_whatif)
    s = sub.add_parser("prereq", aliases=["course"],
                       help="what you need before a course, and which programs it counts toward")
    s.add_argument("code")
    s.set_defaults(f=_cmd_prereq)
    s = sub.add_parser("serve", help="run the local web page at http://127.0.0.1:8000")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--no-browser", action="store_true", help="don't open a browser tab automatically")
    s.set_defaults(f=_cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.f(args) or 0


if __name__ == "__main__":
    sys.exit(main())

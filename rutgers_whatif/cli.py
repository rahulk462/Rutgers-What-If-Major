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
    from . import prereqs, soc, storage, whatif
    cat = soc.load_index()
    if a.code not in cat:
        print(f"{a.code} not in cached SOC data. Run `soc` first.")
        return 1
    tree = prereqs.parse(cat[a.code].get("preReqNotes") or "")
    print(f"{a.code} {cat[a.code]['title']}\n  prerequisites: {prereqs.to_text(tree)}")
    try:
        passed = whatif.passed_codes(storage.load_courses())
        print(f"  you meet them: {'yes' if prereqs.satisfied(tree, passed) else 'no'}")
    except FileNotFoundError:
        pass
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
    s = sub.add_parser("prereq", help="show a course's prerequisites and whether you meet them")
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

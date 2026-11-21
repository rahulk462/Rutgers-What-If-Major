"""Step 2: pull your audit using what `discover` found.

* JSON mode: call each recorded JSON endpoint with httpx + your saved cookies.
* HTML mode: revisit each recorded page headlessly with Playwright and parse it.

Either way there is a random 1-2 s pause between requests, only the pages
you visited yourself during `discover` are fetched, and raw responses are
kept under data/raw/scrape/ so parsing can be re-run offline (`reparse`).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import auth, config, dn_parse, storage
from .courses import AuditRequirement, TakenCourse
from .throttle import Throttle


def _load_pages() -> dict:
    if not config.PAGES_FILE.exists():
        raise SystemExit("No data/dn_pages.json yet. Run `python -m rutgers_whatif discover` first.")
    return json.loads(config.PAGES_FILE.read_text())


def fetch_json(urls: list[str], state: dict, out_dir: Path, throttle: Throttle) -> list[Path]:
    import httpx

    saved = []
    with httpx.Client(cookies=auth.cookies_for_httpx(state), follow_redirects=True, timeout=30,
                      headers={"User-Agent": config.USER_AGENT, "Accept": "application/json",
                               "X-Requested-With": "XMLHttpRequest"}) as client:
        for i, url in enumerate(urls):
            throttle.wait()
            resp = client.get(url)
            if auth.is_login_url(str(resp.url)):
                raise auth.SessionExpired("Session expired. Run `python -m rutgers_whatif login`.")
            resp.raise_for_status()
            path = out_dir / f"{i:03d}.json"
            path.write_text(json.dumps({"url": url, "body": resp.json()}))
            saved.append(path)
    return saved


def fetch_html(urls: list[str], state: dict, out_dir: Path, throttle: Throttle) -> list[Path]:
    from playwright.sync_api import sync_playwright

    saved = []
    with sync_playwright() as p:
        browser = p.chromium.launch(**config.launch_kwargs(headless=True))
        context = browser.new_context(storage_state=state)
        page = context.new_page()
        for i, url in enumerate(urls):
            throttle.wait()
            page.goto(url, wait_until="networkidle")
            if auth.is_login_url(page.url):
                browser.close()
                raise auth.SessionExpired("Session expired. Run `python -m rutgers_whatif login`.")
            path = out_dir / f"{i:03d}.html"
            path.write_text(f"<!-- source: {url} -->\n" + page.content())
            saved.append(path)
        # refresh the saved session so it lasts as long as possible
        auth._secure_write(config.AUTH_FILE, context.storage_state())
        browser.close()
    return saved


def parse_saved(paths: list[Path], selectors: dict | None = None) -> tuple[list[TakenCourse], list[AuditRequirement]]:
    courses: list[TakenCourse] = []
    reqs: list[AuditRequirement] = []
    for path in paths:
        if path.suffix == ".json":
            wrapped = json.loads(path.read_text())
            result = dn_parse.parse_json(wrapped.get("body", wrapped), program=wrapped.get("url", path.name))
        else:
            result = dn_parse.parse_html(path.read_text(), source=path.name, selectors=selectors)
        courses += result["courses"]
        reqs += result["requirements"]
    return dn_parse.dedupe_courses(courses), reqs


def run(mode: str | None = None) -> dict:
    config.ensure_dirs()
    pages = _load_pages()
    mode = mode or pages.get("mode", "html")
    state = auth.load_state()
    out_dir = config.RAW_DIR / "scrape"
    out_dir.mkdir(parents=True, exist_ok=True)
    throttle = Throttle()
    if mode == "json":
        paths = fetch_json(pages["json_endpoints"], state, out_dir, throttle)
    else:
        paths = fetch_html(pages["documents"], state, out_dir, throttle)
    return reparse(paths)


def reparse(paths: list[Path] | None = None) -> dict:
    """Parse already-saved raw pages again (e.g. after tweaking dn_selectors.json)."""
    out_dir = config.RAW_DIR / "scrape"
    if paths is None:
        paths = sorted(out_dir.glob("*.json")) + sorted(out_dir.glob("*.html"))
        if not paths:  # fall back to the discovery captures
            disc = config.RAW_DIR / "discovery"
            paths = sorted(p for p in disc.glob("*.*") if p.name != "index.json")
    selectors = dn_parse.load_selectors(config.DATA_DIR / "dn_selectors.json")
    courses, reqs = parse_saved(paths, selectors)
    audit = storage.save(courses, reqs, source="degree_navigator")
    print(f"Parsed {len(courses)} courses and {len(reqs)} requirement rows -> {config.AUDIT_JSON}")
    return audit

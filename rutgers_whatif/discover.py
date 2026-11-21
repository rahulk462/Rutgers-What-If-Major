"""Step 1 of scraping: find out how Degree Navigator delivers its data.

This is the automated version of "open DevTools -> Network -> Fetch/XHR".
It opens a visible browser with your saved session and records every
response from Rutgers while *you* click through your audit and course
history pages. Afterwards it reports whether any of that data came back as
JSON (then we can call those endpoints directly with httpx) or only as HTML
(then we parse the HTML).

Nothing is sent anywhere; captures are written under data/raw/discovery/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from . import auth, config

KEEP_HOST = "rutgers.edu"
SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|svg|ico|css|woff2?|ttf|js|map)(\?|$)", re.I)


def _safe_name(i: int, url: str, ext: str) -> str:
    path = urlparse(url).path.strip("/").replace("/", "_") or "root"
    path = re.sub(r"[^A-Za-z0-9_.-]", "", path)[:60]
    return f"{i:03d}_{path}.{ext}"


def classify(content_type: str, resource_type: str) -> str | None:
    ct = (content_type or "").lower()
    if "json" in ct:
        return "json"
    if resource_type in ("xhr", "fetch"):
        return "xhr"          # XHR that isn't JSON (e.g. ASP.NET partial HTML)
    if resource_type == "document" and "html" in ct:
        return "html"
    return None


def summarize(index: list[dict]) -> dict:
    """Turn the capture index into the pages file used by `scrape`."""
    documents, json_endpoints, xhr = [], [], []
    for row in index:
        if row["status"] >= 400 or auth.is_login_url(row["url"]):
            continue
        target = {"html": documents, "json": json_endpoints, "xhr": xhr}[row["kind"]]
        if row["method"] == "GET" and row["url"] not in target:
            target.append(row["url"])
    return {"documents": documents, "json_endpoints": json_endpoints, "xhr_endpoints": xhr,
            "mode": "json" if json_endpoints else "html"}


def run(auth_file: Path = config.AUTH_FILE, start_url: str = config.DN_HOME_URL,
        wait=lambda prompt, tick=None: input(prompt)) -> dict:
    from playwright.sync_api import sync_playwright

    config.ensure_dirs()
    out_dir = config.RAW_DIR / "discovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []

    def on_response(resp):
        url = resp.url
        if KEEP_HOST not in urlparse(url).netloc or SKIP_EXT.search(url):
            return
        kind = classify(resp.headers.get("content-type", ""), resp.request.resource_type)
        if not kind:
            return
        try:
            body = resp.body()
        except Exception:  # redirects / aborted requests have no body
            return
        ext = "json" if kind == "json" else "html"
        name = _safe_name(len(index), url, ext)
        (out_dir / name).write_bytes(body)
        index.append({"url": url, "method": resp.request.method, "status": resp.status,
                      "kind": kind, "content_type": resp.headers.get("content-type", ""),
                      "file": name, "bytes": len(body)})

    state = auth.load_state(auth_file)
    from . import browser as br

    with sync_playwright() as p:
        browser, channel = br.launch_headed(p)
        context = browser.new_context(storage_state=state)
        page = context.new_page()
        page.on("response", on_response)
        br.bring_to_front(page, channel)
        page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        br.bring_to_front(page, channel)
        if auth.is_login_url(page.url):
            browser.close()
            raise auth.SessionExpired("Your saved session has expired. Log in again first.")
        print(
            "\nRecording. In the separate browser window that just opened (not your own browser), open (slowly, one at a time):\n"
            "  1. your degree audit for each program you are in\n"
            "  2. your course history / 'My Courses' page\n"
            "  3. optionally a what-if audit for another program\n"
            "Then come back here and press Enter."
        )

        def tick() -> dict:
            st = br.window_state(page, auth.is_login_url)
            st["captured"] = len(index)
            return st

        wait("Press Enter when done... ", tick)
        try:
            browser.close()
        except Exception:  # noqa: BLE001 - window may already be closed
            pass

    (out_dir / "index.json").write_text(json.dumps(index, indent=2))
    pages = summarize(index)
    config.PAGES_FILE.write_text(json.dumps(pages, indent=2))
    print(f"\nCaptured {len(index)} responses -> {out_dir}")
    print(f"JSON endpoints: {len(pages['json_endpoints'])} | HTML pages: {len(pages['documents'])} | "
          f"non-JSON XHR: {len(pages['xhr_endpoints'])}")
    print(f"Mode chosen for scraping: {pages['mode'].upper()} (edit {config.PAGES_FILE} to change).")
    return pages

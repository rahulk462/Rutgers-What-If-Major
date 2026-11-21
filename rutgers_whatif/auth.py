"""Manual login + session reuse.

``login()`` opens a *visible* Chromium window at Degree Navigator. You type
your NetID/password and approve Duo yourself; this code never touches those
fields. Once you are on your Degree Navigator page you press Enter in the
terminal and the browser's cookies/localStorage are written to ``auth.json``
(permissions 600, git-ignored). Later commands reuse that file until Rutgers
expires the session, at which point you run ``login`` again.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from urllib.parse import urlparse

from . import config


class SessionExpired(RuntimeError):
    """Raised when the saved session no longer gets us into Degree Navigator."""


def is_login_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(marker in host for marker in config.LOGIN_HOST_MARKERS)


def _secure_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def login(auth_file: Path = config.AUTH_FILE, start_url: str = config.DN_HOME_URL) -> Path:
    """Open a headed browser, let the user log in by hand, save the session."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(**config.launch_kwargs(headless=False))
        context = browser.new_context()
        page = context.new_page()
        page.goto(start_url)
        print(
            "\nA browser window is open. Log in with your NetID and approve Duo yourself.\n"
            "When your Degree Navigator page has fully loaded, come back here and press Enter."
        )
        input("Press Enter when you are logged in... ")
        if is_login_url(page.url):
            browser.close()
            raise SystemExit("Still on the login page; nothing saved. Run `login` again.")
        _secure_write(auth_file, context.storage_state())
        browser.close()
    print(f"Session saved to {auth_file} (keep it private; it is git-ignored).")
    return auth_file


def load_state(auth_file: Path = config.AUTH_FILE) -> dict:
    if not auth_file.exists():
        raise SessionExpired(f"No saved session at {auth_file}. Run `python -m rutgers_whatif login`.")
    return json.loads(auth_file.read_text())


def cookies_for_httpx(state: dict, host_suffix: str = "rutgers.edu"):
    """Turn a Playwright storage_state into an httpx cookie jar (Rutgers cookies only)."""
    import httpx

    jar = httpx.Cookies()
    for c in state.get("cookies", []):
        domain = c.get("domain", "")
        if domain.lstrip(".").endswith(host_suffix):
            jar.set(c["name"], c["value"], domain=domain, path=c.get("path", "/"))
    return jar


def check_session(auth_file: Path = config.AUTH_FILE, url: str = config.DN_HOME_URL) -> bool:
    """True if the saved cookies still reach Degree Navigator without a login redirect."""
    import httpx

    state = load_state(auth_file)
    with httpx.Client(cookies=cookies_for_httpx(state), follow_redirects=True, timeout=30,
                      headers={"User-Agent": config.USER_AGENT}) as client:
        resp = client.get(url)
    return resp.status_code < 400 and not is_login_url(str(resp.url))

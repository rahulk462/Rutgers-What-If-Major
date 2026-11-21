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


def _terminal_wait(prompt: str, tick=None) -> None:
    input(prompt)


class LoginWindowClosed(RuntimeError):
    pass


def login(auth_file: Path = config.AUTH_FILE, start_url: str = config.DN_HOME_URL,
          wait=_terminal_wait) -> Path:
    """Open a visible browser window, let the user log in by hand there, save the session.

    ``wait(prompt, tick)`` blocks until the user says they're done; ``tick()``
    reports what the login window currently shows so a UI can display it.
    """
    from playwright.sync_api import sync_playwright

    from . import browser as br

    with sync_playwright() as p:
        browser, channel = br.launch_headed(p)
        try:
            context = browser.new_context()
            page = context.new_page()
            print("Opened a separate browser window for Rutgers login.")
            print("Sign in THERE (NetID + Duo). Signing in in your own browser tab won't work.")
            br.bring_to_front(page, channel)
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:  # noqa: BLE001 - keep the window open; user can still navigate
                print(f"Degree Navigator was slow to load ({e.__class__.__name__}); keep going in the window.")
            br.bring_to_front(page, channel)

            def tick() -> dict:
                return br.window_state(page, is_login_url)

            wait("When Degree Navigator has loaded in that window, press Enter... ", tick)
            state = tick()
            print(f"Login window is on: {state.get('url') or '(closed)'}")
            if state["state"] == "closed":
                raise LoginWindowClosed("The login window was closed before the session was saved. "
                                        "Click Log in again and leave the window open until you click I'm done.")
            if state["state"] != "signed_in":
                # The window may be sitting on a "Log In Successful" page (cas.rutgers.edu) or
                # somewhere else; ask Degree Navigator itself whether we're logged in.
                print("Checking with Degree Navigator whether the login worked...")
                try:
                    page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
                except Exception as e:  # noqa: BLE001
                    print(f"Degree Navigator didn't load ({e.__class__.__name__}).")
                state = tick()
                print(f"Degree Navigator sent the window to: {state.get('url') or '(closed)'}")
            if state["state"] == "login":
                raise SessionExpired("Degree Navigator still shows the Rutgers sign-in page, so nothing was saved. "
                                     "Finish NetID + Duo in that window until you see your Degree Navigator "
                                     "page, then click I'm done.")
            data = context.storage_state()
            n = sum(1 for c in data.get("cookies", []) if c.get("domain", "").lstrip(".").endswith("rutgers.edu"))
            print(f"Saving {n} Rutgers cookies.")
            if n == 0:
                raise SessionExpired("The window has no Rutgers login cookies, so nothing was saved. "
                                     "Sign in to Degree Navigator in that window, then click I'm done.")
            _secure_write(auth_file, data)
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
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

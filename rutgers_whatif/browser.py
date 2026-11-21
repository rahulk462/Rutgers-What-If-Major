"""Opening the visible browser window used for login and discovery.

Playwright drives its *own* browser window, separate from the browser you
normally use: signing in to Degree Navigator in your everyday Chrome/Safari
tab does nothing for this tool. These helpers make that window easy to find
(brought to the front) and turn launch failures into plain-English errors.
"""

from __future__ import annotations

import subprocess
import sys

from . import config


class BrowserLaunchError(RuntimeError):
    pass


INSTALL_HINT = ("Playwright's browser isn't installed. In a terminal, in the project folder, run:\n"
                "    python -m playwright install chromium\n"
                "then try again.")

# Browsers we can fall back to if Playwright's bundled Chromium is missing.
FALLBACK_CHANNELS = ("chrome", "msedge")
MAC_APP_NAMES = {None: ("Google Chrome for Testing", "Chromium"), "chrome": ("Google Chrome",),
                 "msedge": ("Microsoft Edge",)}


def launch_headed(p):
    """Launch a visible browser. Returns (browser, channel_used)."""
    kw = config.launch_kwargs(headless=False)
    kw.setdefault("args", []).append("--new-window")
    channel = config.browser_channel()
    if channel:
        kw["channel"] = channel
    try:
        return p.chromium.launch(**kw), channel
    except Exception as first:  # noqa: BLE001
        missing = "Executable doesn't exist" in str(first) or "playwright install" in str(first)
        if not missing or channel or "executable_path" in kw:
            raise BrowserLaunchError(f"Couldn't open the login browser window: {first}") from first
        for ch in FALLBACK_CHANNELS:
            try:
                print(f"Playwright's Chromium isn't installed; using your installed {ch} in a separate window instead.")
                return p.chromium.launch(**{**kw, "channel": ch}), ch
            except Exception:  # noqa: BLE001
                continue
        raise BrowserLaunchError(INSTALL_HINT) from first


def bring_to_front(page, channel: str | None = None) -> None:
    """Raise the Playwright window above your other windows (best effort)."""
    try:
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "darwin":
        for app in MAC_APP_NAMES.get(channel, ()):
            try:
                subprocess.run(["osascript", "-e", f'tell application "{app}" to activate'],
                               capture_output=True, timeout=3)
            except Exception:  # noqa: BLE001
                pass


def window_state(page, is_login_url) -> dict:
    """What the login window is showing right now (used for live status)."""
    try:
        if page.is_closed():
            return {"state": "closed", "url": ""}
        url = page.url
    except Exception:  # noqa: BLE001 - browser gone
        return {"state": "closed", "url": ""}
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    if is_login_url(url):
        return {"state": "login", "url": host}
    if host.endswith("rutgers.edu"):
        return {"state": "signed_in", "url": host}
    return {"state": "other", "url": host}

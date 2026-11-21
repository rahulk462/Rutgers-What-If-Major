"""Paths, URLs and politeness settings.

Everything personal lives under ``data/`` (git-ignored) and the browser
session lives in ``auth.json`` (git-ignored). Override locations with the
RWI_HOME environment variable if you want them somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.environ.get("RWI_HOME", Path.cwd()))

AUTH_FILE = Path(os.environ.get("RWI_AUTH_FILE", HOME / "auth.json"))
DATA_DIR = HOME / "data"
RAW_DIR = DATA_DIR / "raw"          # raw HTML / JSON captured from Degree Navigator
SOC_DIR = DATA_DIR / "soc"          # cached Schedule of Classes downloads
DB_FILE = DATA_DIR / "whatif.sqlite"
AUDIT_JSON = DATA_DIR / "audit.json"
PAGES_FILE = DATA_DIR / "dn_pages.json"
MANUAL_FILE = DATA_DIR / "manual_courses.json"  # AP / transfer credit you add by hand        # pages/endpoints found by `discover`

# Degree Navigator entry point. Logging in goes through Rutgers CAS + Duo,
# which you always complete by hand in the visible browser window.
DN_HOME_URL = os.environ.get("RWI_DN_URL", "https://dn.rutgers.edu/")
# Hosts that mean "you are not logged in (any more)".
LOGIN_HOST_MARKERS = ("cas.rutgers.edu", "duosecurity.com", "idp.rutgers.edu", "login.rutgers.edu")

SOC_API = "https://sis.rutgers.edu/soc/api/courses.json"
TERM_CODES = {"winter": 0, "spring": 1, "summer": 7, "fall": 9}

# Politeness: random delay between page loads / requests (seconds).
MIN_DELAY = float(os.environ.get("RWI_MIN_DELAY", "1.0"))
MAX_DELAY = float(os.environ.get("RWI_MAX_DELAY", "2.0"))

USER_AGENT = "rutgers-whatif/0.1 (personal degree planning tool; single user)"


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, SOC_DIR):
        d.mkdir(parents=True, exist_ok=True)


def launch_kwargs(headless: bool) -> dict:
    """Arguments for chromium.launch(); set RWI_CHROMIUM_PATH to use a specific browser binary."""
    kw: dict = {"headless": headless}
    if os.environ.get("RWI_CHROMIUM_PATH"):
        kw["executable_path"] = os.environ["RWI_CHROMIUM_PATH"]
    return kw


def browser_channel() -> str | None:
    """RWI_BROWSER=chrome or msedge uses your installed browser (separate profile) instead of Playwright's Chromium."""
    ch = os.environ.get("RWI_BROWSER", "").strip().lower()
    return ch or None

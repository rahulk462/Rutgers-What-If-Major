"""Local web page for the tool: ``python -m rutgers_whatif serve``.

Standard library only. It listens on 127.0.0.1 so nothing outside your own
computer can reach it, and it rejects requests whose Host/Origin isn't
localhost (protects against other websites poking it from your browser).
Long jobs (login, discover, scrape, course download) run one at a time in a
background thread; the page polls /api/status to show their progress.
"""

from __future__ import annotations

import contextlib
import io
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
PAGE = Path(__file__).parent / "web" / "index.html"


class _Log(io.TextIOBase):
    def __init__(self, sink: list[str]):
        self.sink = sink

    def write(self, s: str) -> int:
        for line in s.splitlines():
            if line.strip():
                self.sink.append(line)
        return len(s)


class Jobs:
    """At most one background job; the browser 'Done' button releases waits."""

    def __init__(self):
        self.lock = threading.Lock()
        self.name: str | None = None
        self.state = "idle"            # idle | running | waiting | done | error
        self.log: list[str] = []
        self.prompt = ""
        self._continue = threading.Event()

    def wait_for_user(self, prompt: str) -> None:
        self.prompt = prompt.replace("Press Enter", "Click 'I'm done'")
        self.state = "waiting"
        self.log.append(self.prompt)
        self._continue.clear()
        self._continue.wait()
        self.state = "running"
        self.prompt = ""

    def release(self) -> bool:
        if self.state != "waiting":
            return False
        self._continue.set()
        return True

    def start(self, name: str, fn) -> bool:
        with self.lock:
            if self.state in ("running", "waiting"):
                return False
            self.name, self.state, self.log, self.prompt = name, "running", [], ""

        def target():
            try:
                with contextlib.redirect_stdout(_Log(self.log)):
                    fn()
                self.state = "done"
                self.log.append("Finished.")
            except BaseException as e:  # noqa: BLE001 - surface everything to the page
                self.state = "error"
                self.log.append(f"Error: {e}")
                if not isinstance(e, (SystemExit, RuntimeError, FileNotFoundError)):
                    self.log.append(traceback.format_exc(limit=3))

        threading.Thread(target=target, daemon=True).start()
        return True

    def to_dict(self) -> dict:
        return {"name": self.name, "state": self.state, "log": self.log[-200:], "prompt": self.prompt}


JOBS = Jobs()


def status() -> dict:
    from . import soc
    from .requirements import load_programs

    cached = sorted(p.stem for p in config.SOC_DIR.glob("*_*_*.json")) if config.SOC_DIR.exists() else []
    audit = None
    if config.AUDIT_JSON.exists():
        a = json.loads(config.AUDIT_JSON.read_text())
        audit = {"fetched_at": a.get("fetched_at"), "source": a.get("source"),
                 "courses": len(a.get("courses", [])), "requirements": len(a.get("requirements", []))}
    pages = json.loads(config.PAGES_FILE.read_text()) if config.PAGES_FILE.exists() else None
    return {
        "session_saved": config.AUTH_FILE.exists(),
        "discovered": None if pages is None else {"mode": pages.get("mode"),
                                                  "json": len(pages.get("json_endpoints", [])),
                                                  "html": len(pages.get("documents", []))},
        "audit": audit,
        "soc_terms": cached,
        "soc_courses": len(soc.load_index()) if cached else 0,
        "programs": [{"id": k, "name": v["name"], "kind": v.get("kind", "major")}
                     for k, v in load_programs().items()],
        "job": JOBS.to_dict(),
    }


def run_whatif(programs: list[str], current: list[str]) -> dict:
    from . import soc, storage, whatif
    from .requirements import load_programs

    progs = load_programs()
    ids = [p for p in programs if p in progs] or list(progs)
    cur = [c for c in current if c in progs]
    courses = storage.load_courses()
    report = whatif.compare(progs, ids, courses, soc.load_index(), current=cur)
    report["courses"] = [c.to_dict() for c in courses]
    return report


def start_job(action: str, body: dict) -> tuple[bool, str]:
    from . import auth, discover, scrape, soc, storage

    if action == "login":
        return JOBS.start("login", lambda: auth.login(wait=JOBS.wait_for_user)), "login"
    if action == "check":
        def check():
            print("Session is valid." if auth.check_session() else "Session expired. Log in again.")
        return JOBS.start("check-session", check), "check"
    if action == "discover":
        return JOBS.start("discover", lambda: discover.run(wait=JOBS.wait_for_user)), "discover"
    if action == "scrape":
        return JOBS.start("scrape", lambda: scrape.run(mode=body.get("mode") or None)), "scrape"
    if action == "reparse":
        return JOBS.start("reparse", lambda: scrape.reparse()), "reparse"
    if action == "soc":
        year = int(body.get("year"))
        terms = body.get("terms") or ["spring", "fall"]

        def fetch():
            for t in terms:
                print(f"Downloading {year} {t} ...")
                print(f"  saved {soc.fetch_term(year, t)}")
        return JOBS.start("soc", fetch), "soc"
    if action == "import":
        text = body.get("csv", "")
        if not text.strip():
            return False, "empty CSV"
        config.ensure_dirs()
        tmp = config.DATA_DIR / "uploaded_courses.csv"
        tmp.write_text(text)

        def do_import():
            courses = storage.import_courses(tmp)
            storage.save(courses, [], source="import:web")
            print(f"Imported {len(courses)} courses.")
        return JOBS.start("import", do_import), "import"
    return False, f"unknown action {action}"


class Handler(BaseHTTPRequestHandler):
    server_version = "rutgers-whatif"

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ALLOWED_HOSTS:
            return False
        return True

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        url = urlparse(self.path)
        try:
            if url.path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/status":
                return self._json(200, status())
            if url.path == "/api/whatif":
                q = parse_qs(url.query)
                progs = [p for v in q.get("programs", []) for p in v.split(",") if p]
                cur = [p for v in q.get("current", []) for p in v.split(",") if p]
                return self._json(200, run_whatif(progs, cur))
        except FileNotFoundError as e:
            return self._json(409, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._json(415, {"error": "send application/json"})
        length = min(int(self.headers.get("Content-Length") or 0), 2_000_000)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        path = urlparse(self.path).path
        if path == "/api/done":
            return self._json(200, {"released": JOBS.release()})
        if path.startswith("/api/run/"):
            try:
                ok, msg = start_job(path.rsplit("/", 1)[1], body)
            except (TypeError, ValueError) as e:
                return self._json(400, {"error": str(e)})
            if not ok:
                return self._json(409, {"error": "another job is running" if msg in
                                        ("login", "check", "discover", "scrape", "reparse", "soc", "import") else msg})
            return self._json(202, {"started": msg})
        return self._json(404, {"error": "not found"})


def serve(port: int = 8000, open_browser: bool = True) -> None:
    config.ensure_dirs()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Rutgers What-If is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()

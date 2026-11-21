import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from rutgers_whatif import config, web

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "SOC_DIR", tmp_path / "data" / "soc")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "data" / "raw")
    monkeypatch.setattr(config, "AUDIT_JSON", tmp_path / "data" / "audit.json")
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "data" / "whatif.sqlite")
    monkeypatch.setattr(config, "PAGES_FILE", tmp_path / "data" / "dn_pages.json")
    monkeypatch.setattr(config, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(config, "MANUAL_FILE", tmp_path / "data" / "manual_courses.json")
    config.ensure_dirs()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_job(base):
    for _ in range(50):
        s = json.loads(get(base + "/api/status")[1])
        if s["job"]["state"] not in ("running", "waiting"):
            return s
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_page_and_status(server):
    code, body = get(server + "/")
    assert code == 200 and b"Rutgers What-If" in body
    s = json.loads(get(server + "/api/status")[1])
    assert s["session_saved"] is False and len(s["programs"]) >= 8


def test_rejects_foreign_host(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(server + "/api/status", {"Host": "evil.example"})
    assert e.value.code == 403


def test_import_then_whatif(server):
    csv = (ROOT / "examples" / "sample_courses.csv").read_text()
    code, _ = post(server + "/api/run/import", {"csv": csv})
    assert code == 202
    s = wait_job(server)
    assert s["job"]["state"] == "done" and s["audit"]["courses"] == 12
    code, body = get(server + "/api/whatif?programs=math-minor&current=cs-bs")
    r = json.loads(body)
    ids = [p["id"] for p in r["programs"]]
    assert ids == ["cs-bs", "math-minor"] and "add" in r["programs"][1]


def test_waiting_job_released_by_done(server):
    seen = []
    assert web.JOBS.start("demo", lambda: (web.JOBS.wait_for_user("Press Enter when done"), seen.append(1)))
    for _ in range(50):
        if web.JOBS.state == "waiting":
            break
        time.sleep(0.05)
    assert "I'm done" in web.JOBS.prompt
    assert post(server + "/api/done", {})[1]["released"] is True
    wait_job(server)
    assert seen == [1]


def test_add_and_list_ap_credit(server):
    code, body = post(server + "/api/courses/add", {"code": "01:640:151", "term": "AP", "credits": "4"})
    assert code == 200 and body["added"]["transfer"]
    assert post(server + "/api/courses/add", {"code": "nope"})[0] == 400
    rows = json.loads(get(server + "/api/courses")[1])["courses"]
    assert rows[0]["code"] == "01:640:151" and rows[0]["source"] == "manual"
    r = json.loads(get(server + "/api/whatif?programs=math-minor")[1])
    assert "01:640:151" in r["programs"][0]["applied"]

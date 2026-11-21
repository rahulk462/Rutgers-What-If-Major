from rutgers_whatif import auth, discover
from rutgers_whatif.throttle import Throttle


def test_throttle_waits_between_calls():
    t = [0.0]
    slept = []
    th = Throttle(1.0, 2.0, sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)), clock=lambda: t[0])
    th.wait()
    th.wait()
    assert slept and 1.0 <= slept[0] <= 2.0


def test_login_url_detection():
    assert auth.is_login_url("https://cas.rutgers.edu/login?service=x")
    assert not auth.is_login_url("https://dn.rutgers.edu/")


def test_cookie_filter_only_rutgers():
    jar = auth.cookies_for_httpx({"cookies": [
        {"name": "a", "value": "1", "domain": ".rutgers.edu", "path": "/"},
        {"name": "b", "value": "2", "domain": "evil.example", "path": "/"}]})
    assert jar.get("a") == "1" and jar.get("b") is None


def test_discover_summary_prefers_json():
    idx = [{"url": "https://dn.rutgers.edu/a", "method": "GET", "status": 200, "kind": "html"},
           {"url": "https://dn.rutgers.edu/api/audit", "method": "GET", "status": 200, "kind": "json"},
           {"url": "https://cas.rutgers.edu/login", "method": "GET", "status": 200, "kind": "html"}]
    s = discover.summarize(idx)
    assert s["mode"] == "json" and s["json_endpoints"] == ["https://dn.rutgers.edu/api/audit"]
    assert s["documents"] == ["https://dn.rutgers.edu/a"]


def test_gitignore_protects_secrets():
    from pathlib import Path
    text = (Path(__file__).parent.parent / ".gitignore").read_text()
    assert "auth.json" in text and "data/" in text


class _FakePage:
    def __init__(self, url, closed=False):
        self.url, self._closed = url, closed

    def is_closed(self):
        return self._closed


def test_window_state():
    from rutgers_whatif import browser as br
    assert br.window_state(_FakePage("https://cas.rutgers.edu/login"), auth.is_login_url)["state"] == "login"
    assert br.window_state(_FakePage("https://dn.rutgers.edu/DN/Audit"), auth.is_login_url)["state"] == "signed_in"
    assert br.window_state(_FakePage("https://example.com/"), auth.is_login_url)["state"] == "other"
    assert br.window_state(_FakePage("", closed=True), auth.is_login_url)["state"] == "closed"

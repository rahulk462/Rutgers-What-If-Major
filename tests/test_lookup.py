import json
from pathlib import Path

from rutgers_whatif import lookup
from rutgers_whatif.requirements import load_programs

SOC = json.loads((Path(__file__).parent / "fixtures" / "soc_sample.json").read_text())
PROGRAMS = load_programs()


def test_path_for_algorithms_from_scratch():
    d = lookup.describe("01:198:344", SOC, PROGRAMS, passed=set())
    assert not d["ready"]
    codes = [p["code"] for p in d["path"]]
    # needs data structures (via intro CS) and discrete II, earliest first
    assert codes.index("01:198:111") < codes.index("01:198:112")
    assert "01:198:206" in codes


def test_ready_when_prereqs_met():
    d = lookup.describe("01:198:211", SOC, PROGRAMS, passed={"01:198:112"})
    assert d["ready"] and d["path"] == []


def test_counts_toward_programs():
    d = lookup.describe("01:640:477", SOC, PROGRAMS, passed=set())
    progs = {c["program"] for c in d["counts_toward"]}
    assert {"stat-ba", "math-ba", "stat-minor"} <= progs
    assert "cs-bs" not in progs


def test_search():
    assert lookup.search("data structures", SOC)[0]["code"] == "01:198:112"
    assert lookup.search("198:211", SOC)[0]["code"] == "01:198:211"

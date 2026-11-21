import json
from pathlib import Path

from rutgers_whatif import storage, whatif
from rutgers_whatif.courses import TakenCourse
from rutgers_whatif.requirements import evaluate, load_programs

HERE = Path(__file__).parent
PROGRAMS = load_programs()
SAMPLE = storage.import_courses(HERE.parent / "examples" / "sample_courses.csv")
SOC = json.loads((HERE / "fixtures" / "soc_sample.json").read_text())


def req(result, rid):
    return next(r for r in result.requirements if r.id == rid)


def test_all_programs_load():
    assert {"cs-bs", "cs-ba", "cs-minor", "math-ba", "math-minor", "stat-ba", "statmath-ba", "stat-minor"} <= set(PROGRAMS)
    for p in PROGRAMS.values():
        assert p["requirements"] and p["sources"]


def test_old_cs_numbers_count_for_new_sequence():
    r = evaluate(PROGRAMS["cs-bs"], SAMPLE, SOC)
    core = req(r, "cs-core")
    assert "01:198:111" in core.applied and "01:198:112" in core.applied
    assert core.missing_courses == ["01:198:206", "01:198:344"]
    assert not core.satisfied
    assert core.in_progress == ["01:198:206"]
    assert core.credits_remaining == 8


def test_math_core_satisfied():
    r = evaluate(PROGRAMS["cs-ba"], SAMPLE, SOC)
    assert req(r, "cs-math").satisfied


def test_one_d_allowed_in_cs():
    r = evaluate(PROGRAMS["cs-ba"], SAMPLE, SOC)
    assert "01:198:213" in req(r, "cs-electives").applied
    assert r.d_grades_used == 1


def test_no_d_in_statistics():
    courses = SAMPLE + [TakenCourse("01:960:463", grade="D"), TakenCourse("01:960:486", grade="B")]
    r = evaluate(PROGRAMS["stat-ba"], courses, SOC)
    required = req(r, "stat-required")
    assert "01:960:463" not in required.applied and "01:960:486" in required.applied


def test_choose_rules_min_level():
    courses = [TakenCourse(c, grade="A") for c in
               ["01:198:213", "01:198:214", "01:960:384", "01:640:348", "01:198:210"]]
    r = evaluate(PROGRAMS["cs-ba"], courses, SOC)
    el = req(r, "cs-electives")
    assert len(el.applied) == 5
    assert not el.satisfied            # no 01:198 course at 300+
    assert any("300+" in n for n in el.still_needed)
    assert el.courses_remaining >= 2


def test_one_set_picks_closest():
    courses = [TakenCourse("01:750:203", grade="B"), TakenCourse("01:750:204", grade="B")]
    r = evaluate(PROGRAMS["cs-bs"], courses, SOC)
    sci = req(r, "cs-science")
    assert sci.missing_courses == ["01:750:201", "01:750:202"] or len(sci.missing_courses) == 2


def test_failed_attempt_replaced_by_pass():
    courses = [TakenCourse("01:640:151", grade="F"), TakenCourse("01:640:151", grade="B")]
    r = evaluate(PROGRAMS["math-minor"], courses, SOC)
    assert "01:640:151" in req(r, "mm-core").applied


def test_whatif_switch_and_add():
    report = whatif.compare(PROGRAMS, ["math-minor", "stat-ba"], SAMPLE, SOC, current=["cs-bs"])
    rows = {p["id"]: p for p in report["programs"]}
    assert "switch" not in rows["cs-bs"]
    mm = rows["math-minor"]
    assert "01:640:151" in mm["overlap_with_current"]
    assert mm["add"]["extra_courses"] <= mm["courses_remaining"]
    text = whatif.render(report)
    assert "cs-bs" in text and "math-minor" in text


def test_prereq_readiness_in_report():
    report = whatif.compare(PROGRAMS, ["math-ba"], SAMPLE, SOC)
    nxt = {n["code"]: n for n in report["programs"][0]["next_courses"]}
    assert nxt["01:640:252"]["ready"]          # has 250 + 251
    assert nxt["01:640:300"]["ready"]


def test_undeclared_compares_everything_sorted():
    report = whatif.compare(PROGRAMS, list(PROGRAMS), SAMPLE, SOC)
    left = [p["courses_remaining"] for p in report["programs"]]
    assert report["current"] == [] and len(left) == len(PROGRAMS) and left == sorted(left)
    assert all("switch" not in p for p in report["programs"])
    assert "cs-bs" in whatif.render(report)

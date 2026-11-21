from pathlib import Path

from rutgers_whatif import dn_parse
from rutgers_whatif.courses import grade_status, normalize_term

HTML = (Path(__file__).parent / "fixtures" / "dn_audit_synthetic.html").read_text()


def test_parse_course_table():
    res = dn_parse.parse_html(HTML)
    by = {c.code: c for c in res["courses"]}
    assert by["01:198:111"].grade == "A" and by["01:198:111"].credits == 4.0
    assert by["01:640:151"].term == "Fall 2024"
    assert by["01:198:206"].status == "in_progress"


def test_parse_requirements():
    res = dn_parse.parse_html(HTML)
    reqs = {r.name.split(":")[0]: r for r in res["requirements"]}
    assert reqs["R1"].satisfied is False
    assert reqs["R1"].credits_remaining == 8
    assert "01:198:205" in reqs["R1"].courses_applied
    assert reqs["R2"].satisfied is True


def test_parse_json_generic():
    payload = {"data": {"courses": [{"CourseCode": "01:198:111", "Grade": "A", "Term": "Fall 2024", "Credits": "4"}],
                        "reqs": [{"RequirementName": "R1 Core", "Satisfied": False}]}}
    res = dn_parse.parse_json(payload, "x")
    assert res["courses"][0].code == "01:198:111" and res["courses"][0].credits == 4.0
    assert res["requirements"][0].satisfied is False


def test_terms_and_grades():
    assert normalize_term("2025 1") == "Spring 2025"
    assert normalize_term("Fall2024") == "Fall 2024"
    assert grade_status("W") == "failed"
    assert grade_status("") == "in_progress"
    assert grade_status("TR") == "passed"

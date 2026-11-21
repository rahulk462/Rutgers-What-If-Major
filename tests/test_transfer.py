from pathlib import Path

import pytest

from rutgers_whatif import config, dn_parse, storage, whatif
from rutgers_whatif.courses import TakenCourse
from rutgers_whatif.requirements import load_programs

HTML = (Path(__file__).parent / "fixtures" / "dn_ap_synthetic.html").read_text()


def test_ap_rows_count_as_completed():
    by = {c.code: c for c in dn_parse.parse_html(HTML)["courses"]}
    assert by["01:640:151"].transfer and by["01:640:151"].status == "passed" and by["01:640:151"].grade == "T"
    assert by["01:355:101"].transfer and by["01:355:101"].status == "passed"
    # a blank grade on a normal term is still "in progress"
    assert not by["01:198:112"].transfer and by["01:198:112"].status == "in_progress"


def test_transfer_table_without_grade_column():
    by = {c.code: c for c in dn_parse.parse_html(HTML)["courses"]}
    assert by["01:640:152"].transfer and by["01:640:152"].status == "passed"
    assert by["01:960:211"].credits == 3.0


def test_csv_import_marks_ap(tmp_path):
    f = tmp_path / "c.csv"
    f.write_text("code,title,credits,grade,term\n01:640:151,Calc I,4,,AP\n")
    c = storage.import_courses(f)[0]
    assert c.transfer and c.status == "passed"


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "AUDIT_JSON", tmp_path / "audit.json")
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "w.sqlite")
    monkeypatch.setattr(config, "MANUAL_FILE", tmp_path / "manual_courses.json")
    return tmp_path


def test_manual_ap_survives_rescrape_and_counts(data_dir):
    storage.add_manual("01:640:151", credits=4)
    storage.add_manual("640:152")                           # short code accepted
    assert {c.code for c in storage.load_courses()} == {"01:640:151", "01:640:152"}  # no audit yet
    storage.save([TakenCourse("01:640:250", grade="A")], [], source="scrape")
    courses = storage.load_courses()
    assert {c.code for c in courses} == {"01:640:151", "01:640:152", "01:640:250"}
    report = whatif.compare(load_programs(), ["cs-ba"], courses, {})
    math = next(r for r in report["programs"][0]["requirements"] if r["id"] == "cs-math")
    assert math["satisfied"]
    assert storage.remove_manual("01:640:151") == 1
    assert "01:640:151" not in {c.code for c in storage.load_courses()}


def test_manual_rejects_bad_code(data_dir):
    with pytest.raises(ValueError):
        storage.add_manual("calc")


def test_add_ap_exam(data_dir):
    added = storage.add_ap_exam("Calculus BC", 5)
    assert [c.code for c in added] == ["01:640:151", "01:640:152"] and all(c.transfer for c in added)
    assert storage.add_ap_exam("computer science a", 4)[0].code == "01:198:110"
    with pytest.raises(ValueError):
        storage.add_ap_exam("Calculus AB", 3)
    with pytest.raises(ValueError):
        storage.add_ap_exam("Underwater Basket Weaving", 5)
    codes = {c.code for c in storage.load_courses()}
    assert {"01:640:151", "01:640:152", "01:198:110"} <= codes

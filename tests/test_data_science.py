from rutgers_whatif.courses import TakenCourse
from rutgers_whatif.requirements import evaluate, load_programs

PROGRAMS = load_programs()
DS = ["ds-bs-cs", "ds-bs-econ", "ds-bs-chem", "ds-ba-stat", "ds-ba-societal", "ds-minor"]


def c(code, grade="A"):
    return TakenCourse(code=code, title="", credits=3, grade=grade, term="Fall 2025")


def req(result, rid):
    return next(r for r in result.requirements if r.id == rid)


def test_data_science_programs_load():
    assert set(DS) <= set(PROGRAMS)
    for pid in DS:
        assert "ds.sas.rutgers.edu" in PROGRAMS[pid]["sources"][0]


def test_old_data_in_context_number_counts():
    r = evaluate(PROGRAMS["ds-ba-stat"], [c("04:189:220")])
    assert req(r, "ds-ba-stat-context").satisfied


def test_minor_track_and_domain_do_not_double_count():
    courses = [c("01:198:142"), c("01:960:291"), c("01:960:295"), c("01:960:463"), c("01:198:461")]
    r = evaluate(PROGRAMS["ds-minor"], courses)
    assert req(r, "dsm-track").satisfied
    assert not req(r, "dsm-domain").satisfied  # 960:463 already used by the track
    r = evaluate(PROGRAMS["ds-minor"], courses + [c("01:198:439")])
    assert all(x.satisfied for x in r.requirements)


def test_minor_allows_no_d():
    r = evaluate(PROGRAMS["ds-minor"], [c("01:198:142", "D")])
    assert not req(r, "dsm-data101").satisfied

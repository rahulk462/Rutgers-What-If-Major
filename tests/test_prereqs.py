import json
from pathlib import Path

from rutgers_whatif import prereqs

SOC = json.loads((Path(__file__).parent / "fixtures" / "soc_sample.json").read_text())


def tree(code):
    return prereqs.parse(SOC[code]["preReqNotes"])


def test_simple_or():
    t = tree("01:198:211")
    assert prereqs.satisfied(t, {"01:198:112"})
    assert prereqs.satisfied(t, {"14:332:351"})
    assert not prereqs.satisfied(t, set())


def test_nested_and_or():
    t = tree("01:198:206")
    assert prereqs.satisfied(t, {"01:198:205", "01:640:152"})
    assert prereqs.satisfied(t, {"14:332:312", "01:640:192"})
    assert not prereqs.satisfied(t, {"01:198:205"})
    assert not prereqs.satisfied(t, {"01:640:152"})


def test_and_inside_title_is_not_an_operator():
    # "DIFFERENTIAL EQUATIONS FOR ENGINEERING  AND PHYSICS  and 01:640:300"
    t = tree("01:640:311")
    assert prereqs.codes(t) == {"01:640:244", "01:640:300", "01:640:252"}
    assert prereqs.satisfied(t, {"01:640:252", "01:640:300"})
    assert not prereqs.satisfied(t, {"01:640:300"})


def test_equal_or_greater():
    t = tree("01:198:111")
    assert prereqs.satisfied(t, {"01:640:112"})
    assert prereqs.satisfied(t, {"01:640:151"})
    assert not prereqs.satisfied(t, {"01:640:026"})


def test_empty_means_no_prereqs():
    assert prereqs.parse("") is None
    assert prereqs.satisfied(None, set())


def test_duplicates_collapsed():
    t = prereqs.parse("(01:640:152 CALC II  and 01:640:152 CALC II )")
    assert isinstance(t, prereqs.Course) and t.code == "01:640:152"

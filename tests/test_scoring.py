"""Score formula tests. Run:  python -m pytest -q"""
import json
from pathlib import Path

import pytest

from backend.checklist import normalize_checklist
from backend.scoring import round_half_up, score, validate_items

CL = normalize_checklist(json.loads((Path(__file__).parent.parent / "config" / "checklist_v1.json").read_text("utf-8")))


def answers(**over):
    """All criteria at their best answer, with overrides like c03={"answer": "na"}."""
    items = []
    for c in CL["criteria"]:
        it = {"criterion_id": c["id"], "evidence_ids": [], "checked_range": None, "explanation": ""}
        if c["type"] == "scale":
            it.update(answer="score", value=c["scale"][0]["value"])
        elif c["type"] == "critical":
            it.update(answer="no", value=None)
        else:
            it.update(answer="yes", value=None)
        it.update(over.get(c["id"], {}))
        items.append(it)
    return items


def test_all_best_is_100():
    assert score(CL, answers())["total"] == 100


def test_na_redistribution_example():
    # c03, c07 = N/A; c04 = 15 of 20; c06 = 7 of 10  ->  65.5 / 75 * 100 = 87.33
    r = score(CL, answers(c03={"answer": "na"}, c07={"answer": "na"},
                          c04={"value": 15}, c06={"value": 7}))
    assert r["total"] == 87.33
    assert r["applicable_weight"] == 75
    assert sum(i["max_points"] for i in r["items"] if i["status"] == "scored") == pytest.approx(100, abs=0.05)


def test_no_gives_zero_points():
    r = score(CL, answers(c01={"answer": "no"}))
    assert r["total"] == 90
    assert next(i for i in r["items"] if i["criterion_id"] == "c01")["points"] == 0


def test_critical_flag_separate_by_default():
    r = score(CL, answers(c08={"answer": "yes"}))
    assert r["critical_error"] is True and r["critical_items"] == ["c08"]
    assert r["total"] == 100


def test_critical_can_zero_total():
    cl = {**CL, "critical_zeroes_total": True}
    r = score(cl, answers(c08={"answer": "yes"}))
    assert r["total"] == 0 and r["total_before_critical"] == 100


def test_all_weighted_na_gives_none():
    cl = {**CL, "criteria": [c for c in CL["criteria"] if c["na_allowed"] or c["type"] == "critical"]}
    items = [{"criterion_id": c["id"], "answer": "no" if c["type"] == "critical" else "na", "value": None}
             for c in cl["criteria"]]
    assert score(cl, items)["total"] is None


def test_sections_add_up():
    r = score(CL, answers(c04={"value": 10}))
    secs = {s["id"]: s for s in r["sections"]}
    assert secs["safety"]["points"] == pytest.approx(30)  # c03 20 + c04 10
    assert secs["critical"]["points"] is None


def test_rounding_half_up():
    assert round_half_up(87.335, 2) == 87.34
    assert round_half_up(2.5, 0) == 3


def test_validation_catches_bad_answers():
    errs = validate_items(CL, answers(c01={"answer": "na"}, c04={"value": 13}, c05={"evidence_ids": [99]}), 20)
    joined = " ".join(errs)
    assert "c01" in joined and "c04" in joined and "c05" in joined


def test_validation_missing_and_extra():
    items = [i for i in answers() if i["criterion_id"] != "c02"] + [{"criterion_id": "zzz", "answer": "yes"}]
    errs = validate_items(CL, items)
    assert any("c02" in e for e in errs) and any("zzz" in e for e in errs)


def test_new_criterion_works_without_code_changes():
    data = json.loads(json.dumps(CL))
    data["criteria"].append({"id": "c09", "section": "flow", "title": "Новый", "type": "scale", "weight": 25,
                             "na_allowed": False, "scale": [{"value": 5, "label": "max"}, {"value": 0, "label": "min"},
                                                            {"value": 3, "label": "mid"}]})
    cl = normalize_checklist(data)
    items = answers() + [{"criterion_id": "c09", "answer": "score", "value": 3}]
    r = score(cl, items)
    # weights 100 + 25 = 125; earned 100 + 25*3/5 = 115 -> 92.0
    assert r["total"] == 92.0


def test_checklist_validation():
    bad = json.loads(json.dumps(CL))
    bad["criteria"][0]["weight"] = -1
    bad["criteria"][1]["id"] = bad["criteria"][2]["id"]
    with pytest.raises(ValueError) as e:
        normalize_checklist(bad)
    assert "вес" in str(e.value) and "повторяется" in str(e.value)

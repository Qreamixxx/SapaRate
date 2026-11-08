"""results.json export and validator."""
import copy
import json

import pytest

from backend import exporter, storage
from scripts import validate_results

TR = [{"id": i, "timestamp": f"00:{i:02d}", "speaker": s, "text": "x"}
      for i, s in enumerate(["client", "bot", "operator", "client", "operator"])]
CONV = {"conversation_id": "t-001", "channel": "agent chat", "language": "RU", "transcript": TR, "audio_url": None}
CALL = {**CONV, "conversation_id": "t-call", "channel": "voice call", "audio_url": "http://a"}


def item(cid, ctype, answer, value=None, ev=(), expl="ok"):
    return {"criterion_id": cid, "title": cid, "type": ctype, "answer": answer, "value": value,
            "explanation": expl, "evidence_ids": list(ev), "checked_range": None}


def make_ev(**over):
    items = {
        "c01": item("c01", "binary", "yes", ev=[2], expl="Поздоровался [2]"),
        "c02": item("c02", "binary", "na", ev=[0]),
        "c03": item("c03", "binary", "na", ev=[0]),
        "c04": item("c04", "scale", "score", 15, ev=[2, 4]),
        "c05": item("c05", "binary", "yes", ev=[2]),
        "c06": item("c06", "scale", "score", 7, ev=[2]),
        "c07": item("c07", "binary", "no", ev=[4]),
        "c08": item("c08", "critical", "no", ev=[]),
    }
    items.update(over)
    return {"checklist_id": "x", "checklist_version": 1, "usage": {"model": "gemini-test", "provider": "gemini"},
            "result": {"total": 76.47, "items": list(items.values())}}


def test_evidence_shifted_by_one_and_rationale_refs():
    rec = exporter.record_ok(make_ev(), CONV)
    c = {x["criterion_id"]: x for x in rec["criteria"]}
    assert c["contact"]["evidence_turns"] == [3]            # 0-based reply 2 -> 3
    assert TR[c["contact"]["evidence_turns"][0] - 1]["speaker"] == "operator"
    assert c["contact"]["rationale"] == "Поздоровался [3]"
    assert c["consultation"]["evidence_turns"] == [3, 5]


def test_na_is_null_scale_is_number_and_order():
    rec = exporter.record_ok(make_ev(), CONV)
    assert [c["criterion_id"] for c in rec["criteria"]] == exporter.CODES
    v = {c["criterion_id"]: c["value"] for c in rec["criteria"]}
    assert v["discovery"] is None and v["identification"] is None
    assert v["consultation"] == 15 and v["dialogue"] == 7 and v["closure"] is False and v["contact"] is True


def test_critical_flag_matches_value():
    rec = exporter.record_ok(make_ev(c08=item("c08", "critical", "yes", ev=[2])), CONV)
    assert rec["criteria"][-1]["value"] is True and rec["score"]["critical_flag"] is True
    rec = exporter.record_ok(make_ev(), CONV)
    assert rec["score"]["critical_flag"] is False


def test_error_record():
    rec = exporter.record_error("t-9", "модель не ответила")
    assert rec == {"conversation_id": "t-9", "status": "error", "criteria": [], "score": None,
                   "error": "модель не ответила"}


def doc_of(*recs):
    return {"schema_version": "1.0", "team_name": "PRO и Bali",
            "model": {"mode": "external_api", "name": "m"}, "results": list(recs)}


def good():
    return exporter.record_ok(make_ev(), CONV)


def test_validator_accepts_good_file_and_error_record():
    d = doc_of(good(), exporter.record_error("t-err", "boom"))
    data = [CONV, {**CONV, "conversation_id": "t-err"}]
    assert exporter.validate(d, data) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r["criteria"].pop(), "criteria должны быть"),
    (lambda r: r["criteria"][0].update(value=None), "null"),
    (lambda r: r["criteria"][3].update(value=12), "value должно быть одним из"),
    (lambda r: r["criteria"][0].update(value="yes"), "true/false"),
    (lambda r: r["criteria"][0].update(evidence_turns=[6]), "вне диапазона"),
    (lambda r: r["criteria"][0].update(evidence_turns=[0]), "вне диапазона"),
    (lambda r: r["score"].update(critical_flag=True), "critical_flag"),
    (lambda r: r["score"].update(final_score=100.5), "final_score"),
    (lambda r: r["score"].update(final_score=50.123), "final_score"),
])
def test_validator_rejects_bad_files(mutate, needle):
    rec = copy.deepcopy(good())
    mutate(rec)
    problems = exporter.validate(doc_of(rec), [CONV])
    assert problems and any(needle in p for p in problems), problems


def test_validator_duplicates_missing_and_error_shape():
    probs = exporter.validate(doc_of(good(), good()), [CONV])
    assert any("повторяется" in p for p in probs)
    probs = exporter.validate(doc_of(good()), [CONV, {**CONV, "conversation_id": "other"}])
    assert any("отсутствует" in p for p in probs)
    bad_err = {"conversation_id": "t-001", "status": "error", "criteria": [1], "score": {"final_score": 0}, "error": ""}
    probs = exporter.validate(doc_of(bad_err), [CONV])
    assert len(probs) >= 3


def test_contact_null_only_for_calls():
    rec = copy.deepcopy(exporter.record_ok(make_ev(), CALL))
    rec["criteria"][0].update(value=None, rationale="Приветствие не попало в запись")
    assert exporter.validate(doc_of(rec), [CALL]) == []
    rec2 = copy.deepcopy(rec)
    rec2["conversation_id"] = "t-001"
    assert any("contact" in p for p in exporter.validate(doc_of(rec2), [CONV]))


def test_prod_needs_exactly_ten():
    recs = [{**good(), "conversation_id": f"p-{i}"} for i in range(10)]
    data = [{**CONV, "conversation_id": f"p-{i}"} for i in range(10)]
    assert exporter.validate(doc_of(*recs), data, expect_count=10) == []
    assert any("ровно 10" in p for p in exporter.validate(doc_of(*recs[:9]), data[:9], expect_count=10))


def test_cli_validator_exit_codes(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(json.dumps(doc_of(good())), encoding="utf-8")
    d = tmp_path / "data.json"
    d.write_text(json.dumps({"isSuccess": True, "data": {"records": [CONV]}}), encoding="utf-8")
    assert validate_results.main([str(f), "--data", str(d)]) == 0
    assert validate_results.main([str(f), "--data", str(d), "--expect-count", "10"]) == 1
    f.write_text("{not json", encoding="utf-8")
    assert validate_results.main([str(f), "--data", str(d)]) == 1


def test_replaced_criterion_keeps_code():
    # criterion text replaced in the editor keeps its id -> same code; a 9th criterion has no code
    assert exporter.code_for(4, "c05", []) == "empathy"
    assert exporter.code_for(8, "c09", []) is None
    assert exporter.code_for(2, "custom", []) == "identification"


def test_model_name_of_groq_in_results(monkeypatch):
    """Evaluations made by the fallback provider put its real model name into model.name."""
    monkeypatch.setattr(exporter, "latest_eval", lambda cid, checklist_id=None: {
        **make_ev(), "usage": {"model": "openai/gpt-oss-120b", "provider": "openai"}})
    monkeypatch.setattr(storage, "get_checklist", lambda *a, **k: {"criteria": []})
    doc = exporter.build([CONV])
    assert doc["model"] == {"mode": "external_api", "name": "openai/gpt-oss-120b"}
    assert doc["results"][0]["status"] == "ok"

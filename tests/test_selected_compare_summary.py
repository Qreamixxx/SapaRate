"""Selected re-evaluation, version comparison and set summary - on a temporary database, no model calls."""
import copy
import json
import time

import pytest

from backend import llm, service, settings, storage


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "_conn", None)
    service.bootstrap()
    recs = [{"conversation_id": f"d{i}", "channel": "agent chat", "language": "RU", "audio_url": None,
             "transcript": [{"timestamp": "00:00", "speaker": "client", "text": "?"},
                            {"timestamp": "00:05", "speaker": "operator", "text": "Здравствуйте"}]} for i in range(4)]
    service.upload_group("G", {"isSuccess": True, "data": {"records": recs}})
    calls = []
    state = {"empathy": "yes"}

    def fake_eval(cl, conv, facts):
        calls.append((conv["conversation_id"], cl["version"]))
        items = []
        for c in cl["criteria"]:
            it = {"criterion_id": c["id"], "answer": "yes", "value": None, "evidence_ids": [1], "checked_range": None,
                  "explanation": "ok [1]"}
            if c["type"] == "scale":
                it.update(answer="score", value=c["scale"][0]["value"])
            if c["type"] == "critical":
                it.update(answer="yes" if conv["conversation_id"] == "d3" else "no")
            if c["id"] == "c05" and cl["version"] == 2 and conv["conversation_id"] == "d1":
                it["answer"] = "no"
            if c["id"] == "c03":
                it["answer"] = "na"
            items.append(it)
        return {"items": items, "usage": {"input_tokens": 1, "output_tokens": 1, "calls": 1}, "provider": "gemini",
                "model": "fake"}

    monkeypatch.setattr(llm, "evaluate", fake_eval)
    return calls


def wait(job):
    for _ in range(100):
        j = service.get_job(job["job_id"])
        if j["finished"]:
            return j
        time.sleep(0.05)
    raise AssertionError("batch did not finish")


def test_batch_only_selected_and_validation(env):
    cl = service.get_checklist("chat-quality")
    job = service.start_batch("chat-quality", 1, "G", ["d0", "d2"], False)
    assert job["total"] == 2 and wait(job)["done"] == 2
    assert sorted(c[0] for c in env) == ["d0", "d2"]
    with pytest.raises(ValueError):
        service.start_batch("chat-quality", 1, "G", ["nope"], False)
    with pytest.raises(ValueError):
        service.start_batch("chat-quality", 1, "G", [], False)       # empty selection must not mean "everything"
    whole = service.start_batch("chat-quality", 1, "G", None, True)   # old behaviour: whole set (only missing)
    assert whole["total"] == 2
    wait(whole)
    assert cl["version"] == 1


def make_v2():
    cl = copy.deepcopy(service.get_checklist("chat-quality"))
    for k in ("checklist_id", "version", "created_at"):
        cl.pop(k)
    next(c for c in cl["criteria"] if c["id"] == "c05")["yes_rule"] = "новая формулировка"
    return service.save_checklist("chat-quality", cl)


def test_old_evaluations_kept_and_compare(env):
    wait(service.start_batch("chat-quality", 1, "G", None, False))
    v2 = make_v2()
    assert v2["version"] == 2
    wait(service.start_batch("chat-quality", 2, "G", ["d1", "d2"], False))
    # old v1 evaluations are still there
    assert {e["checklist_version"] for e in service.evaluations_for("d1")} == {1, 2}
    r = service.compare_versions("chat-quality", 1, 2, "G")
    assert r["summary"]["compared"] == 2 and r["summary"]["only_in_a"] == 2
    row = next(x for x in r["rows"] if x["conversation_id"] == "d1")
    assert [c["criterion_id"] for c in row["changed"]] == ["c05"]
    assert row["diff"] < 0 and row["total_b"] < row["total_a"]
    same = next(x for x in r["rows"] if x["conversation_id"] == "d2")
    assert same["changed"] == [] and same["diff"] == 0
    assert r["summary"]["changed_dialogues"] == 1 and r["summary"]["avg_b"] < r["summary"]["avg_a"]


def test_summary(env):
    wait(service.start_batch("chat-quality", 1, "G", None, False))
    s = service.summary("G")
    assert s["dialogues"] == 4 and s["evaluated"] == 4 and s["critical"] == ["d3"]
    c03 = next(c for c in s["criteria"] if c["criterion_id"] == "c03")
    assert c03["percent"] == {"na": 100.0}
    c01 = next(c for c in s["criteria"] if c["criterion_id"] == "c01")
    assert c01["percent"]["yes"] == 100.0
    assert s["avg_total"] is not None


def test_endpoint_functions(env):
    from backend import main
    wait(service.start_batch("chat-quality", 1, "G", None, False))
    assert main.summary("G")["evaluated"] == 4
    assert main.compare("chat-quality", 1, 1, "G")["summary"]["compared"] == 4
    with pytest.raises(service.NotFound):
        main.compare("chat-quality", 1, 9, None)
    job = main.batch(main.BatchReq(checklist_id="chat-quality", version=1, conversation_ids=["d0"]))
    assert job["total"] == 1
    wait(job)
    assert (settings.ROOT / "frontend" / "index.html").exists()

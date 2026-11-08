"""control_run: retries of failed dialogues, error records, MOCK refusal."""
import json

from backend import settings, storage
from scripts import control_run


def test_refuses_mock(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "x.db")
    monkeypatch.setattr(storage, "_conn", None)
    monkeypatch.setattr(settings, "PROVIDER", "mock")
    assert control_run.main(["G", "--out", str(tmp_path / "r.json")]) == 2
    assert "MOCK" in capsys.readouterr().out


def test_retry_then_error_record(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "x.db")
    monkeypatch.setattr(storage, "_conn", None)
    monkeypatch.setattr(settings, "PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    recs = [{"conversation_id": f"c{i}", "channel": "agent chat", "language": "RU", "audio_url": None,
             "transcript": [{"timestamp": "00:00", "speaker": "client", "text": "?"},
                            {"timestamp": "00:05", "speaker": "operator", "text": "Здравствуйте"}]} for i in range(3)]
    f = tmp_path / "set.json"
    f.write_text(json.dumps({"isSuccess": True, "data": {"records": recs}}), encoding="utf-8")

    attempts = {}

    def fake_eval(cid, checklist_id, version=None):
        attempts[cid] = attempts.get(cid, 0) + 1
        if cid == "c1" and attempts[cid] == 1:
            raise RuntimeError("временный сбой")
        if cid == "c2":
            raise RuntimeError("всегда падает")
        items = [{"criterion_id": f"c0{i}", "title": "t", "type": "binary", "answer": "yes", "value": None,
                  "explanation": "ok [1]", "evidence_ids": [1], "checked_range": None} for i in range(1, 8)]
        items[3].update(type="scale", answer="score", value=20)
        items[5].update(type="scale", answer="score", value=10)
        items.append({"criterion_id": "c08", "title": "t", "type": "critical", "answer": "no", "value": None,
                      "explanation": "", "evidence_ids": [], "checked_range": None})
        return {"conversation_id": cid, "checklist_id": checklist_id, "checklist_version": 1,
                "usage": {"model": "fake", "provider": "gemini"}, "result": {"total": 88.5, "critical_error": False, "items": items}}

    monkeypatch.setattr(control_run.service, "evaluate_conversation", fake_eval)
    out = tmp_path / "out.json"
    code = control_run.main(["G", "--file", str(f), "--out", str(out), "--retries", "1", "--retry-wait", "0",
                             "--workers", "2", "--expect-count", "3"])
    assert code == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    st = {r["conversation_id"]: r["status"] for r in doc["results"]}
    assert st == {"c0": "ok", "c1": "ok", "c2": "error"}
    assert attempts["c1"] == 2 and attempts["c2"] == 2
    assert doc["results"][1]["criteria"][0]["evidence_turns"] == [2]
    assert doc["model"]["name"] == "fake"


def test_dry_run_makes_no_model_calls_and_keeps_real_db(monkeypatch, tmp_path):
    import json as _j
    from backend import llm
    real_db = tmp_path / "real.db"
    monkeypatch.setattr(settings, "DB_PATH", real_db)
    monkeypatch.setattr(storage, "_conn", None)
    monkeypatch.setattr(settings, "PROVIDER", "auto")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")

    def boom(*a, **k):
        raise AssertionError("model must not be called")

    monkeypatch.setattr(llm, "call_gemini", boom)
    monkeypatch.setattr(llm, "CALLERS", {"gemini": boom, "openai": boom})
    recs = [{"conversation_id": f"c{i}", "channel": "agent chat", "language": "RU", "audio_url": None,
             "transcript": [{"timestamp": "00:00", "speaker": "client", "text": "?"},
                            {"timestamp": "00:05", "speaker": "operator", "text": "Здравствуйте, я Ива"}]} for i in range(10)]
    f = tmp_path / "set.json"
    f.write_text(_j.dumps({"isSuccess": True, "data": {"records": recs}}), encoding="utf-8")
    out = tmp_path / "dry.json"
    assert control_run.main(["G", "--file", str(f), "--dry-run", "--out", str(out)]) == 0
    doc = _j.loads(out.read_text(encoding="utf-8"))
    assert len(doc["results"]) == 10 and all(r["status"] == "ok" for r in doc["results"])
    assert not real_db.exists()                       # the real database was not touched

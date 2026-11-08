"""LLM pipeline tests with a fake Gemini API (no network): prompt contents, parsing, retry on a bad answer."""
import json

from backend import datasource, llm, settings
from backend.facts import compute_facts
from tests.test_scoring import CL

CONV = datasource.normalize({
    "conversation_id": "t-1", "channel": "agent chat", "language": "RU", "audio_url": None,
    "transcript": [
        {"timestamp": "00:00", "speaker": "client", "text": "Не вижу перевод"},
        {"timestamp": "00:03", "speaker": "bot", "text": "Здравствуйте! Я бот."},
        {"timestamp": "00:10", "speaker": "system", "text": "Эскалация на оператора."},
        {"timestamp": "01:00", "speaker": "operator", "text": "Здравствуйте, я Соня. Проверим."},
        {"timestamp": "01:20", "speaker": "system", "text": "Личность клиента подтверждена."},
        {"timestamp": "02:00", "speaker": "operator", "text": "Передала специалистам. До свидания!"},
    ],
})


def good_items(bad=False):
    items = []
    for c in CL["criteria"]:
        it = {"criterion_id": c["id"], "explanation": "Ок [3]", "evidence_ids": [3], "checked_range": None,
              "answer": "yes", "value": None}
        if c["type"] == "scale":
            it.update(answer="score", value=c["scale"][1]["value"])
        if c["type"] == "critical":
            it.update(answer="no", evidence_ids=[])
        items.append(it)
    if bad:
        items[0]["evidence_ids"] = [42]          # message that does not exist
        items[3]["value"] = 13                   # not a scale step
    return {"items": items}


def gemini_reply(payload):
    return {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True},
                                                  {"text": json.dumps(payload, ensure_ascii=False)}]}}],
            "usageMetadata": {"promptTokenCount": 3000, "candidatesTokenCount": 800, "thoughtsTokenCount": 200}}


def test_prompt_is_built_from_checklist():
    system = llm.build_system({**CL, "version": 7})
    for c in CL["criteria"]:
        assert c["id"] in system and c["title"] in system
    assert "версия 7" in system and "20/15/10/5/0" in system
    user = llm.build_user(CONV, compute_facts(CONV, CL))
    assert "[3] 01:00 operator: Здравствуйте, я Соня." in user
    assert "Первая реплика оператора: [3]" in user


def test_retry_after_invalid_answer(monkeypatch):
    calls = []

    def fake_post(url, body, headers=None, timeout=0):
        calls.append(body)
        return gemini_reply(good_items(bad=len(calls) == 1))

    monkeypatch.setattr(settings, "PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(llm.http_util, "post_json", fake_post)
    res = llm.evaluate(CL, CONV, compute_facts(CONV, CL))
    assert len(calls) == 2
    feedback = calls[1]["contents"][-1]["parts"][0]["text"]
    assert "[42]" in feedback and "c04" in feedback
    assert res["usage"]["calls"] == 2 and res["usage"]["output_tokens"] == 2000
    assert {i["criterion_id"] for i in res["items"]} == {c["id"] for c in CL["criteria"]}


def test_answer_normalization():
    raw = {"items": [{"criterion_id": "c04", "answer": "15", "evidence_ids": ["#3", "m5"], "explanation": "x"},
                     {"criterion_id": "c01", "answer": "Да", "evidence_ids": [3.0], "checked_range": ["1", 5]}]}
    a, b = llm.normalize_items(CL, raw)
    assert (a["answer"], a["value"], a["evidence_ids"]) == ("score", 15, [3, 5])
    assert (b["answer"], b["evidence_ids"], b["checked_range"]) == ("yes", [3], [1, 5])


def test_fallback_to_next_provider(monkeypatch):
    def gemini_limited(*a, **k):
        raise llm.RateLimited("limit")

    monkeypatch.setattr(settings, "PROVIDER", "gemini,mock")
    monkeypatch.setitem(llm.CALLERS, "gemini", gemini_limited)
    res = llm.evaluate(CL, CONV, compute_facts(CONV, CL))
    assert res["provider"] == "mock"


def test_keys_then_models_on_daily_limit(monkeypatch):
    from backend import llm, settings
    calls = []

    def fake(model, key, system, turns, cl):
        calls.append((model, key))
        if key in ("k1", "k2") and model == "m1":
            raise llm.RateLimited("Gemini m1: дневной лимит исчерпан")
        if model == "m1" and key == "k3":
            raise llm.RateLimited("Gemini m1: дневной лимит исчерпан")
        return "{}", {"input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "k1,k2")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k3")
    monkeypatch.setattr(settings, "GEMINI_MAX_KEYS", 0)
    monkeypatch.setattr(settings, "GEMINI_MODEL", "m1, m2")
    monkeypatch.setattr(llm, "_call_gemini_model", fake)
    llm._dead.clear()
    _, usage = llm.call_gemini("s", [{"role": "user", "content": "x"}], {})
    # all three keys tried on m1 first, only then model m2 with key 1
    assert calls == [("m1", "k1"), ("m1", "k2"), ("m1", "k3"), ("m2", "k1")]
    assert usage["model"] == "m2" and usage["key"] == 1
    llm.call_gemini("s", [{"role": "user", "content": "x"}], {})
    assert calls[4:] == [("m2", "k1")]  # exhausted (m1, key) pairs are not asked again
    llm._dead.clear()


def test_next_key_same_model_and_max_keys(monkeypatch):
    from backend import llm, settings
    calls = []

    def fake(model, key, system, turns, cl):
        calls.append((model, key))
        if key == "k1":
            raise llm.RateLimited("дневной лимит")
        return "{}", {"input_tokens": 0, "output_tokens": 0}

    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "k1,k2,k3")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k3")      # duplicate is not added twice
    monkeypatch.setattr(settings, "GEMINI_MODEL", "m1,m2")
    monkeypatch.setattr(llm, "_call_gemini_model", fake)
    llm._dead.clear()
    monkeypatch.setattr(settings, "GEMINI_MAX_KEYS", 0)
    assert llm.gemini_keys() == ["k1", "k2", "k3"]
    _, u = llm.call_gemini("s", [], {})
    assert u["model"] == "m1" and u["key"] == 2 and calls == [("m1", "k1"), ("m1", "k2")]
    monkeypatch.setattr(settings, "GEMINI_MAX_KEYS", 2)
    assert llm.gemini_keys() == ["k1", "k2"]
    llm._dead.clear()


def test_use_keys_restricts_and_labels(monkeypatch):
    from backend import llm, settings
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "a,b,c,d")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_KEY_LABELS", "06,07,08,09")
    monkeypatch.setattr(settings, "GEMINI_MAX_KEYS", 0)
    monkeypatch.setattr(settings, "GEMINI_USE_KEYS", "06,07")
    assert llm.gemini_key_items() == [("06", "a"), ("07", "b")]
    monkeypatch.setattr(settings, "GEMINI_USE_KEYS", "")
    assert len(llm.gemini_keys()) == 4
    calls = []

    def fake(model, key, system, turns, cl):
        calls.append(key)
        return "{}", {"input_tokens": 0, "output_tokens": 0}

    monkeypatch.setattr(settings, "GEMINI_USE_KEYS", "08,09")
    monkeypatch.setattr(llm, "_call_gemini_model", fake)
    llm._dead.clear()
    _, u = llm.call_gemini("s", [], {})
    assert calls == ["c"] and u["key"] == "08"          # keys 06/07 are never touched


def test_exhausted_keys_skipped_fast_no_sleep(monkeypatch):
    """06,07 daily-limited -> goes straight to 08 without sleeping or extra passes."""
    from backend import llm, settings
    import time as _t
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "a,b,c")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_KEY_LABELS", "06,07,08")
    monkeypatch.setattr(settings, "GEMINI_USE_KEYS", "")
    monkeypatch.setattr(settings, "GEMINI_MAX_KEYS", 0)
    monkeypatch.setattr(settings, "GEMINI_MODEL", "m1,m2")
    calls = []

    def fake(model, key, system, turns, cl):
        calls.append((model, key))
        if key in ("a", "b"):
            raise llm.RateLimited("Gemini: дневной лимит исчерпан")
        return "{}", {"input_tokens": 0, "output_tokens": 0}

    slept = []
    monkeypatch.setattr(_t, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(llm, "_call_gemini_model", fake)
    llm._dead.clear()
    _, u = llm.call_gemini("s", [], {})
    assert u["key"] == "08" and u["model"] == "m1" and slept == []
    n = len(calls)
    llm.call_gemini("s", [], {})
    assert len(calls) == n + 1                          # dead pairs not asked again
    llm._dead.clear()


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _clean_key_settings(monkeypatch):
    from backend import settings
    monkeypatch.setattr(settings, "GEMINI_KEY_LABELS", "")
    monkeypatch.setattr(settings, "GEMINI_USE_KEYS", "")

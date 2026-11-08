"""Business logic: evaluations, batch runs, appeals and reviewer decisions."""
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from . import datasource, llm, settings, storage
from .checklist import normalize_checklist
from .facts import compute_facts
from .scoring import score, validate_items


class NotFound(Exception):
    pass


# ---------------------------------------------------------------- startup
def bootstrap() -> None:
    """First start: load the default checklist and any cached datasets from data/*.json."""
    if storage.checklist_count() == 0:
        raw = json.loads(settings.DEFAULT_CHECKLIST_FILE.read_text(encoding="utf-8"))
        storage.save_checklist(raw.get("checklist_id", "default"), normalize_checklist(raw))
    if storage.count_conversations() == 0 and settings.DATA_DIR.exists():
        for f in sorted(settings.DATA_DIR.glob("*.json")):
            try:
                records = datasource.parse_payload(json.loads(f.read_text(encoding="utf-8")))
                storage.upsert_conversations(f.stem, records)
            except (ValueError, json.JSONDecodeError) as e:
                print(f"[cqa] skipped {f.name}: {e}")


# ---------------------------------------------------------------- datasets
def load_group(group_id: str) -> dict:
    records = datasource.fetch_group(group_id)
    storage.upsert_conversations(group_id, records)
    return {"group_id": group_id, "count": len(records)}


def upload_group(group_id: str, payload) -> dict:
    records = datasource.parse_payload(payload)
    storage.upsert_conversations(group_id, records)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / f"{group_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"group_id": group_id, "count": len(records)}


def _summary(ev: dict | None) -> dict | None:
    if not ev:
        return None
    return {"evaluation_id": ev["evaluation_id"], "total": ev["result"]["total"],
            "original_total": ev["original"]["total"], "critical_error": ev["result"]["critical_error"],
            "checklist_id": ev["checklist_id"], "checklist_version": ev["checklist_version"],
            "created_at": ev["created_at"], "model": ev["usage"].get("model"), "appealed": bool(ev["overrides"])}


def list_conversations(group_id: str | None = None) -> list[dict]:
    latest: dict[str, dict] = {}
    for ev in storage.all_evaluations():  # ordered by time, so the last one wins
        latest[ev["conversation_id"]] = ev
    out = []
    for c in storage.list_conversations(group_id):
        tr = c["transcript"]
        out.append({
            "conversation_id": c["conversation_id"], "group_id": c.get("group_id"),
            "channel": c.get("channel"), "language": c.get("language"), "is_call": c.get("is_call"),
            "messages": len(tr), "operator_messages": sum(1 for t in tr if t.get("speaker") == "operator"),
            "preview": next((t.get("text", "")[:140] for t in tr if t.get("speaker") == "client"), ""),
            "latest": _summary(latest.get(c["conversation_id"])),
        })
    return out


def get_conversation(conversation_id: str) -> dict:
    conv = storage.get_conversation(conversation_id)
    if not conv:
        raise NotFound("Диалог не найден")
    return conv


def audio_src(conversation_id: str) -> dict:
    conv = get_conversation(conversation_id)
    if not conv.get("audio_url"):
        raise NotFound("У диалога нет записи")
    return {"src": datasource.resolve_audio(conv["audio_url"]), "original_url": conv["audio_url"]}


# ---------------------------------------------------------------- checklists
def get_checklist(checklist_id: str, version: int | None = None) -> dict:
    cl = storage.get_checklist(checklist_id, version)
    if not cl:
        raise NotFound("Чек-лист не найден")
    return cl


def save_checklist(checklist_id: str, data: dict) -> dict:
    checklist_id = (checklist_id or "").strip()
    if not checklist_id:
        raise ValueError("Укажите id чек-листа")
    return storage.save_checklist(checklist_id, normalize_checklist(data))


# ---------------------------------------------------------------- evaluation
def evaluate_conversation(conversation_id: str, checklist_id: str, version: int | None = None) -> dict:
    conv = get_conversation(conversation_id)
    cl = get_checklist(checklist_id, version)
    facts = compute_facts(conv, cl)
    res = llm.evaluate(cl, conv, facts)
    result = score(cl, res["items"])
    ev = {
        "evaluation_id": storage.new_id("ev"),
        "conversation_id": conversation_id,
        "checklist_id": cl["checklist_id"], "checklist_version": cl["version"], "checklist_name": cl.get("name"),
        "created_at": storage.now(),
        "facts": facts,
        "llm_items": res["items"],      # the model's answers, never modified
        "overrides": {},                # reviewer decisions per criterion
        "original": result,             # score before any appeal
        "result": result,               # current score (with overrides)
        "usage": {**res["usage"], "provider": res["provider"], "model": res["model"]},
    }
    return storage.save_evaluation(ev)


def get_evaluation(evaluation_id: str) -> dict:
    ev = storage.get_evaluation(evaluation_id)
    if not ev:
        raise NotFound("Оценка не найдена")
    return ev


def evaluations_for(conversation_id: str) -> list[dict]:
    return storage.evaluations_for(conversation_id)


# ---------------------------------------------------------------- batch
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_batch(checklist_id: str, version: int | None, group_id: str | None,
                conversation_ids: list[str] | None, only_missing: bool) -> dict:
    cl = get_checklist(checklist_id, version)
    if conversation_ids is not None and len(conversation_ids) == 0:
        raise ValueError("Не выбрано ни одного диалога")
    ids = conversation_ids or [c["conversation_id"] for c in storage.list_conversations(group_id)]
    ids = list(dict.fromkeys(ids))
    unknown = [i for i in ids if not storage.get_conversation(i)]
    if unknown:
        raise ValueError("Нет таких диалогов: " + ", ".join(unknown[:5]))
    if only_missing:
        ids = [i for i in ids if not storage.has_evaluation(i, cl["checklist_id"], cl["version"])]
    job = {"job_id": storage.new_id("job"), "total": len(ids), "done": 0, "failed": 0, "errors": [],
           "finished": len(ids) == 0, "checklist_id": cl["checklist_id"], "checklist_version": cl["version"],
           "started_at": storage.now()}
    _jobs[job["job_id"]] = job

    def one(cid: str):
        try:
            evaluate_conversation(cid, cl["checklist_id"], cl["version"])
            with _jobs_lock:
                job["done"] += 1
        except Exception as e:  # noqa: BLE001 - one failed dialogue must not stop the batch
            with _jobs_lock:
                job["failed"] += 1
                job["errors"].append({"conversation_id": cid, "error": str(e)[:300]})

    def run():
        with ThreadPoolExecutor(max_workers=settings.BATCH_CONCURRENCY) as pool:
            list(pool.map(one, ids))
        job["finished"] = True
        job["finished_at"] = storage.now()

    if ids:
        threading.Thread(target=run, daemon=True).start()
    return job


def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise NotFound("Задача не найдена")
    return job


# ---------------------------------------------------------------- appeals
def _item(result: dict, criterion_id: str) -> dict | None:
    return next((i for i in result["items"] if i["criterion_id"] == criterion_id), None)


def _apply_overrides(ev: dict, overrides: dict) -> list[dict]:
    items = copy.deepcopy(ev["llm_items"])
    for it in items:
        o = overrides.get(it["criterion_id"])
        if o:
            it["answer"], it["value"] = o["answer"], o["value"]
            it["override"] = o
    return items


def create_appeal(evaluation_id: str, criterion_id: str, comment: str) -> dict:
    ev = get_evaluation(evaluation_id)
    item = _item(ev["result"], criterion_id)
    if not item:
        raise ValueError("В оценке нет такого критерия")
    if not (comment or "").strip():
        raise ValueError("Добавьте комментарий к апелляции")
    if any(a["criterion_id"] == criterion_id for a in storage.list_appeals("open", evaluation_id)):
        raise ValueError("По этому критерию уже есть открытая апелляция")
    ap = {
        "appeal_id": storage.new_id("ap"), "evaluation_id": evaluation_id,
        "conversation_id": ev["conversation_id"], "criterion_id": criterion_id,
        "criterion_title": item["title"], "comment": comment.strip(), "status": "open",
        "created_at": storage.now(),
        "disputed": {k: item.get(k) for k in ("answer", "value", "points", "max_points", "status",
                                              "explanation", "evidence_ids", "checked_range")},
        "total_at_filing": ev["result"]["total"], "decision": None,
    }
    return storage.save_appeal(ap)


def enrich_appeal(ap: dict) -> dict:
    """Adds what the reviewer needs: criterion rules, current score and the dialogue fragment."""
    ev = storage.get_evaluation(ap["evaluation_id"])
    conv = storage.get_conversation(ap["conversation_id"])
    if not ev or not conv:
        return ap
    cl = storage.get_checklist(ev["checklist_id"], ev["checklist_version"]) or {"criteria": []}
    crit = next((c for c in cl["criteria"] if c["id"] == ap["criterion_id"]), None)
    d = ap["disputed"]
    ids = set()
    for e in d.get("evidence_ids") or []:
        ids.update(range(e - 1, e + 2))
    rng = d.get("checked_range")
    if rng:
        ids.update(range(rng[0], min(rng[1], rng[0] + 7) + 1))
    n = len(conv["transcript"])
    fragment = [t for t in conv["transcript"] if t["id"] in ids and 0 <= t["id"] < n]
    return {**ap, "criterion": crit, "fragment": fragment, "channel": conv.get("channel"),
            "language": conv.get("language"), "is_call": conv.get("is_call"),
            "current_item": _item(ev["result"], ap["criterion_id"]),
            "totals": {"original": ev["original"]["total"], "current": ev["result"]["total"]},
            "checklist_version": ev["checklist_version"]}


def list_appeals(status: str | None = None, evaluation_id: str | None = None) -> list[dict]:
    return [enrich_appeal(a) for a in storage.list_appeals(status, evaluation_id)]


def decide_appeal(appeal_id: str, action: str, answer: str | None, value, reason: str) -> dict:
    ap = storage.get_appeal(appeal_id)
    if not ap:
        raise NotFound("Апелляция не найдена")
    if ap["status"] != "open":
        raise ValueError("Апелляция уже рассмотрена")
    if not (reason or "").strip():
        raise ValueError("Укажите причину решения")
    if action not in ("confirm", "change"):
        raise ValueError("Решение: confirm (подтвердить) или change (изменить)")

    ev = get_evaluation(ap["evaluation_id"])
    cl = get_checklist(ev["checklist_id"], ev["checklist_version"])
    crit = next(c for c in cl["criteria"] if c["id"] == ap["criterion_id"])
    before = _item(ev["result"], ap["criterion_id"])
    total_before = ev["result"]["total"]

    if action == "change":
        if crit["type"] == "scale" and answer != "na":
            answer = "score"
            value = float(value) if value is not None else None
            if value is not None and value.is_integer():
                value = int(value)
        else:
            value = None
        original = _item(ev["original"], ap["criterion_id"])
        override = {"answer": answer, "value": value, "reason": reason.strip(), "appeal_id": appeal_id,
                    "decided_at": storage.now(), "original_answer": original["answer"],
                    "original_value": original["value"], "original_points": original["points"]}
        overrides = {**ev["overrides"], ap["criterion_id"]: override}
        items = _apply_overrides(ev, overrides)
        errors = validate_items(cl, items)
        if errors:
            raise ValueError("; ".join(errors))
        ev["overrides"] = overrides
        ev["result"] = score(cl, items)
        storage.save_evaluation(ev)

    after = _item(ev["result"], ap["criterion_id"])
    ap["status"] = "changed" if action == "change" else "confirmed"
    ap["decision"] = {
        "action": action, "answer": after["answer"], "value": after["value"], "reason": reason.strip(),
        "decided_at": storage.now(), "total_before": total_before, "total_after": ev["result"]["total"],
        "points_before": before["points"], "points_after": after["points"],
    }
    storage.save_appeal(ap)
    return {"appeal": enrich_appeal(ap), "evaluation": ev}


# ---------------------------------------------------------------- stats (for the cost question)
def stats() -> dict:
    evs = storage.all_evaluations()
    real = [e for e in evs if e["usage"].get("provider") != "mock"]
    n = len(real) or 1
    return {
        "evaluations": len(evs), "llm_evaluations": len(real),
        "avg_input_tokens": round(sum(e["usage"]["input_tokens"] for e in real) / n),
        "avg_output_tokens": round(sum(e["usage"]["output_tokens"] for e in real) / n),
        "avg_latency_ms": round(sum(e["usage"].get("latency_ms", 0) for e in real) / n),
        "avg_cost_usd": round(sum(e["usage"].get("cost_usd", 0) for e in real) / n, 6),
        "total_cost_usd": round(sum(e["usage"].get("cost_usd", 0) for e in real), 4),
        "open_appeals": len(storage.list_appeals("open")),
        **llm.active_model(),
    }


# ---------------------------------------------------------------- compare versions / summary (saved data only, no model calls)
def _latest_by_version(group_id: str | None, checklist_id: str, version: int) -> dict[str, dict]:
    ids = {c["conversation_id"] for c in storage.list_conversations(group_id)} if group_id else None
    out: dict[str, dict] = {}
    for ev in storage.all_evaluations():  # ordered by time: the last one of this version wins
        if ev["checklist_id"] == checklist_id and ev["checklist_version"] == version                 and ev["usage"].get("provider") != "mock" and (ids is None or ev["conversation_id"] in ids):
            out[ev["conversation_id"]] = ev
    return out


def _vals(ev: dict) -> dict[str, tuple]:
    return {i["criterion_id"]: (i["answer"], i["value"]) for i in ev["result"]["items"]}


def compare_versions(checklist_id: str, a: int, b: int, group_id: str | None = None) -> dict:
    """Per dialogue: total in version a, in version b, difference and which criteria changed."""
    get_checklist(checklist_id, a)
    get_checklist(checklist_id, b)
    ea, eb = _latest_by_version(group_id, checklist_id, a), _latest_by_version(group_id, checklist_id, b)
    titles = {i["criterion_id"]: i["title"] for ev in list(ea.values())[:1] + list(eb.values())[:1]
              for i in ev["result"]["items"]}
    rows = []
    for cid in [c["conversation_id"] for c in storage.list_conversations(group_id)]:
        if cid not in ea or cid not in eb:
            continue
        va, vb = _vals(ea[cid]), _vals(eb[cid])
        changed = [{"criterion_id": k, "title": titles.get(k, k), "before": {"answer": va.get(k, (None, None))[0], "value": va.get(k, (None, None))[1]},
                    "after": {"answer": vb.get(k, (None, None))[0], "value": vb.get(k, (None, None))[1]}}
                   for k in dict.fromkeys(list(va) + list(vb)) if va.get(k) != vb.get(k)]
        ta, tb = ea[cid]["result"]["total"], eb[cid]["result"]["total"]
        rows.append({"conversation_id": cid, "total_a": ta, "total_b": tb,
                     "diff": round(tb - ta, 2) if ta is not None and tb is not None else None,
                     "critical_a": ea[cid]["result"]["critical_error"], "critical_b": eb[cid]["result"]["critical_error"],
                     "changed": changed})
    ta = [r["total_a"] for r in rows if r["total_a"] is not None]
    tb = [r["total_b"] for r in rows if r["total_b"] is not None]
    return {"checklist_id": checklist_id, "a": a, "b": b, "group_id": group_id, "rows": rows,
            "summary": {"compared": len(rows), "only_in_a": len(set(ea) - set(eb)), "only_in_b": len(set(eb) - set(ea)),
                        "changed_dialogues": sum(1 for r in rows if r["changed"] or r["diff"]),
                        "avg_a": round(sum(ta) / len(ta), 2) if ta else None,
                        "avg_b": round(sum(tb) / len(tb), 2) if tb else None}}


def summary(group_id: str | None = None) -> dict:
    """Set summary from the latest saved evaluation of each dialogue: average, answer shares per criterion, gross errors."""
    ids = [c["conversation_id"] for c in storage.list_conversations(group_id)]
    latest: dict[str, dict] = {}
    for ev in storage.all_evaluations():
        if ev["usage"].get("provider") != "mock":
            latest[ev["conversation_id"]] = ev
    evs = [latest[i] for i in ids if i in latest]
    totals = [e["result"]["total"] for e in evs if e["result"]["total"] is not None]
    crit: dict[str, dict] = {}
    for e in evs:
        for it in e["result"]["items"]:
            c = crit.setdefault(it["criterion_id"], {"criterion_id": it["criterion_id"], "title": it["title"], "type": it["type"],
                                                    "counts": {}, "n": 0})
            key = "na" if it["answer"] == "na" else (str(it["value"]) if it["type"] == "scale" else it["answer"])
            c["counts"][key] = c["counts"].get(key, 0) + 1
            c["n"] += 1
    for c in crit.values():
        c["percent"] = {k: round(v / c["n"] * 100, 1) for k, v in c["counts"].items()}
    return {"group_id": group_id, "dialogues": len(ids), "evaluated": len(evs),
            "avg_total": round(sum(totals) / len(totals), 2) if totals else None,
            "criteria": list(crit.values()),
            "critical": [e["conversation_id"] for e in evs if e["result"]["critical_error"]]}

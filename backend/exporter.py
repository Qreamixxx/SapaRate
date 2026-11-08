"""Builds results.json (organizers' format 1.0) from saved evaluations, and checks such a file.

Mapping SapaRate -> organizers' criterion codes is by checklist order (c01..c08 -> contact..critical),
so a criterion whose text is replaced in the checklist editor keeps the same code.
"""
import json
import re
from pathlib import Path

from . import settings, storage

SCHEMA_VERSION = "1.0"
TEAM_NAME = "PRO и Bali"
CODES = ["contact", "discovery", "identification", "consultation", "empathy", "dialogue", "closure", "critical"]
NULLABLE = {"discovery", "identification", "consultation", "closure"}
BINARY = {"contact", "discovery", "identification", "empathy", "closure", "critical"}
SCALES = {"consultation": {0, 5, 10, 15, 20}, "dialogue": {0, 4, 7, 10}}

_REF = re.compile(r"\[(\d+)\]")


def shift_refs(text: str) -> str:
    """Replies are 0-based inside SapaRate and 1-based in results.json: [10] -> [11] in the rationale."""
    return _REF.sub(lambda m: f"[{int(m.group(1)) + 1}]", text or "")


def code_for(index: int, criterion_id: str, criteria: list[dict]) -> str | None:
    """c01..c08 by id; otherwise by position among the first eight criteria."""
    m = re.fullmatch(r"c0?([1-8])", criterion_id)
    if m:
        return CODES[int(m.group(1)) - 1]
    return CODES[index] if index < len(CODES) else None


def _evidence(item: dict, conv: dict) -> list[int]:
    ids = [e for e in (item.get("evidence_ids") or []) if isinstance(e, int)]
    if not ids and item.get("checked_range"):
        a, b = item["checked_range"]
        ids = list(range(a, min(b, a + 4) + 1))
    if not ids:
        ops = [t["id"] for t in conv["transcript"] if t.get("speaker") == "operator"]
        ids = ops[:1] + ops[-1:] if ops else []
    n = len(conv["transcript"])
    return sorted({e + 1 for e in ids if 0 <= e < n})  # +1: results.json counts replies from 1


def record_ok(ev: dict, conv: dict) -> dict:
    result = ev["result"]
    if result.get("total") is None:
        raise ValueError("итог не посчитан (нет применимых критериев)")
    criteria_defs = (storage.get_checklist(ev["checklist_id"], ev["checklist_version"]) or {}).get("criteria", [])
    crits: dict[str, dict] = {}
    for idx, row in enumerate(result["items"]):
        code = code_for(idx, row["criterion_id"], criteria_defs)
        if code is None or code in crits:
            continue  # a 9th criterion has no code in the organizers' format
        ans = row["answer"]
        if row["type"] == "scale":
            value = None if ans == "na" else (int(row["value"]) if float(row["value"]).is_integer() else row["value"])
        elif ans == "na":
            value = None
        else:
            value = ans == "yes"
        crits[code] = {"criterion_id": code, "value": value, "rationale": shift_refs(row.get("explanation", "")),
                       "evidence_turns": _evidence(row, conv)}
    missing = [c for c in CODES if c not in crits]
    if missing:
        raise ValueError("нет критериев: " + ", ".join(missing))
    ordered = [crits[c] for c in CODES]
    return {"conversation_id": conv["conversation_id"], "status": "ok", "criteria": ordered,
            "score": {"final_score": round(float(result["total"]), 2), "critical_flag": ordered[-1]["value"] is True}}


def record_error(conversation_id: str, reason: str) -> dict:
    return {"conversation_id": conversation_id, "status": "error", "criteria": [], "score": None,
            "error": reason[:300]}


def latest_eval(conversation_id: str, checklist_id: str | None = None) -> dict | None:
    for ev in storage.evaluations_for(conversation_id):  # newest first
        if ev["usage"].get("provider") == "mock":
            continue
        if checklist_id and ev["checklist_id"] != checklist_id:
            continue
        return ev
    return None


def build(convs: list[dict], errors: dict[str, str] | None = None, checklist_id: str | None = None,
          evals: dict[str, dict] | None = None) -> dict:
    """errors: conversation_id -> reason (always written as status=error);
    evals: conversation_id -> evaluation to use (default: the newest real evaluation)."""
    errors, evals = errors or {}, evals or {}
    results, models = [], []
    for conv in convs:
        cid = conv["conversation_id"]
        if cid in errors:
            results.append(record_error(cid, errors[cid]))
            continue
        ev = evals.get(cid) or latest_eval(cid, checklist_id)
        if ev is None:
            results.append(record_error(cid, errors.get(cid, "диалог не оценён")))
            continue
        try:
            results.append(record_ok(ev, conv))
            m = ev["usage"].get("model")
            if m and m not in models:
                models.append(m)
        except Exception as e:  # noqa: BLE001 - one bad record must not break the file
            results.append(record_error(cid, f"ошибка выгрузки: {e}"))
    return {"schema_version": SCHEMA_VERSION, "team_name": TEAM_NAME,
            "model": {"mode": "external_api", "name": ", ".join(models) or "unknown"}, "results": results}


def write(doc: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ validation
def validate(doc, dataset: list[dict] | None = None, expect_count: int | None = None) -> list[str]:
    """Returns a list of human-readable problems (empty = file is fine)."""
    p: list[str] = []
    if not isinstance(doc, dict):
        return ["Файл должен быть JSON-объектом"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        p.append(f"schema_version должен быть \"{SCHEMA_VERSION}\"")
    if doc.get("team_name") != TEAM_NAME:
        p.append(f"team_name должен быть \"{TEAM_NAME}\"")
    model = doc.get("model")
    if not isinstance(model, dict) or model.get("mode") not in ("local", "external_api", "hybrid") \
            or not isinstance(model.get("name"), str) or not model.get("name"):
        p.append("model: нужны mode (local/external_api/hybrid) и непустой name")
    results = doc.get("results")
    if not isinstance(results, list):
        return p + ["results должен быть массивом"]

    by_id = {d["conversation_id"]: d for d in dataset} if dataset else {}
    seen: set[str] = set()
    for pos, r in enumerate(results):
        cid = r.get("conversation_id") if isinstance(r, dict) else None
        tag = f"[{cid or f'запись #{pos}'}]"
        if not isinstance(r, dict) or not isinstance(cid, str) or not cid:
            p.append(f"{tag}: нет conversation_id")
            continue
        if cid in seen:
            p.append(f"{tag}: ID повторяется")
        seen.add(cid)
        conv = by_id.get(cid)
        if dataset and conv is None:
            p.append(f"{tag}: такого ID нет в наборе")
        n = len(conv["transcript"]) if conv else None
        status = r.get("status")
        if status == "error":
            if r.get("criteria") != []:
                p.append(f"{tag}: у error criteria должен быть пустым []")
            if r.get("score") is not None:
                p.append(f"{tag}: у error score должен быть null")
            if not r.get("error"):
                p.append(f"{tag}: у error нужен текст причины в поле error")
            continue
        if status != "ok":
            p.append(f"{tag}: status должен быть ok или error")
            continue
        crits = r.get("criteria")
        if not isinstance(crits, list) or [c.get("criterion_id") if isinstance(c, dict) else None for c in crits] != CODES:
            got = [c.get("criterion_id") if isinstance(c, dict) else None for c in crits] if isinstance(crits, list) else crits
            p.append(f"{tag}: criteria должны быть ровно {CODES} в этом порядке, а не {got}")
            continue
        is_call = bool(conv and (conv.get("audio_url") or "call" in str(conv.get("channel", "")).lower()))
        for c in crits:
            code, v = c["criterion_id"], c.get("value")
            ctag = f"{tag} {code}"
            if v is None:
                if code not in NULLABLE and not (code == "contact" and (is_call or conv is None)):
                    p.append(f"{ctag}: null (N/A) здесь не разрешён")
                elif code == "contact" and not c.get("rationale"):
                    p.append(f"{ctag}: null у contact требует объяснения в rationale")
            elif code in BINARY:
                if not isinstance(v, bool):
                    p.append(f"{ctag}: value должно быть true/false, а не {v!r}")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or v not in SCALES[code]:
                p.append(f"{ctag}: value должно быть одним из {sorted(SCALES[code])}, а не {v!r}")
            if not isinstance(c.get("rationale"), str):
                p.append(f"{ctag}: rationale должен быть строкой")
            ev = c.get("evidence_turns")
            if not isinstance(ev, list):
                p.append(f"{ctag}: evidence_turns должен быть массивом")
            else:
                for e in ev:
                    if isinstance(e, bool) or not isinstance(e, int) or e < 1 or (n is not None and e > n):
                        p.append(f"{ctag}: evidence_turns {e!r} вне диапазона 1…{n if n is not None else 'длина'}")
        sc = r.get("score")
        if not isinstance(sc, dict):
            p.append(f"{tag}: у ok нужен score")
            continue
        fs = sc.get("final_score")
        if isinstance(fs, bool) or not isinstance(fs, (int, float)) or not 0 <= fs <= 100 or round(fs, 2) != fs:
            p.append(f"{tag}: final_score должен быть числом 0–100 с точностью до 2 знаков, а не {fs!r}")
        crit_val = crits[-1].get("value")
        if sc.get("critical_flag") is not crit_val:
            p.append(f"{tag}: critical_flag ({sc.get('critical_flag')!r}) не совпадает с critical ({crit_val!r})")

    if dataset:
        for cid in by_id:
            if cid not in seen:
                p.append(f"[{cid}]: диалог набора отсутствует в файле")
    if expect_count is not None and len(results) != expect_count:
        p.append(f"Записей {len(results)}, ожидается ровно {expect_count}")
    return p


def load_dataset_file(path: Path) -> list[dict]:
    from . import datasource
    return datasource.parse_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def dataset_for(group_id: str) -> list[dict]:
    """Conversations of the group: the database first, then data/<group>.json."""
    convs = storage.list_conversations(group_id)
    if convs:
        return convs
    f = settings.DATA_DIR / f"{group_id}.json"
    if f.exists():
        return load_dataset_file(f)
    raise ValueError(f"Набор {group_id} не загружен (нет в базе и нет data/{group_id}.json)")

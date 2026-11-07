"""Checks a checklist edited in the UI before it is saved as a new version."""

import re

TYPES = ("binary", "scale", "critical")
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


def normalize_checklist(data: dict) -> dict:
    """Returns a cleaned copy or raises ValueError with all problems listed."""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ValueError("Чек-лист должен быть объектом")
    out = {
        "name": str(data.get("name") or "Чек-лист").strip(),
        "rounding": int(data.get("rounding", 2)),
        "max_total": float(data.get("max_total", 100) or 100),
        "critical_zeroes_total": bool(data.get("critical_zeroes_total", False)),
        "wait_threshold_sec": float(data.get("wait_threshold_sec") or 0),
        "extra_rules": str(data.get("extra_rules") or "").strip(),
        "sections": [],
        "criteria": [],
    }
    if not 0 <= out["rounding"] <= 6:
        errors.append("Округление: от 0 до 6 знаков")

    for s in data.get("sections") or []:
        sid = str(s.get("id") or "").strip()
        if not _ID.match(sid):
            errors.append(f"Секция «{s.get('title')}»: некорректный id")
        out["sections"].append({"id": sid, "title": str(s.get("title") or sid).strip()})
    section_ids = {s["id"] for s in out["sections"]}

    seen = set()
    for i, c in enumerate(data.get("criteria") or [], 1):
        cid = str(c.get("id") or "").strip()
        ctype = {"critical_flag": "critical"}.get(c.get("type"), c.get("type"))
        label = f"Критерий {cid or '#' + str(i)}"
        if not _ID.match(cid):
            errors.append(f"{label}: id только из латиницы/цифр, без пробелов")
        if cid in seen:
            errors.append(f"{label}: id повторяется")
        seen.add(cid)
        if ctype not in TYPES:
            errors.append(f"{label}: тип должен быть binary, scale или critical")
        try:
            weight = float(c.get("weight") or 0)
        except (TypeError, ValueError):
            weight = -1
        if weight < 0:
            errors.append(f"{label}: вес — неотрицательное число")
        crit = {
            "id": cid,
            "section": str(c.get("section") or "").strip(),
            "title": str(c.get("title") or "").strip(),
            "type": ctype,
            "weight": 0.0 if ctype == "critical" else weight,
            "na_allowed": bool(c.get("na_allowed")) and ctype != "critical",
            "yes_rule": str(c.get("yes_rule") or "").strip(),
            "na_rule": str(c.get("na_rule") or "").strip(),
            "note": str(c.get("note") or "").strip(),
        }
        if not crit["title"]:
            errors.append(f"{label}: нет названия")
        if crit["section"] and crit["section"] not in section_ids:
            errors.append(f"{label}: секции «{crit['section']}» нет в списке секций")
        if ctype == "scale":
            steps = []
            for s in c.get("scale") or []:
                try:
                    steps.append(
                        {
                            "value": float(s.get("value")),
                            "label": str(s.get("label") or "").strip(),
                        }
                    )
                except (TypeError, ValueError):
                    errors.append(f"{label}: ступень шкалы должна быть числом")
            values = [s["value"] for s in steps]
            if len(steps) < 2:
                errors.append(f"{label}: у шкалы нужно минимум 2 ступени")
            elif len(set(values)) != len(values):
                errors.append(f"{label}: ступени шкалы повторяются")
            elif max(values) <= 0:
                errors.append(f"{label}: максимальная ступень должна быть больше 0")
            steps.sort(key=lambda s: -s["value"])
            for s in steps:
                if s["value"].is_integer():
                    s["value"] = int(s["value"])
            crit["scale"] = steps
        out["criteria"].append(crit)

    if not out["criteria"]:
        errors.append("Добавьте хотя бы один критерий")
    elif not any(c["type"] != "critical" and c["weight"] > 0 for c in out["criteria"]):
        errors.append("Нужен хотя бы один критерий с весом больше 0")
    if errors:
        raise ValueError("; ".join(errors))
    return out

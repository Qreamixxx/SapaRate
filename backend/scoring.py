"""
ALL SCORE FORMULAS LIVE HERE. The model never calculates points; it only answers each criterion.

How the total is calculated (edit here if the checklist rules say otherwise):

  1. Applicable criteria = criteria with weight > 0, that are not the gross-error flag,
     and whose answer is not N/A.
  2. W = sum of the weights of the applicable criteria.
  3. N/A weight is redistributed proportionally:
         effective_weight = weight / W * max_total        (max_total is 100 by default)
  4. Share of the weight a criterion earns:
         binary:  yes -> 1, no -> 0
         scale:   chosen step / highest step               (e.g. 15 of 20 -> 0.75)
  5. points = effective_weight * share
  6. total = sum(points), rounded to `rounding` digits, half-up (87.335 -> 87.34).
     The unrounded points are summed, so per-row rounding never shifts the total.
  7. Gross-error criteria (type "critical"): answer "yes" means a violation was found.
     It is flagged separately and does not change the total, unless the checklist sets
     "critical_zeroes_total": true, in which case the total becomes 0.

Answer format of one item:
    {"criterion_id": "c04", "answer": "yes" | "no" | "na" | "score", "value": 15 or None, ...}
"""
from decimal import ROUND_HALF_UP, Decimal

BINARY_ANSWERS = ("yes", "no")


def round_half_up(x: float | None, digits: int = 2) -> float | None:
    if x is None:
        return None
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))


def scale_values(criterion: dict) -> list[float]:
    return [float(s["value"]) for s in criterion.get("scale", [])]


def scale_max(criterion: dict) -> float:
    return max(scale_values(criterion))


def is_weighted(criterion: dict) -> bool:
    return criterion["type"] != "critical" and float(criterion.get("weight") or 0) > 0


def _num_list(values) -> str:
    return ", ".join(f"{v:g}" for v in values)


def validate_items(checklist: dict, items: list[dict], n_messages: int | None = None) -> list[str]:
    """Checks the answers against the checklist. Returns a list of errors (empty = OK)."""
    errors: list[str] = []
    by_id: dict[str, dict] = {}
    for it in items:
        cid = it.get("criterion_id")
        if cid in by_id:
            errors.append(f"Критерий {cid} указан дважды")
        by_id[cid] = it
    known = {c["id"] for c in checklist["criteria"]}
    for cid in by_id:
        if cid not in known:
            errors.append(f"Критерия {cid} нет в чек-листе")

    for c in checklist["criteria"]:
        it = by_id.get(c["id"])
        if it is None:
            errors.append(f"Нет ответа по критерию {c['id']}")
            continue
        answer = it.get("answer")
        if answer == "na":
            if not c.get("na_allowed"):
                errors.append(f"{c['id']}: N/A для этого критерия не разрешён")
        elif c["type"] == "scale":
            value = it.get("value")
            if answer != "score" or value is None or float(value) not in scale_values(c):
                errors.append(f"{c['id']}: нужен answer=\"score\" и value — одна ступень из [{_num_list(scale_values(c))}]")
        elif answer not in BINARY_ANSWERS:
            allowed = "yes, no" + (", na" if c.get("na_allowed") else "")
            errors.append(f"{c['id']}: answer должен быть одним из: {allowed}")

        if n_messages is not None:
            for e in it.get("evidence_ids") or []:
                if not isinstance(e, int) or not 0 <= e < n_messages:
                    errors.append(f"{c['id']}: реплики [{e}] нет в диалоге (есть [0]–[{n_messages - 1}])")
            rng = it.get("checked_range")
            if rng is not None:
                if len(rng) != 2 or not all(isinstance(x, int) and 0 <= x < n_messages for x in rng) or rng[0] > rng[1]:
                    errors.append(f"{c['id']}: checked_range должен быть [с, по] в пределах [0]–[{n_messages - 1}]")
    return errors


def score(checklist: dict, items: list[dict]) -> dict:
    digits = int(checklist.get("rounding", 2))
    max_total = float(checklist.get("max_total", 100))
    by_id = {it["criterion_id"]: it for it in items}

    def share(c: dict, it: dict) -> float:
        if c["type"] == "scale":
            return float(it["value"]) / scale_max(c)
        return 1.0 if it["answer"] == "yes" else 0.0

    applicable = [c for c in checklist["criteria"]
                  if is_weighted(c) and by_id.get(c["id"], {}).get("answer") != "na"]
    W = sum(float(c["weight"]) for c in applicable)

    rows, raw_total, per_section = [], 0.0, {}
    for c in checklist["criteria"]:
        it = by_id.get(c["id"], {})
        row = {
            "criterion_id": c["id"], "title": c.get("title", c["id"]), "section": c.get("section"),
            "type": c["type"], "weight": float(c.get("weight") or 0),
            "answer": it.get("answer"), "value": it.get("value") if c["type"] == "scale" else None,
            "scale_max": scale_max(c) if c["type"] == "scale" else None,
            "explanation": it.get("explanation", ""), "evidence_ids": it.get("evidence_ids") or [],
            "checked_range": it.get("checked_range"), "override": it.get("override"),
            "effective_weight": 0.0, "points": None, "max_points": None,
        }
        if c["type"] == "critical":
            row["status"] = "violation" if it.get("answer") == "yes" else "clean"
        elif not is_weighted(c):
            row["status"] = "info"
        elif it.get("answer") == "na":
            row["status"] = "na"
        else:
            ew = float(c["weight"]) / W * max_total
            pts = ew * share(c, it)
            raw_total += pts
            acc = per_section.setdefault(c.get("section"), [0.0, 0.0])
            acc[0] += pts
            acc[1] += ew
            row.update(status="scored", effective_weight=round_half_up(ew, digits),
                       points=round_half_up(pts, digits), max_points=round_half_up(ew, digits))
        rows.append(row)

    critical_items = [c["id"] for c in checklist["criteria"]
                      if c["type"] == "critical" and by_id.get(c["id"], {}).get("answer") == "yes"]
    total_before_critical = round_half_up(raw_total, digits) if W > 0 else None
    total = total_before_critical
    if critical_items and checklist.get("critical_zeroes_total") and total is not None:
        total = 0.0

    sections = []
    for s in checklist.get("sections", []):
        acc = per_section.get(s["id"])
        sections.append({
            "id": s["id"], "title": s.get("title", s["id"]),
            "points": round_half_up(acc[0], digits) if acc else None,
            "max": round_half_up(acc[1], digits) if acc else None,
            "percent": round_half_up(acc[0] / acc[1] * 100, 1) if acc and acc[1] else None,
        })

    return {
        "items": rows, "sections": sections, "total": total,
        "total_before_critical": total_before_critical,
        "critical_error": bool(critical_items), "critical_items": critical_items,
        "applicable_weight": W, "max_total": max_total,
    }

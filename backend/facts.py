"""Facts the code computes itself (not the model): who wrote first, long waits, system events.
They are passed to the model as hints and shown in the UI."""


def _fmt(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60} мин {sec % 60:02d} с"


def compute_facts(conv: dict, checklist: dict) -> dict:
    tr = conv["transcript"]
    threshold = float(checklist.get("wait_threshold_sec") or 0)
    ops = [t for t in tr if t.get("speaker") == "operator"]
    facts = {
        "language": conv.get("language"),
        "channel": conv.get("channel"),
        "messages": len(tr),
        "operator_messages": len(ops),
        "first_operator_id": ops[0]["id"] if ops else None,
        "last_operator_id": ops[-1]["id"] if ops else None,
        "system_events": [{"id": t["id"], "text": (t.get("text") or "")[:160]}
                          for t in tr if t.get("speaker") == "system"],
        "long_waits": [],
        "first_response_sec": None,
        "wait_threshold_sec": threshold or None,
    }

    # waits: client message -> next operator reply longer than the checklist threshold (chats only)
    if threshold and not conv.get("is_call"):
        pending = None
        for t in tr:
            if t.get("speaker") == "client" and pending is None:
                pending = t
            elif t.get("speaker") == "operator":
                if pending is not None and pending["offset_sec"] is not None and t["offset_sec"] is not None:
                    gap = t["offset_sec"] - pending["offset_sec"]
                    if gap > threshold:
                        facts["long_waits"].append({"from_id": pending["id"], "to_id": t["id"],
                                                    "seconds": round(gap), "text": _fmt(gap)})
                pending = None

    # first response: from the hand-over to an operator (system event) or the first client message
    if ops and ops[0]["offset_sec"] is not None:
        handover = next((t for t in tr if t.get("speaker") == "system" and t["id"] < ops[0]["id"]), None)
        start = handover or next((t for t in tr if t.get("speaker") == "client"), None)
        if start and start["offset_sec"] is not None:
            facts["first_response_sec"] = max(0, round(ops[0]["offset_sec"] - start["offset_sec"]))
    return facts


def facts_to_text(f: dict) -> str:
    lines = [f"Язык по данным: {f['language']}. Канал: {f['channel']}. Реплик: {f['messages']}, "
             f"из них оператора: {f['operator_messages']}."]
    if f["first_operator_id"] is None:
        lines.append("Оператор в диалоге не писал.")
    else:
        lines.append(f"Первая реплика оператора: [{f['first_operator_id']}], последняя: [{f['last_operator_id']}].")
    if f["first_response_sec"] is not None:
        lines.append(f"Время до первой реплики оператора после передачи диалога: {_fmt(f['first_response_sec'])}.")
    if f["wait_threshold_sec"]:
        if f["long_waits"]:
            lines.append("Ожидания ответа оператора дольше порога: " +
                         "; ".join(f"[{w['from_id']}]→[{w['to_id']}] {w['text']}" for w in f["long_waits"]) + ".")
        elif f["channel"] and "call" not in str(f["channel"]).lower():
            lines.append("Ожиданий ответа оператора дольше порога нет.")
    return "\n".join(lines)

"""Trainer sandbox: turns typed "К: ... / О: ..." lines into a dialogue, saves it to the group "Тренажёр" and evaluates it
with the normal pipeline (service.evaluate_conversation). Nothing here changes scoring or export."""
import re
import uuid

from . import datasource, service, storage

GROUP = "Тренажёр"
PREFIX = re.compile(r"^\s*(к|клиент|c|client|о|оператор|o|operator)\s*[:：-]\s*(.*)$", re.I)
CLIENT = {"к", "клиент", "c", "client"}


def parse(text: str) -> list[dict]:
    """Lines 'К: ...' (client) and 'О: ...' (operator); a line without a prefix continues the previous message."""
    msgs: list[dict] = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        m = PREFIX.match(raw)
        if m:
            who = "client" if m.group(1).lower() in CLIENT else "operator"
            msgs.append({"speaker": who, "text": m.group(2).strip()})
        elif msgs:
            msgs[-1]["text"] += " " + raw.strip()
        else:
            raise ValueError("Каждая строка должна начинаться с «К:» (клиент) или «О:» (оператор)")
    msgs = [x for x in msgs if x["text"]]
    if not any(x["speaker"] == "client" for x in msgs) or not any(x["speaker"] == "operator" for x in msgs):
        raise ValueError("Нужна хотя бы одна реплика клиента («К: …») и одна оператора («О: …»)")
    for i, x in enumerate(msgs):
        x["timestamp"] = f"{(i * 5) // 60:02d}:{(i * 5) % 60:02d}"
    return msgs


def language(text: str) -> str:
    if re.search(r"[әғқңөұүіӘҒҚҢӨҰҮІ]", text):
        return "KZ"
    if re.search(r"[а-яА-ЯёЁ]", text):
        return "RU"
    return "EN" if re.search(r"[a-zA-Z]", text) else "RU"


def evaluate_text(text: str, checklist_id: str | None = None) -> dict:
    transcript = parse(text)
    cid = "trainer-" + uuid.uuid4().hex[:8]
    rec = datasource.normalize({"conversation_id": cid, "channel": "agent chat", "language": language(text),
                                "transcript": transcript, "audio_url": None})
    storage.upsert_conversations(GROUP, [rec])
    cl = checklist_id or storage.list_checklists()[0]["checklist_id"]
    ev = service.evaluate_conversation(cid, cl, None)
    return {"conversation_id": cid, "evaluation_id": ev["evaluation_id"], "total": ev["result"]["total"]}

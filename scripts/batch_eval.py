"""Evaluate a whole dataset from the command line (useful for the control set at hour 23).

    python scripts/batch_eval.py CONTROL            # download group CONTROL and evaluate everything
    python scripts/batch_eval.py DEV --missing      # only dialogues without an evaluation for this checklist version
    python scripts/batch_eval.py DEV --no-fetch     # use what is already loaded

Results go to the same database the UI uses, plus reports/<group>.csv.
"""
import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import service, settings, storage  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("group_id")
    p.add_argument("--checklist", default=None, help="checklist id (default: the first one)")
    p.add_argument("--version", type=int, default=None, help="checklist version (default: latest)")
    p.add_argument("--missing", action="store_true", help="skip dialogues already evaluated with this version")
    p.add_argument("--no-fetch", action="store_true", help="do not download, use loaded data")
    p.add_argument("--workers", type=int, default=settings.BATCH_CONCURRENCY)
    a = p.parse_args()

    service.bootstrap()
    if not a.no_fetch:
        print(f"Загружаю набор {a.group_id}…")
        print(f"  диалогов: {service.load_group(a.group_id)['count']}")
    checklist_id = a.checklist or storage.list_checklists()[0]["checklist_id"]
    cl = service.get_checklist(checklist_id, a.version)
    convs = storage.list_conversations(a.group_id)
    ids = [c["conversation_id"] for c in convs]
    if a.missing:
        ids = [i for i in ids if not storage.has_evaluation(i, cl["checklist_id"], cl["version"])]
    print(f"Чек-лист {cl['checklist_id']} v{cl['version']}, к оценке: {len(ids)}, потоков: {a.workers}")

    rows, started = [], time.time()

    def one(cid):
        try:
            ev = service.evaluate_conversation(cid, cl["checklist_id"], cl["version"])
            r, u = ev["result"], ev["usage"]
            row = {"conversation_id": cid, "total": r["total"], "critical_error": r["critical_error"],
                   **{i["criterion_id"]: ("na" if i["answer"] == "na" else i["value"] if i["type"] == "scale" else i["answer"])
                      for i in r["items"]},
                   "model": u["model"], "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
                   "cost_usd": u["cost_usd"], "latency_s": round(u["latency_ms"] / 1000, 1), "error": ""}
            print(f"  ✓ {cid:<14} {r['total']!s:>6}{'  ГРУБАЯ ОШИБКА' if r['critical_error'] else ''}")
        except Exception as e:  # noqa: BLE001
            row = {"conversation_id": cid, "error": str(e)[:300]}
            print(f"  ✗ {cid:<14} {e}")
        rows.append(row)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        list(pool.map(one, ids))

    ok = [r for r in rows if not r.get("error")]
    out = Path(settings.ROOT / "reports")
    out.mkdir(exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    path = out / f"{a.group_id}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    n = len(ok) or 1
    print(f"\nГотово за {time.time() - started:.0f} с: {len(ok)} оценено, {len(rows) - len(ok)} с ошибкой.")
    print(f"Средние токены: {sum(r['input_tokens'] for r in ok) / n:.0f} вход + {sum(r['output_tokens'] for r in ok) / n:.0f} выход; "
          f"стоимость: ${sum(r['cost_usd'] for r in ok) / n:.5f} за оценку. Отчёт: {path}")


if __name__ == "__main__":
    main()

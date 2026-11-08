"""One command for the control hour: download the set, evaluate everything in parallel, export, validate.

    python scripts/control_run.py <group_id>                      # -> results/prod/results.json (+ check, 10 records)
    python scripts/control_run.py <group_id> --file control.json  # API is down: use a saved API answer
    python scripts/control_run.py DEV --limit 10 --fresh --out results/rehearsal/results.json   # rehearsal

It does NOT run git push.
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):  # Windows consoles (cp1251) cannot print ✓/✗
    _s.reconfigure(encoding="utf-8", errors="replace")

from backend import exporter, llm, service, settings, storage  # noqa: E402


def evaluate_all(ids, cl, workers, fresh, retries, retry_wait):
    """Returns (evals, errors). Failed dialogues are retried `retries` more times."""
    evals: dict[str, dict] = {}
    errors: dict[str, str] = {}
    todo = list(ids)
    if not fresh:
        for cid in list(todo):
            if storage.has_evaluation(cid, cl["checklist_id"], cl["version"]):
                evals_ev = exporter.latest_eval(cid, cl["checklist_id"])
                if evals_ev and evals_ev["checklist_version"] == cl["version"]:
                    evals[cid] = evals_ev
                    todo.remove(cid)
        if evals:
            print(f"Уже оценены (пропускаю): {len(evals)}")
    stop = {"daily": False}

    def one(cid):
        if stop["daily"]:
            errors[cid] = "дневной лимит модели исчерпан, оценка не выполнялась"
            return
        t = time.time()
        try:
            ev = service.evaluate_conversation(cid, cl["checklist_id"], cl["version"])
            evals[cid] = ev
            errors.pop(cid, None)
            print(f"  ✓ {cid:<14} {ev['result']['total']!s:>6}  {time.time() - t:4.0f} с"
                  f"{'  ГРУБАЯ ОШИБКА' if ev['result']['critical_error'] else ''}", flush=True)
        except Exception as e:  # noqa: BLE001
            errors[cid] = str(e)[:300]
            if "дневной лимит" in str(e):
                stop["daily"] = True
            print(f"  ✗ {cid:<14} {str(e)[:120]}", flush=True)

    for rnd in range(retries + 1):
        if not todo:
            break
        if rnd:
            print(f"Повтор упавших ({len(todo)}), попытка {rnd}/{retries} через {retry_wait} с…", flush=True)
            time.sleep(retry_wait)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(one, todo))
        todo = [c for c in todo if c in errors and not stop["daily"]]
    return evals, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("group_id")
    ap.add_argument("--file", default=None, help="сохранённый ответ API (JSON), если API недоступен")
    ap.add_argument("--workers", type=int, default=4, help="сколько диалогов оценивать одновременно")
    ap.add_argument("--retries", type=int, default=2, help="сколько раз повторять упавшие")
    ap.add_argument("--retry-wait", type=int, default=20)
    ap.add_argument("--out", default=None, help="куда писать (по умолчанию results/prod/results.json)")
    ap.add_argument("--expect-count", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None, help="взять только первые N диалогов (для репетиции)")
    ap.add_argument("--ids", default=None, help="только эти conversation_id через запятую (для проверок)")
    ap.add_argument("--fresh", action="store_true", help="оценить заново, даже если уже оценено (репетиция)")
    ap.add_argument("--model", default=None, help="название модели Gemini (иначе GEMINI_MODEL из .env)")
    ap.add_argument("--keys", default=None, help="только эти ключи по названию, напр. 06,07 (остальные не трогать)")
    ap.add_argument("--checklist", default=None)
    a = ap.parse_args(argv)
    started = time.time()
    if a.model:
        settings.GEMINI_MODEL = a.model
    if a.keys:
        settings.GEMINI_USE_KEYS = a.keys
    service.bootstrap()
    chain = llm.active_model()
    print(f"Модель: {chain['chain']} / {chain['model']}, потоков: {a.workers}, ключи: {[lb for lb, _ in llm.gemini_key_items()]}")
    if chain["provider"] == "mock":
        print("✗ Включён MOCK-режим (нет ключа). Останавливаюсь, чтобы не выгрузить заглушки.")
        return 2

    # 1. get the set
    if a.file:
        import json
        n = service.upload_group(a.group_id, json.loads(Path(a.file).read_text(encoding="utf-8")))["count"]
        print(f"Набор {a.group_id} из файла {a.file}: {n} диалогов")
    else:
        try:
            n = service.load_group(a.group_id)["count"]
            print(f"Набор {a.group_id} из API: {n} диалогов")
        except ValueError as e:
            print(f"✗ API не ответил: {e}\n  Сохраните ответ в файл и запустите с --file <файл>")
            return 2
    convs = storage.list_conversations(a.group_id)
    if a.ids:
        want = [x.strip() for x in a.ids.split(",") if x.strip()]
        convs = [c for c in convs if c["conversation_id"] in want]
    if a.limit:
        convs = convs[:a.limit]
    ids = [c["conversation_id"] for c in convs]
    expect = a.expect_count if a.expect_count is not None else (len(ids) if a.limit or a.out else 10)

    # 2. evaluate
    cl = service.get_checklist(a.checklist or storage.list_checklists()[0]["checklist_id"])
    print(f"Чек-лист {cl['checklist_id']} v{cl['version']}, к оценке: {len(ids)}")
    evals, errors = evaluate_all(ids, cl, a.workers, a.fresh, a.retries, a.retry_wait)

    # 3. export + validate
    out = Path(a.out) if a.out else ROOT / "results" / "prod" / "results.json"
    doc = exporter.build(convs, errors, cl["checklist_id"], evals)
    exporter.write(doc, out)
    problems = exporter.validate(doc, convs, expect)
    ok = sum(1 for r in doc["results"] if r["status"] == "ok")
    secs = time.time() - started
    print(f"\nГотово: {out}\nok: {ok}, error: {len(doc['results']) - ok}, время: {secs:.0f} с ({secs / 60:.1f} мин). "
          f"Модель в файле: {doc['model']['name']}")
    for cid, why in errors.items():
        print(f"  error {cid}: {why[:150]}")
    if problems:
        print(f"✗ Проверка формата не пройдена ({len(problems)}):")
        for p in problems:
            print("  -", p)
        return 1
    print(f"✓ Проверка формата пройдена (ожидалось записей: {expect})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

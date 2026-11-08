"""Check a results.json file against the organizers' format 1.0.

    python scripts/validate_results.py results/dev/results.json
    python scripts/validate_results.py results/prod/results.json --expect-count 10
    python scripts/validate_results.py file.json --data data/CONTROL.json   # dataset to compare IDs / lengths

Exit code 0 = fine, 1 = problems (printed as a list).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):  # Windows consoles (cp1251) cannot print ✓/✗
    _s.reconfigure(encoding="utf-8", errors="replace")

from backend import exporter  # noqa: E402


def guess_dataset(path: Path, doc: dict) -> Path | None:
    """results/dev -> data/DEV.json; otherwise the only other file in data/ if it is unambiguous."""
    if path.parent.name == "dev" and (ROOT / "data" / "DEV.json").exists():
        return ROOT / "data" / "DEV.json"
    ids = {r.get("conversation_id") for r in doc.get("results", []) if isinstance(r, dict)}
    for f in sorted((ROOT / "data").glob("*.json")):
        try:
            got = {d["conversation_id"] for d in exporter.load_dataset_file(f)}
        except Exception:  # noqa: BLE001
            continue
        if ids & got:
            return f
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--expect-count", type=int, default=None)
    ap.add_argument("--data", default=None, help="набор диалогов (JSON ответа API) для сверки ID и длины transcript")
    a = ap.parse_args(argv)
    path = Path(a.path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"✗ Не удалось прочитать {path}: {e}")
        return 1
    data_path = Path(a.data) if a.data else guess_dataset(path, doc)
    dataset = None
    if data_path:
        dataset = exporter.load_dataset_file(data_path)
    else:
        print("! Набор диалогов не найден: проверка ID и номеров реплик по длине пропущена (укажите --data)")
    problems = exporter.validate(doc, dataset, a.expect_count)
    if problems:
        print(f"✗ {path}: найдено проблем: {len(problems)}")
        for p in problems:
            print("  -", p)
        return 1
    res = doc["results"]
    ok = sum(1 for r in res if r["status"] == "ok")
    print(f"✓ {path}: формат верный. Записей {len(res)} (ok {ok}, error {len(res) - ok}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

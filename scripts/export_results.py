"""Export saved evaluations to results/<dev|prod>/results.json (organizers' format 1.0) and validate it.

    python scripts/export_results.py DEV dev
    python scripts/export_results.py <CONTROL_GROUP_ID> prod
    python scripts/export_results.py DEV dev --out results/rehearsal/results.json
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):  # Windows consoles (cp1251) cannot print ✓/✗
    _s.reconfigure(encoding="utf-8", errors="replace")

from backend import exporter, service  # noqa: E402


def export(group_id: str, kind: str, out: Path | None = None, errors: dict | None = None,
           checklist_id: str | None = None, expect_count: int | None = None) -> tuple[Path, list[str], dict]:
    service.bootstrap()
    convs = exporter.dataset_for(group_id)
    doc = exporter.build(convs, errors, checklist_id)
    path = out or ROOT / "results" / kind / "results.json"
    exporter.write(doc, path)
    if expect_count is None and kind == "prod":
        expect_count = 10
    return path, exporter.validate(doc, convs, expect_count), doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("group_id")
    ap.add_argument("kind", choices=["dev", "prod"])
    ap.add_argument("--out", default=None, help="другой путь вместо results/<kind>/results.json")
    ap.add_argument("--checklist", default=None)
    ap.add_argument("--expect-count", type=int, default=None)
    a = ap.parse_args(argv)
    path, problems, doc = export(a.group_id, a.kind, Path(a.out) if a.out else None,
                                 checklist_id=a.checklist, expect_count=a.expect_count)
    ok = sum(1 for r in doc["results"] if r["status"] == "ok")
    print(f"Записано {path}: ok {ok}, error {len(doc['results']) - ok}. Модель: {doc['model']['name']}")
    if problems:
        print(f"✗ Проверка не пройдена, проблем: {len(problems)}")
        for p in problems:
            print("  -", p)
        return 1
    print("✓ Проверка формата пройдена")
    return 0


if __name__ == "__main__":
    sys.exit(main())

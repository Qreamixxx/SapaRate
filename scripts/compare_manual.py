"""Compare a results.json with a hand-made check (data/manual_check.json): agreement per criterion.
    python scripts/compare_manual.py results/dev/results.json [data/manual_check.json]
Not the organizers' truth - only a rough way to find obvious prompt mistakes."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CODES = ["contact", "discovery", "identification", "consultation", "empathy", "dialogue", "closure", "critical"]


def compare(res_path, man_path="data/manual_check.json", show=True):
    res = {r["conversation_id"]: r for r in json.loads(Path(res_path).read_text("utf-8"))["results"]}
    man = json.loads(Path(man_path).read_text("utf-8"))
    disputed = {tuple(x) for x in man.pop("_disputed", [])}  # doubtful hand labels are not counted
    ok = {c: 0 for c in CODES}
    n = {c: 0 for c in CODES}
    diffs = []
    for cid, truth in man.items():
        r = res.get(cid)
        if not r or r["status"] != "ok":
            continue
        got = {c["criterion_id"]: c["value"] for c in r["criteria"]}
        for c in CODES:
            if (cid, c) in disputed:
                continue
            n[c] += 1
            if got[c] == truth[c]:
                ok[c] += 1
            else:
                diffs.append((cid, c, truth[c], got[c]))
    if show:
        for c in CODES:
            print(f"  {c:<15} {ok[c]}/{n[c]}  {100 * ok[c] / max(n[c], 1):.0f}%")
        tot, tn = sum(ok.values()), sum(n.values())
        print(f"  ВСЕГО           {tot}/{tn}  {100 * tot / max(tn, 1):.0f}%")
        for d in diffs:
            print("   расхождение:", d[0], d[1], "ручная =", d[2], "модель =", d[3])
    return ok, n, diffs


if __name__ == "__main__":
    compare(*sys.argv[1:3])

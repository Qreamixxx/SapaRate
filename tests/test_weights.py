"""Weights: fractional weights are accepted everywhere, the rebalance keeps the sum at exactly 100.00."""
import json
from pathlib import Path

from backend.checklist import normalize_checklist
from backend.scoring import score
from backend.weights import rebalance

CL = json.loads((Path(__file__).parent.parent / "config" / "checklist_v1.json").read_text("utf-8"))


def test_example_from_the_task():
    # Contact 10 -> 15 (locked); the others (20, 15, ... sum 90) are scaled by 85/90
    w = [15, 15, 20, 20, 15, 15, 5]
    out, msg = rebalance(w, [True] + [False] * 6)
    assert msg == "" and round(sum(out), 2) == 100.0
    assert out[0] == 15 and out[2] == round(20 * 85 / 90, 2) + (out[2] - round(20 * 85 / 90, 2))  # ratio kept up to rounding
    assert abs(out[6] - 5 * 85 / 90) < 0.02 and abs(out[2] - 18.89) < 0.02


def test_ratios_kept_and_exact_sum():
    out, _ = rebalance([11, 15, 20, 20, 15, 15, 5], [True] + [False] * 6)
    assert round(sum(out), 2) == 100.0
    assert abs(out[2] / out[1] - 20 / 15) < 0.02


def test_two_manual_weights_both_locked():
    out, _ = rebalance([15, 25, 20, 20, 15, 15, 5], [True, True] + [False] * 5)
    assert out[0] == 15 and out[1] == 25 and round(sum(out), 2) == 100.0


def test_locked_over_100_or_nothing_free_changes_nothing():
    w = [60, 50, 20, 20, 15, 15, 5]
    out, msg = rebalance(w, [True, True] + [False] * 5)
    assert out == w and "больше" in msg
    out, msg = rebalance([10, 15, 20, 20, 15, 15, 5], [True] * 7)
    assert out == [10, 15, 20, 20, 15, 15, 5] and "закреплены" in msg


def test_remainder_goes_to_biggest_unlocked():
    out, _ = rebalance([10, 1, 1, 1], [True, False, False, False])
    assert round(sum(out), 2) == 100.0


def test_fractional_weights_accepted_by_checklist_and_scoring():
    cl = json.loads(json.dumps(CL))
    for c, w in zip(cl["criteria"], [15, 18.89, 17.78, 17.78, 13.33, 13.33, 4.89, 0]):
        c["weight"] = w
    n = normalize_checklist(cl)
    assert [c["weight"] for c in n["criteria"]][:3] == [15.0, 18.89, 17.78]
    items = [{"criterion_id": c["id"], "answer": "score" if c["type"] == "scale" else ("no" if c["type"] == "critical" else "yes"),
              "value": max(s["value"] for s in c["scale"]) if c["type"] == "scale" else None} for c in n["criteria"]]
    assert score(n, items)["total"] == 100.0     # a share of the maximum: never above 100

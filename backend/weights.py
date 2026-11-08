"""Weight rebalancing used by the checklist editor ("sum is always 100" mode).

The editor (frontend/js/components/checklist-editor.js, rebalance) does the same steps; this module is the tested reference.
The scoring formula (scoring.py) is NOT affected: the total is always a share of the applicable maximum.
"""


def rebalance(weights: list[float], locked: list[bool], total: float = 100.0):
    """Returns (new_weights, message). Locked weights stay as they are, the others are scaled proportionally so that
    the sum is exactly `total` (2 decimals, the rounding remainder goes to the biggest unlocked weight).
    If locked weights exceed `total` or nothing is unlocked, nothing is changed and a message is returned."""
    L = sum(w for w, k in zip(weights, locked) if k)
    free = [i for i, k in enumerate(locked) if not k]
    if L > total + 1e-7:
        return list(weights), f"Закреплённые веса дают {L:g}, это больше {total:g}: пересчёт не выполнен"
    if not free:
        return list(weights), "Все веса закреплены, пересчитывать нечего"
    rest = total - L
    S = sum(weights[i] for i in free)
    raw = [(weights[i] * rest / S) if S > 0 else rest / len(free) for i in free]
    r = [round(x + 1e-9, 2) for x in raw]
    diff = round(rest - sum(r), 2)
    big = r.index(max(r))
    r[big] = round(r[big] + diff, 2)
    out = list(weights)
    for k, i in enumerate(free):
        out[i] = r[k]
    return out, ""

"""Successive halving over seeds, decided from held-out evaluations (pure functions, no I/O).

Used in the November 2026 campaign (docs/campaign_2026-11.md): at every milestone M the seeds that reached M are scored
on the held-out panel; the leader is the best score; at most half of the seeds are stopped, and only those whose gap to
the leader exceeds z standard errors; the leader, the best seed of the best other lineage and every seed under a
`protect_until` grace are never stopped; every freed slot gets a fork of the leader's newest checkpoint under a new seed.

Straggler rule: the round waits for every applicable seed's eval at M only until some seed has a checkpoint
`lead` updates past M; then it runs without the missing seeds. A straggler cannot lead and is judged against the leader
at the newest earlier milestone both have an eval for (same-update comparison), or waits for the next round. A
straggler that is its lineage's only seed is protected. Seeds slow for a good reason (harder reset mix) otherwise gate
every round.

Roster: {"active": {seed: {"host", "lineage", "start", optional "protect_until"}}, "next_seed": int}.
Score: {"success": fraction on the panel, "n": trials}.
"""
from __future__ import annotations

import math


def score_subset(per_task: dict[str, dict], tasks: list[str]) -> dict:
    """Panel score restricted to `tasks` from per-task {"successes", "n"} records."""
    n = sum(per_task[t]["n"] for t in tasks)
    k = sum(per_task[t]["successes"] for t in tasks)
    return {"success": k / n, "n": n}


def clearly_below(leader: dict, other: dict, z: float = 1.96) -> tuple[bool, float, float]:
    """(gap > z * se, gap, z * se) for two binomial panel scores."""
    p, q = leader["success"], other["success"]
    se = math.sqrt(p * (1 - p) / leader["n"] + q * (1 - q) / other["n"])
    gap = p - q
    return gap > z * se, gap, z * se


def gate(milestone: int, applicable: dict, have: set, newest_checkpoint: dict, lead: int = 250) -> tuple[list, int, bool]:
    """(missing seeds, newest checkpoint of any applicable seed, proceed without the missing ones?)."""
    missing = sorted(int(s) for s in applicable if s not in have)
    ahead = max([newest_checkpoint.get(s, 0) for s in applicable] + [0])
    return missing, ahead, ahead >= milestone + lead


def decide(milestone: int, roster: dict, scores: dict, history: dict | None = None, stragglers: tuple = (), z: float = 1.96) -> dict:
    """Round document from the scores {seed: score} of the seeds evaluated at `milestone`.

    `history` {(seed, milestone): score} supplies the earlier milestones used to judge stragglers.
    """
    act = roster["active"]
    history = history or {}
    stragglers = [str(s) for s in stragglers]
    order = sorted(scores, key=lambda s: (-scores[s]["success"], int(s)))
    leader = order[0]
    lead = scores[leader]
    lineage = lambda s: act[s]["lineage"]
    others = [s for s in order if lineage(s) != lineage(leader)]
    protected = {leader} | ({others[0]} if others else set())
    protected |= {s for s in order + stragglers if act[s].get("protect_until", 0) > milestone}
    protected |= {s for s in stragglers if lineage(s) not in {lineage(o) for o in order}}
    cap = (len(order) + len(stragglers)) // 2
    stop, table = [], {}
    for s in reversed(order):
        below, gap, band = clearly_below(lead, scores[s], z)
        table[s] = dict(scores[s], gap=round(gap, 4), band=round(band, 4), clearly_below=below, lineage=lineage(s))
        if s not in protected and below and len(stop) < cap:
            stop.append(s)
    for s in stragglers:
        common = [m for (k, m) in history if k == s and (leader, m) in history]
        if not common:
            table[s] = dict(straggler=True, compared_at=None, clearly_below=False, lineage=lineage(s))
            continue
        m = max(common)
        below, gap, band = clearly_below(history[(leader, m)], history[(s, m)], z)
        table[s] = dict(history[(s, m)], straggler=True, compared_at=m, gap=round(gap, 4), band=round(band, 4), clearly_below=below, lineage=lineage(s))
        if s not in protected and below and len(stop) < cap:
            stop.append(s)
    forks, nxt = [], roster["next_seed"]
    for s in stop:
        forks.append({"seed": nxt, "host": act[s]["host"], "slot_from_seed": int(s), "lineage": lineage(leader)})
        nxt += 1
    return {
        "milestone": milestone,
        "leader": int(leader),
        "leader_score": lead,
        "protected": sorted(map(int, protected)),
        "stop": [{"seed": int(s), "host": act[s]["host"], "score": round(table[s]["success"], 4)} for s in stop],
        "forks": forks,
        "next_seed": nxt,
        "stragglers": sorted(map(int, stragglers)),
        "scores": {str(s): table[s] for s in order + stragglers},
    }


def apply_round(roster: dict, rd: dict, fork_from: dict) -> dict:
    """Roster after a round (idempotent): stopped seeds move to `stopped`, forks join `active`."""
    import copy

    r = copy.deepcopy(roster)
    r.setdefault("stopped", {})
    for s in rd["stop"]:
        if str(s["seed"]) in r["active"]:
            r["stopped"][str(s["seed"])] = dict(r["active"].pop(str(s["seed"])), round=rd["milestone"], score=s["score"])
    for f in rd["forks"]:
        r["active"].setdefault(str(f["seed"]), {"host": f["host"], "lineage": f["lineage"], "start": fork_from["update"], "slot_from_seed": f["slot_from_seed"], "fork_from": fork_from})
    r["next_seed"] = max(r["next_seed"], rd["next_seed"])
    return r

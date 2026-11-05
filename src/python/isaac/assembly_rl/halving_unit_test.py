import json

from isaac.assembly_rl import halving


def sc(p, n=2720):
    return {"success": p, "n": n}


def roster():
    return {
        "active": {
            "12": {"host": "h2", "lineage": 12, "start": 0},
            "14": {"host": "h2", "lineage": 14, "start": 0},
            "16": {"host": "h1", "lineage": 14, "start": 1550},
            "17": {"host": "h1", "lineage": 14, "start": 1550},
            "25": {"host": "h2", "lineage": 24, "start": 1900, "protect_until": 3500},
        },
        "next_seed": 30,
    }


def test_score_subset_and_noise_band():
    per_task = {"A": {"successes": 150, "n": 160}, "B": {"successes": 160, "n": 160}, "N": {"successes": 30, "n": 160}}
    assert halving.score_subset(per_task, ["A", "B"]) == {"success": 310 / 320, "n": 320}
    below, gap, band = halving.clearly_below(sc(0.96), sc(0.94))
    assert below and abs(gap - 0.02) < 1e-12 and 0.011 < band < 0.012
    assert not halving.clearly_below(sc(0.943), sc(0.932))[0]


def test_gate_waits_until_the_field_is_lead_updates_ahead():
    app = roster()["active"]
    assert halving.gate(2500, app, {"17", "14", "25"}, {"17": 2700, "16": 2300, "12": 2100}) == ([12, 16], 2700, False)
    assert halving.gate(2500, app, {"17", "14", "25"}, {"17": 2750, "16": 2300, "12": 2100}) == ([12, 16], 2750, True)
    assert halving.gate(2500, app, set(app), {"17": 2500}) == ([], 2500, False)


def test_round_with_stragglers():
    history = {("16", 2000): sc(0.90), ("17", 2000): sc(0.936), ("25", 2000): sc(0.943), ("14", 2000): sc(0.932), ("12", 1500): sc(0.70), ("14", 1500): sc(0.758)}
    rd = halving.decide(2500, roster(), {"25": sc(0.96), "17": sc(0.95), "14": sc(0.94)}, history, [12, 16])
    assert rd["leader"] == 25 and rd["protected"] == [12, 17, 25] and rd["stragglers"] == [12, 16]
    assert [s["seed"] for s in rd["stop"]] == [14, 16]  # 14 clearly below at 2500; 16 clearly below the leader at 2000
    assert rd["scores"]["16"]["compared_at"] == 2000 and rd["scores"]["12"]["compared_at"] is None
    assert [(f["seed"], f["slot_from_seed"], f["lineage"]) for f in rd["forks"]] == [(30, 14, 24), (31, 16, 24)]
    json.dumps(rd)  # serialisable
    kept = halving.decide(2500, roster(), {"25": sc(0.96), "17": sc(0.95), "14": sc(0.955)}, {**history, ("16", 2000): sc(0.94)}, [12, 16])
    assert kept["stop"] == []
    r2 = halving.apply_round(roster(), rd, {"update": 2550, "seed_dir": "seed25"})
    assert set(r2["stopped"]) == {"14", "16"} and r2["active"]["30"]["start"] == 2550 and r2["next_seed"] == 32


def test_plain_round_keeps_two_lineages_alive():
    # leader lineage 24; the best seed of the best OTHER lineage (14) is protected, so two lineages survive;
    # seed 12 (third lineage, clearly below) and seed 16 are stopped, at most half of the four
    rd = halving.decide(2500, roster(), {"25": sc(0.96), "14": sc(0.93), "16": sc(0.90), "12": sc(0.85)})
    assert rd["leader"] == 25 and rd["protected"] == [14, 25] and [s["seed"] for s in rd["stop"]] == [12, 16]
    assert {f["slot_from_seed"] for f in rd["forks"]} == {12, 16} and rd["next_seed"] == 32

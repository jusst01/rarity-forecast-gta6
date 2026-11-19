"""Synthetic LIVE-regime smoke test & scorer for make.fun gta6-trophy-rarity-forecast-01
Generates 20 synthetic cases, runs our main.py and kit starter, scores by mean pinball loss on logit scale.
"""

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

def logit(p):
    p = max(0.0001, min(0.9999, p))
    return math.log(p / (1.0 - p))

def pinball(y, q, tau):
    return max(tau * (y - q), (1.0 - tau) * (q - y))

def generate_synthetic_case(case_id, seed):
    # Deterministic pseudo-random using simple LCG
    state = seed + ord(case_id[-1])
    def rng():
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7fffffff
        return state / 2147483647.0

    trophies = [
        {"id": 1, "name": "Platinum", "tier": "platinum", "points": 300, "secret": False},
        {"id": 2, "name": "100% Completion", "tier": "gold", "points": 90, "secret": False},
        {"id": 3, "name": "Early Story", "tier": "bronze", "points": 15, "secret": True},
        {"id": 4, "name": "Mid Story 1.1%", "tier": "bronze", "points": 15, "secret": True},
        {"id": 5, "name": "Side Quest", "tier": "silver", "points": 30, "secret": False},
    ]

    history = []
    base_n = 1000
    start_time = 1731974400 # 2026-11-19T00:00:00Z

    # 10 history events over 2 days
    rates = [0.05, 0.1, 2.0, 1.1, 5.0]
    for step in range(10):
        t = start_time + step * 7200 # every 2 hours
        dt_str = "2026-11-19T" + f"{step*2:02d}:00:00Z"
        base_n = int(base_n * (1.0 + 0.05 * rng()))

        step_rates = []
        for i, r in enumerate(rates):
            # grow rates with some noise and lag
            growth = 1.0 + 0.1 * step * (1.0 - 0.1 * i) + 0.05 * rng()
            new_r = min(99.0, max(0.01, r * growth))
            if i == 1: # 100% trophy reaches 100% eventually
                if step > 6: new_r = 100.0
            step_rates.append(new_r)

        history.append({
            "slot": dt_str,
            "at": dt_str,
            "players_tracked": base_n,
            "trophies_earned": int(base_n * 0.5),
            "rates": step_rates
        })

    target_dt = "2026-11-19T24:00:00Z"
    # True rates at target (synthetic truth)
    true_rates = []
    for i, r in enumerate(rates):
        true_r = min(99.99, max(0.01, r * (1.0 + 0.3 + 0.1 * rng())))
        if i == 1: true_r = 100.0
        true_rates.append(true_r)

    case_data = {
        "schema": "makefun/gta6-trophies-case/v1",
        "id": case_id,
        "at": "2026-11-19T20:00:00Z",
        "horizon_minutes": 6516, # ~4.5 days
        "target": target_dt,
        "levels": [0.05, 0.25, 0.5, 0.75, 0.95],
        "game": {"name": "Grand Theft Auto VI", "platform": "PS5"},
        "trophies": trophies,
        "history": history
    }
    return case_data, true_rates

def run_scorer():
    taus = [0.05, 0.25, 0.5, 0.75, 0.95]
    our_losses = []
    starter_losses = []

    repo_dir = Path(__file__).resolve().parent.parent
    starter_script = repo_dir.parent / "kit" / "starter" / "main.py"
    our_script = repo_dir / "main.py"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / "in"
        tmp_out_ours = Path(tmpdir) / "out_ours"
        tmp_out_starter = Path(tmpdir) / "out_starter"
        tmp_in.mkdir()
        tmp_out_ours.mkdir()
        tmp_out_starter.mkdir()

        cases_truth = {}
        for i in range(20):
            cid = f"synth{i:02d}"
            case_data, true_rates = generate_synthetic_case(cid, seed=i*13+7)
            cases_truth[cid] = true_rates
            (tmp_in / f"{cid}.in").write_text(json.dumps(case_data))

        # Run our model
        subprocess.run([sys.executable, str(our_script)], env={"MAKEFUN_INPUT_DIR": str(tmp_in), "MAKEFUN_OUTPUT_DIR": str(tmp_out_ours)}, check=True)
        # Run kit starter
        subprocess.run([sys.executable, str(starter_script)], env={"MAKEFUN_INPUT_DIR": str(tmp_in), "MAKEFUN_OUTPUT_DIR": str(tmp_out_starter)}, check=True)

        for cid, true_rates in cases_truth.items():
            our_out = json.loads((tmp_out_ours / f"{cid}.out").read_text())
            starter_out = json.loads((tmp_out_starter / f"{cid}.out").read_text())

            for t_idx, tr in enumerate(true_rates):
                y_true = logit(tr)

                # Ours
                our_q_pcts = our_out["trophies"][t_idx]["q"]
                for tau_idx, tau in enumerate(taus):
                    q_val = logit(our_q_pcts[tau_idx])
                    our_losses.append(pinball(y_true, q_val, tau))

                # Starter
                st_q_pcts = starter_out["trophies"][t_idx]["q"]
                for tau_idx, tau in enumerate(taus):
                    q_val = logit(st_q_pcts[tau_idx])
                    starter_losses.append(pinball(y_true, q_val, tau))

    mean_our = sum(our_losses) / len(our_losses)
    mean_starter = sum(starter_losses) / len(starter_losses)
    print(f"Synthetic LIVE Smoke Test (20 cases):")
    print(f"  Our Model Mean Pinball Loss:    {mean_our:.4f}")
    print(f"  Kit Starter Mean Pinball Loss: {mean_starter:.4f}")
    if mean_our < mean_starter:
        print("  RESULT: Our model successfully outperforms kit starter!")
    else:
        print("  RESULT: Our model score needs tuning relative to starter.")

if __name__ == "__main__":
    run_scorer()

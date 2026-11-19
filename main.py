"""Refresh-Aware Rarity Forecaster — GTA VI trophy earn rates (gta6-trophy-rarity-forecast-01)
Implements DESIGN.md S0-S9, Python standard library only.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# sys.path guard for grader -P
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

def clamp(x: float, lo: float = 0.01, hi: float = 99.99) -> float:
    return max(lo, min(hi, x))

def logit(pct: float) -> float:
    p_frac = max(0.00001, min(0.99999, pct / 100.0))
    return math.log(p_frac / (1.0 - p_frac))

def inv_logit(l: float) -> float:
    p = 1.0 / (1.0 + math.exp(-l))
    return max(0.0, min(100.0, p * 100.0))

def round4(x: float) -> float | int:
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value.is_integer() else value

def parse_iso(dt_str: str) -> datetime:
    if not dt_str:
        return datetime.now(timezone.utc)
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.now(timezone.utc)

def hours_since_epoch(dt: datetime) -> float:
    epoch = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)
    delta = dt - epoch
    return delta.total_seconds() / 3600.0

def median(lst: list[float]) -> float:
    if not lst:
        return 0.0
    s = sorted(lst)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    else:
        return 0.5 * (s[n // 2 - 1] + s[n // 2])

def theil_sen(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if abs(dx) > 1e-9:
                slopes.append((ys[j] - ys[i]) / dx)
    slope = median(slopes) if slopes else 0.0
    intercepts = [ys[i] - slope * xs[i] for i in range(n)]
    intercept = median(intercepts) if intercepts else 0.0
    return slope, intercept

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bisection_mixture(mu1, s1, w1, mu2, s2, w2, target_p, lo=-15.0, hi=15.0):
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        cdf = w1 * norm_cdf((mid - mu1) / max(1e-6, s1)) + w2 * norm_cdf((mid - mu2) / max(1e-6, s2))
        if cdf < target_p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)

def forecast_case(case: dict, name: str) -> dict:
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    trophies = case["trophies"]
    history = case["history"]
    horizon_days = case["horizon_minutes"] / 1440.0
    target_dt = parse_iso(case.get("target"))

    # S0 Sanitize & S1 Eventize
    events = []
    max_n = 10
    for h_item in history:
        dt = parse_iso(h_item.get("at", h_item.get("slot")))
        n = h_item.get("players_tracked", 10)
        if n is not None:
            max_n = max(max_n, n)
        rates = h_item.get("rates", [])
        clean_rates = []
        for r in rates:
            if r is None:
                clean_rates.append(0.0)
            else:
                clean_rates.append(clamp(float(r), 0.0, 100.0))
        events.append({"dt": dt, "n": max_n, "rates": clean_rates})

    events.sort(key=lambda x: x["dt"])

    unique_events = []
    for ev in events:
        if not unique_events:
            unique_events.append(ev)
        else:
            prev = unique_events[-1]
            if ev["n"] != prev["n"] or ev["rates"] != prev["rates"]:
                unique_events.append(ev)
    events = unique_events[-150:]

    n_values = [ev["n"] for ev in events]
    is_flat = len(events) < 2 or (max(n_values) - min(n_values) < 2)

    rows = []

    if is_flat:
        # S6a FLAT branch
        last_rates = history[-1]["rates"] if history else [0.0] * len(trophies)
        for i, trophy in enumerate(trophies):
            r_last = last_rates[i] if i < len(last_rates) and last_rates[i] is not None else 0.0

            # 100% trophy pinning
            if r_last >= 99.99 or "100%" in trophy["name"]:
                rows.append({"id": trophy["id"], "q": [99.0, 99.9, 100, 100, 100]})
                continue

            if r_last < 0.05:
                r_last = 0.05

            L_last = logit(r_last)
            mu1 = L_last + math.log(638.0 / 3868.0)
            s1 = 0.35 * max(0.5, math.sqrt(horizon_days))
            mu2 = L_last
            s2 = 0.15 * max(0.5, math.sqrt(horizon_days))

            qs = []
            for tau in LEVELS:
                l_val = bisection_mixture(mu1, s1, 0.85, mu2, s2, 0.15, tau)
                pct = inv_logit(l_val)
                qs.append(round4(pct))

            for j in range(1, len(qs)):
                if qs[j] < qs[j-1]:
                    qs[j] = qs[j-1]
            rows.append({"id": trophy["id"], "q": [round4(clamp(q, 0, 100)) for q in qs]})
    else:
        xs = [hours_since_epoch(ev["dt"]) for ev in events]
        target_x = hours_since_epoch(target_dt)

        ln_ns = [math.log(max(10, ev["n"])) for ev in events]
        n_slope, n_intercept = theil_sen(xs, ln_ns)
        pred_ln_n = n_intercept + n_slope * target_x
        pred_n = math.exp(pred_ln_n)

        last_ev = events[-1]
        last_rates = last_ev["rates"]

        tiers = [t.get("tier", "bronze") for t in trophies]
        tier_slopes = {}
        trophy_data = []

        for i, trophy in enumerate(trophies):
            r = last_rates[i] if i < len(last_rates) else 0.0
            if r >= 99.99 or "100%" in trophy["name"]:
                trophy_data.append({"slope": 0.0, "intercept": 0.0, "is_100": True})
                continue

            e_vals = [math.log(max(0.5, (ev["rates"][i] / 100.0) * ev["n"])) for ev in events if i < len(ev["rates"])]
            if len(e_vals) == len(xs) and len(xs) >= 2:
                s_slope, s_intercept = theil_sen(xs, e_vals)
            else:
                s_slope, s_intercept = 0.0, 0.0
            trophy_data.append({"slope": s_slope, "intercept": s_intercept, "is_100": False})
            tier = tiers[i]
            tier_slopes.setdefault(tier, []).append(s_slope)

        tier_med_slopes = {tier: median(sls) for tier, sls in tier_slopes.items()}

        for i, trophy in enumerate(trophies):
            t_info = trophy_data[i]
            if t_info["is_100"]:
                rows.append({"id": trophy["id"], "q": [99.0, 99.9, 100, 100, 100]})
                continue

            r_last = last_rates[i] if i < len(last_rates) else 0.0
            if r_last < 0.05:
                r_last = 0.05

            n_events = len(events)
            w = n_events / (n_events + 6.0)
            tier_med = tier_med_slopes.get(tiers[i], 0.0)
            shrunk_slope = w * t_info["slope"] + (1.0 - w) * tier_med

            pred_ln_e = t_info["intercept"] + shrunk_slope * target_x
            pred_e = min(pred_n * 0.999, math.exp(pred_ln_e))
            pred_rate = 100.0 * pred_e / max(1.0, pred_n)

            p_frac = clamp(pred_rate / 100.0, 0.001, 0.999)
            sigma_ln_n = 0.15
            s0 = 0.08
            s_rw = 0.2
            s_drift = 0.1
            s_jump = 0.15

            var_val = (s0**2) + (s_rw**2) * horizon_days + (s_drift**2) * (horizon_days**2) + ((sigma_ln_n / max(0.05, 1.0 - p_frac))**2) + (s_jump**2) * (horizon_days / max(0.1, horizon_days))
            sigma_total = math.sqrt(max(0.001, var_val))

            median_logit = logit(pred_rate)
            qs = []
            for z_val in Z:
                l_q = median_logit + z_val * sigma_total
                qs.append(round4(inv_logit(l_q)))

            for j in range(1, len(qs)):
                if qs[j] < qs[j-1]:
                    qs[j] = qs[j-1]
            rows.append({"id": trophy["id"], "q": [round4(clamp(q, 0, 100)) for q in qs]})

    return {"trophies": rows}

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()

"""Refresh-Aware Rarity Forecaster — GTA VI trophy earn rates (gta6-trophy-rarity-forecast-01)

Second entry: the V3 model (see ../briefs/V3-SPEC.md). It eventizes the reads,
decomposes each rarity into earners / players, fits saturating log-time trends
(x = ln(1 + hours since the first read)) with damped slopes, shrinks them toward
tier x band group medians, blends the result with persistence on the logit scale,
and prices the remaining spread from event residuals and horizon. The FLAT branch
(the launch refresh has not happened yet) uses a count-consistent dilution
mixture. Every case and every row has a persistence fallback, so the program
never raises and never emits an invalid row.

Python standard library only.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader runs `python3 -P -s`: -P keeps this file's directory off sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard-normal quantiles at the five scored levels.
Z = [-1.644854, -0.674490, 0.0, 0.674490, 1.644854]

PINNED = [99.0, 99.9, 100.0, 100.0, 100.0]

# The disclosed launch refresh: 638 -> 3,868 tracked players.
GROWTH = 3868.0 / 638.0
FLAT_W_MAIN = 0.95
FLAT_W_TAIL = 0.05
FLAT_SIGMA_MAIN = 0.10
FLAT_SIGMA_TAIL = 0.15

SLOPE_DAMPING = 0.6       # both the player and the earner log-time slopes
CAP_DOWN = -2.2           # max logit movement downward from the last rate
CAP_UP = 1.6              # max logit movement upward from the last rate
MIN_SIGMA_RSD = 0.12
MAX_SIGMA_RSD = 0.6
SPARSE_SIGMA = 1.2        # floor when the last event implies fewer than one earner


# --------------------------------------------------------------------------
# small numeric helpers
# --------------------------------------------------------------------------

def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def logit_pct(p):
    """Logit of a percentage, with p clamped to [0.01, 99.99]."""
    p = clamp(float(p), 0.01, 99.99)
    frac = p / 100.0
    return math.log(frac / (1.0 - frac))


def inv_logit(ell):
    """Percentage from a logit, guarded for very large |ell|."""
    if ell >= 0.0:
        # 1 + exp(-ell) is safe for ell >= 0
        return 100.0 / (1.0 + math.exp(-ell))
    e = math.exp(ell)
    return 100.0 * e / (1.0 + e)


def median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def round_half_up(x):
    """JavaScript-style Math.round: half away from zero."""
    if x >= 0.0:
        return int(math.floor(x + 0.5))
    return -int(math.floor(-x + 0.5))


def round4(x):
    """Round to 4 decimals, half up; whole numbers become ints (JSON 100, not 100.0)."""
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000.0
    if value == int(value):
        return int(value)
    return value


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def theil_sen(xs, ys):
    """Slope = median pairwise slope over distinct x; intercept = median(y - slope*x)."""
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0, (float(ys[0]) if ys else 0.0)
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if abs(dx) > 1e-12:
                slopes.append((ys[j] - ys[i]) / dx)
    slope = median(slopes) if slopes else 0.0
    intercepts = [ys[i] - slope * xs[i] for i in range(n)]
    return slope, median(intercepts)


def parse_ts(value):
    """Parse an ISO-8601 timestamp into an aware datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------
# eventize
# --------------------------------------------------------------------------

def build_events(case):
    """Collapse reads into distinct states, oldest first.

    Returns a list of dicts {hours, n, rates} where hours is measured from the
    first read's timestamp, n is the tracked-player count and rates holds floats
    (None read as 0.0). Raises on unusable timestamps so the caller can fall back.
    """
    history = case.get("history")
    if not isinstance(history, list):
        history = []

    parsed = []
    for item in history:
        if not isinstance(item, dict):
            continue
        dt = parse_ts(item.get("at", item.get("slot")))
        if dt is None:
            raise ValueError("unparseable read timestamp")
        parsed.append((dt, item))

    if not parsed:
        return []

    parsed.sort(key=lambda pair: pair[0])
    first_dt = parsed[0][0]

    events = []
    prev_key = None
    for dt, item in parsed:
        raw_rates = item.get("rates")
        if not isinstance(raw_rates, list):
            raw_rates = []
        key = (item.get("players_tracked"), tuple(raw_rates))
        if events and key == prev_key:
            continue
        prev_key = key
        n_raw = item.get("players_tracked")
        try:
            n_val = float(n_raw) if n_raw is not None else 0.0
        except (TypeError, ValueError):
            n_val = 0.0
        values = []
        for r in raw_rates:
            if r is None:
                values.append(0.0)
            else:
                try:
                    values.append(clamp(float(r), 0.0, 100.0))
                except (TypeError, ValueError):
                    values.append(0.0)
        hours = (dt - first_dt).total_seconds() / 3600.0
        events.append({"hours": hours, "n": n_val, "rates": values})

    return events


# --------------------------------------------------------------------------
# persistence fallback (never-crash)
# --------------------------------------------------------------------------

def last_read_rates(case):
    history = case.get("history")
    if not isinstance(history, list) or not history:
        return [], 0.0
    last = history[-1]
    if not isinstance(last, dict):
        return [], 0.0
    rates = last.get("rates")
    if not isinstance(rates, list):
        rates = []
    try:
        n_last = float(last.get("players_tracked") or 0.0)
    except (TypeError, ValueError):
        n_last = 0.0
    return rates, n_last


def rate_at(rates, index):
    if index < len(rates):
        value = rates[index]
        if value is not None:
            try:
                return clamp(float(value), 0.0, 100.0)
            except (TypeError, ValueError):
                pass
    return 0.0


def persistence_row(rate, spread):
    if rate >= 99.99:
        return list(PINNED)
    lg = logit_pct(rate)
    qs = [round4(inv_logit(lg + z * spread)) for z in Z]
    return monotone(qs)


def persistence_rows(case):
    """Persistence forecast: last rates, random-walk logit spread."""
    trophies = case.get("trophies")
    if not isinstance(trophies, list):
        return []
    try:
        horizon_days = max(0.0, float(case.get("horizon_minutes") or 0.0) / 1440.0)
    except (TypeError, ValueError):
        horizon_days = 0.0
    spread = max(0.35, 0.5 * math.sqrt(horizon_days))
    rates, _ = last_read_rates(case)
    rows = []
    for i, trophy in enumerate(trophies):
        if not isinstance(trophy, dict) or "id" not in trophy:
            return []
        rows.append({"id": trophy["id"], "q": persistence_row(rate_at(rates, i), spread)})
    return rows


def monotone(qs):
    out = []
    prev = 0.0
    for value in qs:
        value = clamp(float(value), 0.0, 100.0)
        if value < prev:
            value = prev
        out.append(round4(value))
        prev = value
    return out


# --------------------------------------------------------------------------
# FLAT branch — count-consistent dilution
# --------------------------------------------------------------------------

def mixture_quantile(mu_main, s_main, w_main, mu_tail, s_tail, w_tail, level):
    lo, hi = -16.0, 16.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        cdf = (w_main * norm_cdf((mid - mu_main) / s_main)
               + w_tail * norm_cdf((mid - mu_tail) / s_tail))
        if cdf < level:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def flat_row(last_rate, n_last):
    if last_rate >= 99.99:
        return list(PINNED)
    n_den = n_last if n_last > 0.0 else 1.0
    earners = round_half_up(last_rate / 100.0 * n_den)
    if earners > 0:
        diluted = 100.0 * earners / (n_den * GROWTH)
    else:
        diluted = 0.02
    mu_main = logit_pct(diluted)
    mu_tail = logit_pct(max(last_rate, 0.05))
    qs = []
    for level in LEVELS:
        ell = mixture_quantile(mu_main, FLAT_SIGMA_MAIN, FLAT_W_MAIN,
                               mu_tail, FLAT_SIGMA_TAIL, FLAT_W_TAIL, level)
        qs.append(inv_logit(ell))
    return monotone(qs)


def forecast_flat(events, trophies):
    if events:
        last = events[-1]
        rates = last["rates"]
        n_last = last["n"]
    else:
        rates, n_last = [], 0.0
    rows = []
    for i, trophy in enumerate(trophies):
        rows.append({"id": trophy["id"], "q": flat_row(rate_at(rates, i), n_last)})
    return rows


# --------------------------------------------------------------------------
# LIVE branch — saturating log-time fits
# --------------------------------------------------------------------------

def band_of(rate):
    if rate < 1.0:
        return 0
    if rate < 10.0:
        return 1
    if rate < 50.0:
        return 2
    return 3


def live_row(i, trophy, events, xs, x_last, x_tgt, n_tgt, lam, horizon_days):
    last = events[-1]
    rates_last = last["rates"]
    r_last = rate_at(rates_last, i)
    if r_last >= 99.99:
        return list(PINNED)

    n_last = last["n"] if last["n"] > 0.0 else 1.0
    n_target = n_tgt if n_tgt > 0.0 else 1.0
    last_logit = logit_pct(max(r_last, 0.05))

    # (1) earner slope: integer earners implied by each event's rate and N
    earner_ys = []
    for ev in events:
        r = rate_at(ev["rates"], i)
        n_ev = ev["n"] if ev["n"] > 0.0 else 10.0
        earners = round_half_up(r / 100.0 * n_ev)
        earner_ys.append(math.log(max(0.5, float(earners))))
    raw_slope, _ = theil_sen(xs, earner_ys)

    # (2) group shrinkage toward the (tier, band) median raw slope
    tier = trophy.get("tier", "bronze")
    key = (tier, band_of(r_last))
    group = live_row.groups.get(key, [])
    fallback = live_row.global_median
    group_med = median(group) if group else fallback
    weight = live_row.n_events / (live_row.n_events + 6.0)
    shrunk = weight * raw_slope + (1.0 - weight) * group_med

    # (3) trend median through the damped earner slope, capped by players
    e_last = round_half_up(r_last / 100.0 * n_last)
    ln_e_tgt = math.log(max(e_last, 0.5)) + SLOPE_DAMPING * shrunk * (x_tgt - x_last)
    e_tgt = min(math.exp(ln_e_tgt), 0.999 * n_target)
    trend_rate = 100.0 * e_tgt / n_target
    trend_logit = logit_pct(trend_rate)

    # (4) movement cap relative to the last rate
    trend_logit = clamp(trend_logit, last_logit + CAP_DOWN, last_logit + CAP_UP)

    # (5) persistence blend
    m = (1.0 - lam) * trend_logit + lam * last_logit

    # (6) spread from the event logit-rate residuals plus horizon and disagreement
    logit_ys = []
    for ev in events:
        r = rate_at(ev["rates"], i)
        logit_ys.append(logit_pct(max(r, 0.01)))
    s_slope, s_intercept = theil_sen(xs, logit_ys)
    residuals = []
    for x_val, y_val in zip(xs, logit_ys):
        residuals.append(y_val - (s_slope * x_val + s_intercept))
    rsd = math.sqrt(sum(r * r for r in residuals) / len(residuals)) if residuals else 0.0
    rsd = clamp(rsd, MIN_SIGMA_RSD, MAX_SIGMA_RSD)

    disagreement = lam * (1.0 - lam) * (trend_logit - last_logit) ** 2
    if disagreement < 0.0:
        disagreement = 0.0
    sigma = math.sqrt(0.10 ** 2 + 0.16 ** 2 * horizon_days + 0.25 * rsd ** 2 + disagreement)
    if e_last < 1:
        sigma = max(sigma, SPARSE_SIGMA)

    qs = [inv_logit(m + z * sigma) for z in Z]
    return monotone(qs)


def forecast_live(events, trophies, horizon_minutes):
    xs = [math.log(1.0 + ev["hours"]) for ev in events]
    x_last = xs[-1]
    horizon_days = max(0.0, float(horizon_minutes) / 1440.0)
    x_tgt = math.log(1.0 + events[-1]["hours"] + float(horizon_minutes) / 60.0)

    # players: Theil-Sen on ln(max(N, 10)), then two damped anchored extrapolations
    ln_ns = [math.log(max(ev["n"], 10.0)) for ev in events]
    b_n, _ = theil_sen(xs, ln_ns)
    n_last = events[-1]["n"] if events[-1]["n"] > 0.0 else 10.0
    extrapolations = []
    for f in (0.85, 1.0):
        extrapolations.append(n_last * math.exp(f * SLOPE_DAMPING * b_n * (x_tgt - x_last)))
    n_tgt = max(median(extrapolations), 1.0)

    # persistence shrinkage weight; the 0.97 clamp is load-bearing
    lam = min(0.97, 0.80 + 0.35 * math.exp(-horizon_days / 2.0))

    # per-trophy raw slopes, grouped for shrinkage
    raw_slopes = {}
    groups = {}
    for i, trophy in enumerate(trophies):
        r_last = rate_at(events[-1]["rates"], i)
        if r_last >= 99.99:
            continue
        ys = []
        for ev in events:
            r = rate_at(ev["rates"], i)
            n_ev = ev["n"] if ev["n"] > 0.0 else 10.0
            earners = round_half_up(r / 100.0 * n_ev)
            ys.append(math.log(max(0.5, float(earners))))
        slope, _ = theil_sen(xs, ys)
        raw_slopes[i] = slope
        groups.setdefault((trophy.get("tier", "bronze"), band_of(r_last)), []).append(slope)

    live_row.groups = groups
    live_row.global_median = median(list(raw_slopes.values()))
    live_row.n_events = len(events)

    rows = []
    for i, trophy in enumerate(trophies):
        try:
            qs = live_row(i, trophy, events, xs, x_last, x_tgt, n_tgt, lam, horizon_days)
        except Exception:
            # per-row fallback to persistence
            spread = max(0.35, 0.5 * math.sqrt(horizon_days))
            qs = persistence_row(rate_at(events[-1]["rates"], i), spread)
        rows.append({"id": trophy["id"], "q": qs})
    return rows


# --------------------------------------------------------------------------
# row validation and the never-crash entry point
# --------------------------------------------------------------------------

def valid_rows(rows, trophies):
    if not isinstance(rows, list) or len(rows) != len(trophies):
        return False
    if len(trophies) == 0:
        return True
    for row, trophy in zip(rows, trophies):
        if not isinstance(row, dict) or not isinstance(trophy, dict):
            return False
        if "id" not in trophy or row.get("id") != trophy["id"]:
            return False
        qs = row.get("q")
        if not isinstance(qs, list) or len(qs) != 5:
            return False
        prev = None
        for value in qs:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
            if not math.isfinite(float(value)):
                return False
            value = float(value)
            if value < 0.0 or value > 100.0:
                return False
            if prev is not None and value < prev - 1e-12:
                return False
            prev = value
    return True


def forecast_case(case, name):
    """Forecast one case; never raises and never returns an invalid row set."""
    trophies = case.get("trophies") if isinstance(case, dict) else None
    if not isinstance(trophies, list):
        return {"trophies": []}

    # normalize once so every trophy carries an id; downstream code (and the
    # row assembly below) then always emits exactly one row per case trophy
    if not all(isinstance(t, dict) for t in trophies):
        return {"trophies": []}
    case = {**case, "trophies": [{**t, "id": t.get("id", i + 1)} for i, t in enumerate(trophies)]}
    trophies = case["trophies"]

    try:
        rows = _forecast_rows(case, trophies)
        if valid_rows(rows, trophies):
            return {"trophies": rows}
    except Exception:
        pass

    # whole-case fallback: persistence
    try:
        rows = persistence_rows(case)
        if valid_rows(rows, trophies):
            return {"trophies": rows}
    except Exception:
        pass

    # last resort: every trophy at its last-read rate with a wide logit spread
    try:
        rows = []
        rates, _ = last_read_rates(case)
        for i, trophy in enumerate(trophies):
            if not isinstance(trophy, dict) or "id" not in trophy:
                return {"trophies": []}
            rows.append({"id": trophy["id"], "q": persistence_row(rate_at(rates, i), 0.5)})
        if valid_rows(rows, trophies):
            return {"trophies": rows}
    except Exception:
        pass

    return {"trophies": []}


def _forecast_rows(case, trophies):
    events = build_events(case)
    for trophy in trophies:
        if not isinstance(trophy, dict) or "id" not in trophy:
            raise ValueError("trophy without id")

    horizon_minutes = case.get("horizon_minutes")
    try:
        horizon_minutes = float(horizon_minutes)
    except (TypeError, ValueError):
        horizon_minutes = 0.0
    if not math.isfinite(horizon_minutes) or horizon_minutes < 0.0:
        horizon_minutes = 0.0

    n_values = {ev["n"] for ev in events}
    is_flat = len(events) < 2 or len(n_values) <= 1

    if is_flat:
        rows = forecast_flat(events, trophies)
    else:
        rows = forecast_live(events, trophies, horizon_minutes)
    return rows


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(case, dict):
            continue
        trophies = case.get("trophies")
        if not isinstance(trophies, list):
            # Nothing to key rows on; skip rather than crash the run.
            continue
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()

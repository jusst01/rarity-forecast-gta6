#!/usr/bin/env python3
"""Edge-case check for the v3 rarity forecaster.

Builds mutated cases from ../kit/input/p00.in and asserts that
main.forecast_case always emits exactly one valid row per trophy.

Run:  python3 tools/edge_check.py
"""
import copy
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIT_CASE = REPO.parent / "kit" / "input" / "p00.in"

sys.path.insert(0, str(REPO))
import main  # noqa: E402


def load_base():
    with KIT_CASE.open(encoding="utf-8") as fh:
        return json.load(fh)


def with_reads(case, reads):
    case = copy.deepcopy(case)
    case["reads"] = reads
    return case


def mutated_cases(base):
    cases = []

    cases.append(("empty history", with_reads(base, [])))

    first = base.get("reads") or []
    cases.append(("single read", with_reads(base, first[:1])))

    null_rates = []
    for read in first:
        read = dict(read)
        read["rates"] = [None] * len(base["trophies"])
        null_rates.append(read)
    cases.append(("all-null rates", with_reads(base, null_rates)))

    zero_rates = []
    for read in first:
        read = dict(read)
        read["rates"] = [0.0] * len(base["trophies"])
        zero_rates.append(read)
    cases.append(("all-zero rates", with_reads(base, zero_rates)))

    truncated = []
    for read in first:
        read = dict(read)
        read["rates"] = list(read.get("rates") or [])[: len(base["trophies"]) // 2]
        truncated.append(read)
    cases.append(("truncated rates lists", with_reads(base, truncated)))

    no_id = copy.deepcopy(base)
    no_id["trophies"] = [dict(t) for t in no_id["trophies"]]
    no_id["trophies"][1].pop("id", None)
    cases.append(("trophy without id", no_id))

    no_horizon = copy.deepcopy(base)
    no_horizon.pop("horizon_minutes", None)
    cases.append(("missing horizon_minutes", no_horizon))

    return cases


def check_rows(forecast, trophies):
    rows = forecast.get("trophies") if isinstance(forecast, dict) else None
    if not isinstance(rows, list):
        return "no trophies list"
    if len(rows) != len(trophies):
        return f"row count {len(rows)} != trophy count {len(trophies)}"
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return f"row {idx} not an object"
        if "id" not in row:
            return f"row {idx} missing id"
        qs = row.get("q")
        if not isinstance(qs, list) or len(qs) != 5:
            return f"row {idx} q is not 5 quantiles"
        prev = None
        for value in qs:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return f"row {idx} non-numeric quantile"
            value = float(value)
            if not math.isfinite(value):
                return f"row {idx} non-finite quantile"
            if value < 0.0 or value > 100.0:
                return f"row {idx} quantile {value} outside [0,100]"
            if prev is not None and value < prev - 1e-9:
                return f"row {idx} quantiles not non-decreasing"
            prev = value
    return None


def main_check():
    base = load_base()
    failures = 0
    for name, case in mutated_cases(base):
        trophies = case.get("trophies") or []
        try:
            forecast = main.forecast_case(case, name)
        except Exception as exc:  # forecast_case must never raise
            print(f"FAIL  {name}: raised {type(exc).__name__}: {exc}")
            failures += 1
            continue
        problem = check_rows(forecast, trophies)
        if problem:
            print(f"FAIL  {name}: {problem}")
            failures += 1
        else:
            print(f"PASS  {name}: {len(trophies)} rows")
    total = len(mutated_cases(base))
    print(f"\n{total - failures}/{total} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main_check())

"""Validation script for make.fun gta6-trophy-rarity-forecast-01
Runs Validation B (format, runtime, specific rows), C (determinism), and D (synthetic smoke test).
"""

import json
import os
import subprocess
import sys
import time
import tempfile
from pathlib import Path

def validate_output(in_path: Path, out_path: Path):
    case = json.loads(in_path.read_text())
    out_text = out_path.read_text(encoding="utf-8")

    # File size check (< 65536 bytes)
    assert len(out_text.encode("utf-8")) <= 65536, f"File size exceeds 65536 bytes: {len(out_text.encode('utf-8'))}"

    data = json.loads(out_text)
    assert "trophies" in data, "Missing 'trophies' key"
    rows = data["trophies"]

    expected_trophies = case["trophies"]
    assert len(rows) == len(expected_trophies), f"Row count {len(rows)} != trophy count {len(expected_trophies)}"

    case_ids = [t["id"] for t in expected_trophies]
    out_ids = [r["id"] for r in rows]
    assert sorted(out_ids) == sorted(case_ids), "Trophy IDs do not match case trophies"
    assert len(set(out_ids)) == len(out_ids), "Trophy IDs are not unique"

    for r in rows:
        q = r["q"]
        assert len(q) == 5, f"Quantile list length {len(q)} != 5"
        for val in q:
            assert isinstance(val, (int, float)), f"Quantile value {val} is not numeric"
            assert 0.0 <= val <= 100.0, f"Quantile value {val} out of bounds [0, 100]"
        for i in range(1, len(q)):
            assert q[i] >= q[i-1], f"Quantiles not non-decreasing: {q}"

def run_validation():
    repo_dir = Path(__file__).resolve().parent.parent
    main_py = repo_dir / "main.py"
    input_dir = Path("../kit/input")

    print("=== Validation B: Our model on p00 and p01 ==00===")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / "in"
        tmp_out = Path(tmpdir) / "out"
        tmp_in.mkdir()
        tmp_out.mkdir()

        for case_name in ["p00.in", "p01.in"]:
            in_file = input_dir / case_name
            if in_file.exists():
                (tmp_in / case_name).write_text(in_file.read_text())

        start_time = time.monotonic()
        res = subprocess.run([sys.executable, str(main_py)], env={"MAKEFUN_INPUT_DIR": str(tmp_in), "MAKEFUN_OUTPUT_DIR": str(tmp_out)}, capture_output=True, text=True)
        elapsed = time.monotonic() - start_time
        print(f"Run completed in {elapsed:.3f} seconds. Exit code: {res.returncode}")
        if res.stderr:
            print("Stderr:", res.stderr)

        for case_name in ["p00.in", "p01.in"]:
            in_file = tmp_in / case_name
            out_file = tmp_out / f"{case_name.replace('.in', '.out')}"
            if out_file.exists():
                t0 = time.monotonic()
                validate_output(in_file, out_file)
                t_val = time.monotonic() - t0
                print(f"  {case_name}: Format valid, validation took {t_val:.4f}s")

                case_data = json.loads(in_file.read_text())
                out_data = json.loads(out_file.read_text())

                # Print specific rows: 1.10% trophy, platinum, 100% trophy
                print(f"\nResults for {case_name}:")
                for i, trophy in enumerate(case_data["trophies"]):
                    t_id = trophy["id"]
                    t_name = trophy["name"]
                    t_tier = trophy["tier"]
                    last_rate = case_data["history"][-1]["rates"][i] if case_data["history"] else None
                    row = out_data["trophies"][i]["q"]

                    is_110 = last_rate is not None and abs(last_rate - 1.10) < 1e-3
                    is_plat = t_tier == "platinum" or "Platinum" in t_name
                    is_100 = last_rate is not None and last_rate >= 99.99 or "100%" in t_name or "100% Completion" in t_name

                    if is_110 or is_plat or is_100:
                        print(f"  Trophy {t_id} ({t_name}, tier={t_tier}, last_rate={last_rate}): q = {row}")

    print("\n=== Validation C: Determinism (p00 run twice) ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / "in"
        tmp_out1 = Path(tmpdir) / "out1"
        tmp_out2 = Path(tmpdir) / "out2"
        tmp_in.mkdir()
        tmp_out1.mkdir()
        tmp_out2.mkdir()
        (tmp_in / "p00.in").write_text((input_dir / "p00.in").read_text())

        subprocess.run([sys.executable, str(main_py)], env={"MAKEFUN_INPUT_DIR": str(tmp_in), "MAKEFUN_OUTPUT_DIR": str(tmp_out1)}, check=True)
        subprocess.run([sys.executable, str(main_py)], env={"MAKEFUN_INPUT_DIR": str(tmp_in), "MAKEFUN_OUTPUT_DIR": str(tmp_out2)}, check=True)

        bytes1 = (tmp_out1 / "p00.out").read_bytes()
        bytes2 = (tmp_out2 / "p00.out").read_bytes()
        assert bytes1 == bytes2, "Outputs differ between runs!"
        print("  Determinism verified: Outputs are byte-identical across runs.")

    print("\n=== Validation D: Synthetic LIVE-regime smoke test ===")
    synth_script = repo_dir / "tools" / "synth_check.py"
    subprocess.run([sys.executable, str(synth_script)], check=True)

if __name__ == "__main__":
    run_validation()

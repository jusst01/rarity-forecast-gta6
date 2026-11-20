import os
import sys
import json
import tempfile
import time
import shutil
import subprocess
from pathlib import Path

def run_check_1():
    print("=== STEP 1: Combined Check ===")
    kit_starter = Path("../kit/starter/main.py").resolve()
    our_main = Path("main.py").resolve()
    p00_in = Path("../kit/input/p00.in").resolve()
    p01_in = Path("../kit/input/p01.in").resolve()

    # (a) Run kit starter on p00 in temp dir
    with tempfile.TemporaryDirectory() as tmp_in, tempfile.TemporaryDirectory() as tmp_out:
        shutil.copy(p00_in, Path(tmp_in) / "p00.in")
        env = {"MAKEFUN_INPUT_DIR": tmp_in, "MAKEFUN_OUTPUT_DIR": tmp_out}
        subprocess.run([sys.executable, "-I", str(kit_starter)], env=env, check=True)
        out_path = Path(tmp_out) / "p00.out"
        data = json.loads(out_path.read_text())
        # Find trophy with last-read rate 1.10
        p00_case = json.loads(p00_in.read_text())
        target_trophy_id = None
        for i, t in enumerate(p00_case["trophies"]):
            # Get last read rate for t
            # In starter or input, how are rates structured? Let's check.
            # Usually latest read rates in case['reads'][-1]['rates'][i] or similar
            rates = p00_case["reads"][-1]["rates"]
            r = rates[i] if i < len(rates) else None
            if r is not None and abs(r - 1.10) < 1e-5:
                target_trophy_id = t["id"]
                break

        starter_row_110 = None
        for row in data["trophies"]:
            if row["id"] == target_trophy_id:
                starter_row_110 = row["q"]
                break
        print(f"(a) Kit starter p00 row for 1.10% trophy (id {target_trophy_id}): {starter_row_110}")
        print(f"    Expected: [0.8974, 1.012, 1.1, 1.1955, 1.3477]")

    # (b) Run our main.py on p00 and p01, validate format, size <= 65536, print runtime per case, rows for id 1, id 2, and 1.10% trophy
    with tempfile.TemporaryDirectory() as tmp_in, tempfile.TemporaryDirectory() as tmp_out:
        shutil.copy(p00_in, Path(tmp_in) / "p00.in")
        shutil.copy(p01_in, Path(tmp_in) / "p01.in")
        env = {"MAKEFUN_INPUT_DIR": tmp_in, "MAKEFUN_OUTPUT_DIR": tmp_out}

        t0 = time.time()
        subprocess.run([sys.executable, "-I", str(our_main)], env=env, check=True)
        dt = time.time() - t0
        print(f"(b) Our main.py run on p00 and p01 completed in {dt:.4f}s total.")

        for case_name in ["p00", "p01"]:
            out_file = Path(tmp_out) / f"{case_name}.out"
            size = out_file.stat().st_size
            print(f"    {case_name}.out size: {size} bytes (<= 65536: {size <= 65536})")
            content = json.loads(out_file.read_text())
            trophies_out = content["trophies"]
            print(f"    {case_name}.out rows count: {len(trophies_out)} (== 55: {len(trophies_out) == 55})")

            # Validate format: 55 rows, ids complete (1..55), quantiles non-decreasing within [0, 100]
            ids = [r["id"] for r in trophies_out]
            print(f"    {case_name} IDs complete (1..55): {sorted(ids) == list(range(1, 56))}")

            valid_qs = True
            for r in trophies_out:
                qs = r["q"]
                if len(qs) != 5:
                    valid_qs = False
                prev = -1
                for q in qs:
                    if not (0 <= q <= 100) or q < prev:
                        valid_qs = False
                    prev = q
            print(f"    {case_name} quantiles valid & non-decreasing in [0,100]: {valid_qs}")

            # Print rows for id 1, id 2, and 1.10% trophy
            row1 = next((r for r in trophies_out if r["id"] == 1), None)
            row2 = next((r for r in trophies_out if r["id"] == 2), None)
            row110 = next((r for r in trophies_out if r["id"] == target_trophy_id), None)
            print(f"    {case_name} id 1: {row1['q'] if row1 else 'N/A'}")
            print(f"    {case_name} id 2: {row2['q'] if row2 else 'N/A'}")
            print(f"    {case_name} id {target_trophy_id} (1.10% trophy): {row110['q'] if row110 else 'N/A'}")

    # (c) Run p00 a second time and diff for byte-identical determinism
    with tempfile.TemporaryDirectory() as tmp_in1, tempfile.TemporaryDirectory() as tmp_out1, \
         tempfile.TemporaryDirectory() as tmp_in2, tempfile.TemporaryDirectory() as tmp_out2:
        shutil.copy(p00_in, Path(tmp_in1) / "p00.in")
        shutil.copy(p00_in, Path(tmp_in2) / "p00.in")

        subprocess.run([sys.executable, "-I", str(our_main)], env={"MAKEFUN_INPUT_DIR": tmp_in1, "MAKEFUN_OUTPUT_DIR": tmp_out1}, check=True)
        subprocess.run([sys.executable, "-I", str(our_main)], env={"MAKEFUN_INPUT_DIR": tmp_in2, "MAKEFUN_OUTPUT_DIR": tmp_out2}, check=True)

        bytes1 = (Path(tmp_out1) / "p00.out").read_bytes()
        bytes2 = (Path(tmp_out2) / "p00.out").read_bytes()
        identical = (bytes1 == bytes2)
        print(f"(c) p00 run 1 and run 2 byte-identical determinism: {identical}")

def run_check_2():
    print("\n=== STEP 2: Never-Crash Edges == / Mutated p00 copies ===")
    our_main = Path("main.py").resolve()
    p00_in = Path("../kit/input/p00.in").resolve()
    case_data = json.loads(p00_in.read_text())

    mutations = {}

    # 1. empty history (reads = [])
    m1 = json.loads(json.dumps(case_data))
    m1["reads"] = []
    mutations["empty_history"] = m1

    # 2. single read (reads = [reads[0]])
    m2 = json.loads(json.dumps(case_data))
    if m2["reads"]:
        m2["reads"] = m2["reads"][:1]
    mutations["single_read"] = m2

    # 3. all-null rates (rates = None or nulls)
    m3 = json.loads(json.dumps(case_data))
    for rd in m3["reads"]:
        rd["rates"] = [None] * len(rd["rates"])
    mutations["all_null_rates"] = m3

    # 4. all-zero rates
    m4 = json.loads(json.dumps(case_data))
    for rd in m4["reads"]:
        rd["rates"] = [0.0] * len(rd["rates"])
    mutations["all_zero_rates"] = m4

    with tempfile.TemporaryDirectory() as tmp_in, tempfile.TemporaryDirectory() as tmp_out:
        for name, mut in mutations.items():
            mut_path = Path(tmp_in) / f"{name}.in"
            mut_path.write_text(json.dumps(mut))

        subprocess.run([sys.executable, "-I", str(our_main)], env={"MAKEFUN_INPUT_DIR": tmp_in, "MAKEFUN_OUTPUT_DIR": tmp_out}, check=True)

        for name in mutations.keys():
            out_file = Path(tmp_out) / f"{name}.out"
            exists = out_file.exists()
            if not exists:
                print(f"  Mutation {name}: NO OUTPUT FILE")
                continue
            content = json.loads(out_file.read_text())
            trophies = content.get("trophies", [])
            valid = (len(trophies) == 55)
            # check quantiles
            for r in trophies:
                qs = r.get("q", [])
                if len(qs) != 5:
                    valid = False
                prev = -1
                for q in qs:
                    if not isinstance(q, (int, float)) or not (0 <= q <= 100) or q < prev:
                        valid = False
                    prev = q
            print(f"  Mutation {name:15s}: valid 55-row output = {valid} (rows: {len(trophies)})")

if __name__ == "__main__":
    run_check_1()
    run_check_2()

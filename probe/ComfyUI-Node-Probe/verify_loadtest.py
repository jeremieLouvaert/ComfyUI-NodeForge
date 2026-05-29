"""
Real-server load test for ComfyUI-Node-Probe.

Run this AFTER deploying the pack and restarting ComfyUI. It talks to the
running ComfyUI HTTP API (default 127.0.0.1:8188) and proves two things:
  1. REGISTRATION: all 6 probe nodes appear in /object_info with correct
     input/output schema (i.e. ComfyUI imported the pack with no error).
  2. LIVE EXECUTION: a real graph (ProbeTestImage -> ProbeUnsharpMask ->
     SaveImage) is submitted to /prompt and runs to completion.

Usage:  python verify_loadtest.py [port]   (default port 8188)
Stdlib only (urllib + json), so it runs on the embedded python.
"""
import sys
import json
import time
import uuid
import urllib.request
import urllib.error

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8188
BASE = f"http://127.0.0.1:{PORT}"

EXPECTED = [
    "ProbeTestImage", "ProbeChannelShuffle", "ProbeLumaKeyMask",
    "ProbeTileMosaic", "ProbeUnsharpMask", "ProbeLumaSplit",
]
# expected output type(s) per node, to confirm schema (not just presence)
EXPECTED_OUT = {
    "ProbeTestImage": ["IMAGE"],
    "ProbeChannelShuffle": ["IMAGE"],
    "ProbeLumaKeyMask": ["MASK"],
    "ProbeTileMosaic": ["IMAGE"],
    "ProbeUnsharpMask": ["IMAGE"],
    "ProbeLumaSplit": ["IMAGE", "IMAGE"],
}


def get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def server_up():
    try:
        get("/system_stats", timeout=5)
        return True
    except Exception:
        return False


def check_registration():
    print("=" * 64)
    print("1. REGISTRATION  (GET /object_info/<node>)")
    print("=" * 64)
    all_ok = True
    for name in EXPECTED:
        try:
            info = get(f"/object_info/{name}")
            entry = info.get(name)
            if not entry:
                print(f"[MISSING] {name}  -- not in /object_info")
                all_ok = False
                continue
            outs = entry.get("output", [])
            outs_norm = [o if isinstance(o, str) else o for o in outs]
            exp = EXPECTED_OUT[name]
            schema_ok = list(outs_norm) == exp
            req_inputs = list(entry.get("input", {}).get("required", {}).keys())
            tag = "OK  " if schema_ok else "SCHEMA?"
            print(f"[{tag}] {name:22s} outputs={outs_norm}  inputs={req_inputs}")
            all_ok = all_ok and schema_ok
        except urllib.error.HTTPError as e:
            print(f"[MISSING] {name}  -- HTTP {e.code}")
            all_ok = False
        except Exception as e:
            print(f"[ERROR ] {name}  -- {type(e).__name__}: {e}")
            all_ok = False
    return all_ok


def run_live_graph():
    print("\n" + "=" * 64)
    print("2. LIVE EXECUTION  (POST /prompt: TestImage -> Unsharp -> Save)")
    print("=" * 64)
    graph = {
        "1": {"class_type": "ProbeTestImage",
              "inputs": {"width": 256, "height": 256}},
        "2": {"class_type": "ProbeUnsharpMask",
              "inputs": {"image": ["1", 0], "sigma": 2.0, "amount": 1.5}},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "node_probe"}},
    }
    client_id = str(uuid.uuid4())
    try:
        resp = post("/prompt", {"prompt": graph, "client_id": client_id})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"[FAIL] /prompt rejected the graph: HTTP {e.code}\n{body[:800]}")
        return False
    pid = resp.get("prompt_id")
    if not pid:
        print(f"[FAIL] no prompt_id returned: {resp}")
        return False
    print(f"  submitted prompt_id={pid}; polling /history ...")
    for _ in range(60):  # up to ~60s
        time.sleep(1)
        hist = get(f"/history/{pid}")
        if pid in hist:
            status = hist[pid].get("status", {})
            sstr = status.get("status_str")
            completed = status.get("completed")
            if sstr == "success" and completed:
                outs = hist[pid].get("outputs", {})
                saved = outs.get("3", {}).get("images", [])
                print(f"[PASS] graph executed; SaveImage wrote {len(saved)} image(s): "
                      f"{[s.get('filename') for s in saved]}")
                return True
            if sstr == "error":
                msgs = status.get("messages", [])
                print(f"[FAIL] graph errored: {msgs}")
                return False
    print("[FAIL] timed out waiting for execution (60s)")
    return False


if __name__ == "__main__":
    print(f"ComfyUI-Node-Probe load test -> {BASE}\n")
    if not server_up():
        print(f"ComfyUI is not reachable at {BASE}.")
        print("Start/restart ComfyUI, then re-run this script (pass the port as arg if not 8188).")
        sys.exit(2)
    reg_ok = check_registration()
    exec_ok = run_live_graph()
    print("\n" + "-" * 64)
    print(f"REGISTRATION: {'PASS' if reg_ok else 'FAIL'}   LIVE EXECUTION: {'PASS' if exec_ok else 'FAIL'}")
    sys.exit(0 if (reg_ok and exec_ok) else 1)

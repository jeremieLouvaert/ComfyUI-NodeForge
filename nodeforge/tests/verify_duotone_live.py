"""
Live-server verification for the banked Duotone node (run AFTER restarting ComfyUI).

Mirrors probe/ComfyUI-Node-Probe/verify_loadtest.py: confirms the node REGISTERS
(GET /object_info) with the right output schema, and EXECUTES in a real graph
(POST /prompt) using a built-in image source -> the duotone node -> SaveImage.

Usage (with ComfyUI running):
  python nodeforge/tests/verify_duotone_live.py [port]   (default 8188)

The node class is auto-detected from the banked pack so this keeps working even if
a future run banks under a different class name.
"""
import os
import sys
import json
import time
import uuid
import glob
import re
import urllib.request
import urllib.error

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8188
BASE = f"http://127.0.0.1:{PORT}"
CUSTOM_NODES = os.environ.get(
    "NODEFORGE_CUSTOM_NODES",
    r"F:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\ComfyUI\custom_nodes")


def get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def find_duotone_class():
    packs = glob.glob(os.path.join(CUSTOM_NODES, "ComfyUI-NodeForge-*"))
    for p in packs:
        for f in glob.glob(os.path.join(p, "nodes", "*.py")):
            if f.endswith("__init__.py"):
                continue
            src = open(f, encoding="utf-8").read()
            if "duotone" in src.lower():
                m = re.search(r"NODE_CLASS_MAPPINGS\s*=\s*\{\s*['\"](\w+)['\"]", src)
                if m:
                    return m.group(1)
    return None


def main():
    try:
        get("/system_stats", timeout=5)
    except Exception:
        print(f"ComfyUI is not reachable at {BASE}. Start it, then re-run.")
        sys.exit(2)

    cls = find_duotone_class()
    if not cls:
        print("Could not find a banked Duotone node class in custom_nodes.")
        sys.exit(2)
    print(f"Verifying banked node class: {cls}")

    # 1. registration
    reg_ok = False
    try:
        info = get(f"/object_info/{cls}")
        entry = info.get(cls)
        if entry:
            outs = entry.get("output", [])
            reg_ok = list(outs) == ["IMAGE"]
            print(f"[{'OK' if reg_ok else 'SCHEMA?'}] registered; outputs={outs} "
                  f"inputs={list(entry.get('input', {}).get('required', {}).keys())}")
        else:
            print(f"[MISSING] {cls} not in /object_info")
    except urllib.error.HTTPError as e:
        print(f"[MISSING] {cls} HTTP {e.code}")

    # 2. live execution: a built-in test image -> duotone -> SaveImage
    graph = {
        "1": {"class_type": "EmptyImage",
              "inputs": {"width": 256, "height": 256, "batch_size": 1, "color": 8421504}},
        "2": {"class_type": cls,
              "inputs": {"image": ["1", 0], "color_shadows": "#101840",
                         "color_highlights": "#ffd080", "gamma": 1.0}},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "nodeforge_duotone"}},
    }
    exec_ok = False
    try:
        resp = post("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
        pid = resp.get("prompt_id")
        print(f"  submitted prompt_id={pid}; polling ...")
        for _ in range(60):
            time.sleep(1)
            hist = get(f"/history/{pid}")
            if pid in hist:
                st = hist[pid].get("status", {})
                if st.get("status_str") == "success" and st.get("completed"):
                    saved = hist[pid].get("outputs", {}).get("3", {}).get("images", [])
                    print(f"[PASS] executed; SaveImage wrote {len(saved)} image(s): "
                          f"{[s.get('filename') for s in saved]}")
                    exec_ok = True
                    break
                if st.get("status_str") == "error":
                    print(f"[FAIL] graph errored: {st.get('messages')}")
                    break
        else:
            print("[FAIL] timed out (60s)")
    except urllib.error.HTTPError as e:
        print(f"[FAIL] /prompt rejected: HTTP {e.code}\n{e.read().decode('utf-8','ignore')[:600]}")

    print("-" * 60)
    print(f"REGISTRATION: {'PASS' if reg_ok else 'FAIL'}   LIVE EXECUTION: {'PASS' if exec_ok else 'FAIL'}")
    sys.exit(0 if (reg_ok and exec_ok) else 1)


if __name__ == "__main__":
    main()

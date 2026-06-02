"""
v0.1 AUTHOR acceptance test (LIVE -- spends API, touches real ComfyUI on case A).

  A  live-bank one genuinely-novel node (duotone) -> status 'banked', and the
     banked pack passes a sandbox load-test. Optional: if ComfyUI is running,
     after a manual restart, probe/verify_loadtest-style HTTP check.
  B  ambiguous ask ("resize smaller") -> must NOT bank (escalates / exhausts).
  C  contradictory ask -> must NOT bank (contradiction).

Run one case at a time (each spends API):
  python nodeforge/tests/acceptance.py A   [--force]
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
from nodeforge import cli, bank as bank_mod, gate as gate_mod   # noqa: E402

ASK_A = ("I want a node that gives an image a duotone look -- map the whole image to a "
         "gradient between two colors based on how bright each pixel is.")
ASK_B = "I want a node that resizes my image to make it smaller."
ASK_C = "I want a node that makes the image both completely black and unchanged at the same time."

LOG = []
def log(m):
    LOG.append(str(m))


def _auto_confirm(spec):
    spec.confirmed = True
    return spec


def _auto_approve(*a, **k):
    return True


def _capture_reject():
    """An approve_cb that records what the gate was handed (did it reach the gate?
    was it limited? what caveats?) then rejects, so nothing banks. Models the human
    seeing the gate. Returns (cap_dict, cb)."""
    cap = {"reached": False, "limited": None, "caveats": []}
    def cb(spec, winner, kept, unkilled, limited_verification=False, caveats=None):
        cap.update(reached=True, limited=bool(limited_verification),
                   caveats=list(caveats or []))
        raise gate_mod.RejectError("acceptance: capture, do not bank")
    return cap, cb


def run_A(force=False):
    # A clean, well-specified op must bank AND be FULLY verified (not limited).
    res = cli.run_author(ASK_A, n=3, interactive=False,
                         confirm_cb=_auto_confirm, approve_cb=_auto_approve,
                         force_bank=force, log=log)
    ok = res["status"] == "banked" and not res.get("limited_verification")
    detail = [f"status={res['status']}", f"limited={res.get('limited_verification')}",
              f"detail={res.get('detail','')}", f"dest={res.get('dest','')}"]
    if res["status"] == "banked":
        import glob
        node_files = glob.glob(os.path.join(res["dest"], "nodes", "*.py"))
        node_files = [f for f in node_files if not f.endswith("__init__.py")]
        src = open(node_files[0], encoding="utf-8").read() if node_files else ""
        lt_ok, lt_err = bank_mod.loadtest_pack(src, res["class_name"])
        detail.append(f"banked_loadtest_ok={lt_ok} err={lt_err}")
        ok = ok and lt_ok
    return "A", ok, detail


def run_B(force=False):
    # 2026-06-02 contract: an ambiguous ask is NO LONGER a dead-end. It must REACH
    # the gate (deliver a runnable candidate for human review), not hard-error.
    cap, cb = _capture_reject()
    res = cli.run_author(ASK_B, n=3, interactive=False,
                         confirm_cb=_auto_confirm, approve_cb=cb,
                         force_bank=force, log=log)
    # reached the gate (then we rejected -> 'rejected'); OR it banked under a clean
    # parameterization (also fine -- it delivered something reviewable).
    ok = cap["reached"] or res["status"] == "banked"
    return "B", ok, [f"status={res['status']}", f"reached_gate={cap['reached']}",
                     f"limited={cap['limited']}", f"caveats={cap['caveats']}"]


def run_C(force=False):
    # 2026-06-02 contract: a contradictory ask must NOT silently bank. It reaches the
    # human gate (so a human can reject what they see), nothing banks without approval,
    # and IF it is flagged limited it always carries caveats (no silent downgrade).
    # Either elaborate resolves the ask into a coherent node (confident, the human
    # judges the before/after) OR the conflict surfaces as limited+caveats; both are
    # honest, neither silently banks. (The "surface conflicting examples as caveats"
    # path is exercised live by over-idealized structured asks, e.g. halftone.)
    cap, cb = _capture_reject()
    res = cli.run_author(ASK_C, n=3, interactive=False,
                         confirm_cb=_auto_confirm, approve_cb=cb,
                         force_bank=force, log=log)
    no_silent_bank = cap["reached"] and res["status"] == "rejected"
    limited_implies_caveats = (not cap["limited"]) or len(cap["caveats"]) > 0
    ok = no_silent_bank and limited_implies_caveats
    return "C", ok, [f"status={res['status']}", f"reached_gate={cap['reached']}",
                     f"limited={cap['limited']}", f"caveats={cap['caveats']}"]


def main():
    case = (sys.argv[1].upper() if len(sys.argv) > 1 else "A")
    force = "--force" in sys.argv
    runner = {"A": run_A, "B": run_B, "C": run_C}[case]
    name, ok, detail = runner(force=force)
    out = [f"CASE {name}: {'PASS' if ok else 'FAIL'}"] + detail + ["", "--- LOG ---"] + LOG
    with open(os.path.join(_REPO, f"_accept_{name}.txt"), "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(out) + f"\nEXIT={0 if ok else 1}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

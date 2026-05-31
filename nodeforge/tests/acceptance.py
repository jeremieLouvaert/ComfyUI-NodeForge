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
from nodeforge import cli, bank as bank_mod   # noqa: E402

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


def run_A(force=False):
    res = cli.run_author(ASK_A, n=3, interactive=False,
                         confirm_cb=_auto_confirm, approve_cb=_auto_approve,
                         force_bank=force, log=log)
    ok = res["status"] == "banked"
    detail = [f"status={res['status']}", f"detail={res.get('detail','')}",
              f"dest={res.get('dest','')}"]
    if ok:
        # banked pack must pass a sandbox load-test of its node module
        import glob
        node_files = glob.glob(os.path.join(res["dest"], "nodes", "*.py"))
        node_files = [f for f in node_files if not f.endswith("__init__.py")]
        src = open(node_files[0], encoding="utf-8").read() if node_files else ""
        lt_ok, lt_err = bank_mod.loadtest_pack(src, res["class_name"])
        detail.append(f"banked_loadtest_ok={lt_ok} err={lt_err}")
        ok = ok and lt_ok
    return "A", ok, detail


def run_B(force=False):
    res = cli.run_author(ASK_B, n=3, interactive=False,
                         confirm_cb=_auto_confirm, approve_cb=_auto_approve,
                         force_bank=force, log=log)
    ok = res["status"] != "banked"   # must NOT bank
    return "B", ok, [f"status={res['status']}", f"detail={res.get('detail','')}",
                     f"question={res.get('question','')[:200]}"]


def run_C(force=False):
    res = cli.run_author(ASK_C, n=3, interactive=False,
                         confirm_cb=_auto_confirm, approve_cb=_auto_approve,
                         force_bank=force, log=log)
    ok = res["status"] != "banked"   # must NOT bank
    return "C", ok, [f"status={res['status']}", f"detail={res.get('detail','')}"]


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

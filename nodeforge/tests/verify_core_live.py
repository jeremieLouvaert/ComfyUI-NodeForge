"""
Live e2e check of the wired v0.2 core-node precedence in precheck.find_existing
(real Manager + core index, real Sonnet rerank). Costs ~3 rerank calls.

Proves the live contract:
  - a core-answerable ask  -> kind=='core' (built-in surfaced, no pack/author)
  - a genuine authoring ask -> None (falls through to author; never over-claims)
Run with the embedded python (needs ANTHROPIC_API_KEY).
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
from nodeforge import precheck  # noqa: E402

# Asserts the RELIABLY-FIXED contract: DISTINCTIVE core nodes (the documented
# row-15 / "where are the SD3 nodes" misdirect) win core precedence, and a genuine
# authoring ask falls through to author. NOTE (documented soft-limit): generic
# image RESIZE is IMPROVED by the rerank built-in-preference fix (eval ImageScale
# 0.90->0.95, batch_images_to_masks 0.70->0.85, core_recall 3/5->4/5) but is NOT
# guaranteed live -- for that ultra-common op a polished custom resize pack can
# still out-score core ImageScale at rerank (a soft cost: advisory, never
# auto-installed, not a wrong answer). Not asserted, precisely because it is a
# known non-guarantee.
CASES = [
    ("Where to get the SD3 nodes (TripleCLIPLoader, ModelSamplingSD3, EmptySD3LatentImage)", "core"),
    ("Where the 'Apply ControlNet (Advanced)' node went / why it is missing", "core"),
    # genuine authoring: no built-in and no confident pack (eval top_pack ~0.40)
    ("Pixel-perfect 90-degree rotation and mirroring of a rendered image, not latent", None),
]

if __name__ == "__main__":
    ok = True
    for ask, expect in CASES:
        hit = precheck.find_existing(ask)
        kind = hit["kind"] if hit else None
        node = (hit.get("node_name") or hit.get("title")) if hit else "-"
        good = (kind == expect)
        ok = ok and good
        print(f"[{'OK ' if good else 'XX '}] expect={str(expect):6s} got={str(kind):6s} "
              f"({node} {hit['score']:.2f})" if hit else
              f"[{'OK ' if good else 'XX '}] expect={str(expect):6s} got=None -> author")
    print("verify_core_live:", "ALL PASS" if ok else "FAIL")

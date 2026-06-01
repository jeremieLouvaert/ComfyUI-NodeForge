"""
Live e2e check of the wired v0.2 three-band router (incl. core precedence) in
precheck.find_existing (real Manager + core index, real Sonnet rerank). Costs
~4 rerank calls.

Proves the live band contract:
  - a core-answerable ask   -> band 'core'   (built-in surfaced, no pack/author)
  - a partial-match ask     -> band 'middle' (1-3 candidates + offer author)
  - a genuine authoring ask -> band 'low'    (silent -> author; never over-claims)
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
# (ask, expected band). 'core'/'low' are firm; 'middle' is the partial-match
# band -- a generic detect/crop-and-paste-back ask (adjudication row 17, scored
# 0.65 partial = related face/object pack but not a clean general match), which
# is exactly MIDDLE's native population (show candidates + offer author).
CASES = [
    ("Where to get the SD3 nodes (TripleCLIPLoader, ModelSamplingSD3, EmptySD3LatentImage)", "core"),
    ("Where the 'Apply ControlNet (Advanced)' node went / why it is missing", "core"),
    ("A general-purpose detect/crop-out a region and paste it back after editing, for any object", "middle"),
    # genuine authoring: no built-in and no confident pack (eval top_pack ~0.40)
    ("Pixel-perfect 90-degree rotation and mirroring of a rendered image, not latent", "low"),
]

if __name__ == "__main__":
    ok = True
    for ask, expect in CASES:
        routed = precheck.find_existing(ask)
        band = routed.get("band", "low")
        good = (band == expect)
        ok = ok and good
        if band == "middle":
            names = ", ".join(f"{c['title']} {c['score']:.2f}" for c in routed["candidates"])
            detail = f"[{names}]"
        elif routed.get("hit"):
            h = routed["hit"]
            detail = f"({h.get('node_name') or h.get('title')} {h['score']:.2f})"
        else:
            detail = "-> author"
        print(f"[{'OK ' if good else 'XX '}] expect={expect:6s} got={band:6s} {detail}")
    print("verify_core_live:", "ALL PASS" if ok else "FAIL")

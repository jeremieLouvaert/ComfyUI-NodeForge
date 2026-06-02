"""
Stage 5 -- the human-approval gate (escalating-oracle layer 8).

Presents the winning implementation + the test report (what was checked + the
teeth evidence) + a visual before/after diff rendered on real fixtures, and asks
the human to approve (bank) or reject (reason feeds back to Stage 0/1). Approval
is the security boundary, so it is never skippable in interactive mode; the auto
mode (scripted acceptance) takes an explicit decision.
"""
import os

from . import sandbox, nodegen


class RejectError(Exception):
    pass


def render_before_after(spec, candidate, out_dir):
    """Render each confirmed example's input and the winner's output to PNGs.
    Returns {key: path}. Best-effort."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        fixtures = [{"example_id": e.id, "input_spec": e.input_spec.to_dict()}
                    for e in spec.examples]
        cand = {"id": "winner", "source": candidate.source, "class_name": candidate.class_name}
        return sandbox.render(fixtures, out_dir, candidate=cand)
    except Exception:
        return {}


def format_report(spec, candidate, kept_checks, unkilled_mutants, thumbs,
                  limited_verification=False, caveats=None):
    L = ["=" * 70, f"APPROVAL GATE: {spec.title}", "=" * 70]
    if limited_verification:
        L.append("\n!! LIMITED VERIFICATION: automated checks could not fully confirm "
                 "this node.\n   Review the code and the before/after carefully before "
                 "approving. Caveats:")
        for c in (caveats or ["a full automated verification could not be built"]):
            L.append(f"     - {c}")
    L.append(f"\nWinning implementation (class {candidate.class_name}):\n")
    L.append(candidate.source)
    L.append("\n" + "-" * 70)
    L.append(f"Verification: {len(kept_checks)} teeth-tested checks, each confirmed to")
    L.append("reject at least one plausible wrong variant AND accept the reference:")
    for c in kept_checks:
        L.append(f"  - {c.name}  (kills: {', '.join(c.teeth) or 'n/a'})")
    if unkilled_mutants:
        L.append("\nRESIDUAL RISK (honest): these mutation classes were NOT caught by any")
        L.append("check -- a node with one of these bugs could pass verification:")
        for m in unkilled_mutants:
            L.append(f"  ! {m}")
    if thumbs:
        L.append("\nVisual before/after (open these to judge correctness):")
        for k, v in sorted(thumbs.items()):
            L.append(f"  {k}: {v}")
    L.append("")
    return "\n".join(L)


def approve(spec, candidate, kept_checks, unkilled_mutants, render_dir=None,
            interactive=True, decision=None, inp=input, out=print,
            limited_verification=False, caveats=None):
    """Return True to bank, raise RejectError(reason) to reject. `decision` (auto
    mode): True/False/("reject","reason")."""
    thumbs = render_before_after(spec, candidate, render_dir) if render_dir else {}
    out(format_report(spec, candidate, kept_checks, unkilled_mutants, thumbs,
                      limited_verification=limited_verification, caveats=caveats))

    if not interactive:
        if decision is True:
            return True
        reason = decision[1] if isinstance(decision, (tuple, list)) and len(decision) > 1 else "auto-reject"
        raise RejectError(reason)

    while True:
        out("\nApprove and bank this node?  [y]es  [n]o (reason)  ")
        choice = inp("> ").strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no", ""):
            reason = inp("rejection reason (feeds back to spec): ").strip()
            raise RejectError(reason or "rejected at gate")
        out("please answer y or n")

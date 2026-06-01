"""
Offline unit tests for the v0.1.1 thin retrieval pre-check (no API, no network).

Covers the three things that can silently go wrong:
  - the tau_high band cut (>= fires, < does not, empty -> None)
  - prompt_existing defaults (empty/'a' = author anyway; never auto-suppress)
  - the run_author gate: pre-check is SKIPPED in non-interactive mode with no cb
    (the acceptance contract -- it must never run inside acceptance.py).
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
from nodeforge import precheck, cli  # noqa: E402


def _scored(score):
    return [{"id": "p", "score": score, "reason": "r",
             "pack": {"title": "SomePack", "reference": "https://x/y"}}]


def test_pick_band():
    assert precheck._pick([], 0.95) is None,                "empty -> None"
    assert precheck._pick(_scored(0.94), 0.95) is None,     "0.94 < 0.95 -> None"
    assert precheck._pick(_scored(0.95), 0.95) is not None, "0.95 >= 0.95 -> hit"
    assert precheck._pick(_scored(1.00), 0.95) is not None, "1.00 -> hit"
    hit = precheck._pick(_scored(0.97), 0.95)
    assert hit["title"] == "SomePack" and hit["url"] == "https://x/y" and hit["score"] == 0.97
    # row-1 regression: 0.92 must NOT fire at the firmed cut
    assert precheck._pick(_scored(0.92), 0.95) is None,     "row-1 0.92 stays below the firmed cut"


def test_prompt_defaults():
    hit = {"title": "P", "score": 0.99, "url": "", "reason": ""}
    assert precheck.prompt_existing(hit, _input=lambda *_: "") is True,   "empty default = author anyway"
    assert precheck.prompt_existing(hit, _input=lambda *_: "a") is True,  "'a' = author anyway"
    assert precheck.prompt_existing(hit, _input=lambda *_: "s") is False, "'s' = stop/install"
    assert precheck.prompt_existing(hit, _input=lambda *_: "stop") is False


def test_gate_skipped_noninteractive(monkeypatch_done=[]):
    # find_existing must NOT be called when interactive=False and no precheck_cb,
    # which is exactly how acceptance.py drives run_author. We replace
    # find_existing with a tripwire and assert it never fires; we stop the loop
    # immediately after the gate by making elaborate raise a sentinel.
    called = {"hit": False, "elaborate": False}

    def tripwire(*a, **k):
        called["hit"] = True
        return {"title": "X", "score": 1.0, "url": "", "reason": ""}

    class _Stop(Exception):
        pass

    def fake_elaborate(*a, **k):
        called["elaborate"] = True
        raise _Stop()

    precheck.find_existing = tripwire
    from nodeforge import spec as spec_mod
    spec_mod.elaborate = fake_elaborate
    try:
        cli.run_author("anything", interactive=False,
                       confirm_cb=lambda s: s, approve_cb=lambda *a, **k: True,
                       log=lambda *_: None)
    except _Stop:
        pass
    assert called["hit"] is False,      "pre-check MUST be skipped in non-interactive mode"
    assert called["elaborate"] is True, "loop should have proceeded to Stage 0"


if __name__ == "__main__":
    test_pick_band()
    test_prompt_defaults()
    test_gate_skipped_noninteractive()
    print("test_precheck: ALL PASS")

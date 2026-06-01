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
    return [{"id": "p", "score": score, "reason": "r", "source": "custom",
             "pack": {"title": "SomePack", "reference": "https://x/y"}}]


def _core_row(score, name="ImageScale", disp="Upscale Image"):
    return {"id": f"core:{name}", "score": score, "reason": "built-in", "source": "core",
            "core": {"name": name, "display_name": disp, "category": "image/upscaling"}}


def test_pick_band():
    # custom-pack band (tau_high=0.95), no core present
    assert precheck._pick([], 0.95) is None,                "empty -> None"
    assert precheck._pick(_scored(0.94), 0.95) is None,     "0.94 < 0.95 -> None"
    assert precheck._pick(_scored(0.95), 0.95) is not None, "0.95 >= 0.95 -> hit"
    assert precheck._pick(_scored(1.00), 0.95) is not None, "1.00 -> hit"
    hit = precheck._pick(_scored(0.97), 0.95)
    assert hit["kind"] == "custom" and hit["title"] == "SomePack" and hit["url"] == "https://x/y" and hit["score"] == 0.97
    # row-1 regression: 0.92 must NOT fire at the firmed cut
    assert precheck._pick(_scored(0.92), 0.95) is None,     "row-1 0.92 stays below the firmed cut"


def test_pick_core_precedence():
    # core band cut at tau_core=0.90
    assert precheck._pick([_core_row(0.89)], 0.95, 0.90) is None,    "core 0.89 < 0.90 -> None"
    hit = precheck._pick([_core_row(0.90)], 0.95, 0.90)
    assert hit and hit["kind"] == "core" and hit["node_name"] == "ImageScale", "core 0.90 -> core hit"
    # CORE PRECEDENCE: a confident core node beats a confident custom pack
    mixed = [_scored(0.99)[0], _core_row(0.93)]
    hit = precheck._pick(mixed, 0.95, 0.90)
    assert hit["kind"] == "core" and hit["node_name"] == "ImageScale", "core beats custom pack"
    # but a sub-tau core falls back to the custom-pack band
    mixed2 = [_scored(0.97)[0], _core_row(0.80)]
    hit = precheck._pick(mixed2, 0.95, 0.90)
    assert hit["kind"] == "custom" and hit["title"] == "SomePack", "sub-tau core -> custom fallback"


def test_prompt_defaults():
    hit = {"kind": "custom", "title": "P", "score": 0.99, "url": "", "reason": ""}
    assert precheck.prompt_existing(hit, _input=lambda *_: "") is True,   "empty default = author anyway"
    assert precheck.prompt_existing(hit, _input=lambda *_: "a") is True,  "'a' = author anyway"
    assert precheck.prompt_existing(hit, _input=lambda *_: "s") is False, "'s' = stop/install"
    assert precheck.prompt_existing(hit, _input=lambda *_: "stop") is False
    # core hit: same never-auto-suppress contract (empty -> author anyway)
    core_hit = {"kind": "core", "title": "Upscale Image", "node_name": "ImageScale",
                "category": "image/upscaling", "score": 0.97, "url": "", "reason": ""}
    assert precheck.prompt_existing(core_hit, _input=lambda *_: "") is True,  "core empty default = author anyway"
    assert precheck.prompt_existing(core_hit, _input=lambda *_: "s") is False, "core 's' = use built-in"


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
    test_pick_core_precedence()
    test_prompt_defaults()
    test_gate_skipped_noninteractive()
    print("test_precheck: ALL PASS")

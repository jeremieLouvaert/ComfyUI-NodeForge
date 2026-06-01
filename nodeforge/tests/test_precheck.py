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


def _custom_row(score, title="P", url="https://github.com/o/r"):
    return {"id": title, "score": score, "reason": "r", "source": "custom",
            "pack": {"title": title, "reference": url}}


def test_route_bands():
    # band boundaries (tau_high=0.95, tau_low=0.50)
    assert precheck._route([])["band"] == "low",                "empty -> low (author)"
    assert precheck._route(_scored(0.95))["band"] == "high",    "0.95 -> high"
    assert precheck._route(_scored(0.94))["band"] == "middle",  "0.94 -> middle"
    assert precheck._route(_scored(0.50))["band"] == "middle",  "0.50 inclusive lower bound"
    assert precheck._route(_scored(0.49))["band"] == "low",     "0.49 below tau_low -> low"
    # CORE PRECEDENCE composes with MIDDLE: a confident built-in beats a middle
    # custom band (don't offer-to-author what ComfyUI ships).
    r = precheck._route([_custom_row(0.80), _core_row(0.88)], 0.95, 0.50, 0.85)
    assert r["band"] == "core" and r["hit"]["node_name"] == "ImageScale", "core beats middle custom"
    # a SUB-tau core is dropped (not shown as a middle candidate -- can't install it)
    r = precheck._route([_custom_row(0.80), _core_row(0.70)], 0.95, 0.50, 0.85)
    assert r["band"] == "middle" and len(r["candidates"]) == 1 and r["candidates"][0]["kind"] == "custom"


def test_route_middle_assembly():
    rows = [_custom_row(0.92, "A"), _custom_row(0.71, "B"), _custom_row(0.60, "C"),
            _custom_row(0.55, "D"), _custom_row(0.49, "E")]
    r = precheck._route(rows)
    assert r["band"] == "middle"
    titles = [c["title"] for c in r["candidates"]]
    assert titles == ["A", "B", "C"],                    "top-3, sorted desc"
    assert all(0.50 <= c["score"] < 0.95 for c in r["candidates"])
    assert "E" not in titles,                            "0.49 (below tau_low) never shown (neg control)"
    assert "D" not in titles,                            "only top-3 shown"


def test_enrich_health_excludes_deprecated():
    # _enrich_health imports build_index.registry_health at call time; patch it.
    sys.path.insert(0, precheck._EVAL)
    import build_index  # noqa: E402
    orig = build_index.registry_health
    build_index.registry_health = lambda *a, **k: {
        "n1": {"repository": "https://github.com/o/dep.git", "deprecated": True,
               "github_stars": 3, "downloads": 5, "status": ""},
        "n2": {"repository": "https://github.com/o/ok", "deprecated": False,
               "github_stars": 40, "downloads": 900, "status": "NodeStatusActive"},
    }
    try:
        cands = [{"title": "Dep", "score": 0.7, "url": "https://github.com/o/dep", "reason": ""},
                 {"title": "Ok", "score": 0.6, "url": "https://github.com/o/ok", "reason": ""}]
        out = precheck._enrich_health("x", cands, exclude_deprecated=True)
        assert [c["title"] for c in out] == ["Ok"],     "deprecated hard-excluded from middle"
        assert out[0]["health"]["stars"] == 40,         "health attached to the survivor"
        # attach-only path (HIGH) keeps the deprecated one, flagged not hidden
        out2 = precheck._enrich_health("x", cands, exclude_deprecated=False)
        assert len(out2) == 2 and out2[0]["health"]["deprecated"] is True
        # a candidate with no registry match is passed through unchanged (no exclude on ABSENCE)
        none_match = [{"title": "Z", "score": 0.6, "url": "https://github.com/o/unknown", "reason": ""}]
        assert precheck._enrich_health("x", none_match, exclude_deprecated=True) == none_match
    finally:
        build_index.registry_health = orig


def test_prompt_middle():
    cands = [{"title": "A", "score": 0.80, "url": "", "reason": ""},
             {"title": "B", "score": 0.60, "url": "", "reason": ""}]
    assert precheck.prompt_middle(cands, _input=lambda *_: "") == (True, None),  "empty default = author"
    assert precheck.prompt_middle(cands, _input=lambda *_: "a") == (True, None), "'a' = author"
    aa, ch = precheck.prompt_middle(cands, _input=lambda *_: "2")
    assert aa is False and ch["title"] == "B",                                   "'2' = stop + pick B"
    assert precheck.prompt_middle(cands, _input=lambda *_: "s") == (False, None), "'s' = stop, no author"
    assert precheck.prompt_middle(cands, _input=lambda *_: "9") == (True, None), "out-of-range -> author"


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
    test_route_bands()
    test_route_middle_assembly()
    test_enrich_health_excludes_deprecated()
    test_prompt_middle()
    test_prompt_defaults()
    test_gate_skipped_noninteractive()
    print("test_precheck: ALL PASS")

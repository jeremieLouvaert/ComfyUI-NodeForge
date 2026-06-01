"""
Axes and ask_choice tests (OFFLINE -- no LLM, no torch).

Tests:
  _filter_pinned_axes:
    - shape axis is DROPPED when an invariant pins the output shape explicitly
    - the SAME shape axis is KEPT for a bare "resize smaller" spec with no shape invariant
    - value axis DROPPED when spec prose mentions the axis keyword
    - value axis KEPT when spec prose has no mention of the axis keyword
  ask_choice:
    - "2" returns the 2nd option
    - "" returns the 1st option (safe default)
    - "9" (out-of-range) returns the 1st option (safe default)

Run by file path with PYTHONPATH=repo root.
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)

from nodeforge.spec import _filter_pinned_axes          # noqa: E402
from nodeforge.confirm import ask_choice                # noqa: E402
from nodeforge import records                           # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _spec(invariants=None, examples=None, input_types=None):
    """Build a minimal Spec for filter tests."""
    return records.Spec(
        ask="test ask",
        title="Test",
        input_types=input_types or {"required": {"image": ["IMAGE"]}},
        return_types=["IMAGE"],
        invariants=invariants or [],
        examples=examples or [],
    )


def _example(statement):
    """Minimal Example whose nl_statement + expectation.statement both equal `statement`."""
    return records.Example(
        id="e1",
        nl_statement=statement,
        input_spec=records.InputSpec(generator="solid", params={"color": [0, 0, 0], "h": 2, "w": 2}),
        expectation=records.Expectation(kind="invariant", statement=statement),
    )


_SHAPE_AXIS = {"axis": "output_size", "dimension": "shape",
               "interpretations": ["same as input", "half in both H and W"]}

_VALUE_AXIS = {"axis": "clamp_mode", "dimension": "value",
               "interpretations": ["clamp to [0,1]", "wrap mod 1"]}

_VALUE_AXIS_ABSENT = {"axis": "some_other_knob", "dimension": "value",
                      "interpretations": ["option A", "option B"]}

_CHANNEL_AXIS = {"axis": "alpha_handling", "dimension": "channel",
                 "interpretations": ["always output RGB", "preserve alpha as RGBA"]}


# ---------------------------------------------------------------------------
# _filter_pinned_axes tests
# ---------------------------------------------------------------------------

def test_shape_axis_dropped_when_invariant_pins_shape():
    """Shape axis MUST be dropped when an invariant explicitly pins output shape."""
    spec = _spec(invariants=["Output is [B, H//2, W//2, C]"])
    result = _filter_pinned_axes(spec, [_SHAPE_AXIS])
    assert result == [], (
        f"Expected shape axis to be dropped when invariant pins shape, got: {result}"
    )


def test_shape_axis_kept_when_no_shape_invariant():
    """Shape axis MUST be kept for a bare 'resize smaller' spec with no shape invariant."""
    spec = _spec(invariants=["output stays in [0,1]"])
    result = _filter_pinned_axes(spec, [_SHAPE_AXIS])
    assert len(result) == 1 and result[0]["axis"] == "output_size", (
        f"Expected shape axis to be kept when no shape invariant present, got: {result}"
    )


def test_shape_axis_kept_on_loose_smaller_invariant():
    """A loose 'output is smaller' invariant does NOT pin the size (smaller by how
    much?), so the shape axis MUST survive and escalate. Guards the B-ESCALATES
    path against an over-broad shape regex that would re-create the v0.1 B-FAIL."""
    spec = _spec(invariants=["output shape is smaller than the input"])
    result = _filter_pinned_axes(spec, [_SHAPE_AXIS])
    assert len(result) == 1, (
        f"Loose 'smaller' must keep the shape axis (not a concrete pin), got: {result}"
    )


def test_value_halving_does_not_pin_shape():
    """rigor Finding 2: 'half the input pixel value' is a brightness op, NOT a resize,
    so it must NOT drop a shape axis (would be a B-miss for shape ambiguities)."""
    spec = _spec(invariants=["each output pixel is half the input pixel value"])
    result = _filter_pinned_axes(spec, [_SHAPE_AXIS])
    assert len(result) == 1, f"value-halving wrongly pinned shape, dropped axis: got {result}"


def test_none_axis_skipped_not_crash():
    """rigor Finding 1: a null/empty axis name must be skipped, never crash the filter
    (a crash is caught upstream and silently voids ALL filtering)."""
    axes = [{"axis": None, "dimension": "value", "interpretations": ["a", "b"]},
            {"axis": "", "dimension": "shape", "interpretations": ["a", "b"]},
            dict(_VALUE_AXIS_ABSENT)]
    spec = _spec(invariants=["output stays in [0,1]"])
    result = _filter_pinned_axes(spec, axes)   # must not raise
    assert result == [_VALUE_AXIS_ABSENT], f"expected only the valid axis kept, got {result}"


def test_channel_axis_kept_on_bare_channel_prose():
    """rigor Finding 4: bare 'channel' in normal prose must NOT pin the channel axis;
    only a real commitment (RGBA / 'always RGB') should drop it."""
    spec_bare = _spec(invariants=["the red channel of the output equals the input"])
    assert len(_filter_pinned_axes(spec_bare, [_CHANNEL_AXIS])) == 1, "bare 'channel' wrongly pinned"
    spec_commit = _spec(invariants=["the node always outputs RGBA"])
    assert _filter_pinned_axes(spec_commit, [_CHANNEL_AXIS]) == [], "RGBA commitment should pin channel"


def test_value_axis_dropped_when_prose_mentions_keyword():
    """Value axis MUST be dropped when spec prose already mentions the axis keyword."""
    # The axis name "clamp_mode" appears literally in the invariant
    spec = _spec(invariants=["clamp_mode is always hard clamp"])
    result = _filter_pinned_axes(spec, [_VALUE_AXIS])
    assert result == [], (
        f"Expected value axis dropped when keyword in prose, got: {result}"
    )


def test_value_axis_dropped_when_widget_covers_it():
    """Value axis MUST be dropped when a widget of the same name exists in input_types."""
    spec = _spec(input_types={"required": {"image": ["IMAGE"],
                                            "clamp_mode": ["STRING", {"default": "clamp"}]}})
    result = _filter_pinned_axes(spec, [_VALUE_AXIS])
    assert result == [], (
        f"Expected value axis dropped when a widget covers it, got: {result}"
    )


def test_value_axis_kept_when_absent_from_prose_and_widgets():
    """Value axis MUST be kept when axis keyword does not appear in prose or widgets."""
    spec = _spec(invariants=["output stays in [0,1]"])
    result = _filter_pinned_axes(spec, [_VALUE_AXIS_ABSENT])
    assert len(result) == 1 and result[0]["axis"] == "some_other_knob", (
        f"Expected value axis kept when no prose mention and no widget, got: {result}"
    )


def test_dedup_by_axis_name():
    """Duplicate axis names are de-duplicated (first occurrence wins)."""
    axes = [
        {"axis": "output_size", "dimension": "shape", "interpretations": ["A", "B"]},
        {"axis": "output_size", "dimension": "shape", "interpretations": ["C", "D"]},
    ]
    spec = _spec(invariants=["output stays in [0,1]"])  # no shape pin
    result = _filter_pinned_axes(spec, axes)
    assert len(result) == 1 and result[0]["interpretations"] == ["A", "B"], (
        f"Expected de-dup keeping first, got: {result}"
    )


# ---------------------------------------------------------------------------
# ask_choice tests
# ---------------------------------------------------------------------------

def test_ask_choice_valid_index():
    """'2' must return the 2nd option (1-based)."""
    options = ["alpha", "beta", "gamma"]
    result = ask_choice("Pick one:", options, _input=lambda _: "2")
    assert result == "beta", f"Expected 'beta', got: {result!r}"


def test_ask_choice_empty_input_returns_first():
    """Empty input must return options[0] (safe default)."""
    options = ["alpha", "beta", "gamma"]
    result = ask_choice("Pick one:", options, _input=lambda _: "")
    assert result == "alpha", f"Expected 'alpha', got: {result!r}"


def test_ask_choice_out_of_range_returns_first():
    """'9' (out of range for 3-option list) must return options[0]."""
    options = ["alpha", "beta", "gamma"]
    result = ask_choice("Pick one:", options, _input=lambda _: "9")
    assert result == "alpha", f"Expected 'alpha', got: {result!r}"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        ("shape axis dropped when invariant pins shape",
         test_shape_axis_dropped_when_invariant_pins_shape),
        ("shape axis kept when no shape invariant",
         test_shape_axis_kept_when_no_shape_invariant),
        ("shape axis kept on loose 'smaller' invariant",
         test_shape_axis_kept_on_loose_smaller_invariant),
        ("value-halving does not pin shape (rigor F2)",
         test_value_halving_does_not_pin_shape),
        ("none/empty axis skipped not crash (rigor F1)",
         test_none_axis_skipped_not_crash),
        ("channel axis kept on bare 'channel' prose (rigor F4)",
         test_channel_axis_kept_on_bare_channel_prose),
        ("value axis dropped when prose mentions keyword",
         test_value_axis_dropped_when_prose_mentions_keyword),
        ("value axis dropped when widget covers it",
         test_value_axis_dropped_when_widget_covers_it),
        ("value axis kept when absent from prose and widgets",
         test_value_axis_kept_when_absent_from_prose_and_widgets),
        ("dedup by axis name",
         test_dedup_by_axis_name),
        ("ask_choice valid index",
         test_ask_choice_valid_index),
        ("ask_choice empty input returns first",
         test_ask_choice_empty_input_returns_first),
        ("ask_choice out-of-range returns first",
         test_ask_choice_out_of_range_returns_first),
    ]

    out = []
    all_ok = True
    for name, fn in tests:
        try:
            fn()
            out.append(f"PASS: {name}")
        except AssertionError as exc:
            out.append(f"FAIL: {name} -- {exc}")
            all_ok = False
        except Exception as exc:  # noqa: BLE001
            out.append(f"ERROR: {name} -- {type(exc).__name__}: {exc}")
            all_ok = False

    out.append("AXES: " + ("PASS" if all_ok else "FAIL"))
    result_path = os.path.join(_REPO, "_axes_result.txt")
    with open(result_path, "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(out) + f"\nEXIT={0 if all_ok else 1}\n")
    print("\n".join(out))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

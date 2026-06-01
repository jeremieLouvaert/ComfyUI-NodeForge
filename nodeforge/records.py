"""
The cross-process data contract for NodeForge.

STDLIB ONLY -- no torch, no anthropic. This module is imported by BOTH the parent
agent process and the sandbox child subprocess, and the parent must never pull in
torch. Every object travels between processes as JSON (never pickle -- we exec
untrusted LLM code in the child, so the boundary is plain data).

Shapes formalize what benchmark/cases.py already encodes informally plus the
self-verification-model.md section 9.1 example record.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# section 9.1 example record
# ---------------------------------------------------------------------------
@dataclass
class InputSpec:
    """A named synthetic fixture generator + deterministic params.

    `generator` keys into fixtures.GENERATORS (child side). Tiny by design so a
    human can reason about it ("2x2 RGB, red/green swapped")."""
    generator: str                      # solid|gradient|checkerboard|seeded_texture|known_pattern
    params: dict = field(default_factory=dict)

    def to_dict(self): return {"generator": self.generator, "params": self.params}
    @classmethod
    def from_dict(cls, d): return cls(generator=d["generator"], params=d.get("params", {}))


@dataclass
class Expectation:
    """What a confirmed example asserts about the output.

    kind == "literal"  : output equals a pinned literal/value on this fixture.
    kind == "relation" : an input->output relation (e.g. out[...,0]==in[...,2]).
    kind == "invariant": a property the output must satisfy (range, shape, conservation)."""
    kind: str                           # literal|relation|invariant
    statement: str                      # human + machine readable assertion text
    literal: Any = None                 # only meaningful for kind=="literal"

    def to_dict(self): return {"kind": self.kind, "statement": self.statement, "literal": self.literal}
    @classmethod
    def from_dict(cls, d): return cls(kind=d["kind"], statement=d["statement"], literal=d.get("literal"))


@dataclass
class Example:
    """A human-confirmed input->output example (the Stage-1 trusted oracle).

    `args` holds the NON-image widget values this example assumes (e.g.
    {"color_highlights": "#0000ff", "gamma": 1.0}). Many examples only make sense
    at specific widget settings; without this, a literal check would call the node
    at widget DEFAULTS and falsely reject a correct node. Missing keys fall back to
    the widget default at call time."""
    id: str
    nl_statement: str                   # plain language, shown to the human at Stage 1
    input_spec: InputSpec
    expectation: Expectation
    args: dict = field(default_factory=dict)   # non-image widget values for this example
    thumbnail_pair: Optional[list] = None      # [in_png, out_png], filled at confirm time

    def to_dict(self):
        return {"id": self.id, "nl_statement": self.nl_statement,
                "input_spec": self.input_spec.to_dict(),
                "expectation": self.expectation.to_dict(),
                "args": self.args,
                "thumbnail_pair": self.thumbnail_pair}
    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], nl_statement=d["nl_statement"],
                   input_spec=InputSpec.from_dict(d["input_spec"]),
                   expectation=Expectation.from_dict(d["expectation"]),
                   args=d.get("args", {}),
                   thumbnail_pair=d.get("thumbnail_pair"))


# ---------------------------------------------------------------------------
# the spec (Stage 0 output, confirmed at Stage 1)
# ---------------------------------------------------------------------------
@dataclass
class Spec:
    ask: str
    title: str                          # human title -> later the class/display name
    input_types: dict                   # ComfyUI INPUT_TYPES (the "required"/"optional" dict)
    return_types: list                  # e.g. ["IMAGE"] ; list (JSON) -> tuple in the node
    return_names: Optional[list] = None
    contract: str = ""                  # shape/range/dtype prose (Rec.709 etc.)
    examples: list = field(default_factory=list)      # list[Example], 3-6
    invariants: list = field(default_factory=list)    # list[str]
    edge_cases: list = field(default_factory=list)    # list[str]
    # v0.2 ambiguity oracle: interpretive forks the spec left UNPINNED. Each item:
    # {"axis": str, "dimension": "shape"|"value"|"channel"|"dtype",
    #  "interpretations": [str, ...]}. Empty for a fully-specified ask (then the
    #  author loop behaves exactly as v0.1). See docs + decisions.md ambiguity oracle.
    unpinned_axes: list = field(default_factory=list)
    confirmed: bool = False

    def to_dict(self):
        return {"ask": self.ask, "title": self.title, "input_types": self.input_types,
                "return_types": list(self.return_types),
                "return_names": list(self.return_names) if self.return_names else None,
                "contract": self.contract,
                "examples": [e.to_dict() for e in self.examples],
                "invariants": list(self.invariants), "edge_cases": list(self.edge_cases),
                "unpinned_axes": list(self.unpinned_axes),
                "confirmed": self.confirmed}

    @classmethod
    def from_dict(cls, d):
        return cls(ask=d["ask"], title=d["title"], input_types=d["input_types"],
                   return_types=d["return_types"], return_names=d.get("return_names"),
                   contract=d.get("contract", ""),
                   examples=[Example.from_dict(e) for e in d.get("examples", [])],
                   invariants=d.get("invariants", []), edge_cases=d.get("edge_cases", []),
                   unpinned_axes=d.get("unpinned_axes", []),
                   confirmed=d.get("confirmed", False))

    def to_spec_string(self) -> str:
        """Render the free-text spec that generate_battery + codegen consume.

        Matches the prose shape of benchmark/cases.py specs (Operation / Inputs /
        Output / Confirmed examples / invariants) so the proven SYSTEM_PROMPT in
        generate.py reads it the same way it read the benchmark cases."""
        req = self.input_types.get("required", {})
        inputs = ", ".join(f"{k} ({_t(v)})" for k, v in req.items()) or "image (IMAGE)"
        rnames = self.return_names or self.return_types
        outputs = ", ".join(f"{n} ({t})" for n, t in zip(rnames, self.return_types))
        lines = [f"Operation: {self.ask.strip()}",
                 f"Inputs: {inputs}.",
                 f"Output: {outputs}."]
        if self.contract.strip():
            lines.append(self.contract.strip())
        lines.append("Confirmed examples / invariants:")
        for e in self.examples:
            lines.append(f"  - {e.nl_statement.strip()}")
        for inv in self.invariants:
            lines.append(f"  - {inv.strip()}")
        if self.edge_cases:
            lines.append("Edge cases:")
            for ec in self.edge_cases:
                lines.append(f"  - {ec.strip()}")
        # unpinned_axes are DELIBERATELY not rendered here: ref0, the battery, and
        # non-stance impls must see a clean v0.1-identical spec. The chosen
        # interpretation is injected only into stance impls (codegen.generate_stance_impls,
        # via the user message). Keeping axes out of this string is what guarantees
        # the non-stance path is byte-identical to v0.1.
        return "\n".join(lines)


def _t(v):
    """Best-effort INPUT_TYPES value -> type string for spec prose."""
    if isinstance(v, (list, tuple)) and v:
        return v[0] if isinstance(v[0], str) else "?"
    return "?"


# ---------------------------------------------------------------------------
# candidates, checks, results
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """A node implementation source. Impls, ref0, and mutants share one exec path."""
    id: str                             # impl_0 | ref0 | mutant_op:<name> | mutant_llm:N
    source: str                         # full one-class node .py source
    class_name: str
    origin: str                         # impl | ref0 | mutant_op:<name> | mutant_llm | stance
    temperature: Optional[float] = None
    # v0.2 ambiguity oracle: set on stance-directed impls so the divergence the
    # differential sees is attributable to a flagged axis. None for ordinary impls
    # (then analyze_stance delegates verbatim to analyze). Travels as plain JSON.
    # {"axis": str, "interpretation": str, "dimension": "shape"|"value"|"channel"|"dtype"}
    stance: Optional[dict] = None

    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], source=d["source"], class_name=d["class_name"],
                   origin=d["origin"], temperature=d.get("temperature"),
                   stance=d.get("stance"))


@dataclass
class Check:
    """One vetted Stage-2 check (a check_<name> function as source)."""
    name: str
    source: str                         # self-contained def check_<name>(NodeClass): ...
    teeth: list = field(default_factory=list)   # mutant ids it killed (>=1 to count)
    passes_ref0: bool = False           # cleared the specificity guard
    vacuous: bool = False               # killed no mutant -> dropped

    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, d):
        return cls(name=d["name"], source=d["source"], teeth=d.get("teeth", []),
                   passes_ref0=d.get("passes_ref0", False), vacuous=d.get("vacuous", False))


@dataclass
class CheckResult:
    check_name: str
    candidate_id: str
    passed: bool
    detail: str = ""
    raised: bool = False                # an exception counts as failed (run_one_check semantics)

    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, d):
        return cls(check_name=d["check_name"], candidate_id=d["candidate_id"],
                   passed=d["passed"], detail=d.get("detail", ""), raised=d.get("raised", False))


@dataclass
class RunReport:
    """The single JSON payload the sandbox child prints to stdout."""
    job_id: str
    results: list = field(default_factory=list)         # list[CheckResult]
    output_digests: dict = field(default_factory=dict)  # cand_id -> {example_id -> digest(list)}
    load_errors: dict = field(default_factory=dict)     # cand_id -> error string (failed to exec/instantiate)
    open_questions: dict = field(default_factory=dict)  # battery_id -> [str] (triage)
    timed_out: bool = False
    oom: bool = False
    stderr_tail: str = ""
    wall_ms: int = 0
    peak_rss_mb: int = 0

    def to_dict(self):
        return {"job_id": self.job_id,
                "results": [r.to_dict() for r in self.results],
                "output_digests": self.output_digests,
                "load_errors": self.load_errors,
                "open_questions": self.open_questions,
                "timed_out": self.timed_out, "oom": self.oom,
                "stderr_tail": self.stderr_tail, "wall_ms": self.wall_ms,
                "peak_rss_mb": self.peak_rss_mb}

    @classmethod
    def from_dict(cls, d):
        return cls(job_id=d["job_id"],
                   results=[CheckResult.from_dict(r) for r in d.get("results", [])],
                   output_digests=d.get("output_digests", {}),
                   load_errors=d.get("load_errors", {}),
                   open_questions=d.get("open_questions", {}),
                   timed_out=d.get("timed_out", False), oom=d.get("oom", False),
                   stderr_tail=d.get("stderr_tail", ""), wall_ms=d.get("wall_ms", 0),
                   peak_rss_mb=d.get("peak_rss_mb", 0))

    def results_for(self, candidate_id):
        return [r for r in self.results if r.candidate_id == candidate_id]

    def verdict(self, candidate_id):
        """'pass' iff it loaded and every check passed; 'fail' if it loaded but a
        check failed; 'error' if it failed to load OR produced no results at all.

        The 'error' case is kept DISTINCT from 'fail' on purpose: a candidate with
        zero results is an anomaly (a sandbox/loading bug), not evidence the node
        is wrong. Conflating the two once hid a real bug where mutants silently
        produced no results and read as 'caught'. Callers that want broken==caught
        should treat only 'fail' as caught and surface 'error' separately."""
        if candidate_id in self.load_errors:
            return "error"
        rs = self.results_for(candidate_id)
        if not rs:
            return "error"
        return "pass" if all(r.passed for r in rs) else "fail"


def dumps(obj) -> str:
    return json.dumps(obj.to_dict() if hasattr(obj, "to_dict") else obj)

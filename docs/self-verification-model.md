# NodeForge Self-Verification Model (design)

> Status: design, signed off 2026-05-30. No harness until the meta-validation
> benchmark (section 7) passes. This is the core of the product: the probe
> proved codegen is not the bottleneck, self-verification is.
>
> **UPDATE 2026-06-02 (verification is ADVISORY, not a gate):** the escalating
> oracle below is still how confidence is *built*, but it is no longer a hard
> *gate*. After live use showed a chain of strict gates dead-ending on reasonable
> asks, the posture was inverted: the only hard requirements are "the code runs in
> the sandbox" and "the human approves". Every automated stage here (examples,
> teeth/mutants, differential, contradiction, ambiguity) degrades to an honest
> caveat surfaced at the approval gate instead of refusing. Verification therefore
> means "runs and matches the confirmed examples, and the human approved after
> seeing a real before/after" -- NOT "provably semantically correct". A
> plausible-but-wrong node can pass the automated layer; the human review at the
> gate is the real oracle. See the README "How verification works, honestly".

## 1. The problem

The agent takes a vague natural-language ask ("I want a node that does X"),
writes a custom ComfyUI node, and must decide whether the node is *correct*
before asking the human to bank it.

We already know:

- **Structural / runtime correctness is free.** ComfyUI execution tells us a
  node imports, runs, and returns the declared type. The capability probe and
  the live load test (README roadmap items, both passed) settled this.
- **Semantic correctness has no automatic oracle.** "Did the node do the *right*
  thing" is defined only by the user's intent. In the probe, *a human* wrote the
  independent oracles and *a human* confirmed (via the negative control) that
  they had teeth. In production there is no human writing an oracle per node.

The trap is circularity. If the same model writes both the node and its test
from the same misreading of a vague spec, both are wrong-but-consistent: the
test passes, the node is wrong. This is the "marking your own homework" problem,
and it is the same unsolved semantic-oracle problem that killed the aesthetic-loop
wedge (a stable, non-gameable semantic reward). It is THE hard problem here.

## 2. Reframe (what we are actually building)

We are **not** building a fully autonomous semantic oracle. That is likely
impossible for genuinely-novel ops, because "right" lives in the user's head.

The achievable goal: **automate every layer of correctness that can be automated,
inject the human's irreducible semantic judgment at the cheapest possible point,
and make the final approval a glance instead of a code review.** The
human-approval gate is a feature, not a fallback.

Success metric (honest, measurable):

1. **No node is ever banked that fails an automatable check** (contract, property,
   confirmed-example). Hard guarantee.
2. **Residual human verification cost is driven down to "confirm a few examples
   up front + glance at a visual before/after diff."** Not "read 80 lines of torch
   and guess."
3. **Genuine spec ambiguity is surfaced as a targeted question, not silently
   guessed.**

Framing success this way (rather than "the agent self-verifies autonomously") is
the rigor-honest position and matches the probe's documented limits.

## 3. The escalating-oracle pipeline

Correctness is layered. The layers run cheap to expensive, automatable to human.
A node must clear each layer to advance. Most bugs die early and cheaply.

| # | Oracle | Cost | Automatable? | Catches |
|---|--------|------|--------------|---------|
| 1 | **Structural** (static) | free | yes | invalid INPUT_TYPES / RETURN_TYPES / FUNCTION / CATEGORY |
| 2 | **Runtime** (execution) | free | yes | import errors, exceptions on a real IMAGE tensor |
| 3 | **Contract / invariant** | cheap | yes | wrong type; wrong shape convention (`[B,H,W,C]` IMAGE, `[B,H,W]` MASK); dtype; range [0,1]; non-determinism |
| 4 | **Property + metamorphic** | cheap | yes (fallible) | semantic relations: identity at neutral params, invariants, monotonicity, conservation (e.g. shadows+highlights==input) |
| 5 | **Differential consensus** | cheap | yes | divergent interpretations across N implementations -> pinpoints spec ambiguity |
| 6 | **External reference oracle** | medium | yes (when recognized) | mismatch vs a trusted library impl for *standard* ops (PIL/scipy/kornia/OpenCV) |
| 7 | **Confirmed-example oracle** | cheap (human, up front) | yes once confirmed | output disagrees with a human-confirmed input->output example |
| 8 | **Human-approval gate** | human, final | no | everything semantic the layers above could not pin |

Layer 3 already kills a surprising amount with zero understanding of intent: two
of the five negative-control bugs (the `[B,H,W,1]` mask and out-of-range output)
die here. Layer 4 is where most of the *semantic* discrimination lives without a
human. Layers 5 and 7 are how we break circularity (below). Layer 6 is a bonus
that only covers known ops, which is the opposite of the product's novel-op
reason to exist, so it is never the backbone.

## 4. The four anti-circularity rules

These are the actual design content. They are derived directly from the
negative-control / rigor discipline already in the brain.

1. **Tests are authored from the spec, never from reading the implementation.**
   Black-box. A test that reads the code just mirrors the code's bugs.
2. **Prefer properties, relations, and external references over recomputed
   expected values.** Recomputing the expected value is just a second
   implementation that shares the first's blind spots. Assert *that
   shadows+highlights==input*, do not re-derive the split.
3. **Every auto-generated check must itself pass a teeth test** (it must reject at
   least one plausible wrong variant) before it is allowed to *count*. This
   promotes the probe's one-time negative control into a standing,
   per-generated-test requirement. A vacuously-true assertion gives false
   confidence and is worse than no test, so it is dropped and regenerated.
4. **Differential divergence is a question for the human, not a vote.** A majority
   can be a shared blind spot. When N implementations disagree on behavior that
   no confirmed example or invariant pins down, that is spec ambiguity: escalate
   it, do not auto-resolve by majority.

## 5. The v0.1 loop (TDD + lean-core + differential)

Resolved forks (2026-05-30): human judgment sits **up front** (confirm examples,
TDD-style); the v0.1 stack is **lean core + differential** (defer the external
reference oracle, layer 6, to v0.2).

```
Stage 0  Spec elaboration
         vague NL ask -> structured spec:
           - declared INPUT_TYPES / RETURN_TYPES + shape/range contract
           - 3-6 concrete input->output examples (described + tiny numeric or
             visual instance where it helps)
           - invariants / metamorphic relations the op must satisfy
           - known edge cases

Stage 1  Human confirms the spec   <-- the cheap semantic oracle
         plain-language confirm/edit of the examples + invariants.
         Intent is pinned HERE, before any code. No code shown yet.

Stage 2  Test synthesis from the CONFIRMED spec (black-box, before code)
           - contract / invariant assertions (layer 3)
           - example-based assertions from the confirmed examples (layer 7)
           - property / metamorphic assertions (layer 4)
         Each generated assertion is teeth-checked against >=1 auto-mutated
         wrong variant; vacuous assertions are dropped and regenerated (rule 3).

Stage 3  Code generation
         N independent implementations from the confirmed spec
         (varied prompt/temperature; the test-author context is NOT shared
         with the implementer -> rule 1).

Stage 4  Run all N in sandbox against the test battery (real torch)
           - structural + runtime + contract + property + example (layers 1-4,7)
           - differential consensus across the N (layer 5):
               agree            -> confident
               diverge on a confirmed example/invariant -> the diverging impls
                                   are buggy, discard them
               diverge on behavior NO example/invariant covers -> spec ambiguity
                                   -> back to Stage 1 with a targeted question

Stage 5  Human-approval gate (layer 8)
         present: the winning implementation, the test report (what was
         checked + the teeth evidence), and a visual before/after diff on a
         real image. Approve -> bank. Reject -> reason feeds back to Stage 0/1.
```

The example battery from Stage 2 is what makes this TDD: code is generated to
pass a test the human already blessed, not graded by a test the same model
invented after the fact.

## 6. What is deferred

- **Layer 6 (external reference oracle).** Recognizing "this is a standard
  unsharp mask" and testing against PIL/scipy/kornia is high-trust but brittle
  (recognition is the hard part) and only helps the *common* case, which is the
  opposite of the novel-op reason the product exists. v0.2.
- **The authoring agent loop, sandbox, and banked library** (README roadmap
  items 3-4). Not until the model below validates.

## 7. The gate before any harness: the meta-validation benchmark

Same discipline as "prove the fitness function before building the harness" from
the aesthetic-loop entry, and the negative-control discipline from the probe. The
self-verification model must itself be shown to have teeth, on a set where we
already own ground truth, before we build the agent loop.

We already have the set: the **5 correct probe nodes** + the **5 deliberately-broken
variants** from `probe/negative_control.py`. Extend it with vaguer specs (real
asks are vaguer than the clean ones chosen for the probe).

Run Stages 2-4 **without the human** on each item and measure:

- **Teeth:** are all 5 broken variants caught? (catch rate)
- **No false rejection:** do all 5 correct nodes pass? (specificity)
- **Right triage:** for anything undecidable, is it escalated with the *correct*
  targeted question (not a silent guess, not a wrong question)?

If the model cannot hit that bar on a set we have ground truth for, it is sand
and we learned it cheaply, before building anything. This benchmark is the next
concrete buildable artifact.

**RESULT (2026-05-30): PASS.** Built in `benchmark/`. On 6 confirmed specs (the 5
probe node types + realistic bugs + one ambiguity case), 3 trials each, model
claude-sonnet-4-6: teeth 21/21 (100%), specificity 21/21 (100%), triage 3/3, zero
unrecoverable battery errors. The benchmark earned its keep by surfacing two real
issues before they could mislead us: (1) output truncation masquerading as bad
codegen (raised the token cap), and (2) one over-strict check that probed a
clamped op at saturation and false-rejected a correct node (fixed with a
generalizable test-signal-design rule, not by loosening the gate). Honest residual:
a small fraction of raw draws emit a self-inconsistent battery that does not load;
these are detected for free and auto-regenerated, exactly as the product loop will.
The gate is a per-run check, so one clean pass is strong evidence, not a proof that
every future draw self-verifies.

## 8. Honest limits / residual risk

- **Shared blind spot across all N implementations AND the test.** If every
  implementation and the test all inherit the same wrong assumption from the
  confirmed spec, nothing automatic catches it. The human-confirmed examples
  (real ground truth) and the visual diff at the gate are the main defense, and
  they do not fully eliminate it. This is the irreducible residual and must be
  stated plainly to the user, never hidden behind a green check.
- **Under-specified novel ops.** When the op is genuinely bespoke and the human's
  few examples do not pin the whole input domain, correctness is only verified
  *on the examples + invariants*, not proven globally. The visual diff mitigates;
  it does not prove.
- **Cost of N.** Differential testing multiplies codegen, but codegen is the
  cheap, proven part, so this is acceptable. Cap N small (3 to start) and only
  widen on detected divergence.

## 9. Resolved (2026-05-30, v0.1 plan sign-off)

The three build-session opens were resolved at the v0.1 AUTHOR + RETRIEVE plan
sign-off (decisions.md "[2026-05-30] NodeForge v0.1 author+retrieve loop design";
plan at .claude/plans/melodic-leaping-waffle.md). The retrieval-side design lives
in docs/retrieval-model.md.

1. **Example representation.** Each confirmed example is a record
   `{nl_statement, input_spec (named synthetic generator + params), expectation
   (invariant/relation, or a spec-pinned literal), optional thumbnail_pair}`.
   Machine-facing: input_spec builds a small deterministic fixture (solid color,
   gradient, checkerboard, seeded texture, known pattern); the expectation is
   preferably an invariant or relation (rule 2), a literal only where the spec
   pins an exact value/formula. Human-facing: the NL statement plus, for image
   ops, an optional rendered input->output thumbnail pair so confirmation is a
   glance. Prefer tiny inputs a human can reason about ("2x2 RGB, red/green
   swapped") over a 1024px photo. This is a light formalization of what
   benchmark/cases.py already encodes informally (spec "Confirmed examples /
   invariants" + generate.py torch.rand fixtures + property assertions).

2. **Teeth-test mutation engine.** Mutate the spec/behavior, never the candidate's
   code (mutating the candidate shares its blind spots). Mutants come from a
   generic, spec-agnostic library generalizing the five probe/negative_control.py
   bugs into reusable operators (channel permute, Rec.709->mean-luma, MASK
   [B,H,W]->[B,H,W,1], drop-clamp, identity/no-op, global-vs-local reduction,
   sign/logic flip, wrong-factor scale, transpose H/W, off-by-one), plus an LLM
   "write a subtly-wrong implementation from the spec" mutant authored in a context
   separate from both the check-author and the implementer (non-circular, rule 1).
   A generated check counts only if it FAILS on >=1 mutant AND PASSES the confirmed
   examples. This makes the probe's one-time negative control standing and
   per-check. Honest limit: the library catches known bug classes only; a check can
   still be vacuous against an unknown class. Acceptable, and differential + the
   human gate cover the residual.

3. **Stage-4 sandbox boundary.** Verification executes UNAPPROVED LLM-authored code
   (torch on real tensors) before the human approves; the human gate prevents
   banking bad code, not running it during verify, so the verify loop must be
   contained. All execution from Stage 2 onward runs in an isolated child
   subprocess, never in the agent's process and never in the user's live ComfyUI
   server: no network, filesystem read-only except a throwaway temp dir, hard
   wall-clock timeout + memory cap with kill-on-exceed (the queue-hang failure mode
   documented in the brain must not be inherited). GPU runs inside the same sandbox
   only when the op needs it, with a tighter time budget; we do not escalate to the
   real server for verification. The live ComfyUI server is touched only at the
   human-approved BANK step (copy to custom_nodes, clear __pycache__, prompt
   restart). Honest limit / biggest risk: on Windows this subprocess profile is not
   a hard security boundary against a determined attacker; the v0.1 threat model is
   buggy/accidentally-destructive code, not hardened RCE containment (the real
   defenses are no-live-server-until-approved + the human diff glance). Container/VM
   isolation is a v0.2 item if the tool ever auto-runs untrusted community code.

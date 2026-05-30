# NodeForge Self-Verification Model (design)

> Status: design, signed off 2026-05-30. No harness until the meta-validation
> benchmark (section 7) passes. This is the core of the product: the probe
> proved codegen is not the bottleneck, self-verification is.

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

## 9. Open sub-questions for the build session

- Exact representation of "examples" the human confirms: pure NL, a tiny tensor
  literal, or a generated thumbnail pair. (Leaning: NL + an optional generated
  thumbnail pair for image ops.)
- How the mutation engine for the teeth test (rule 3) generates "plausible wrong
  variants" of an assertion cheaply and without itself being circular.
- Where the sandbox boundary sits for Stage 4 (subprocess vs the real ComfyUI
  server) given the security mandate. Likely subprocess for the verify loop,
  real server only at the human-approved bank step.

# Meta-validation benchmark

The gate before any agent loop is built (design doc section 7). It answers one
falsifiable question: **can an LLM, given only a confirmed spec and never the
implementation, auto-generate a verification battery that has teeth?**

It runs Stages 2-4 of the self-verification model **without the human** on a set
where we already own ground truth, and measures three things:

- **Teeth** — fraction of *broken* implementations the battery CATCHES.
- **Specificity** — fraction of *correct* implementations the battery ACCEPTS (no false rejection).
- **Triage** — on a deliberately ambiguous spec, does the battery flag the open question AND still accept both valid (differently-implemented) variants?

The bar: teeth = 100%, specificity = 100%, triage clean, zero unrecoverable battery errors.

## The set

`cases.py` holds 6 confirmed specs, each with full correct + broken ComfyUI node
classes. The 5 core node types and their realistic bugs are lifted from the
capability probe and its negative control (`../probe/`):

| node | correct | broken variant(s) |
|------|---------|-------------------|
| channel shuffle | swap R/B | R/G swap |
| luma key mask | Rec.709 → MASK [B,H,W] | [B,H,W,1] channel dim; channel-average not Rec.709 |
| tile mosaic | per-tile mean | one global mean |
| unsharp mask | sharpen, clamp | returns the blur (softens) |
| luma split | lossless partition | not lossless (shadows = full image) |
| **downscale 2x (ambiguity)** | bilinear AND area (both valid) | no resize |

## How it works

- `generate.py` (Stage 2) hands **only the spec** to Claude and asks for a
  verification module (a list of black-box `check(NodeClass)` functions + an
  `OPEN_QUESTIONS` list), under the four anti-circularity rules. The generator
  never sees any implementation.
- `run_benchmark.py` (Stage 4) execs each battery and runs it against every
  correct and broken implementation, owning the isolation (a raising check
  counts as failed). A draw that fails to generate (truncation) or load (syntax /
  NameError) is auto-regenerated up to `--retries` times — this models the real
  loop's self-debug-on-feedback, since a non-loading battery is a free,
  detectable failure that never reaches the human.

## Run

```
# use the ComfyUI embedded python (has torch + anthropic); needs ANTHROPIC_API_KEY
python run_benchmark.py --trials 3 --model claude-sonnet-4-6
python run_benchmark.py --cases luma_key_mask,luma_split   # subset
```

Per-run artifacts (generated batteries, logs, results.json) land in `results/`
and are gitignored.

## Latest result (2026-05-30, claude-sonnet-4-6, 3 trials/case)

**GATE PASS** — Teeth 21/21 (100%), Specificity 21/21 (100%), Triage 3/3,
0 unrecoverable battery errors, ~$1.14.

Two findings the benchmark surfaced, both fixed:

1. **Output truncation, not bad reasoning.** At `max_tokens=4000`, half the
   batteries were cut off mid-string (unterminated literals / unclosed brackets).
   Raised the cap to 8000 and made truncation a loud explicit error. Semantic
   quality was already perfect on every battery that fit.
2. **One over-strict check false-rejected a correct unsharp mask.** It probed a
   fully-saturated 0-vs-1 edge, where a correct *clamped* unsharp shows zero
   change (the overshoot is clipped) — so the check, not the node, was wrong.
   Fixed by teaching the generator a generalizable test-design principle: do not
   probe a clamped operation at saturation; use mid-tone signals so the effect is
   observable. This improves the product's test generation, it does not game the
   metric.

Residual, honest: a small fraction of raw draws still emit a self-inconsistent
battery (e.g. a `CHECKS` entry that references an undefined function). These do
not load, are detected for free, and are auto-regenerated — exactly how the
product loop handles them. The gate is a per-run check; one clean pass is strong
evidence, not a proof that every future draw self-verifies.

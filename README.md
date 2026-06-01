# ComfyUI-NodeForge

**Describe the ComfyUI node you need. NodeForge finds it if it exists, and forges a new one (verified and banked) if it doesn't.**

> **Status: v0.2** (pre-alpha). A command-line agent that, from a plain-language description, first checks whether a node already exists (ComfyUI core or a community pack), and otherwise authors a brand-new custom node: it drafts the code, tests it in a sandbox against real inputs, shows you the diff and the test result, and on your approval installs it and banks it in your node library. Both halves are live-verified. Thresholds are provisional and ambiguity handling has a known gap (see [Known limits](#known-limits-honest)).

## The idea

ComfyUI has thousands of custom nodes, but two things still hurt: finding the one that does what you want, and the times when the genuinely novel operation you need (a bespoke math op, a format bridge, a one-off API wrapper) simply doesn't exist. "Go write a custom node" is a wall for most users.

NodeForge closes both gaps from a single description:

1. **Find it first.** It searches ComfyUI's built-in nodes and the community pack index, ranks the candidates, and if something already does the job it points you there instead of reinventing it.
2. **Forge it if it's missing.** When nothing fits, it drafts a new custom node, tests it in a sandbox against real inputs, shows you the code and the test result, and on your approval installs it and banks it in your personal library. Over time your ComfyUI grows the capabilities you actually use.

The lineage is the self-authoring / skill-library agent pattern (Voyager, ADAS) applied to ComfyUI's executable node graph as the substrate, rather than to chat. The graph is data; a node is code; the agent closes the loop between them. **Authoring is the hard, novel part (the moat); retrieval is table stakes done responsibly.**

## Design principles (non-negotiable)

- **Human-approval gate.** The agent never silently writes and runs code in your install. You see the diff and the sandboxed test output, and you approve before anything is installed or banked. This is a security boundary, not a UX nicety.
- **Sandboxed write, test, verify, bank loop.** Generated nodes run in isolation first; ComfyUI's own execution is the runtime-correctness oracle (did it import, did it run, is the output the declared type, shape, and range).
- **Verification is the hard part, not generation.** Code generation is largely solved (see the evidence trail below); knowing whether a node did the *right* thing is the real problem. The verify/bank loop is the core of the tool.
- **Banked nodes are curated, not auto-trusted.** Your library is a record of nodes you approved, not whatever the agent emitted.
- **Find before you forge.** Authoring a redundant node is waste; NodeForge checks what already exists first and defers to it.

## Install and usage

NodeForge is a command-line tool that runs *outside* ComfyUI. It only touches your live ComfyUI install at the final, approved bank step.

```bash
git clone https://github.com/jeremieLouvaert/ComfyUI-NodeForge
cd ComfyUI-NodeForge
# Provide an Anthropic API key, via env var or anthropic_api_key.txt in your ComfyUI root:
export ANTHROPIC_API_KEY=sk-ant-...
python -m nodeforge.cli "a node that splits an image into its luma and chroma channels"
```

Flags: `--n` (number of candidate implementations, default 3), `--model`, `--yes` (non-interactive auto-confirm), `--force` (overwrite an existing banked pack), `--no-precheck` (skip the "does this already exist?" retrieval step).

> Note for ComfyUI's embedded Python: its isolated `python._pth` does not put the repo on the import path, so invoke from the repo root (so the `nodeforge` package is importable), or use a standard Python install for the CLI.

## How it works

### Find it first (the retrieval router)

Before authoring anything, NodeForge runs a three-band router over a freshness-cached index of ComfyUI's built-in nodes plus the community pack registry:

- **HIGH** (confident match): recommends you install the existing node and skips authoring.
- **MIDDLE** (partial or related): shows one to three candidate packs and offers to author anyway; you pick.
- **LOW / none**: nothing fits, so it proceeds to author.

A confident **built-in** node takes precedence over a community pack (no install needed for something ComfyUI already ships). Install is always human-confirmed; authoring is never silently suppressed.

### Forge it (the authoring loop)

When nothing fits, a staged pipeline runs: spec elaboration, then you confirm a few input/output examples (the trusted oracle), then teeth-gated test-battery synthesis, then N candidate implementations, then subprocess-sandboxed differential consensus, then the human-approval gate, then bank. The parent process never imports torch and never executes candidate code; all candidate execution happens in a sandbox child (Windows Job-Object memory cap plus wall-clock kill). The design is written up in [`docs/self-verification-model.md`](docs/self-verification-model.md) and [`docs/retrieval-model.md`](docs/retrieval-model.md).

## Evidence trail

This was de-risked before it was built, and the de-risking artifacts ship with the repo:

- [`probe/node_authoring_capability_probe.py`](probe/) — capability probe. A strong LLM, given ComfyUI's node conventions, drafted 5 non-trivial nodes (channel shuffle, luma-key mask, tile mosaic, unsharp mask, luma split). Each is verified against real torch by an **independent** numeric oracle covering the known traps (the `MASK` `[B,H,W]` vs `[B,H,W,C]` convention, separable-Gaussian conv, multi-output typing, `INT`/`FLOAT` widget configs, Rec.709 luma). Result: **5/5 correct.**
- [`probe/negative_control.py`](probe/) — proves the oracles have teeth: 5 deliberately-broken variants are all correctly caught, so the pass is not a self-confirming tautology.
- [`probe/ComfyUI-Node-Probe/`](probe/) — the 5 probe nodes packaged as a real custom-node pack with `verify_loadtest.py`, used for the real-server load test.
- [`benchmark/`](benchmark/) — the meta-validation benchmark: runs the verification model *without the human* on confirmed specs to prove it generates teeth-having, non-over-strict test batteries from a spec alone.

### What's verified

- **Real-server load test** (2026-05-30): probe nodes register with correct schemas in live ComfyUI and a `Probe Test Image -> Probe Unsharp Mask -> SaveImage` graph executes via `/prompt`.
- **Self-verification benchmark** (2026-05-30): teeth 21/21, specificity 21/21, triage 3/3.
- **Author acceptance**: a genuinely-novel *duotone* node authored, sandbox-verified, and banked, then live-verified in a running ComfyUI (`/object_info` registration plus an `EmptyImage -> DuotoneNode -> SaveImage` `/prompt` run). A contradictory ask is correctly refused.
- **Retrieval router**: live-verified routing (SD3 and ControlNet to built-ins, a crop-and-paste-back ask to MIDDLE candidates, a rotation ask to LOW then author).

## Known limits (honest)

- **Ambiguity (the "B" gap).** An under-specified ask (for example "make it smaller") banks one reasonable interpretation rather than asking you to choose. Differential consensus only flags ambiguity when implementations diverge, and a consistent model converges on one reading. An ambiguity oracle ships as a backstop, not a headline; the human-approval gate still sits between any guess and your install.
- **Retrieval is pack-level** and its thresholds are provisional (calibrated on a 29-ask adjudication). A generic ask like "resize to WxH" can still rank a polished community pack above the equivalent built-in.
- **No registry / Manager listing yet.** NodeForge is a developer CLI today, not an installable node pack. A ComfyUI-native frontend (and a Comfy-registry listing) is the next milestone.

## Roadmap

- Ambiguity oracle promoted from backstop to an active "which did you mean?" prompt.
- ComfyUI-native frontend and Comfy-registry distribution.
- Node-level (not just pack-level) retrieval; an external-reference verification oracle.

## License

MIT. See [LICENSE](LICENSE).

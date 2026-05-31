# ComfyUI-NodeForge

**An agent that writes the ComfyUI node you need, when it doesn't exist yet.**

> Status: experimental / pre-alpha. Feasibility probed, architecture in design. Not yet installable.

## The idea

ComfyUI has thousands of custom nodes, but the genuinely novel operation you need (a bespoke math op, a format bridge, a one-off API wrapper) often doesn't exist, and the answer "go write a custom node" is a wall for most users.

NodeForge is a node-authoring agent: when a capability is missing, it drafts a new custom node, tests it in a sandbox against real inputs, shows you the code and the test result, and, on your approval, installs it and banks it in your personal node library. Over time your ComfyUI grows the capabilities you actually use.

The lineage is the self-authoring / skill-library agent pattern (Voyager, ADAS) applied to ComfyUI's executable node graph as the substrate, rather than to chat. The graph is data; a node is code; the agent closes the loop between them.

## Design principles (non-negotiable)

- **Human-approval gate.** The agent never silently writes and runs code in your install. You see the diff and the sandboxed test output, and you approve before anything is installed or banked. This is a security boundary, not a UX nicety.
- **Sandboxed write → test → verify → bank loop.** Generated nodes run in isolation first; ComfyUI's own execution is the runtime-correctness oracle (did it import, did it run, is the output the declared type/shape/range).
- **Verification is the hard part, not generation.** Code generation is largely solved (see the probe below); knowing whether a node did the *right* thing is the real problem. The verify/bank loop is the core of the tool.
- **Banked nodes are curated, not auto-trusted.** Your library is a record of nodes you approved, not whatever the agent emitted.

## What's in this repo right now

This is the de-risking work that precedes the build:

- `probe/node_authoring_capability_probe.py` — capability probe. A strong LLM, given ComfyUI's node conventions, drafted 5 non-trivial nodes (channel shuffle, luma-key mask, tile mosaic, unsharp mask, luma split). Each is verified against real torch by an **independent** numeric oracle covering the known traps (the `MASK` `[B,H,W]` vs `[B,H,W,C]` convention, separable-Gaussian conv, multi-output typing, `INT`/`FLOAT` widget configs, Rec.709 luma). Result: **5/5 correct.**
- `probe/negative_control.py` — proves the oracles have teeth: 5 deliberately-broken node variants are all correctly caught, so the probe pass is not a self-confirming tautology.
- `probe/ComfyUI-Node-Probe/` — the 5 probe nodes packaged as a real custom-node pack (plus a self-contained test-image generator), with `verify_loadtest.py`, an HTTP client that confirms registration (`/object_info`) and live execution (`/prompt`) against a running ComfyUI. Used for the real-server load test.

## Roadmap

1. ~~Real-server load test.~~ **Done (2026-05-30):** all 6 probe nodes register with correct schemas in live ComfyUI, and a `Probe Test Image → Probe Unsharp Mask → SaveImage` graph executes end-to-end via `/prompt`. Confirms LLM-authored nodes work in the real server, not just an offline harness.
2. ~~Self-verification design~~ **Designed (2026-05-30):** see [`docs/self-verification-model.md`](docs/self-verification-model.md). An escalating-oracle pipeline (structural → runtime → contract → property/metamorphic → differential consensus → confirmed-example → human gate), authored from the spec not the code, with a TDD loop where the human confirms a few input→output examples up front as the trusted oracle.
3. ~~Meta-validation benchmark~~ **Passed (2026-05-30):** see [`benchmark/`](benchmark/). Running the model *without the human* on 6 confirmed specs (the 5 probe node types + their realistic bugs + one ambiguity case), 3 trials each: **teeth 21/21 (100%), specificity 21/21 (100%), triage 3/3.** The benchmark surfaced and fixed two real issues (output truncation; one over-strict check probing a clamped op at saturation). Self-verification de-risked: the model can auto-generate teeth-having, non-over-strict batteries from a spec alone.
4. ~~The authoring agent loop + the human-approval gate + sandbox.~~ **Built (2026-05-31):** see [`nodeforge/`](nodeforge/). A Python-CLI agent runs Stage 0 spec-elaboration → 1 human-confirm examples → 2 teeth-gated battery synth (ref0 + example-filter) → 3 N implementations → 4 subprocess-sandboxed differential consensus → 5 human-approval gate → bank. The parent process never imports torch / never execs candidate code; all candidate execution is in a sandbox child (Windows Job-Object memory cap + wall-clock kill). Offline tests green (sandbox parity 7/7 specificity + 7/7 teeth vs the benchmark; mutation engine; ref0 teeth-gate; differential 4/4). **Acceptance 2/3** (`nodeforge/tests/acceptance.py`): **A** a genuinely-novel *duotone* node is authored, self-verified, and banked to ComfyUI custom_nodes (the banked module re-imports + runs correctly under the embedded torch); **C** a contradictory ask is refused (no bank). **B is the known v0.1 gap:** an *ambiguous* ask ("make it smaller") banks one reasonable interpretation instead of escalating — differential-consensus only surfaces ambiguity when implementations diverge, and a consistent model converges on one reading. A forced-divergence ambiguity oracle is the v0.2 fix. The HTTP `/object_info`+`/prompt` live-server check (`nodeforge/tests/verify_duotone_live.py`) runs after a ComfyUI restart.
5. An ambiguity oracle that escalates under-specified asks (the B gap); the ComfyUI-native frontend; the banked node library.

## License

TBD.

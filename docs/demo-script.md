# NodeForge launch demo (shot list)

Target: under 2 minutes. One take if possible. Goal: land the moat ("describe a node that doesn't exist, watch it get authored, verified, and banked, live") and show the router is responsible (it won't reinvent what already exists).

Capture: **asciinema** for the terminal beats (1 and 2), a short **screen recording** for the ComfyUI payoff (beat 3). Stitch the two. Keep the terminal font large.

Prep before recording:
- `ANTHROPIC_API_KEY` set.
- A clean terminal in the repo root, ComfyUI running in the background (for beat 3).
- Optional: do one full rehearsal first (see bottom) so the asks land cleanly and you know the timing.

---

## Beat 1 — "Find it first" (about 15s)

Show that NodeForge checks before it builds.

```
python -m nodeforge.cli "apply ControlNet conditioning to a model"
```

Expected: the retrieval pre-check fires, reports a confident built-in match (ControlNet is a core node), and asks whether to install/use that or author anyway. **Choose stop / use-existing.** One line of narration: "It found that ComfyUI already does this, so it won't reinvent it."

(If you prefer to show the MIDDLE band instead, use `"crop a region, inpaint it, and paste it back"` which routes to related packs plus an author offer. Beat 1 only needs ~15s, so pick one.)

## Beat 2 — "Forge it" (about 75s, the star)

Now ask for something genuinely missing and visual:

```
python -m nodeforge.cli "a duotone node that maps the shadows of an image to one color and the highlights to another, with a gamma control"
```

Show the loop, narrating each stage in a few words:
1. **Spec** elaborates the ask.
2. **Confirm examples** — you confirm the input/output examples (the trusted oracle). Narration: "I confirm a couple of examples; that's the ground truth it tests against."
3. **Sandbox verify** — candidates run in isolation, differential consensus. Narration: "It writes a few implementations and tests them in a sandbox."
4. **Approval gate** — the diff and the test result appear. Narration: "Here's the code and the test result. Nothing touches my install until I approve." **Approve.**
5. **Bank** — it installs and banks `DuotoneNode`.

## Beat 3 — payoff in ComfyUI (about 30s)

Cut to ComfyUI (refresh / restart if needed so the new pack loads). 
- Add the new node (category `AKURATE/NodeForge`, `DuotoneNode`).
- Wire a real image (or `EmptyImage`) -> `DuotoneNode` -> `SaveImage` (or Preview).
- Set a shadow color and a highlight color, run.
- Show the duotone result. Narration: "Ninety seconds ago this node didn't exist. Now it's in my ComfyUI and it works."

---

## Closing card (optional, 3s)

"NodeForge — describe the node you need. github.com/jeremieLouvaert/ComfyUI-NodeForge"

## Rehearsal note

A dry run spends API and banks a node. Before the real take, run beats 1 and 2 once to confirm:
- beat 1's ask routes to a confident built-in (not author),
- beat 2's duotone ask routes to **author** (not a retrieval hit) and banks cleanly,
- the whole thing fits under 2 minutes.

If the duotone ask gets caught by retrieval as "already exists", either pick a more clearly-novel visual op or pass `--no-precheck` for beat 2 (and say so honestly in narration: "skipping the existence check for this one").

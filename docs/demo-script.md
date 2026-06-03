# NodeForge launch demo (shot list)

Target: under 2 minutes. One screen recording inside ComfyUI (NodeForge is a sidebar panel now, so the whole demo is one capture, no terminal). Goal: land the moat ("describe a node that does not exist, watch it get authored, verified, and installed, live, without leaving ComfyUI") and show it is responsible (it will not reinvent what already exists, and nothing installs without your approval).

Capture: a single **screen recording** of ComfyUI with the NodeForge sidebar open. Keep the panel readable; zoom the browser a little if needed.

Prep before recording:
- ComfyUI running with NodeForge installed, `ANTHROPIC_API_KEY` set (or `anthropic_api_key.txt` in the ComfyUI root).
- The NodeForge sidebar tab open.
- Do one full rehearsal first (it spends API and banks a node) so the asks land cleanly and you know the timing.

---

## Beat 1: "Find it first" (about 15s)

Show that NodeForge checks before it builds.

- Type: `apply ControlNet conditioning`
- It reports that ComfyUI already has this (a built-in match) and offers to use that or author anyway. Narration: "It found that ComfyUI already does this, so it will not reinvent it."

(Alternative if you want the MIDDLE band: `crop a region, inpaint it, and paste it back` surfaces related packs plus an author offer. Beat 1 only needs about 15s; pick one.)

## Beat 2: "Forge it" (about 75s, the star)

Now ask for something genuinely missing and visual:

- Type: `a node that gives an image a halftone print look`
- Walk through the panel, narrating each step in a few words:
  1. **Confirm.** Plain-language examples appear ("the darkest areas get the biggest dots"). Narration: "It shows me, in plain English, what it is about to build and how it will check itself. I confirm."
  2. **Working.** A calm progress log. Narration: "It writes the node and tests it in a sandbox."
  3. **Approval gate.** The generated code, the test results, and a real before/after appear. Narration: "Here is the code and a before/after on real images. Nothing touches my install until I approve." **Approve.**
  4. **Installed.** The success card. Narration: "Installed, and added to my node search, no restart."

## Beat 3: payoff in ComfyUI (about 30s)

Stay in ComfyUI.
- Double-click the canvas, search for the new node, drop it in.
- Wire a real photo (or `Load Image`) into it, into `Preview Image`.
- Run. Show the halftone result.
- Narration: "A minute ago this node did not exist. Now it is in my ComfyUI, it is mine, and it works."

---

## Closing card (optional, 3s)

"NodeForge: describe the node you need. github.com/jeremieLouvaert/ComfyUI-NodeForge"

## Rehearsal note

A dry run spends API and banks a node. Before the real take, confirm:
- beat 1's ask routes to a confident built-in (not author),
- beat 2's ask routes to author and goes all the way through to installed,
- the whole thing fits under 2 minutes.

Pick a beat-2 ask you have rehearsed so the confirm examples read cleanly and the result is visibly correct on a real photo. Halftone is a good choice because the effect is obvious; verify on your test image during rehearsal.

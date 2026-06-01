# NodeForge Retrieval Eval — Human Adjudication Sheet

**How to fill in:** For each row, judge whether the top-1 recommended pack genuinely satisfies the ask.
Use **yes** (pack clearly does it), **partial** (pack is related / plausibly helps but is not a clean match), or **no** (wrong pack, irrelevant, or the capability is not actually there).
Write your verdict in the Verdict column. Leave the Score column for reference — do not change it.

---

## Section A — retrieval / custom  (ground-truth answer is a custom pack)

| # | Ask | Top-1 Pack | URL | Score | Verdict |
|---|-----|------------|-----|-------|---------|
| 1 | Extract the nth individual image out of an Image List (split a list back into separate images) | Praveen's ComfyUI Tools | https://github.com/Praveenhalder/praveen-tools | 0.92 | no — has 3-way split and select-last/skip-first only; no nth-index extractor |
| 2 | A node to read prompt text from a file | ComfyUI-iTools | https://github.com/MohammadAboulEla/ComfyUI-iTools | 0.95 | yes — explicitly states "read prompts from a multiline file" |
| 3 | A combined Save/Preview Image node that also lets you edit a mask on the preview and pass it through | comfyui-edit-mask | https://github.com/shadowcz007/comfyui-edit-mask | 0.50 | partial — provides mask editing but not a combined Save/Preview node |
| 4 | An image-overlay node to composite/stamp one image over another with rotation and offset (e.g. watermark) | ComfyUI-Text_Image-Composite [WIP] | https://github.com/aiartvn/A2V_Multi_Image_Composite | 0.70 | yes — URL resolves to A2V Multi Image Composite: offset, rotation, scale, 5-layer blend confirmed |
| 5 | A node that splits an image into a grid of sub-images by rows and columns | ComfyUI-AutoSplitGridImage | https://github.com/stormcenter/ComfyUI-AutoSplitGridImage | 0.95 | yes — explicitly provides grid-based image splitting by rows and columns |
| 6 | A node to color-match / transfer color grading from a reference image to another image | ComfyUI Wavelet Color Fix | https://github.com/elyetis/Comfyui-ColorMatchNodes | 0.95 | yes — URL resolves to ColorMatchNodes: explicitly color-matches target against reference |
| 7 | Save an image while keeping the original input filename instead of adding a prefix and counter | Load Image With Filename | https://github.com/kymeraj/comfyui-load-image-with-filename | 0.75 | yes — outputs original filename; designed to wire into Save Image filename_prefix |
| 8 | A node to remove the background from anime images | Anime Character Segmentation node for comfyui | https://github.com/kwaroran/abg-comfyui | 0.95 | yes — explicitly anime background remover based on AGB model |
| 9 | ComfyUI nodes to run a box-prompt object segmenter / background removal (finegrain box-segmenter) | ComfyUI Qwen2.5-VL Object Detection Node | https://github.com/TTPlanetPig/Comfyui_Object_Detect_QWen_VL | 0.50 | partial — outputs bounding boxes but is a detector, not a box-prompt segmenter |
| 10 | Point a Load Image node at a folder and cycle through its images sequentially (e.g. video frames for ControlNet img2img) | ComfyUI Sequential Image Loader | https://github.com/bruefire/ComfyUI-SeqImageLoader | 0.85 | partial — loads frames in bulk from folder sequences but not one-at-a-time indexed cycling |

---

## Section B — retrieval / core  (ground-truth answer is a ComfyUI core / built-in node)

*Note: the router has no core-node awareness in v0.1, so all 6 of these returned a custom pack. A correct verdict here would be "no" if the recommended custom pack does not genuinely solve the ask, OR "yes/partial" if it coincidentally does.*

| # | Ask | Top-1 Pack | URL | Score | Verdict |
|---|-----|------------|-----|-------|---------|
| 11 | Convert what is drawn/painted on a canvas into a MASK output | ComfyUI-YCNodes_Toolkit | https://github.com/yichengup/ComfyUI-YCNodes_Toolkit | 0.80 | yes — Load_Image_Brush_Mask lets you draw masks directly on images without opening mask editor |
| 12 | Downscale/resize the output of a fixed-ratio upscale-model node to an arbitrary target size | Apex Artist - Image Resize | https://github.com/ApexArtist/comfyui-apex-artist | 0.80 | yes — professional image resizing with multiple algorithms and target dimensions |
| 13 | Turn a batch of images into a batch of masks | Masquerade Nodes | https://github.com/BadCafeCode/masquerade-nodes-comfyui | 0.50 | partial — comprehensive mask pack but image-to-mask batch conversion not confirmed explicit |
| 14 | A button on the Load Image node to open the mask editor directly | comfyui-edit-mask | https://github.com/shadowcz007/comfyui-edit-mask | 0.50 | partial — provides mask editing but not specifically a button on the Load Image node |
| 15 | Where to get the SD3 nodes (TripleCLIPLoader, ModelSamplingSD3, EmptySD3LatentImage) | ComfyUI-SD3-nodes | https://github.com/liusida/ComfyUI-SD3-nodes | 0.90 | partial — these nodes are in ComfyUI core; the custom pack also provides them but misdirects |
| 16 | Where the 'Apply ControlNet (Advanced)' node went / why it is missing | ComfyUI-Advanced-ControlNet | https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet | 0.95 | yes — this is exactly the pack that contains the Apply ControlNet (Advanced) node |

---

## Section C — authoring  (ground-truth: no existing pack; router should have routed to AUTHOR)

*Note: a verdict of "yes/partial" here means the retriever surfaced a real pack that the community missed — that is a genuine recall win even though the thread labeled this as authoring. A verdict of "no" confirms the router should have said AUTHOR.*

| # | Ask | Top-1 Pack | URL | Score | Verdict |
|---|-----|------------|-----|-------|---------|
| 17 | A general-purpose detect/crop-out a region and paste it back after editing (like a face-crop but for any object) | comfyui_facetools | https://github.com/dchatel/comfyui_facetools | 0.65 | partial — does crop/paste-back with rotation-aware detection but face-specific only |
| 18 | A node to refine the edges of a hand-painted/user-modified mask to better follow the object | ComfyUI_Segment_Mask | https://github.com/MarkoCa1/ComfyUI_Segment_Mask | 0.55 | partial — SAM-based re-segmentation could help but does not refine an existing user mask |
| 19 | Randomly select a LoRA but only from within a specific named folder | shinyakidoguchi301/LoRA Tag Loader for ComfyUI | https://github.com/shinyakidoguchi301/comfyui-lora-tag-loader | 0.50 | no — loads LoRA from directory but no random-from-named-folder capability confirmed |
| 20 | Pixel-perfect 90-degree rotation and mirroring of a rendered image (not latent, not filter-based) | ComfyUI PixelArt Detector | https://github.com/dimtoneff/ComfyUI-PixelArt-Detector | 0.40 | no — pixel art palette/scaling tool; does not provide rotation or mirror operations |
| 21 | Automatically crop out the empty space around text in an image (trim to the text bounding box) | MTB Nodes | https://github.com/melMass/comfy_mtb | 0.30 | no — has bounding box and crop nodes but no text-aware autocrop functionality |
| 22 | Invert an image without also inverting its alpha channel | ComfyUI Channel Ops | https://github.com/L33chKing/ComfyUI_Channel_Ops | 0.65 | partial — per-channel operations likely support RGB-only inversion but not explicitly confirmed |
| 23 | Apply a levels/curves adjustment (boost/reduce black and white points) to an image | ComfyUI-EsesImageEffectLevels | https://github.com/quasiblob/ComfyUI-EsesImageEffectLevels | 0.99 | yes — dedicated levels node with black/white point control; genuine recall win |
| 24 | Load images from a folder sequentially, indexing filenames so every image is processed even if the batch is stopped and restarted | ComfyUI-HoldCounter | https://github.com/mitch-avis/ComfyUI-HoldCounter | 0.65 | partial — provides persistent counter for batch indexing but does not load images itself |
| 25 | An outpainting node equivalent to the stablediffusion-infinity 'infinite canvas' project | ComfyUI-Infinity-Canvas | https://github.com/kreonxv/ComfyUI-Infinity-Canvas | 0.85 | yes — explicitly infinite canvas inpainting extension inspired by stablediffusion-infinity |
| 26 | A text-to-music node that runs on an 8GB GPU | ComfyUI InspireMusic Plugin | https://github.com/vanche1212/ComfyUI-InspireMusic | 0.90 | partial — text-to-music via InspireMusic confirmed; 8GB GPU fit not explicitly verified |
| 27 | A node to call Anthropic Claude (describe images / transform text) inside ComfyUI | ComfyUI and Claude | https://github.com/tkreuziger/comfyui-claude | 1.00 | yes — custom nodes using Claude for describing images and transforming texts; genuine recall win |

---

## tau_high FIRMING — 5-row live-README spot-check (2026-06-01)

Fresh-eyes Sonnet adjudicator, blind to the verdicts above, re-judged 5 rows against the **current** real READMEs to firm `tau_high`. Result: **tau_high = 0.95 firmed** (was provisional).

| # | Score | Sheet verdict | Live-README verdict | Note |
|---|-------|---------------|---------------------|------|
| 1  | 0.92 | no      | **no** (held)        | Praveen's tools: fixed 3-way split / select-last / skip-first only; no nth-INDEX extractor. Did NOT flip → first "no" stays at 0.92 → cut stays 0.95. |
| 4  | 0.70 | yes     | yes                  | A2V Multi Image Composite: offset + rotation + scale + blend confirmed. Below band; no effect on tau_high. |
| 15 | 0.90 | partial | **no** (worse)       | SD3-nodes is a *renamed wrapper* of core nodes (SD3 Load Checkpoint/CLIPs/Empty Latent), not TripleCLIPLoader etc. — a misdirect. Confirms 0.90 would admit a bad rec → do NOT drop below 0.95. |
| 23 | 0.99 | yes     | **yes** (re-verified)| Eses levels node: Black/Mid/White point sliders + output range. ≥0.95 band holds. |
| 27 | 1.00 | yes     | **yes** (re-verified)| comfyui-claude: DescribeImage + TransformText via Anthropic API. ≥0.95 band holds. |

**Conclusion:** the 0.92→0.95 question (Decision 2 residual #2) resolves to **keep 0.95**. Row 1 held "no"; row 15 flipping partial→no strengthens the precision cut; both in-band rows (23, 27) re-verified "yes" against live READMEs. `tau_high=0.95` is the wired value for the v0.1.1 pre-check. `tau_low=0.50` unchanged (not used by the thin pre-check, which only fires the HIGH band).
| 28 | Take a screen grab / render of the output of the Preview 3D and Animation node | ComfyUI-gaussian_preview | https://github.com/yichengup/ComfyUI-gaussian_preview | 0.85 | partial — previews/records Gaussian splatting; ask is about Preview 3D and Animation node specifically |
| 29 | Pipe a dynamic filename prefix into a Save Image node via a text/concatenate node | Load Image With Filename | https://github.com/kymeraj/comfyui-load-image-with-filename | 0.65 | partial — outputs source filename; ask is about building arbitrary dynamic prefix via concatenation |

---

## MIDDLE band — three-band re-read (2026-06-01)

Before wiring the full HIGH/MIDDLE/LOW router (v0.2), the trustworthy MIDDLE check is NOT a new
expensive eval — it is a **three-band re-read of the 29 rows above** through the router's lens
(`tau_high=0.95`, `tau_low=0.50`). This is the analog of the "tau_high FIRMING" section: it asks
"does the MIDDLE band, as designed, hold up against the adjudicated verdicts?" rather than
re-running the confounded automated metric.

Mapping every `(score, verdict)` to its band:

| Band | Rows (by #) | Count | Verdict breakdown |
|------|-------------|-------|-------------------|
| **HIGH** (≥0.95) | 2, 5, 6, 8, 16, 23, 27 | 7 | **7/7 yes** (already firmed — recommend-install precision 100% on the sample) |
| **MIDDLE** [0.50, 0.95) | 1, 3, 4, 7, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 22, 24, 25, 26, 28, 29 | 20 | 5 yes / **13 partial** / 2 no |
| **LOW** (<0.50) | 20 (0.40), 21 (0.30) | 2 | **2/2 no → author** |

**Decisive findings (the gate):**

1. **All 13 "partial" adjudications land in MIDDLE — every one.** A "partial" verdict is by
   definition "related / plausibly helps but not a clean match" = exactly MIDDLE's promise:
   *show the candidate AND offer to author; the human picks*. The partials are not a confound to
   be cleaned up; they are the MIDDLE band's native population.

2. **Zero "yes" rows fall below `tau_low`.** The one teeth-check that matters — is any clear
   existing match (a "yes") silently routed to AUTHOR, i.e. a discovery miss / duplicate-author? —
   **passes**: the only sub-0.50 rows are 20 and 21, both "no" (genuine author cases). No clean
   match is suppressed on this sample.

3. **MIDDLE is the structural resolution of the eval confound.** The confound that collapsed the
   *binary* install-precision metric (0.12) was the forced install-vs-author choice on rows that
   are genuinely neither (non-unique packs, unresolved-thread mislabels). Those exact rows — the
   5 mid-yes + 13 partial + 2 mid-no — **all land in MIDDLE**, the band that makes **no** binary
   claim and defers to the human. The three-band router does not need the confounded numbers
   resolved; it *routes around* the confound by construction. A "yes" landing in MIDDLE is not a
   failure (we showed the right pack as a candidate; the human installs it — just without HIGH's
   auto-recommend convenience); a "no" in MIDDLE is the band working (weak candidate shown
   alongside an author offer; human authors).

**`tau_low` placement (firming):** the n=29 data places 0.50 cleanly — 2/2 below it are author
cases; the partials worth showing sit at/above it. The asymmetry is deliberately **wide-MIDDLE**:
the costly error is a *too-high* tau_low that silently authors a duplicate of an existing node
(the Probe-2 dominant pain — discovery), not a *too-low* one that shows a weak candidate the human
ignores. So `tau_low=0.50` is **kept** (provisional on n=29, wide-by-design). Reversible lever if a
future spot-check shows sub-0.55 candidates are pure noise: nudge up; the data has not shown that.

**Conclusion:** the MIDDLE band is validated for wiring **without** a HIGH-grade firming pass,
because it makes no precision-critical claim — it is the human-adjudication band by construction,
and it is precisely what makes the known eval confound not matter.

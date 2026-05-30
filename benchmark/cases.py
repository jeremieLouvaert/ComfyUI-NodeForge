"""
Meta-validation benchmark: the cases.

Each case is a CONFIRMED SPEC (the natural-language spec + examples + invariants
a human would bless in Stage 1) paired with one or more CORRECT node classes and
one or more BROKEN node classes. The benchmark hands ONLY the spec to the test
generator (never the implementations), then runs the generated battery against
every implementation.

Correct nodes are lifted from probe/node_authoring_capability_probe.py.
Broken nodes are the realistic bugs from probe/negative_control.py (plus a
mosaic bug the negative control omitted, and an ambiguity case for triage).

Every node here is a FULL ComfyUI node class (INPUT_TYPES / RETURN_TYPES /
FUNCTION / CATEGORY) so the generated structural + contract checks have a real
class to inspect. Broken nodes are structurally valid; only their behavior is wrong.
"""
import math
import torch
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# helpers shared by some implementations
# ---------------------------------------------------------------------------
def _gaussian_blur(image, sigma):
    radius = max(1, int(math.ceil(3.0 * sigma)))
    xs = torch.arange(-radius, radius + 1, dtype=image.dtype, device=image.device)
    k = torch.exp(-(xs ** 2) / (2.0 * sigma * sigma))
    k = k / k.sum()
    b, h, w, c = image.shape
    x = image.permute(0, 3, 1, 2)
    kh = k.view(1, 1, -1, 1).repeat(c, 1, 1, 1)
    kv = k.view(1, 1, 1, -1).repeat(c, 1, 1, 1)
    x = F.pad(x, (0, 0, radius, radius), mode="reflect")
    x = F.conv2d(x, kh, groups=c)
    x = F.pad(x, (radius, radius, 0, 0), mode="reflect")
    x = F.conv2d(x, kv, groups=c)
    return x.permute(0, 2, 3, 1)


# ===========================================================================
# 1. CHANNEL SHUFFLE  (swap R and B)
# ===========================================================================
class ChannelShuffle:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image):
        return (image[..., [2, 1, 0]].contiguous(),)

class ChannelShuffle_RGswap:  # BUG: swaps R/G instead of R/B
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image):
        return (image[..., [1, 0, 2]].contiguous(),)


# ===========================================================================
# 2. LUMA KEY MASK  (Rec.709 luma threshold -> MASK [B,H,W])
# ===========================================================================
class LumaKeyMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, threshold):
        r, g, b = image[..., 0], image[..., 1], image[..., 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return ((luma > threshold).to(image.dtype),)

class LumaKeyMask_channeldim:  # BUG: returns [B,H,W,1] (classic MASK convention error)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, threshold):
        luma = image[..., 0]*0.2126 + image[..., 1]*0.7152 + image[..., 2]*0.0722
        return ((luma > threshold).to(image.dtype).unsqueeze(-1),)

class LumaKeyMask_avgcoeffs:  # BUG: naive channel average instead of Rec.709 (subtly wrong)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, threshold):
        luma = image.mean(dim=-1)
        return ((luma > threshold).to(image.dtype),)


# ===========================================================================
# 3. TILE MOSAIC  (each grid cell -> its own mean color)
# ===========================================================================
class TileMosaic:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "grid": ("INT", {"default": 8, "min": 1, "max": 64, "step": 1}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, grid):
        b, h, w, c = image.shape
        out = image.clone()
        ys = torch.linspace(0, h, grid + 1).round().long()
        xs = torch.linspace(0, w, grid + 1).round().long()
        for i in range(grid):
            for j in range(grid):
                y0, y1 = ys[i].item(), ys[i + 1].item()
                x0, x1 = xs[j].item(), xs[j + 1].item()
                if y1 <= y0 or x1 <= x0:
                    continue
                tile = image[:, y0:y1, x0:x1, :]
                out[:, y0:y1, x0:x1, :] = tile.mean(dim=(1, 2), keepdim=True)
        return (out,)

class TileMosaic_globalmean:  # BUG: uses one global mean for the whole image (not per-tile)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "grid": ("INT", {"default": 8, "min": 1, "max": 64, "step": 1}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, grid):
        mean = image.mean(dim=(1, 2), keepdim=True)
        return (mean.expand_as(image).contiguous(),)


# ===========================================================================
# 4. UNSHARP MASK  (sharpen via image + amount*(image - blur))
# ===========================================================================
class UnsharpMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "sigma": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 50.0, "step": 0.1}),
            "amount": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, sigma, amount):
        blurred = _gaussian_blur(image, sigma)
        return ((image + amount * (image - blurred)).clamp(0.0, 1.0),)

class UnsharpMask_returnsblur:  # BUG: returns the blur (de-sharpens) -- sign/logic error
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "sigma": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 50.0, "step": 0.1}),
            "amount": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, sigma, amount):
        return (_gaussian_blur(image, sigma).clamp(0.0, 1.0),)


# ===========================================================================
# 5. LUMA SPLIT  (lossless partition into shadows + highlights)
# ===========================================================================
class LumaSplit:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("shadows", "highlights")
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, threshold):
        luma = image[..., 0]*0.2126 + image[..., 1]*0.7152 + image[..., 2]*0.0722
        hi = (luma > threshold).to(image.dtype).unsqueeze(-1)
        return (image * (1.0 - hi), image * hi)

class LumaSplit_notlossless:  # BUG: shadows = full image (overlap) -> shadows+highlights != input
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("shadows", "highlights")
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image, threshold):
        luma = image[..., 0]*0.2126 + image[..., 1]*0.7152 + image[..., 2]*0.0722
        hi = (luma > threshold).to(image.dtype).unsqueeze(-1)
        return (image, image * hi)


# ===========================================================================
# 6. DOWNSCALE 2x  (AMBIGUITY case for triage: interpolation is unspecified)
#    Two CORRECT variants (bilinear, area) must BOTH pass; the broken one
#    (no resize) must be caught; a good battery must NOT over-assert a specific
#    interpolation and SHOULD flag interpolation as an open question.
# ===========================================================================
class Downscale2x_bilinear:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image):
        b, h, w, c = image.shape
        x = image.permute(0, 3, 1, 2)
        x = F.interpolate(x, size=(h // 2, w // 2), mode="bilinear", align_corners=False)
        return (x.permute(0, 2, 3, 1).clamp(0, 1).contiguous(),)

class Downscale2x_area:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image):
        b, h, w, c = image.shape
        x = image.permute(0, 3, 1, 2)
        x = F.interpolate(x, size=(h // 2, w // 2), mode="area")
        return (x.permute(0, 2, 3, 1).clamp(0, 1).contiguous(),)

class Downscale2x_noresize:  # BUG: returns the image unchanged (does not downscale)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "BENCH"
    def execute(self, image):
        return (image,)


# ===========================================================================
# THE CASE REGISTRY
# ===========================================================================
# spec: the confirmed Stage-1 spec handed to the generator (NO implementation).
# correct / broken: lists of (label, class).
# ambiguity: optional dict describing the triage expectation.

CASES = [
    {
        "id": "channel_shuffle",
        "spec": (
            "Operation: swap the red and blue channels of an RGB image, leaving green unchanged.\n"
            "Inputs: image (IMAGE).\n"
            "Output: one IMAGE, same shape as the input.\n"
            "Confirmed examples / invariants:\n"
            "  - Output channel 0 (red) equals the input's channel 2 (blue), everywhere.\n"
            "  - Output channel 2 (blue) equals the input's channel 0 (red), everywhere.\n"
            "  - Output channel 1 (green) equals the input's channel 1, everywhere.\n"
            "  - Shape and value range are preserved."
        ),
        "correct": [("ChannelShuffle", ChannelShuffle)],
        "broken": [("R/G swap (should be R/B)", ChannelShuffle_RGswap)],
    },
    {
        "id": "luma_key_mask",
        "spec": (
            "Operation: produce a binary MASK that is 1 where the image's luma exceeds a threshold, else 0.\n"
            "Inputs: image (IMAGE), threshold (FLOAT, 0..1, default 0.5).\n"
            "Output: one MASK.\n"
            "Luma uses the Rec.709 weights exactly: 0.2126*R + 0.7152*G + 0.0722*B.\n"
            "Convention: a MASK is shape [B,H,W] with NO channel dimension (unlike IMAGE which is [B,H,W,C]).\n"
            "Confirmed examples / invariants:\n"
            "  - Output shape is [B,H,W] (no channel dim).\n"
            "  - Every output value is exactly 0 or 1.\n"
            "  - A mid-grey pixel (0.5,0.5,0.5) at threshold 0.5 is below threshold (luma 0.5, not > 0.5) -> 0.\n"
            "  - A pure-green pixel (0,1,0) has luma 0.7152 (Rec.709), so at threshold 0.5 it is 1, "
            "but its naive channel-average would be 0.333 which is < 0.5. The Rec.709 weighting is mandatory."
        ),
        "correct": [("LumaKeyMask", LumaKeyMask)],
        "broken": [
            ("[B,H,W,1] channel-dim mask", LumaKeyMask_channeldim),
            ("channel-average not Rec.709", LumaKeyMask_avgcoeffs),
        ],
    },
    {
        "id": "tile_mosaic",
        "spec": (
            "Operation: pixelate an image into a grid x grid set of rectangular tiles; each tile becomes a "
            "flat block of that tile's own average color.\n"
            "Inputs: image (IMAGE), grid (INT, default 8).\n"
            "Output: one IMAGE, same shape as the input.\n"
            "Confirmed examples / invariants:\n"
            "  - Output shape and value range match the input.\n"
            "  - Within each tile, every pixel is identical (a flat block).\n"
            "  - Each tile's block color equals the AVERAGE of that SAME tile region in the INPUT (per-tile, "
            "not a single global average of the whole image).\n"
            "  - With grid=1 the whole image becomes one block equal to the global mean."
        ),
        "correct": [("TileMosaic", TileMosaic)],
        "broken": [("global mean (not per-tile)", TileMosaic_globalmean)],
    },
    {
        "id": "unsharp_mask",
        "spec": (
            "Operation: sharpen an image with an unsharp mask: out = image + amount * (image - gaussian_blur(image)).\n"
            "Inputs: image (IMAGE), sigma (FLOAT, default 2.0), amount (FLOAT, default 1.0).\n"
            "Output: one IMAGE, clamped to [0,1], same shape as input.\n"
            "Confirmed examples / invariants:\n"
            "  - amount = 0 returns the input unchanged (identity).\n"
            "  - A perfectly flat image (no high-frequency detail) is returned unchanged for any amount.\n"
            "  - On a textured image with amount > 0, the result has MORE local contrast / detail than the input "
            "(it sharpens; it does not blur or soften).\n"
            "  - Output stays within [0,1]."
        ),
        "correct": [("UnsharpMask", UnsharpMask)],
        "broken": [("returns the blur (softens)", UnsharpMask_returnsblur)],
    },
    {
        "id": "luma_split",
        "spec": (
            "Operation: split an image into a shadows image and a highlights image by a luma threshold. "
            "Pixels with luma > threshold go to highlights (and are black in shadows); the rest go to shadows "
            "(and are black in highlights).\n"
            "Inputs: image (IMAGE), threshold (FLOAT, 0..1, default 0.5).\n"
            "Output: two IMAGEs in order (shadows, highlights).\n"
            "Luma is Rec.709: 0.2126*R + 0.7152*G + 0.0722*B.\n"
            "Confirmed examples / invariants:\n"
            "  - Both outputs are [B,H,W,C] and stay in [0,1].\n"
            "  - The split is a LOSSLESS partition: shadows + highlights reconstructs the input exactly, "
            "for any input (every pixel belongs to exactly one side, the other side is black there).\n"
            "  - A pure-white image at threshold 0.5: shadows all black, highlights = the white image."
        ),
        "correct": [("LumaSplit", LumaSplit)],
        "broken": [("not lossless (shadows = full image)", LumaSplit_notlossless)],
    },
    {
        "id": "downscale_2x_AMBIGUOUS",
        "spec": (
            "Operation: downscale an image to half its height and half its width.\n"
            "Inputs: image (IMAGE).\n"
            "Output: one IMAGE at half resolution.\n"
            "Confirmed examples / invariants:\n"
            "  - Output is [B, H//2, W//2, C] (same batch and channel count, half spatial size).\n"
            "  - Output stays within [0,1].\n"
            "  - The output is a smaller version of the SAME image (not unrelated content).\n"
            "NOTE: the interpolation method (bilinear, area/average, nearest, ...) was NOT specified by the user. "
            "Do not assert a specific interpolation; any reasonable downscale should pass."
        ),
        "correct": [
            ("bilinear", Downscale2x_bilinear),
            ("area", Downscale2x_area),
        ],
        "broken": [("no resize (returns input)", Downscale2x_noresize)],
        "ambiguity": {
            "expect_open_questions": True,
            "topic_hint": ["interpolat", "resampl", "method", "filter", "antialias", "downscal"],
        },
    },
]

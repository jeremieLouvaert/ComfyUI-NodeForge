"""
Node-authoring capability probe (2026-05-29).

Question being answered: can a strong LLM, given ComfyUI's node-authoring
conventions, draft a CORRECT, non-trivial custom node? Correctness =
(a) valid ComfyUI class structure, (b) runs against real torch,
(c) produces the RIGHT output, checked by an INDEPENDENT numeric oracle.

Validity guard: the candidate nodes were drafted as the product agent would
(conventions in context). The oracle for each node computes the expected
result by a DIFFERENT code path / asserts hard invariants, so a node that
merely "looks right" but is semantically wrong FAILS. Failures are the signal.

NOT covered here (honest scope): full ComfyUI server registration + UI
rendering. This tests import, structure, runtime, and numeric correctness
against the real embedded-python torch. Real-server load is the follow-up.

--- CONVENTIONS GIVEN TO THE "AGENT" (the spec a real tool would inject) ---
- IMAGE tensor: torch.float32, shape [B, H, W, C], values in [0,1], C=3 (RGB).
- MASK tensor: torch.float32, shape [B, H, W], values in [0,1]. (NO channel dim.)
- A node is a class with: classmethod INPUT_TYPES() -> {"required": {...}, "optional": {...}},
  RETURN_TYPES (tuple of type strings), optional RETURN_NAMES, FUNCTION (method name str),
  CATEGORY (str). The FUNCTION returns a tuple matching RETURN_TYPES.
- Widget inputs: ("FLOAT", {"default":..,"min":..,"max":..,"step":..}), ("INT", {...}).
"""

import sys
import math
import torch
import torch.nn.functional as F

# ============================================================
# CANDIDATE NODES (drafted by the LLM "agent")
# ============================================================

class ChannelShuffleNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "PROBE"
    def execute(self, image):
        # swap R and B channels
        out = image[..., [2, 1, 0]].contiguous()
        return (out,)


class LumaKeyMaskNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "execute"
    CATEGORY = "PROBE"
    def execute(self, image, threshold):
        # Rec.709 luma, then binary mask. MASK has NO channel dim: [B,H,W].
        r, g, b = image[..., 0], image[..., 1], image[..., 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b  # [B,H,W]
        mask = (luma > threshold).to(image.dtype)
        return (mask,)


class TileMosaicNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "grid": ("INT", {"default": 8, "min": 1, "max": 64, "step": 1}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "PROBE"
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
                mean = tile.mean(dim=(1, 2), keepdim=True)  # [B,1,1,C]
                out[:, y0:y1, x0:x1, :] = mean
        return (out,)


class UnsharpMaskNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "sigma": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 50.0, "step": 0.1}),
            "amount": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "PROBE"
    def _gaussian_blur(self, image, sigma):
        # separable gaussian via two conv passes; reflection pad; per-channel groups
        radius = max(1, int(math.ceil(3.0 * sigma)))
        xs = torch.arange(-radius, radius + 1, dtype=image.dtype, device=image.device)
        k = torch.exp(-(xs ** 2) / (2.0 * sigma * sigma))
        k = k / k.sum()
        b, h, w, c = image.shape
        x = image.permute(0, 3, 1, 2)  # [B,C,H,W]
        kh = k.view(1, 1, -1, 1).repeat(c, 1, 1, 1)
        kv = k.view(1, 1, 1, -1).repeat(c, 1, 1, 1)
        x = F.pad(x, (0, 0, radius, radius), mode="reflect")
        x = F.conv2d(x, kh, groups=c)
        x = F.pad(x, (radius, radius, 0, 0), mode="reflect")
        x = F.conv2d(x, kv, groups=c)
        return x.permute(0, 2, 3, 1)  # back to [B,H,W,C]
    def execute(self, image, sigma, amount):
        blurred = self._gaussian_blur(image, sigma)
        out = image + amount * (image - blurred)
        out = out.clamp(0.0, 1.0)
        return (out,)


class LumaSplitNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("shadows", "highlights")
    FUNCTION = "execute"
    CATEGORY = "PROBE"
    def execute(self, image, threshold):
        r, g, b = image[..., 0], image[..., 1], image[..., 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b  # [B,H,W]
        hi_mask = (luma > threshold).to(image.dtype).unsqueeze(-1)  # [B,H,W,1]
        highlights = image * hi_mask
        shadows = image * (1.0 - hi_mask)
        return (shadows, highlights)


# ============================================================
# TEST HARNESS (independent oracles)
# ============================================================

def check_structure(cls):
    errs = []
    it = cls.INPUT_TYPES()
    if not isinstance(it, dict) or "required" not in it:
        errs.append("INPUT_TYPES missing 'required'")
    if not isinstance(getattr(cls, "RETURN_TYPES", None), tuple):
        errs.append("RETURN_TYPES not a tuple")
    fn = getattr(cls, "FUNCTION", None)
    if not isinstance(fn, str) or not callable(getattr(cls, fn, None)):
        errs.append("FUNCTION not a valid method name")
    if not getattr(cls, "CATEGORY", None):
        errs.append("missing CATEGORY")
    # widget configs sane
    for name, spec in it.get("required", {}).items():
        if spec[0] in ("FLOAT", "INT") and len(spec) > 1:
            cfg = spec[1]
            if "min" in cfg and "max" in cfg and cfg["min"] > cfg["max"]:
                errs.append(f"widget {name} min>max")
    return errs


def img(b=2, h=64, w=48):
    g = torch.Generator().manual_seed(7)
    return torch.rand(b, h, w, 3, generator=g, dtype=torch.float32)


def in_range(t):
    return bool(t.min() >= -1e-6 and t.max() <= 1 + 1e-6)


RESULTS = []
def record(name, passed, detail):
    RESULTS.append((name, passed, detail))


# --- 1. ChannelShuffle ---
def t_channel():
    cls = ChannelShuffleNode
    se = check_structure(cls)
    if se: return record("ChannelShuffle", False, "structure: " + "; ".join(se))
    x = img()
    (out,) = cls().execute(x)
    ok = (out.shape == x.shape
          and torch.allclose(out[..., 0], x[..., 2])
          and torch.allclose(out[..., 2], x[..., 0])
          and torch.allclose(out[..., 1], x[..., 1])
          and in_range(out))
    record("ChannelShuffle", ok, "R/B swapped, G kept, shape+range ok" if ok else "swap incorrect")

# --- 2. LumaKeyMask ---
def t_lumamask():
    cls = LumaKeyMaskNode
    se = check_structure(cls)
    if se: return record("LumaKeyMask", False, "structure: " + "; ".join(se))
    if cls.RETURN_TYPES != ("MASK",):
        return record("LumaKeyMask", False, f"RETURN_TYPES should be ('MASK',), got {cls.RETURN_TYPES}")
    x = img()
    thr = 0.5
    (m,) = cls().execute(x, thr)
    # INDEPENDENT oracle
    luma = x[..., 0]*0.2126 + x[..., 1]*0.7152 + x[..., 2]*0.0722
    exp = (luma > thr).float()
    shape_ok = (m.ndim == 3 and m.shape == x.shape[:3])   # MUST be [B,H,W]
    binary_ok = bool(torch.all((m == 0) | (m == 1)))
    match_ok = torch.allclose(m, exp)
    ok = shape_ok and binary_ok and match_ok
    detail = []
    if not shape_ok: detail.append(f"mask shape {tuple(m.shape)} not [B,H,W]")
    if not binary_ok: detail.append("mask not binary")
    if not match_ok: detail.append("mask != independent luma-threshold")
    record("LumaKeyMask", ok, "MASK [B,H,W], binary, matches Rec.709 oracle" if ok else "; ".join(detail))

# --- 3. TileMosaic ---
def t_mosaic():
    cls = TileMosaicNode
    se = check_structure(cls)
    if se: return record("TileMosaic", False, "structure: " + "; ".join(se))
    x = img(b=1, h=64, w=64)
    grid = 8
    (out,) = cls().execute(x, grid)
    # independent oracle: each 8x8 tile (64/8) must equal that tile's mean color
    tile = 64 // grid
    ok = out.shape == x.shape and in_range(out)
    if ok:
        for i in range(grid):
            for j in range(grid):
                reg = x[:, i*tile:(i+1)*tile, j*tile:(j+1)*tile, :]
                exp = reg.mean(dim=(1, 2), keepdim=True).expand_as(reg)
                if not torch.allclose(out[:, i*tile:(i+1)*tile, j*tile:(j+1)*tile, :], exp, atol=1e-5):
                    ok = False; break
            if not ok: break
    record("TileMosaic", ok, "every tile == its mean color" if ok else "tile means incorrect")

# --- 4. UnsharpMask ---
def t_unsharp():
    cls = UnsharpMaskNode
    se = check_structure(cls)
    if se: return record("UnsharpMask", False, "structure: " + "; ".join(se))
    inst = cls()
    # oracle A: amount=0 => identity
    x = img()
    (o0,) = inst.execute(x, 2.0, 0.0)
    id_ok = torch.allclose(o0, x, atol=1e-5)
    # oracle B: flat image invariance (high-freq is zero)
    flat = torch.full((1, 32, 32, 3), 0.4)
    (of,) = inst.execute(flat, 2.0, 1.5)
    flat_ok = torch.allclose(of, flat, atol=1e-4)
    # oracle C: actually sharpens -> local variance increases on textured input
    (os,) = inst.execute(x, 1.5, 1.0)
    var_ok = bool(os.std() > x.std() + 1e-4)
    range_ok = in_range(os)
    ok = id_ok and flat_ok and var_ok and range_ok
    detail = []
    if not id_ok: detail.append("amount=0 not identity")
    if not flat_ok: detail.append("flat image not preserved")
    if not var_ok: detail.append("does not increase detail (not sharpening)")
    if not range_ok: detail.append("output out of [0,1]")
    record("UnsharpMask", ok, "identity@0, flat-invariant, sharpens, clamped" if ok else "; ".join(detail))

# --- 5. LumaSplit ---
def t_split():
    cls = LumaSplitNode
    se = check_structure(cls)
    if se: return record("LumaSplit", False, "structure: " + "; ".join(se))
    if len(cls.RETURN_TYPES) != 2:
        return record("LumaSplit", False, f"expected 2 outputs, got {cls.RETURN_TYPES}")
    x = img()
    out = cls().execute(x, 0.5)
    if not (isinstance(out, tuple) and len(out) == 2):
        return record("LumaSplit", False, "did not return 2-tuple")
    sh, hi = out
    # independent oracle: partition is lossless (each pixel in exactly one bin)
    recon_ok = torch.allclose(sh + hi, x, atol=1e-6)
    shape_ok = sh.shape == x.shape and hi.shape == x.shape
    ok = recon_ok and shape_ok and in_range(sh) and in_range(hi)
    record("LumaSplit", ok, "shadows+highlights==original, shapes+range ok" if ok else "partition not lossless / shape wrong")


if __name__ == "__main__":
    for t in (t_channel, t_lumamask, t_mosaic, t_unsharp, t_split):
        try:
            t()
        except Exception as e:
            import traceback
            record(t.__name__, False, f"EXCEPTION: {type(e).__name__}: {e}")
            traceback.print_exc()
    print("\n" + "=" * 60)
    print("NODE-AUTHORING CAPABILITY PROBE RESULTS")
    print("=" * 60)
    npass = sum(1 for _, p, _ in RESULTS if p)
    for name, passed, detail in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name:16s} {detail}")
    print("-" * 60)
    print(f"{npass}/{len(RESULTS)} nodes correct")
    sys.exit(0 if npass == len(RESULTS) else 1)

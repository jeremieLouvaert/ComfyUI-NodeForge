"""
Synthetic input fixtures (child-side: imports torch).

A registry of deterministic generators that build tiny ComfyUI IMAGE tensors
([B,H,W,3], float32, [0,1]). Tiny defaults (2x2 / 8x8) so a human can reason
about a fixture and so the sandbox stays fast (self-verification-model.md 9.1:
"prefer tiny inputs a human can reason about over a 1024px photo").

Also renders a tensor to a PNG for the Stage-1 / Stage-5 thumbnails. Both the
generation and the rendering run INSIDE the sandbox child -- the parent has no
torch.
"""
import torch


def _seed(n):
    g = torch.Generator()
    g.manual_seed(int(n))
    return g


def solid(color=(0.5, 0.5, 0.5), h=2, w=2, b=1, **_):
    """A flat block of one color. color is an RGB triple in [0,1]."""
    c = torch.tensor(color, dtype=torch.float32).view(1, 1, 1, 3)
    return c.expand(b, h, w, 3).contiguous()


def gradient(axis="x", h=8, w=8, b=1, **_):
    """A 0..1 luminance ramp along x or y, replicated across channels."""
    if axis == "y":
        ramp = torch.linspace(0, 1, h).view(1, h, 1, 1)
    else:
        ramp = torch.linspace(0, 1, w).view(1, 1, w, 1)
    return ramp.expand(b, h, w, 3).contiguous()


def checkerboard(cell=2, h=8, w=8, b=1, lo=0.2, hi=0.8, **_):
    """A two-value checkerboard -- high-frequency signal for sharpen/resize ops."""
    yi = (torch.arange(h).view(h, 1) // cell)
    xi = (torch.arange(w).view(1, w) // cell)
    board = ((yi + xi) % 2).float() * (hi - lo) + lo     # [h,w]
    return board.view(1, h, w, 1).expand(b, h, w, 3).contiguous()


def seeded_texture(seed=7, h=8, w=8, b=1, **_):
    """Random mid-range texture; deterministic per seed."""
    return torch.rand(b, h, w, 3, generator=_seed(seed), dtype=torch.float32)


def known_pattern(name="rgb_corners", h=4, w=4, b=1, **_):
    """A small pattern with known structure for relation checks.

    rgb_corners: distinct primary-ish colors in the 4 corners, mid grey center."""
    img = torch.full((b, h, w, 3), 0.5)
    if name == "rgb_corners":
        img[:, 0, 0, :] = torch.tensor([1.0, 0.0, 0.0])
        img[:, 0, -1, :] = torch.tensor([0.0, 1.0, 0.0])
        img[:, -1, 0, :] = torch.tensor([0.0, 0.0, 1.0])
        img[:, -1, -1, :] = torch.tensor([0.0, 0.0, 0.0])
    return img.contiguous()


GENERATORS = {
    "solid": solid,
    "gradient": gradient,
    "checkerboard": checkerboard,
    "seeded_texture": seeded_texture,
    "known_pattern": known_pattern,
}


def build(input_spec_dict):
    """Build a tensor from an InputSpec dict {generator, params}."""
    gen = input_spec_dict["generator"]
    if gen not in GENERATORS:
        raise KeyError(f"unknown fixture generator {gen!r}; have {sorted(GENERATORS)}")
    return GENERATORS[gen](**input_spec_dict.get("params", {}))


def render_png(tensor, path, upscale_to=128):
    """Write a [B,H,W,C] or [B,H,W] tensor's first item to a PNG (nearest-upscaled
    so tiny fixtures are visible). Returns the path. Uses Pillow (present in the
    ComfyUI embedded python)."""
    from PIL import Image
    t = tensor.detach().float().clamp(0, 1).cpu()
    if t.ndim == 4:
        t = t[0]
    elif t.ndim == 3 and t.shape[0] in (1,) and t.shape[-1] not in (1, 3):
        t = t[0]
    if t.ndim == 2:                       # MASK [H,W] -> grayscale
        t = t.unsqueeze(-1).expand(-1, -1, 3)
    if t.shape[-1] == 1:
        t = t.expand(-1, -1, 3)
    arr = (t.numpy() * 255).round().astype("uint8")
    im = Image.fromarray(arr, mode="RGB")
    h, w = arr.shape[:2]
    if upscale_to and max(h, w) < upscale_to:
        scale = max(1, upscale_to // max(h, w))
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    im.save(path)
    return path

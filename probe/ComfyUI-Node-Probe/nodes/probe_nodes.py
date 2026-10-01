"""
ComfyUI-Node-Probe -- the 5 LLM-authored probe nodes (verified 2026-05-29),
packaged for a REAL-SERVER load test. Plus one self-contained test-image
generator so a live graph can run with no external image / no other packs.

CATEGORY: AKURATE/Probe. This pack is a throwaway capability probe, not a ship.
"""
import math
import torch
import torch.nn.functional as F


class ProbeTestImage:
    """Synthetic IMAGE source so the live-graph test needs no LoadImage."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "width": ("INT", {"default": 256, "min": 16, "max": 2048, "step": 8}),
            "height": ("INT", {"default": 256, "min": 16, "max": 2048, "step": 8}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Probe"
    def execute(self, width, height):
        ys = torch.linspace(0, 1, height).view(height, 1, 1)
        xs = torch.linspace(0, 1, width).view(1, width, 1)
        r = xs.expand(height, width, 1)
        g = ys.expand(height, width, 1)
        # add some high-frequency structure so UnsharpMask has detail to act on
        checker = (((torch.arange(width).view(1, width, 1) // 16) +
                    (torch.arange(height).view(height, 1, 1) // 16)) % 2).float()
        b = (0.5 * checker).expand(height, width, 1)
        img = torch.cat([r, g, b], dim=-1).clamp(0, 1).unsqueeze(0)  # [1,H,W,3]
        return (img.contiguous(),)


class ProbeChannelShuffle:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Probe"
    def execute(self, image):
        return (image[..., [2, 1, 0]].contiguous(),)


class ProbeLumaKeyMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Probe"
    def execute(self, image, threshold):
        r, g, b = image[..., 0], image[..., 1], image[..., 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return ((luma > threshold).to(image.dtype),)


class ProbeTileMosaic:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "grid": ("INT", {"default": 8, "min": 1, "max": 64, "step": 1}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Probe"
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
                mean = image[:, y0:y1, x0:x1, :].mean(dim=(1, 2), keepdim=True)
                out[:, y0:y1, x0:x1, :] = mean
        return (out,)


class ProbeUnsharpMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "sigma": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 50.0, "step": 0.1}),
            "amount": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Probe"
    def _gaussian_blur(self, image, sigma):
        radius = max(1, int(math.ceil(3.0 * sigma)))
        xs = torch.arange(-radius, radius + 1, dtype=image.dtype, device=image.device)
        k = torch.exp(-(xs ** 2) / (2.0 * sigma * sigma))
        k = k / k.sum()
        b, h, w, c = image.shape
        x = image.permute(0, 3, 1, 2)
        kh = k.view(1, 1, -1, 1).repeat(c, 1, 1, 1)
        kv = k.view(1, 1, 1, -1).repeat(c, 1, 1, 1)
        x = F.conv2d(F.pad(x, (0, 0, radius, radius), mode="reflect"), kh, groups=c)
        x = F.conv2d(F.pad(x, (radius, radius, 0, 0), mode="reflect"), kv, groups=c)
        return x.permute(0, 2, 3, 1)
    def execute(self, image, sigma, amount):
        blurred = self._gaussian_blur(image, sigma)
        return ((image + amount * (image - blurred)).clamp(0.0, 1.0),)


class ProbeLumaSplit:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("shadows", "highlights")
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Probe"
    def execute(self, image, threshold):
        r, g, b = image[..., 0], image[..., 1], image[..., 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        hi = (luma > threshold).to(image.dtype).unsqueeze(-1)
        return (image * (1.0 - hi), image * hi)


NODE_CLASS_MAPPINGS = {
    "ProbeTestImage": ProbeTestImage,
    "ProbeChannelShuffle": ProbeChannelShuffle,
    "ProbeLumaKeyMask": ProbeLumaKeyMask,
    "ProbeTileMosaic": ProbeTileMosaic,
    "ProbeUnsharpMask": ProbeUnsharpMask,
    "ProbeLumaSplit": ProbeLumaSplit,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ProbeTestImage": "Probe Test Image",
    "ProbeChannelShuffle": "Probe Channel Shuffle",
    "ProbeLumaKeyMask": "Probe Luma Key Mask",
    "ProbeTileMosaic": "Probe Tile Mosaic",
    "ProbeUnsharpMask": "Probe Unsharp Mask",
    "ProbeLumaSplit": "Probe Luma Split",
}

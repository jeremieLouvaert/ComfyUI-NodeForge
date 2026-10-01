"""
Negative control for the node-authoring probe.

Inject the EXACT bugs an LLM realistically makes, then run the same independent
oracles. Every broken node MUST be caught (oracle returns FAIL). If a broken
node slips through, the oracle is toothless and the 5/5 pass is meaningless.
"""
import math
import torch
import torch.nn.functional as F


def img(b=2, h=64, w=48):
    g = torch.Generator().manual_seed(7)
    return torch.rand(b, h, w, 3, generator=g, dtype=torch.float32)

def in_range(t):
    return bool(t.min() >= -1e-6 and t.max() <= 1 + 1e-6)


# ---- BROKEN NODES (realistic mistakes) ----

class BadChannelShuffle:  # swaps R/G instead of R/B
    def execute(self, image):
        return (image[..., [1, 0, 2]].contiguous(),)

class BadLumaMask_channeldim:  # returns [B,H,W,1] -- the classic MASK convention error
    def execute(self, image, threshold):
        luma = image[..., 0]*0.2126 + image[..., 1]*0.7152 + image[..., 2]*0.0722
        return ((luma > threshold).to(image.dtype).unsqueeze(-1),)

class BadLumaMask_wrongcoeffs:  # naive average instead of Rec.709 -- looks plausible, subtly wrong
    def execute(self, image, threshold):
        luma = image.mean(dim=-1)
        return ((luma > threshold).to(image.dtype),)

class BadUnsharp_returnsblur:  # returns the blur (de-sharpens) -- sign/logic error
    def _blur(self, image, sigma):
        radius = max(1, int(math.ceil(3.0*sigma)))
        xs = torch.arange(-radius, radius+1, dtype=image.dtype)
        k = torch.exp(-(xs**2)/(2*sigma*sigma))
        k = k/k.sum()
        b,h,w,c = image.shape
        x = image.permute(0,3,1,2)
        kh = k.view(1,1,-1,1).repeat(c,1,1,1)
        kv = k.view(1,1,1,-1).repeat(c,1,1,1)
        x = F.conv2d(F.pad(x,(0,0,radius,radius),mode="reflect"), kh, groups=c)
        x = F.conv2d(F.pad(x,(radius,radius,0,0),mode="reflect"), kv, groups=c)
        return x.permute(0,2,3,1)
    def execute(self, image, sigma, amount):
        return (self._blur(image, sigma).clamp(0,1),)

class BadLumaSplit_notlossless:  # highlights correct, shadows = full image (overlap) -> sh+hi != x
    def execute(self, image, threshold):
        luma = image[...,0]*0.2126 + image[...,1]*0.7152 + image[...,2]*0.0722
        hi = (luma > threshold).to(image.dtype).unsqueeze(-1)
        return (image, image*hi)  # shadows wrong


# ---- ORACLES (copied verbatim from the probe) ----

def oracle_channel(node):
    x = img()
    (out,) = node.execute(x)
    return (out.shape==x.shape and torch.allclose(out[...,0],x[...,2])
            and torch.allclose(out[...,2],x[...,0]) and torch.allclose(out[...,1],x[...,1]) and in_range(out))

def oracle_lumamask(node):
    x = img()
    thr=0.5
    (m,) = node.execute(x, thr)
    luma = x[...,0]*0.2126 + x[...,1]*0.7152 + x[...,2]*0.0722
    exp = (luma > thr).float()
    return (m.ndim==3 and m.shape==x.shape[:3] and bool(torch.all((m==0)|(m==1))) and torch.allclose(m,exp))

def oracle_unsharp(node):
    x = img()
    (o0,) = node.execute(x, 2.0, 0.0)
    id_ok = torch.allclose(o0,x,atol=1e-5)
    flat = torch.full((1,32,32,3),0.4)
    (of,) = node.execute(flat,2.0,1.5)
    flat_ok = torch.allclose(of,flat,atol=1e-4)
    (os_,) = node.execute(x,1.5,1.0)
    var_ok = bool(os_.std() > x.std()+1e-4)
    range_ok = in_range(os_)
    return id_ok and flat_ok and var_ok and range_ok

def oracle_split(node):
    x = img()
    out = node.execute(x,0.5)
    if not (isinstance(out,tuple) and len(out)==2):
        return False
    sh,hi = out
    return torch.allclose(sh+hi,x,atol=1e-6) and sh.shape==x.shape and hi.shape==x.shape and in_range(sh) and in_range(hi)


CASES = [
    ("BadChannelShuffle (R/G swap)",        oracle_channel,  BadChannelShuffle()),
    ("BadLumaMask (channel dim [B,H,W,1])", oracle_lumamask, BadLumaMask_channeldim()),
    ("BadLumaMask (avg not Rec.709)",       oracle_lumamask, BadLumaMask_wrongcoeffs()),
    ("BadUnsharp (returns blur)",           oracle_unsharp,  BadUnsharp_returnsblur()),
    ("BadLumaSplit (not lossless)",         oracle_split,    BadLumaSplit_notlossless()),
]

if __name__ == "__main__":
    print("="*60)
    print("NEGATIVE CONTROL: every broken node MUST be caught (FAIL)")
    print("="*60)
    all_caught = True
    for name, oracle, node in CASES:
        try:
            passed = oracle(node)
        except Exception as e:
            passed = False  # an exception is also "caught" (node is broken)
            print(f"  ({name}: raised {type(e).__name__})")
        caught = not passed
        all_caught = all_caught and caught
        print(f"[{'CAUGHT' if caught else 'SLIPPED THROUGH'}] {name}")
    print("-"*60)
    print("Oracles have teeth." if all_caught else "WARNING: a broken node passed -- oracle is toothless!")

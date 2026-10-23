"""Convert DUMPFRAME raw images to PNG + print stats.  usage: python framedump_to_png.py [dir]"""
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

D = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\madden20_online\modroot\framedump")
OUT = D / "png"
OUT.mkdir(exist_ok=True)


def f11(bits, mbits, ebits=5):
    m = bits & ((1 << mbits) - 1)
    e = (bits >> mbits) & ((1 << ebits) - 1)
    v = np.where(e == 0, m / (1 << mbits) * 2.0 ** -14,
                 (1 + m / (1 << mbits)) * 2.0 ** (e.astype(np.float64) - 15))
    return np.where(e == 31, 65504.0, v)


def decode(raw, w, h, fmt):
    if fmt in ("R8G8B8A8Unorm", "R8G8B8A8Srgb", "B8G8R8A8Unorm", "B8G8R8A8Srgb"):
        a = np.frombuffer(raw, np.uint8).reshape(h, w, 4).astype(np.float64) / 255
        return a[..., [2, 1, 0]] if fmt.startswith("B8") else a[..., :3]
    if fmt == "R8Unorm":
        a = np.frombuffer(raw, np.uint8).reshape(h, w).astype(np.float64) / 255
        return np.repeat(a[..., None], 3, 2)
    if fmt == "R16Unorm":
        a = np.frombuffer(raw, np.uint16).reshape(h, w).astype(np.float64) / 65535
        return np.repeat(a[..., None], 3, 2)
    if fmt == "R16Sfloat":
        a = np.frombuffer(raw, np.float16).reshape(h, w).astype(np.float64)
        return np.repeat(a[..., None], 3, 2)
    if fmt == "R32Sfloat":
        a = np.frombuffer(raw, np.float32).reshape(h, w).astype(np.float64)
        return np.repeat(a[..., None], 3, 2)
    if fmt == "R16G16B16A16Sfloat":
        return np.frombuffer(raw, np.float16).reshape(h, w, 4)[..., :3].astype(np.float64)
    if fmt == "B10G11R11UfloatPack32":
        v = np.frombuffer(raw, np.uint32).reshape(h, w).astype(np.int64)
        r = f11(v & 0x7FF, 6)
        g = f11((v >> 11) & 0x7FF, 6)
        b = f11((v >> 22) & 0x3FF, 5)
        return np.stack([r, g, b], -1)
    if fmt == "A2B10G10R10UnormPack32":
        v = np.frombuffer(raw, np.uint32).reshape(h, w).astype(np.int64)
        return np.stack([(v & 0x3FF), (v >> 10) & 0x3FF, (v >> 20) & 0x3FF], -1) / 1023.0
    return None


for p in sorted(D.glob("*.raw")):
    m = re.match(r"(\d+)_(\w+?)_id(\d+)_(\d+)x(\d+)_(\w+?)_([0-9a-f]+)\.raw", p.name)
    if not m:
        continue
    w, h, fmt = int(m.group(4)), int(m.group(5)), m.group(6)
    a = decode(p.read_bytes(), w, h, fmt)
    if a is None:
        print(f"{p.name}: unsupported fmt")
        continue
    a = np.nan_to_num(a, nan=0.0, posinf=65504.0)
    stats = f"min={a.min():.4g} max={a.max():.4g} mean={a.mean():.4g} nonzero={np.count_nonzero(a.sum(-1)) / (w * h):.1%}"
    mx = a.max()
    vis = a / mx if mx > 1.0 else a  # normalize HDR for viewing
    Image.fromarray((np.clip(vis, 0, 1) * 255).astype(np.uint8)).save(OUT / (p.stem + ".png"))
    print(f"{p.stem[:60]:60} {stats}")

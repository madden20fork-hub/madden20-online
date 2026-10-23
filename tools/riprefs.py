"""Find rip-relative references (lea/mov disp32) to target addresses in eboot code.
usage: python riprefs.py <target_hex> [...]   (eboot-relative)"""
import sys

import numpy as np

d = np.fromfile(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", dtype=np.uint8)[:0x73d4000]
n = len(d) - 4
disp = (d[:n].astype(np.int64) | (d[1:n + 1].astype(np.int64) << 8) |
        (d[2:n + 2].astype(np.int64) << 16) | (d[3:n + 3].astype(np.int64) << 24))
disp = np.where(disp >= 2**31, disp - 2**32, disp)
end = np.arange(n, dtype=np.int64) + 4 + disp   # insn end == disp end for lea/mov reg,[rip+d]
for t in (int(a, 16) for a in sys.argv[1:]):
    hits = np.nonzero(end == t)[0]
    print(f"{t:#x}: " + " ".join(hex(int(h) - 3) for h in hits[:20]))

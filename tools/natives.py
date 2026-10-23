"""natives.py <name_regex> [out_targets.txt] - resolve UI-script native registrations (lea rdx,[impl]; lea rcx,[class];
lea r8,[name]; ... jmp register) by the native's name string; print/write hooktrace targets."""
import re
import struct
import sys

import numpy as np

B = 0x800000000
raw = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()
d = np.frombuffer(raw[:0x73d4000], dtype=np.uint8)
pat = re.compile(sys.argv[1].encode())
names = {}
for m in re.finditer(rb"[A-Za-z_][A-Za-z0-9_]{3,}\x00", raw[0x6000000:0x6800000]):
    s = m.group()[:-1]
    if pat.fullmatch(s):
        names[0x6000000 + m.start()] = s.decode()
n = len(d) - 4
disp = (d[:n].astype(np.int64) | (d[1:n + 1].astype(np.int64) << 8) | (d[2:n + 2].astype(np.int64) << 16) |
        (d[3:n + 3].astype(np.int64) << 24))
disp = np.where(disp >= 2**31, disp - 2**32, disp)
end = np.arange(n, dtype=np.int64) + 4 + disp
out = []
for a, nm in sorted(names.items(), key=lambda kv: kv[1]):
    for h in np.nonzero(end == a)[0]:
        ins = int(h) - 3                       # lea r8,[rip+d] = 4c 8d 05 d32
        if raw[ins:ins + 3] != b"\x4c\x8d\x05":
            continue
        rdx = ins - 14                         # lea rdx,[rip+d] = 48 8d 15 d32 (7) then lea rcx (7)
        if raw[rdx:rdx + 3] != b"\x48\x8d\x15":
            continue
        impl = rdx + 7 + struct.unpack_from("<i", raw, rdx + 3)[0]
        out.append((nm, impl))
        print(f"{nm:40s} impl={impl:#x}  reg@{ins:#x}")
        break
if len(sys.argv) > 2:
    with open(sys.argv[2], "w") as f:
        for nm, impl in out:
            f.write(f"{nm} {impl:#x}\n")

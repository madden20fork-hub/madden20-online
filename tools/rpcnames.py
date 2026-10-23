"""Dump Blaze RPC name tables from the eboot dump: runs of pointers to identifier strings in the
data segment (index i -> command id i+1; empty-string entries are unused ids).
usage: python rpcnames.py [filter-substring]   prints table start, then id:name per entry."""
import re
import struct
import sys
from pathlib import Path

B = 0x800000000
d = Path(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin").read_bytes()
EMPTY = None


def cstr(a):
    o = a - B
    if not (0x6000000 <= o < 0x7400000):
        return None
    e = d.find(b"\0", o, o + 80)
    s = d[o:e]
    if s == b"":
        return ""
    return s.decode() if re.fullmatch(rb"[A-Za-z][A-Za-z0-9_]{2,60}", s) else None


tables = []
o = 0x7400000
end = 0x78e0000
while o < end:
    run = []
    p = o
    while p < end:
        q = struct.unpack_from("<Q", d, p)[0]
        s = cstr(q)
        if s is None:
            break
        run.append(s)
        p += 8
    named = [s for s in run if s]
    if len(named) >= 3 and any(c.islower() for c in named[0][:1]):
        tables.append((o, run))
        o = p
    else:
        o += 8

flt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
for start, run in tables:
    txt = " ".join(run)
    if flt and flt not in txt.lower():
        continue
    print(f"== table @{start:#x} ({len(run)} slots)")
    print("   " + "  ".join(f"{i + 1:#x}:{n}" for i, n in enumerate(run) if n))

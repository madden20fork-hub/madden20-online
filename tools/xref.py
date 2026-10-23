"""Find direct call/jmp rel32 xrefs and rip-relative references to a target in the eboot dump.
usage: python xref.py <target_hex> [--data]   (target eboot-relative or absolute)"""
import re
import sys
from pathlib import Path

BASE = 0x800000000
CODE_END = 0x73d4000
data = Path(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin").read_bytes()
t = int(sys.argv[1], 16)
if t >= BASE:
    t -= BASE
code = data[:CODE_END]
hits = []
# E8/E9 rel32
for m in re.finditer(rb"[\xe8\xe9]", code):
    o = m.start()
    if o + 5 > CODE_END:
        break
    rel = int.from_bytes(code[o + 1:o + 5], "little", signed=True)
    if o + 5 + rel == t:
        hits.append((o, "call" if code[o] == 0xE8 else "jmp"))
if "--data" in sys.argv:
    # rip-relative disp32 (lea/mov): any 4-byte window w where o+4+disp == t (approx, insn end varies 0..1)
    for o in range(0, CODE_END - 4):
        disp = int.from_bytes(code[o:o + 4], "little", signed=True)
        for tail in (0, 1):
            if o + 4 + tail + disp == t:
                hits.append((o - 3, f"rip-ref(+{tail})"))
    # absolute 8-byte pointers in data
    pat = (BASE + t).to_bytes(8, "little")
    for m in re.finditer(re.escape(pat), data):
        hits.append((m.start(), "abs-ptr"))
for o, k in sorted(hits):
    print(f"{o:#09x} {k}")
print(f"; {len(hits)} refs to {t:#x}")

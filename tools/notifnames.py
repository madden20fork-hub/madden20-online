"""Decode the GameManager notification-name switch @0x54b53b0 (`add esi,-3; cmp 0xe3; table @0x63cc258;
default rax = 0x664d24b`; each case = `lea rax,[rip+name]; ret`) -> prints id:name for named ids.
usage: python -I tools/notifnames.py [regex]"""
import re
import struct
import sys

import capstone

B = 0x800000000
d = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()
TABLE, BIAS, MAXI, DEFAULT = 0x63CC258, 3, 0xE3, 0x664D24B
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
pat = re.compile(sys.argv[1]) if len(sys.argv) > 1 else None


def cstr(off):
    e = d.find(b"\0", off)
    return d[off:e].decode(errors="replace")


for i in range(MAXI + 1):
    rel = struct.unpack_from("<i", d, TABLE + i * 4)[0]
    tgt = TABLE + rel
    ins = next(md.disasm(d[tgt:tgt + 16], B + tgt), None)
    name = "?"
    if ins and ins.mnemonic == "lea" and "rip" in ins.op_str:
        disp = int(ins.op_str.split("rip + ")[1].rstrip("]"), 16)
        off = tgt + ins.size + disp
        name = "(default)" if off == DEFAULT else cstr(off)
    elif ins and ins.mnemonic in ("ret",):
        name = "(default)"
    if name != "(default)" and (not pat or pat.search(name)):
        print(f"{i + BIAS:#x} {i + BIAS:3d} {name}")

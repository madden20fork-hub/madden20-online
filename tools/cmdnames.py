"""Resolve a Blaze GetCommandName-style switch: fn does `lea ecx,[rsi-BASE]; cmp eax,MAX; ja; ...
lea rdx,[rip+TABLE]; movsxd rax,[rdx+rcx*4]; add rax,rdx; jmp rax`, each case `lea rax,[rip+name]; ret`.
usage: python cmdnames.py <fn_hex>  -> prints cmdid:name"""
import re
import struct
import sys

import capstone

d = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)


def cstr(a):
    e = d.find(b"\0", a, a + 80)
    return d[a:e].decode("latin1")


fn = int(sys.argv[1], 16)
base = mx = table = None
default_target = None
for ins in md.disasm(d[fn:fn + 0x80], fn):
    m = re.match(r"(e|r)cx, \[rsi - (0x[0-9a-f]+)\]", ins.op_str)
    if ins.mnemonic == "lea" and m:
        base = int(m.group(2), 16)
    if ins.mnemonic == "lea" and re.match(r"ecx, \[rsi\]", ins.op_str):
        base = 0
    if ins.mnemonic == "cmp" and ins.op_str.startswith("eax, 0x"):
        mx = int(ins.op_str.split(", ")[1], 16)
    if ins.mnemonic == "ja":
        default_target = int(ins.op_str, 16)
    m = re.search(r"\[rip \+ (0x[0-9a-f]+)\]", ins.op_str)
    if ins.mnemonic == "lea" and m and base is not None and mx is not None:
        table = ins.address + ins.size + int(m.group(1), 16)
        break
print(f"; base={base:#x} max={mx:#x} table={table:#x}")


def case_name(t):
    for ins in md.disasm(d[t:t + 16], t):
        m = re.search(r"\[rip \+ (0x[0-9a-f]+)\]", ins.op_str)
        if ins.mnemonic == "lea" and m:
            return cstr(ins.address + ins.size + int(m.group(1), 16))
        break
    return None


for i in range(mx + 1):
    off = struct.unpack_from("<i", d, table + 4 * i)[0]
    t = table + off
    if t == default_target:
        continue
    n = case_name(t)
    if n:
        print(f"{base + i:#x}:{n}")

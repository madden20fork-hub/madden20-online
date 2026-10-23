"""Map Blaze component ids -> names: find `lea rax,[rip+"...Component"]; ret` getters and the
`mov eax, imm32; ret` / `mov ax, imm16; ret` id getters within +-0x80 bytes of them."""
import re

d = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()
code = d[:0x73d4000]
names = {}
for m in re.finditer(rb"\x48\x8d\x05(....)\xc3", code, re.S):
    o = m.start()
    tgt = o + 7 + int.from_bytes(m.group(1), "little", signed=True)
    if not (0x6000000 <= tgt < 0x7400000):
        continue
    e = d.find(b"\0", tgt, tgt + 80)
    s = d[tgt:e]
    if s.endswith(b"Component") and re.fullmatch(rb"[A-Za-z0-9_]+", s):
        names[o] = s.decode()
out = []
for o, n in names.items():
    win = code[o - 0x80:o + 0x80]
    ids = set()
    for mm in re.finditer(rb"\xb8(..)\x00\x00\xc3|\x66\xb8(..)\xc3", win, re.S):
        v = int.from_bytes(mm.group(1) or mm.group(2), "little")
        if 0 < v < 0x10000:
            ids.add(v)
    out.append((sorted(ids), n, o))
for ids, n, o in sorted(out, key=lambda x: (x[0] or [0])[0]):
    print(f"{','.join(hex(i) for i in ids) or '?':16} {n:40} getter@{o:#x}")

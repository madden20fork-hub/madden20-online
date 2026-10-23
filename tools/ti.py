"""ti.py <ti_va_hex>... - describe a TDF typeinfo from the eboot dump (kind 2 map, 3 list, 11 struct, 5 enum...).
Typeinfo layout guess (handoff §0): +0 ?, kind byte somewhere; container +0x28 key/elem ti, +0x30 value ti.
Prints raw qwords so the layout can be read, plus resolves pointers to strings / class descriptors."""
import struct
import sys

BASE = 0x800000000
data = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()


def q(va):
    o = va - BASE
    return struct.unpack_from("<Q", data, o)[0] if 0 <= o < len(data) - 8 else None


def cstr(va):
    o = va - BASE
    if not (0 <= o < len(data)):
        return None
    e = data.find(b"\0", o, o + 200)
    s = data[o:e]
    return s.decode() if s and all(32 <= c < 127 for c in s) else None


def name_of(p):
    """p points at a ti or class desc; try [p], [p+8] as strings."""
    for off in (0, 8, 0x10, 0x18):
        v = q(p + off)
        if v and cstr(v):
            return cstr(v)
    return None


def show(va, depth=0):
    pad = "  " * depth
    qs = [q(va + i * 8) for i in range(8)]
    print(pad + f"ti {va:#x}: " + " ".join(f"{x:#x}" if x is not None else "?" for x in qs))
    for i, x in enumerate(qs):
        if x and BASE <= x < BASE + len(data):
            s = cstr(x) or name_of(x)
            if s:
                print(pad + f"  +{i * 8:#x} -> {x:#x} {s}")
    if depth < 2:
        for off in (0x28, 0x30):
            x = q(va + off)
            if x and BASE + 0xa000000 <= x < BASE + 0xb000000:
                show(x, depth + 1)


for a in sys.argv[1:]:
    show(int(a, 16))
    print()

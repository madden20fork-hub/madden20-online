"""Print an EA TDF enum's name=value pairs. usage: python -I enumvals.py <EnumFullName> [...]
Enum descriptor: name* at +0x10/+0x18 after the entry table; entries are 0x20-byte nodes {name*, value, link, link} ending right before the descriptor."""
import re
import struct
import sys

B = 0x800000000
d = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()


def q(a):
    o = a - B
    return struct.unpack_from("<Q", d, o)[0] if 0 <= o < len(d) - 8 else 0


def cstr(a):
    o = a - B
    if not (0 <= o < len(d)):
        return None
    s = d[o:o + 100].split(b"\0")[0]
    return s.decode("latin1") if s and all(32 <= c < 127 for c in s) else None


for name in sys.argv[1:]:
    for m in re.finditer(re.escape(name.encode() + b"\0"), d):
        if d[m.start() - 1] != 0:
            continue
        for pm in re.finditer(re.escape(struct.pack("<Q", B + m.start())), d):
            o = pm.start()
            # entries precede the descriptor: walk back over 0x20-byte nodes whose +0x10 is an UPPER_CASE name
            vals = []
            a = o - 0x20
            while True:
                s = cstr(q(B + a))
                if not s or not re.fullmatch(r"[A-Z0-9_]+", s):
                    break
                vals.append((s, struct.unpack_from("<i", d, a + 8)[0]))
                a -= 0x20
            if vals:
                print(f"== {name} @{o:#x}")
                for s, v in sorted(vals, key=lambda x: x[1]):
                    print(f"  {v:6d} {s}")

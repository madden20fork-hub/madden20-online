"""Dump EA TDF reflection info from the Madden eboot dump.
usage: python tdfrefl.py <ClassName> [...]   e.g. Blaze::Util::PreAuthResponse  (short names ok)
Class descriptor: [+0] full name*, [+8] short name*, [+0x28] members*, [+0x30] member count.
Member record (0x30): [+0] typeinfo*, [+8] name*, [+0x20] u32 tag (packed, <<8), [+0x28] offset."""
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\madden20_online\server")
from tdf import tag_to_str  # noqa: E402

B = 0x800000000
d = Path(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin").read_bytes()


def q(a):
    o = a - B
    return struct.unpack_from("<Q", d, o)[0] if 0 <= o < len(d) - 8 else 0


def cstr(a):
    o = a - B
    if not (0 <= o < len(d)):
        return None
    e = d.find(b"\0", o, o + 160)
    s = d[o:e]
    return s.decode() if s and all(32 <= c < 127 for c in s) else None


def type_name(ti):
    """typeinfo -> best-effort name: scan its first qwords for a printable string pointer."""
    for k in range(0, 0x40, 8):
        s = cstr(q(ti + k))
        if s and len(s) > 2:
            return s
        # one level of indirection
        s = cstr(q(q(ti + k)))
        if s and len(s) > 2:
            return s
    return f"ti@{ti - B:#x}"


def find_class(name):
    full = name.encode() + b"\0"
    hits = []
    for m in re.finditer(re.escape(full), d):
        sa = m.start()
        if sa and d[sa - 1] != 0 and b"::" not in full:
            continue  # short name must start a string
        ptr = struct.pack("<Q", B + sa)
        for pm in re.finditer(re.escape(ptr), d):
            desc = pm.start() + B
            # full-name descriptor: [+0]=full name, [+0x28]=members, [+0x30]=count
            for base in (desc, desc - 8):
                cnt = q(base + 0x30)
                mem = q(base + 0x28)
                if 0 < cnt < 200 and B <= mem < B + len(d) and cstr(q(base)) and "::" in cstr(q(base)):
                    hits.append((base, cstr(q(base)), mem, cnt))
    return list(dict.fromkeys(hits))


def dump(name):
    for base, full, mem, cnt in find_class(name):
        print(f"== {full}  desc={base - B:#x} members={cnt}")
        for i in range(cnt):
            r = mem + i * 0x30
            ti, nm = q(r), cstr(q(r + 8))
            tagv = struct.unpack_from("<I", d, r + 0x20 - B)[0]
            tag = tag_to_str(bytes([(tagv >> 24) & 0xFF, (tagv >> 16) & 0xFF, (tagv >> 8) & 0xFF]))
            off = q(r + 0x28)
            print(f"  {tag:4} {nm:28} off={off:#06x} type={type_name(ti)}")


if __name__ == "__main__":
    for n in sys.argv[1:]:
        dump(n)

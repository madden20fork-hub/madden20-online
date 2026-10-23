"""Read live shadps4 process memory (read-only).
usage: python -I memread.py <addr> [len=0x100]          hexdump
       python -I memread.py --card <match_addr>         decode a Blaze::Mut::Card whose CIID sits at match_addr
Card layout (tdfrefl Blaze::Mut::Card): CIID +0x28, ID +0x30, DATA variable @+0x1a0 (object ptr +0x10),
STDT @+0x1c0 (object ptr +0x10). PlayerCardData: PLID +0xc, POS +0x61, OVR +0x9f, OVRM map @+0xa8."""
import ctypes
import struct
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from memscan import k32, open_proc, pid_of  # noqa: E402

h = open_proc(pid_of())


def rd(addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def q(a):
    b = rd(a, 8)
    return struct.unpack("<Q", b)[0] if b else None


def hexdump(addr, data):
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        print(f"  {addr + i:#014x} +{i:#05x}  {row.hex(' ')}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in row)}")


def card(match):
    base = match - 0x28
    raw = rd(base, 0x3a0)
    print(f"card @ {base:#x}  CIID={struct.unpack_from('<Q', raw, 0x28)[0]} ID={struct.unpack_from('<I', raw, 0x30)[0]}")
    for name, off in (("DATA", 0x1a0), ("STDT", 0x1c0)):
        print(f" {name} variable @+{off:#x}:", raw[off:off + 0x20].hex(" "))
        for k in range(0, 0x20, 8):
            p = struct.unpack_from("<Q", raw, off + k)[0]
            if p > 0x10000 and rd(p, 0xc0):
                o = rd(p, 0xc0)
                print(f"   ptr +{k:#x} -> {p:#x}: PLID={struct.unpack_from('<i', o, 0xc)[0]} POS={o[0x61]} "
                      f"OVR={o[0x9f]}  vtbl={struct.unpack_from('<Q', o, 0)[0]:#x}")
                hexdump(p + 0x90, o[0x90:0xc0])


if sys.argv[1] == "--card":
    card(int(sys.argv[2], 16))
else:
    a = int(sys.argv[1], 16)
    n = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x100
    hexdump(a, rd(a, n) or b"")

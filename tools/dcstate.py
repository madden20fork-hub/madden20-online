"""Live Draft Champions manager state (global @0x80abebb08): current DraftInfo + cached draft event.
usage: python -I dcstate.py"""
import ctypes
import struct
import sys

sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import k32, open_proc, pid_of  # noqa: E402

h = open_proc(pid_of())


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g))
    return b.raw[:g.value]


def q(a):
    return struct.unpack("<Q", rd(a, 8))[0]


mgr = q(0x80ABEBB08)
print("mgr", hex(mgr), "picked card", struct.unpack("<I", rd(mgr + 0x188, 4))[0], "picked pos", rd(mgr + 0x228, 1)[0])
di = q(mgr + 0x2A0)
if di:
    r = rd(di, 0x80)
    print("DraftInfo DFID", struct.unpack_from("<I", r, 0x10)[0], "INST", struct.unpack_from("<Q", r, 0x18)[0],
          "STAT", struct.unpack_from("<I", r, 0x20)[0], "RNUM", struct.unpack_from("<i", r, 0x3C)[0],
          "RTYP", struct.unpack_from("<i", r, 0x40)[0])
    b, e = struct.unpack_from("<QQ", r, 0x58)
    for i in range((e - b) // 8):
        o = q(b + 8 * i)
        c = rd(o + 0x10, 0x40)
        print("  opt", i, "CIID", struct.unpack_from("<Q", c, 0x28)[0], "ID", struct.unpack_from("<I", c, 0x30)[0])
ev = q(mgr + 0x288)
if ev:
    r = rd(ev, 0x3F0)
    print("event DFID", struct.unpack_from("<I", r, 0x14)[0], "TYPE", struct.unpack_from("<i", r, 0x64)[0],
          "TOTR", struct.unpack_from("<i", r, 0x98)[0], "STAT", struct.unpack_from("<i", r, 0x338)[0],
          "INST", struct.unpack_from("<Q", r, 0x2E8)[0])

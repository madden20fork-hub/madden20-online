"""Dump the game-settings singleton [0x80abebb08] fields the MUT game load reads (+0x98, +0x9a, +0xa8->+0x50)."""
import sys, ctypes, struct
sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import k32, open_proc, pid_of
h = open_proc(pid_of())
def rd(a, n):
    b = ctypes.create_string_buffer(n); g = ctypes.c_size_t()
    k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)); return b.raw[:g.value]
q = lambda a: struct.unpack("<Q", rd(a, 8))[0]
o = q(0x80abebb08)
print("obj", hex(o), "vt", hex(q(o) - 0x800000000) if o else None)
if o:
    blk = rd(o, 0x100)
    print("+98", blk[0x98], "+9a", blk[0x9a], "+a8", hex(struct.unpack_from("<Q", blk, 0xa8)[0]))
    p = struct.unpack_from("<Q", blk, 0xa8)[0]
    if p:
        print("  [+a8]+50 ->", hex(q(p + 0x50)))

"""live.py <python expr> - evaluate with Q(addr) (qword), D(addr) (dword), R(addr,n) bytes from the running shadps4."""
import ctypes
import struct
import sys

sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import k32, open_proc, pid_of  # noqa: E402

h = open_proc(pid_of())


def R(a, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(a), buf, n, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def Q(a):
    b = R(a, 8)
    return struct.unpack("<Q", b)[0] if b else None


def D(a):
    b = R(a, 4)
    return struct.unpack("<I", b)[0] if b else None


for e in sys.argv[1:]:
    v = eval(e)
    print(e, "=", [hex(x) if isinstance(x, int) else x for x in v] if isinstance(v, (list, tuple)) else
          (hex(v) if isinstance(v, int) else v))

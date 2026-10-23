"""memstr.py <regex> [lo_hex hi_hex] [max] - scan live shadps4 memory for printable strings matching regex."""
import ctypes
import re
import sys

sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import k32, open_proc, pid_of, regions  # noqa: E402

ALL = "--all" in sys.argv          # every address, not just the first per distinct string
sys.argv = [a for a in sys.argv if a != "--all"]
pat = re.compile(sys.argv[1].encode())
lo = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x1000000000
hi = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x1100000000
mx = int(sys.argv[4]) if len(sys.argv) > 4 else 300
h = open_proc(pid_of())
seen, n = set(), 0
for base, size in regions(h):
    if base + size < lo or base > hi:
        continue
    for off in range(0, size, 1 << 20):
        ln = min(1 << 20, size - off)
        buf = ctypes.create_string_buffer(ln)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), buf, ln, ctypes.byref(got)):
            continue
        for m in re.finditer(rb"[\x20-\x7e]{5,}", buf.raw[:got.value]):
            s = m.group()
            if pat.search(s) and (ALL or s not in seen):
                seen.add(s)
                print(hex(base + off + m.start()), s[:220].decode())
                n += 1
                if n >= mx:
                    sys.exit()

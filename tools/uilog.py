"""Pull Madden's in-memory UI script log lines (node_ut / logic_ut / madden.mut ... "::" messages) from the live
process. usage: python -I uilog.py [regex filter, default: draft|Draft|Pick|Slot|Notify]"""
import ctypes
import re
import sys

sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import k32, open_proc, pid_of, regions  # noqa: E402

flt = re.compile(sys.argv[1] if len(sys.argv) > 1 else r"draft|Draft|Pick|Slot|Notify")
h = open_proc(pid_of())


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g))
    return b.raw[:g.value]


pat = re.compile(rb"[ -~]{0,160}::[ -~]{4,400}")
seen = set()
for base, size in regions(h, 0x1000000000, 0x1100000000):
    if size > 0x8000000:
        continue
    for m in pat.finditer(rd(base, size)):
        s = m.group().decode("latin1")
        if s in seen or not flt.search(s) or "Blaze::" in s or "list<" in s or "map<" in s:
            continue
        seen.add(s)
        print(f"{base + m.start():#x} {s[:400]}")

"""strs.py <regex> [maxhits] - search printable ASCII strings in the Madden eboot dump, print VA + string."""
import re
import sys

BASE = 0x800000000
data = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()
pat = re.compile(sys.argv[1].encode(), re.I)
mx = int(sys.argv[2]) if len(sys.argv) > 2 else 200
n = 0
for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
    s = m.group()
    if pat.search(s):
        print(hex(BASE + m.start()), s.decode()[:200])
        n += 1
        if n >= mx:
            break

"""Triage a run_cdb crash: rip + faulting insn, registers that point at strings, disasm context,
last Blaze requests.  usage: python triage.py <tag>"""
import re
import subprocess
import sys
from pathlib import Path

tag = sys.argv[1]
txt = Path(rf"C:\madden20_online\runs\crash_{tag}.txt").read_text(errors="ignore")
i = txt.find("==== CRASH")
if i < 0:
    raise SystemExit("no crash block (game still running or exited cleanly)")
blk = txt[i:i + 4000]
regs = dict(re.findall(r"\b(r[a-z0-9]{1,2})=([0-9a-f]{16})", blk))
m = re.search(r"\n([0-9a-f]{8}`[0-9a-f]{8}) ([0-9a-f]+)\s+(.+)", blk)
print("fault:", m.group(1), m.group(3).strip() if m else "?")
B = 0x800000000
d = Path(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin").read_bytes()
for r, v in sorted(regs.items()):
    v = int(v, 16)
    if B <= v < B + len(d):
        o = v - B
        s = d[o:d.find(b"\0", o, o + 80)]
        if s and all(32 <= c < 127 for c in s) and len(s) >= 3:
            print(f"  {r} -> {s.decode()!r}")
rip = int(regs.get("rip", "0"), 16)
if B <= rip < B + 0x73d4000:
    out = subprocess.run([sys.executable, "-I", str(Path(__file__).parent / "dis.py"), hex(rip),
                          "--back", "0x50", "--len", "0x60"], capture_output=True, text=True).stdout
    print(out)
log = Path(r"C:\madden20_online\server\logs\blaze_server.log").read_text(errors="ignore").splitlines()
reqs = [l for l in log if " << " in l and "type=4" not in l][-8:]
print("last requests:\n  " + "\n  ".join(reqs))

"""Walk guest return addresses for named threads of the running shadps4.
usage: python guest_stack.py <ThreadName> [<ThreadName> ...]
Gets TIDs via thread_names.py logic, dumps 0x3000 bytes of stack from each thread's rsp with cdb,
keeps values inside eboot code whose preceding bytes are a call instruction."""
import os
import re
import subprocess
import sys
from pathlib import Path

BASE = 0x800000000
CODE_END = BASE + 0x73d4000
DUMP = Path(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin")
CDB = r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe"
TOOLS = Path(__file__).parent
data = DUMP.read_bytes()


def is_ret_addr(v):
    if not (BASE <= v < CODE_END):
        return False
    o = v - BASE
    if data[o - 5] == 0xE8:
        return True
    for k in (2, 3, 6, 7):  # ff /2 indirect call forms
        if data[o - k] == 0xFF and (data[o - k + 1] >> 3) & 7 == 2:
            return True
    return False


def call_target(v):
    o = v - BASE
    if data[o - 5] == 0xE8:
        return v + int.from_bytes(data[o - 4:o], "little", signed=True)
    return None


pid = subprocess.run("tasklist /FI \"IMAGENAME eq shadps4.exe\" /FO CSV /NH", capture_output=True,
                     text=True, shell=True).stdout.split('","')[1]
names = subprocess.run([sys.executable, "-I", str(TOOLS / "thread_names.py"), pid],
                       capture_output=True, text=True).stdout
tids = {}
for line in names.splitlines():
    t, _, n = line.partition("\t")
    tids.setdefault(n, []).append(t)
cmd = ""
for want in sys.argv[1:]:
    for t in tids.get(want, []):
        cmd += f".echo ==== {want} {t}; ~~[0x{t}]s; r rsp; dq @rsp L600; "
env = dict(os.environ)
out = subprocess.run([CDB, "-p", pid, "-pvr", "-c", cmd + "qd"], capture_output=True, text=True,
                     env=env).stdout
cur = None
gotn = {}
for line in (Path(r"C:\madden20_online\dump\got_names.txt").read_text().splitlines()):
    a, _, n = line.partition(" ")
    gotn[int(a, 16) + BASE] = n


def plt_name(t):
    if t is None:
        return ""
    o = t - BASE
    if 0 <= o < len(data) - 6 and data[o] == 0xFF and data[o + 1] == 0x25:
        slot = t + 6 + int.from_bytes(data[o + 2:o + 6], "little", signed=True)
        return " -> " + gotn.get(slot, f"GOT[{slot - BASE:#x}]")
    return f" (calls {t - BASE:#x})"


for line in out.splitlines():
    m = re.match(r"^==== (\S+) (\S+)", line)
    if m:
        print(f"\n### {m.group(1)} tid={m.group(2)}")
        continue
    m = re.match(r"^([0-9a-f]{8}`[0-9a-f]{8})\s+((?:[0-9a-f]{8}`[0-9a-f]{8}\s*)+)", line)
    if m:
        addr = int(m.group(1).replace("`", ""), 16)
        for i, v in enumerate(re.findall(r"[0-9a-f]{8}`[0-9a-f]{8}", m.group(2))):
            val = int(v.replace("`", ""), 16)
            if is_ret_addr(val):
                print(f"  [{addr + 8 * i:x}] ret {val - BASE:#09x}{plt_name(call_target(val))}")

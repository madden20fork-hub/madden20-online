"""drive.py <tag> <step>... - send key groups to the game and screenshot after each.
step syntax: 'keys:k1,ms,k2,...@wait_s=name'  e.g. 'right,600,right,800,n@25=hub'
Prints new http netres lines and new Blaze Mut requests seen during the run."""
import os
import subprocess
import sys
import time
from pathlib import Path

T = Path(r"C:\madden20_online\tools")
LOGS = Path(os.environ.get("MADDEN_LOGS", r"C:\madden20_online\server\logs"))  # override for a test install
HTTP = LOGS / "http_server.log"
BLZ = LOGS / "blaze_server.log"
tag = sys.argv[1]
hp, bp = HTTP.stat().st_size, BLZ.stat().st_size


def k(*a):
    subprocess.run([sys.executable, "-I", str(T / "keys_bg.py"), *a], capture_output=True)


for step in sys.argv[2:]:
    keys, _, rest = step.partition("@")
    wait, _, name = rest.partition("=")
    if keys:
        k(*keys.split(","))
    time.sleep(float(wait or 2))
    if name:
        out = subprocess.run([sys.executable, "-I", str(T / "shot.py"), f"{tag}_{name}"], capture_output=True,
                             text=True).stdout
        print(name, out.strip().split("->")[-1].strip(), flush=True)
        if "no shadps4 window" in out:
            sys.exit("game died")

h = HTTP.read_bytes()[hp:].decode(errors="ignore").splitlines()
net = [l for l in h if "netres" in l and "->" in l]
print(f"http: {len(h)} lines, netres results {len(net)}")
for l in net[:40]:
    print("  ", l)
b = BLZ.read_bytes()[bp:].decode(errors="ignore").splitlines()
for l in b:
    if (l[:2].isdigit() and ("<<" in l and "Mut." in l or "   " in l[8:12])) or "Traceback" in l or "Error" in l:
        print("  B", l[:200])

"""Field-render repro: (game already launched) boot -> menu -> Exhibition > Play Now > Resume, then screenshot
every 10 s while the game loads. Main menu on a fresh boot has X-Factor highlighted, Exhibition is 1 right.
usage: python -I field_repro.py <tag> [load_shots=8]   -> shots/<tag>_menu.png, <tag>_l1..N.png"""
import subprocess
import sys
import time
from pathlib import Path

T = Path(r"C:\madden20_online\tools")
tag = sys.argv[1]
n_shots = int(sys.argv[2]) if len(sys.argv) > 2 else 8


def k(*a):
    subprocess.run([sys.executable, "-I", str(T / "keys_bg.py"), *a], capture_output=True)


def shot(n):
    return subprocess.run([sys.executable, "-I", str(T / "shot.py"), n], capture_output=True, text=True).stdout


r = subprocess.run([sys.executable, "-I", str(T / "boot_to_menu.py"), tag], capture_output=True, text=True)
print(r.stdout.strip(), r.stderr.strip()[-300:])
if "alive" not in r.stdout:
    sys.exit(1)
k("right", "800", "n")      # Exhibition
time.sleep(8)
k("n")                      # Play Now
time.sleep(8)
k("n")                      # Resume
for i in range(1, n_shots + 1):
    time.sleep(10)
    out = shot(f"{tag}_l{i}")
    print(i, out.strip()[-60:])
    if "no shadps4 window" in out:
        sys.exit("game died")

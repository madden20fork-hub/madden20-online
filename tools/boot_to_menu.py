"""After launching the game: wait for the window, press Start, wait for the Blaze login (PostAuth), settle.
Prints the main-menu screenshot path. usage: python -I boot_to_menu.py <tag>"""
import subprocess
import sys
import time
from pathlib import Path

T = Path(r"C:\madden20_online\tools")
LOG = Path(r"C:\madden20_online\server\logs\blaze_server.log")
tag = sys.argv[1]


def k(*a):
    subprocess.run([sys.executable, "-I", str(T / "keys_bg.py"), *a], capture_output=True)


def shot(n):
    return subprocess.run([sys.executable, "-I", str(T / "shot.py"), n], capture_output=True, text=True).stdout


def alive():
    return "shadps4" in subprocess.run('tasklist /FI "IMAGENAME eq shadps4.exe" /NH', capture_output=True,
                                       text=True, shell=True).stdout


t0 = time.time()
while "rect=" not in shot(f"{tag}_wait"):
    time.sleep(3)
    if time.time() - t0 > 180:
        sys.exit("no window")
time.sleep(70)
if not alive():
    sys.exit("game died before Start")
pos = LOG.stat().st_size
k("n", "1500", "enter", "1500", "n")
t1 = time.time()
while b"PostAuth" not in LOG.read_bytes()[pos:]:
    time.sleep(2)
    if time.time() - t1 > 150 or not alive():
        sys.exit("no login / game died")
time.sleep(25)
print("menu:", "alive" if alive() else "DIED", shot(f"{tag}_menu").split("->")[-1].strip())

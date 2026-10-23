"""Reproducible perf scene: boot -> Start -> main menu -> Exhibition > Play Now > Custom Game (COLTS @ PATRIOTS)
-> Ready -> Advance to game, then sample the --show-fps overlay. Run the game first (run_madden.ps1/run_cdb.sh
with --show-fps). Input via keys_bg (no focus steal).
usage: python -I perf_playnow.py <tag>   -> shots/<tag>_menu_fps.png, <tag>_game_fps.png, runs/<tag>_perf.txt"""
import subprocess
import sys
import time
from pathlib import Path

T = Path(r"C:\madden20_online\tools")
BLAZE_LOG = Path(r"C:\madden20_online\server\logs\blaze_server.log")
tag = sys.argv[1]
out = open(rf"C:\madden20_online\runs\{tag}_perf.txt", "w")


def say(*a):
    msg = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(msg, flush=True)
    out.write(msg + "\n")
    out.flush()


def keys(*k):
    subprocess.run([sys.executable, "-I", str(T / "keys_bg.py"), *k], capture_output=True)


def shot(name):
    return subprocess.run([sys.executable, "-I", str(T / "shot.py"), name], capture_output=True, text=True).stdout


def fps(name, n):
    subprocess.run([sys.executable, "-I", str(T / "fps_strip.py"), name, str(n)], capture_output=True)
    say("fps strip", name)


def wait_window(limit=180):
    t0 = time.time()
    while time.time() - t0 < limit:
        if "rect=" in shot(f"{tag}_wait"):
            return True
        time.sleep(3)
    return False


def wait_login(since, limit=180):
    t0 = time.time()
    while time.time() - t0 < limit:
        with open(BLAZE_LOG, "rb") as f:
            f.seek(since)
            if b"PostAuth" in f.read():
                return True
        time.sleep(2)
    return False


say("waiting for window")
if not wait_window():
    say("no window")
    sys.exit(1)
time.sleep(70)                     # title screen + superbundle mounts
pos = BLAZE_LOG.stat().st_size
keys("n", "1500", "enter", "1500", "n")
say("start pressed; login:", wait_login(pos))
time.sleep(25)
fps(f"{tag}_menu", 4)
# the main menu remembers the last tile -> go fully left (X-Factor) first, then 2 right = Exhibition
keys("left", "300", "left", "300", "left", "300", "left", "300", "left", "500",
     "right", "500", "right", "800", "n", "1500", "n")      # Exhibition > Play Now
time.sleep(10)
keys("n")                                                     # Custom Game
time.sleep(10)
keys("n")                                                     # accept teams
time.sleep(6)
keys("n")                                                     # Ready
time.sleep(40)
shot(f"{tag}_settings")
keys("n")                                                     # Advance to game
say("advancing to game")
time.sleep(120)
fps(f"{tag}_game1", 6)
time.sleep(20)
fps(f"{tag}_game2", 6)
shot(f"{tag}_game_full")
say("done")

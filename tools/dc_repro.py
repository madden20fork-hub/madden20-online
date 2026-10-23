"""Draft Champions repro: (game already launched) boot -> menu -> Ultimate Team -> PLAY -> DRAFT -> Solo Draft ->
Start (free entry). Fresh boot: main menu has X-Factor highlighted; Ultimate Team is 2 right.
usage: python -I dc_repro.py <tag>   -> shots/<tag>_*.png"""
import os
import subprocess
import sys
import time
from pathlib import Path

T = Path(r"C:\madden20_online\tools")
tag = sys.argv[1]
SLOW = float(os.environ.get("DCSLOW", "1"))   # sleep multiplier (e.g. 3 under cdb)
_sleep = time.sleep
time.sleep = lambda s: _sleep(s * SLOW)


def k(*a):
    subprocess.run([sys.executable, "-I", str(T / "keys_bg.py"), *a], capture_output=True)


def shot(n):
    out = subprocess.run([sys.executable, "-I", str(T / "shot.py"), f"{tag}_{n}"], capture_output=True, text=True).stdout
    print(n, out.strip()[-50:], flush=True)
    if "no shadps4 window" in out:
        sys.exit("game died")


if not os.environ.get("DCSKIPBOOT"):           # DCSKIPBOOT=1: game is already at the main menu
    r = subprocess.run([sys.executable, "-I", str(T / "boot_to_menu.py"), tag], capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip()[-300:])
    if "alive" not in r.stdout:
        sys.exit(1)
k("right", "600", "right", "800", "n")          # Ultimate Team
time.sleep(25)
shot("hub")
k("u")                                           # PLAY tab
time.sleep(3)
k("down", "500", "down", "500", "down", "500", "right")   # DRAFT tile
time.sleep(2)
k("n")
time.sleep(12)
shot("landing")
k("right", "600", "down", "600", "n")           # Solo Draft
time.sleep(10)
shot("events")
k("n")                                           # Start Now (single free payment option)
time.sleep(12)


def fix_window():
    """Some boots open the window partly off-screen; put it at (0,0) 1600x940 without stealing focus."""
    import ctypes
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(h, buf, 256)
        if "Madden NFL 20" in buf.value:
            found.append(h)
        return True
    u32.EnumWindows(cb, 0)
    for h in found:
        u32.SetWindowPos(ctypes.c_void_p(h), None, 0, 0, 1600, 940, 0x14)


fix_window()
time.sleep(2)
shot("draft")
for i in range(1, int(sys.argv[2]) + 1 if len(sys.argv) > 2 else 1):
    k("n")                                       # take the highlighted option
    time.sleep(8)
    shot(f"pick{i}")

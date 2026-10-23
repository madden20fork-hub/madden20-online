"""Screenshot the shadPS4 game window via desktop grab (PrintWindow returns black on swapchains).
usage: python shot.py <name>   -> C:\\madden20_online\\shots\\<name>.png ; prints title + pixel stats.
Focuses the window first (AttachThreadInput trick), so it must be unoccluded after focus."""
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

from PIL import ImageGrab, ImageStat

user = ctypes.windll.user32
user.SetProcessDPIAware()
OUT = Path(r"C:\madden20_online\shots")
OUT.mkdir(parents=True, exist_ok=True)


def find_windows():
    import subprocess
    pids = set()
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq shadps4.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        pid = wt.DWORD()
        user.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and user.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(h, buf, 512)
            r = wt.RECT()
            user.GetWindowRect(h, ctypes.byref(r))
            found.append((h, buf.value, (r.left, r.top, r.right, r.bottom)))
        return True

    user.EnumWindows(cb, 0)
    return found


def focus(h):
    fg = user.GetForegroundWindow()
    tid = user.GetWindowThreadProcessId(h, None)
    ft = user.GetWindowThreadProcessId(fg, None)
    user.AttachThreadInput(ft, tid, True)
    user.ShowWindow(h, 9)
    user.BringWindowToTop(h)
    user.SetForegroundWindow(h)
    user.AttachThreadInput(ft, tid, False)
    time.sleep(0.5)


name = sys.argv[1] if len(sys.argv) > 1 else "shot"
wins = find_windows()
if not wins:
    raise SystemExit("no shadps4 window")
wins.sort(key=lambda w: (w[2][2] - w[2][0]) * (w[2][3] - w[2][1]), reverse=True)
h, title, rect = wins[0]
focus(h)
user.GetWindowRect(h, ctypes.byref(r := wt.RECT()))
rect = (r.left, r.top, r.right, r.bottom)
img = ImageGrab.grab(bbox=rect, all_screens=True)
p = OUT / f"{name}.png"
img.save(p)
st = ImageStat.Stat(img.convert("L"))
print(f"title={title!r} rect={rect} fg={user.GetForegroundWindow() == h} "
      f"extrema={img.convert('L').getextrema()} mean={st.mean[0]:.1f} -> {p}")

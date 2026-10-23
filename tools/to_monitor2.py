"""Move the shadPS4 game window onto the second (non-primary) monitor, without taking focus.
usage: python -I to_monitor2.py [--wait SECONDS]   (--wait: poll until the window exists, then move it,
and keep re-asserting for a few seconds because shadPS4/SDL repositions the window right after creating it)."""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

user = ctypes.windll.user32
user.SetProcessDPIAware()
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010


def second_monitor():
    mons = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    def cb(hm, _dc, r, _):
        mons.append((r.contents.left, r.contents.top, r.contents.right, r.contents.bottom))
        return True

    user.EnumDisplayMonitors(None, None, cb, 0)
    others = [m for m in mons if not (m[0] == 0 and m[1] == 0)]
    return others[0] if others else None


def game_window():
    out = subprocess.run('tasklist /FI "IMAGENAME eq shadps4.exe" /FO CSV /NH', capture_output=True,
                         text=True, shell=True).stdout
    if "shadps4" not in out:
        return None
    pid = int(out.split('","')[1])
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        p = wt.DWORD()
        user.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(h, buf, 256)
            if buf.value.startswith("shadPS4"):
                found.append(h)
        return True

    user.EnumWindows(cb, 0)
    return found[0] if found else None


def move(h, mon):
    r = wt.RECT()
    user.GetWindowRect(h, ctypes.byref(r))
    mw, mh = mon[2] - mon[0], mon[3] - mon[1]
    w, hgt = min(r.right - r.left, mw), min(r.bottom - r.top, mh)
    x, y = mon[0] + (mw - w) // 2, mon[1] + (mh - hgt) // 2
    if (r.left, r.top) != (x, y):
        user.SetWindowPos(h, None, x, y, w, hgt, SWP_NOZORDER | SWP_NOACTIVATE)
        return True
    return False


def give_focus_back(prev, game):
    """shadPS4/SDL takes the foreground when its window is created; hand it back to the owner's window."""
    if not prev or prev == game or not user.IsWindow(prev) or user.GetForegroundWindow() != game:
        return False
    gt = user.GetWindowThreadProcessId(game, None)
    pt = user.GetWindowThreadProcessId(prev, None)
    user.AttachThreadInput(gt, pt, True)
    user.SetForegroundWindow(prev)
    user.AttachThreadInput(gt, pt, False)
    return user.GetForegroundWindow() == prev


def main():
    wait = float(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 0
    prev_fg = user.GetForegroundWindow()   # taken BEFORE the game window exists
    mon = second_monitor()
    if not mon:
        raise SystemExit("no second monitor")
    t0 = time.time()
    h = game_window()
    while not h and time.time() - t0 < wait:
        time.sleep(0.5)
        h = game_window()
    if not h:
        raise SystemExit("no shadPS4 window")
    # re-assert for ~20 s: the window gets resized/repositioned during boot
    end = time.time() + (20 if wait else 0)
    moved = move(h, mon)
    restored = give_focus_back(prev_fg, h)
    while time.time() < end:
        time.sleep(0.5)
        moved |= move(h, mon)
        restored |= give_focus_back(prev_fg, h)
    print("focus handed back" if restored else "focus untouched")
    r = wt.RECT()
    user.GetWindowRect(h, ctypes.byref(r))
    print("monitor2", mon, "window rect", (r.left, r.top, r.right, r.bottom), "moved" if moved else "already there")


main()

"""Move the shadPS4 window so its top-left is at (x, y) (default 0,0) without resizing or activating it.
usage: python -I win_origin.py [x y]   (for single-monitor setups where to_monitor2.py has no target)"""
import ctypes
import ctypes.wintypes as wt
import sys

user = ctypes.windll.user32
user.SetProcessDPIAware()
x, y = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, 0)
w, hgt = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (0, 0)   # optional size; 0 = keep
found = []


@ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
def cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user.GetWindowTextW(hwnd, buf, 256)
    if buf.value.startswith("shadPS4") and "CUSA" in buf.value and user.IsWindowVisible(hwnd):
        found.append(hwnd)
    return True


user.EnumWindows(cb, 0)
if not found:
    sys.exit("no window")
flags = 0x0004 | 0x0010 | (0 if w else 0x0001)                                  # NOZORDER|NOACTIVATE[|NOSIZE]
print(user.SetWindowPos(found[0], None, x, y, w, hgt, flags))

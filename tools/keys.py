"""Focus the shadPS4 window and send keys via SendInput scancodes.
usage: python keys.py <key>[:hold_ms] ...   keys: n enter f10 space up down left right esc b c v
       a bare number = sleep that many ms."""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

user = ctypes.windll.user32
SC = {"n": 0x31, "enter": 0x1C, "f10": 0x44, "space": 0x39, "up": 0xC8, "down": 0xD0,
      "left": 0xCB, "right": 0xCD, "esc": 0x01, "b": 0x30, "c": 0x2E, "v": 0x2F, "f9": 0x43}
EXT = {"up", "down", "left", "right"}


class KI(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class INP(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def send(sc, up, ext):
    flags = 0x0008 | (0x0002 if up else 0) | (0x0001 if ext else 0)
    i = INP(type=1)
    i.ki = KI(0, sc & 0xFF, flags, 0, 0)
    user.SendInput(1, ctypes.byref(i), ctypes.sizeof(INP))


def focus():
    out = subprocess.run("tasklist /FI \"IMAGENAME eq shadps4.exe\" /FO CSV /NH", capture_output=True,
                         text=True, shell=True).stdout
    pid = int(out.split('","')[1])
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        p = wt.DWORD()
        user.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user.IsWindowVisible(h):
            found.append(h)
        return True

    user.EnumWindows(cb, 0)
    h = found[0]
    fg = user.GetForegroundWindow()
    tid = user.GetWindowThreadProcessId(h, None)
    ft = user.GetWindowThreadProcessId(fg, None)
    user.AttachThreadInput(ft, tid, True)
    user.ShowWindow(h, 9)
    user.BringWindowToTop(h)
    user.SetForegroundWindow(h)
    user.AttachThreadInput(ft, tid, False)
    time.sleep(0.4)
    return h


def restore(h):
    fg = user.GetForegroundWindow()
    ft = user.GetWindowThreadProcessId(fg, None)
    tid = user.GetWindowThreadProcessId(h, None)
    user.AttachThreadInput(ft, tid, True)
    user.SetForegroundWindow(h)
    user.AttachThreadInput(ft, tid, False)


# the owner works on the main monitor while the game runs on monitor 2: remember his window and hand
# focus back as soon as the keys are sent. Every key re-checks focus so nothing types into his window.
prev_fg = user.GetForegroundWindow()
game = focus()
ok = user.GetForegroundWindow() == game
print("fg=", ok)
try:
    if not ok:
        raise SystemExit("game window not focused - refusing to send keys")
    for arg in sys.argv[1:]:
        if arg.isdigit():
            time.sleep(int(arg) / 1000)
            continue
        if user.GetForegroundWindow() != game:
            raise SystemExit("game window lost focus - stopped sending keys")
        k, _, hold = arg.partition(":")
        send(SC[k], False, k in EXT)
        time.sleep((int(hold) if hold else 120) / 1000)
        send(SC[k], True, k in EXT)
        time.sleep(0.15)
        print("sent", k)
finally:
    if prev_fg and prev_fg != game:
        restore(prev_fg)
        print("focus restored")

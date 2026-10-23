"""Send keys to the shadPS4 window WITHOUT focusing it (PostMessage WM_KEYDOWN/WM_KEYUP), so the owner can
keep working on the main monitor while the game runs on monitor 2.
usage: python -I keys_bg.py <key>[:hold_ms] ...   keys: n enter f10 f9 space up down left right esc b c v
       a bare number = sleep that many ms."""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

user = ctypes.windll.user32
user.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
# name: (virtual key, scancode, extended)
KEYS = {"n": (0x4E, 0x31, 0), "enter": (0x0D, 0x1C, 0), "f10": (0x79, 0x44, 0), "f9": (0x78, 0x43, 0),
        "space": (0x20, 0x39, 0), "up": (0x26, 0x48, 1), "down": (0x28, 0x50, 1), "left": (0x25, 0x4B, 1),
        "right": (0x27, 0x4D, 1), "esc": (0x1B, 0x01, 0), "b": (0x42, 0x30, 0), "c": (0x43, 0x2E, 0),
        "v": (0x56, 0x2F, 0),
        # shadPS4 default.ini: q=L1 u=R1 e=L2 o=R2 x=L3 m=R3, wasd = left stick, ijkl = right stick
        "q": (0x51, 0x10, 0), "u": (0x55, 0x16, 0), "e": (0x45, 0x12, 0), "o": (0x4F, 0x18, 0),
        "x": (0x58, 0x2D, 0), "m": (0x4D, 0x32, 0), "w": (0x57, 0x11, 0), "a": (0x41, 0x1E, 0),
        "s": (0x53, 0x1F, 0), "d": (0x44, 0x20, 0), "i": (0x49, 0x17, 0), "j": (0x4A, 0x24, 0),
        "k": (0x4B, 0x25, 0), "l": (0x4C, 0x26, 0),
        # numpad = SDL "special" keys: PostMessage delivers them to an UNFOCUSED window (letter keys need focus).
        # default.ini also binds cross=kp2 circle=kp6 triangle=kp8 square=kp4. scancodes are the arrow bases, ext=0.
        "kp2": (0x62, 0x50, 0), "kp6": (0x66, 0x4D, 0), "kp8": (0x68, 0x48, 0), "kp4": (0x64, 0x4B, 0)}
# PS4 names -> keys (cross=n circle=b triangle=c square=v options=enter touchpad=space)
ALIAS = {"cross": "n", "circle": "b", "triangle": "c", "square": "v", "options": "enter", "l1": "q", "r1": "u",
         "l2": "e", "r2": "o", "l3": "x", "r3": "m"}


def game_window():
    out = subprocess.run('tasklist /FI "IMAGENAME eq shadps4.exe" /FO CSV /NH', capture_output=True,
                         text=True, shell=True).stdout
    if "shadps4" not in out:
        raise SystemExit("shadps4 not running")
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
    if not found:
        raise SystemExit("no shadPS4 window")
    return found[0]


def post(h, key, up):
    vk, sc, ext = KEYS[key]
    lp = 1 | (sc << 16) | (ext << 24)
    if up:
        lp |= 0xC0000000
    user.PostMessageW(h, WM_KEYUP if up else WM_KEYDOWN, vk, lp)


h = game_window()
for arg in sys.argv[1:]:
    if arg.isdigit():
        time.sleep(int(arg) / 1000)
        continue
    k, _, hold = arg.partition(":")
    k = ALIAS.get(k, k)
    post(h, k, False)
    time.sleep((int(hold) if hold else 120) / 1000)
    post(h, k, True)
    time.sleep(0.15)
    print("posted", k)

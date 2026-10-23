"""res_poke.py [scale] - Madden 20 PS4 Pro render resolution cap.
Waits for shadps4, polls the GameRenderSettings pointer global [0x807a6a9a0] (set by the settings getter @0x84d5ff)
and, as soon as it is non-null, writes `scale` (default 2560/3840 = 1440p of the Pro 4K output) into
ResolutionScale (+0x68), ForwardMinResolutionScale (+0x98) and ForwardMaxResolutionScale (+0x54).
The game reads these once while creating its render targets, so this must win the race at boot.
Field offsets come from the GameRenderSettings type info (field table @0x80aaf1790, 10-17)."""
import ctypes
import struct
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = ctypes.c_void_p
k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 2560 / 3840
GLOBAL = 0x807a6a9a0
FIELDS = (0x68, 0x98, 0x54)


def pid():
    out = subprocess.run('tasklist /FI "IMAGENAME eq shadps4.exe" /FO CSV /NH', capture_output=True, text=True,
                         shell=True).stdout
    return int(out.split('","')[1]) if '","' in out else None


def rd(h, a, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(a), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok and got.value == n else None


t0 = time.time()
p = None
while p is None and time.time() - t0 < 120:
    p = pid()
    time.sleep(0.05)
if p is None:
    sys.exit("no shadps4")
h = k32.OpenProcess(0x1F0FFF, False, p)
while time.time() - t0 < 300:
    b = rd(h, GLOBAL, 8)
    if b is None:                       # eboot not mapped yet, or a stale pid from a just-killed run
        q = pid()
        if q and q != p:
            p, h = q, k32.OpenProcess(0x1F0FFF, False, q)
        time.sleep(0.01)
        continue
    inst = struct.unpack("<Q", b)[0]
    if inst:
        got = ctypes.c_size_t()
        for off in FIELDS:
            k32.WriteProcessMemory(h, ctypes.c_void_p(inst + off), struct.pack("<f", SCALE), 4, ctypes.byref(got))
        vals = [struct.unpack("<f", rd(h, inst + o, 4))[0] for o in FIELDS]
        print(f"poked GameRenderSettings @{inst:#x} after {time.time() - t0:.1f}s: {vals}", flush=True)
        # keep it pinned for a while in case defaults are re-applied during boot
        end = time.time() + 60
        while time.time() < end:
            for off in FIELDS:
                k32.WriteProcessMemory(h, ctypes.c_void_p(inst + off), struct.pack("<f", SCALE), 4,
                                       ctypes.byref(got))
            time.sleep(0.01)
        sys.exit(0)
    time.sleep(0.001)
sys.exit("settings global never set")

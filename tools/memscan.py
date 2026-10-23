"""Scan the live shadps4 process memory for byte patterns (read-only, ReadProcessMemory).
usage: python -I memscan.py <hex-or-ascii pattern> [...] [--max N] [--ctx BYTES] [--min-region 0x...]
  patterns starting with 'hex:' are hex bytes, otherwise ASCII. Prints host address + context hexdump."""
import ctypes
import ctypes.wintypes as wt
import re
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


def pid_of(name="shadps4.exe"):
    out = subprocess.run(f'tasklist /FI "IMAGENAME eq {name}" /FO CSV /NH', capture_output=True, text=True,
                         shell=True).stdout
    return int(out.split('","')[1])


def open_proc(pid):
    return k32.OpenProcess(0x0410, False, pid)  # QUERY_INFORMATION | VM_READ


def regions(h, lo=0, hi=0x7FFFFFFFFFFF):
    a = lo
    m = MBI()
    while a < hi and k32.VirtualQueryEx(h, ctypes.c_void_p(a), ctypes.byref(m), ctypes.sizeof(m)):
        base, size = m.BaseAddress or 0, m.RegionSize
        if m.State == 0x1000 and m.Protect & 0xEE and not m.Protect & 0x100:  # committed, readable, no guard
            yield base, size
        a = base + size


def read(h, addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return b""
    return buf.raw[:got.value]


def scan(h, pats, max_hits=20, chunk=64 << 20):
    hits = {p: [] for p in pats}
    for base, size in regions(h):
        off = 0
        while off < size:
            n = min(chunk, size - off)
            data = read(h, base + off, n + 64)
            for p in pats:
                if len(hits[p]) >= max_hits:
                    continue
                for m in re.finditer(re.escape(p), data[:n + len(p) - 1]):
                    hits[p].append(base + off + m.start())
                    if len(hits[p]) >= max_hits:
                        break
            off += n
        if all(len(v) >= max_hits for v in hits.values()):
            break
    return hits


if __name__ == "__main__":
    args = sys.argv[1:]
    mx = int(args[args.index("--max") + 1]) if "--max" in args else 20
    ctx = int(args[args.index("--ctx") + 1]) if "--ctx" in args else 64
    pats = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
    pats = [bytes.fromhex(p[4:]) if p.startswith("hex:") else p.encode() for p in pats]
    h = open_proc(pid_of())
    res = scan(h, pats, mx)
    for p, addrs in res.items():
        print(f"== {p!r}: {len(addrs)} hits")
        for a in addrs:
            d = read(h, a - ctx // 2, ctx)
            print(f"  {a:#x}  {d.hex()}")

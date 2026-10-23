"""Dump guest memory [base, base+size) of a process into a flat file at offset va-base (holes = 0).
usage: python dump_image.py <pid> <out> [base_hex] [size_hex]"""
import ctypes
import ctypes.wintypes as wt
import sys

k = ctypes.windll.kernel32


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD), ("_a", wt.WORD),
                ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD), ("Protect", wt.DWORD),
                ("Type", wt.DWORD), ("_b", wt.DWORD)]


k.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(MBI), ctypes.c_size_t]
k.VirtualQueryEx.restype = ctypes.c_size_t
k.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
                                ctypes.POINTER(ctypes.c_size_t)]
k.OpenProcess.restype = wt.HANDLE

pid = int(sys.argv[1])
out = sys.argv[2]
base = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x800000000
size = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0xbd70000
h = k.OpenProcess(0x0400 | 0x0010, False, pid)
if not h:
    raise SystemExit("OpenProcess failed")
buf = bytearray(size)
va = base
got = 0
while va < base + size:
    mbi = MBI()
    if not k.VirtualQueryEx(h, va, ctypes.byref(mbi), ctypes.sizeof(mbi)):
        break
    end = min(mbi.BaseAddress + mbi.RegionSize, base + size)
    readable = mbi.State == 0x1000 and not (mbi.Protect & 0x100) and (mbi.Protect & 0xEE)
    if readable:
        n = end - va
        tmp = (ctypes.c_char * n)()
        rd = ctypes.c_size_t()
        if k.ReadProcessMemory(h, va, tmp, n, ctypes.byref(rd)):
            buf[va - base:va - base + rd.value] = tmp.raw[:rd.value]
            got += rd.value
        print(f"{va - base:#010x}-{end - base:#010x} prot={mbi.Protect:#x} read={rd.value:#x}")
    va = end
open(out, "wb").write(buf)
print(f"wrote {out} readable={got:#x}")

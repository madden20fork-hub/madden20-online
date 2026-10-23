"""Debugger-free tracing of guest functions in the running game. shadPS4 reserves the whole guest address range, so
nothing can be allocated within rel32 reach of the eboot: each hooked function's first bytes are replaced by an
absolute `jmp [rip+0]` (14 bytes) to a stub in a page allocated anywhere. The stub appends
{event, rsi, rdx, rcx, r8} to a ring buffer, replays the stolen instructions (a rip-relative `mov reg,[rip+d]` is
rewritten as `movabs reg, abs; mov reg,[reg]`) and jumps back.
usage: python -I hook_events.py install          patch (once per game process; page remembered in runs/hook.json)
       python -I hook_events.py show [N]         print the last N ring entries (default 40)
Targets: the draft UI listener events (vtable @0x7740b20 +0x2e8/+0x2f0/+0x2f8/+0x300)."""
import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import pid_of  # noqa: E402

B = 0x800000000
# name, function, stolen bytes as (non-rip bytes hex, optional rip-relative load: (reg_movabs_prefix, deref, abs))
# 0x46e7d80/0x46e7ea0: push rbp/mov rbp,rsp/push r15/r14/r12/rbx (11 bytes) + mov r12,[rip+d] (7) = 18
# 0x46e7fc0: push rbp..push rbx + sub rsp,0x18 = 17 bytes;  0x46e8240: push rbp..push rbx + push rax = 14 bytes
TARGETS = [
    ("UpdateDraftInfo", 0x46E7D80, "554889e541574156415453", (0x46E7D92 + 0x62C23F6), 18),
    ("NewPicksReady", 0x46E7EA0, "554889e541574156415453", (0x46E7EB2 + 0x62C22D6), 18),
    ("SlotPreviewReady", 0x46E7FC0, "554889e5415741564155415453" + "4883ec18", None, 17),
    ("PickComplete", 0x46E8240, "554889e54157415641554154" + "5350", None, 14),
]
STATE = Path(r"C:\madden20_online\runs\hook.json")
RING = 256                                         # entries of 40 bytes: id, rsi, rdx, rcx, r8

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.VirtualProtectEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.FlushInstructionCache.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t]

pid = pid_of()
h = k32.OpenProcess(0x1F0FFF, False, pid)


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        raise OSError(f"read {a:#x}: {ctypes.get_last_error()}")
    return b.raw[:g.value]


def wr(a, data, code=False):
    old = wt.DWORD()
    if code:
        if not k32.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), 0x40, ctypes.byref(old)):
            raise OSError(f"protect {a:#x}: {ctypes.get_last_error()}")
    g = ctypes.c_size_t()
    if not k32.WriteProcessMemory(h, ctypes.c_void_p(a), data, len(data), ctypes.byref(g)):
        raise OSError(f"write {a:#x}: {ctypes.get_last_error()}")
    if code:
        k32.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), old.value, ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(a), len(data))


def jmp_abs(dst):
    return b"\xff\x25\x00\x00\x00\x00" + struct.pack("<Q", dst)


def install():
    if STATE.exists():
        st = json.loads(STATE.read_text())
        if st.get("pid") == pid:
            print("already installed", hex(st["page"]))
            return
    page = k32.VirtualAllocEx(h, None, 0x10000, 0x3000, 0x40)
    if not page:
        raise OSError(f"alloc: {ctypes.get_last_error()}")
    code = page + 0x4000                 # data: [page]=seq u64, [page+0x100..]=ring
    for idx, (name, rel, plain_hex, rip_abs, stolen) in enumerate(TARGETS):
        fn = B + rel
        plain = bytes.fromhex(plain_hex)
        cur = rd(fn, stolen)
        if cur[:len(plain)] != plain:
            print(f"{name}: unexpected bytes {cur.hex()} - skipped")
            continue
        s = bytearray()
        s += b"\x50\x41\x53"                                         # push rax; push r11
        s += b"\x49\xbb" + struct.pack("<Q", page)                   # movabs r11, page
        s += b"\xb8\x01\x00\x00\x00"                                 # mov eax, 1
        s += b"\xf0\x49\x0f\xc1\x03"                                 # lock xadd [r11], rax
        s += b"\x25" + struct.pack("<I", RING - 1)                   # and eax, RING-1
        s += b"\x6b\xc0\x28"                                         # imul eax, eax, 40
        s += b"\x49\x01\xc3"                                         # add r11, rax
        s += b"\x49\x81\xc3" + struct.pack("<I", 0x100)              # add r11, 0x100
        s += b"\x49\xc7\x03" + struct.pack("<i", idx + 1)            # mov qword [r11], idx+1
        s += b"\x49\x89\x73\x08\x49\x89\x53\x10\x49\x89\x4b\x18\x4d\x89\x43\x20"   # rsi, rdx, rcx, r8
        s += b"\x41\x5b\x58"                                         # pop r11; pop rax
        s += plain                                                   # replay the stolen prologue
        if rip_abs:                                                  # mov r12,[rip+d] -> movabs r12,abs; mov r12,[r12]
            s += b"\x49\xbc" + struct.pack("<Q", B + rip_abs) + b"\x4d\x8b\x24\x24"
        s += jmp_abs(fn + stolen)
        wr(code, bytes(s), code=True)
        patch = jmp_abs(code)
        wr(fn, patch + b"\x90" * (stolen - len(patch)), code=True)
        print(f"hooked {name} @ {fn:#x} -> stub {code:#x}")
        code += (len(s) + 15) & ~15
    STATE.write_text(json.dumps({"pid": pid, "page": page}))


def show(n=40):
    st = json.loads(STATE.read_text())
    page = st["page"]
    seq = struct.unpack("<Q", rd(page, 8))[0]
    raw = rd(page + 0x100, RING * 40)
    print("events so far:", seq)
    for s in range(max(0, seq - n), seq):
        i = s % RING
        ev, rsi, rdx, rcx, r8 = struct.unpack_from("<QQQQQ", raw, i * 40)
        name = TARGETS[ev - 1][0] if 1 <= ev <= len(TARGETS) else f"?{ev}"
        print(f"#{s:4} {name:17} rsi={rsi:#x} edx={rdx & 0xffffffff} ecx={rcx & 0xffffffff} r8={r8 & 0xffffffff}")


if __name__ == "__main__":
    if sys.argv[1] == "install":
        install()
    else:
        show(int(sys.argv[2]) if len(sys.argv) > 2 else 40)

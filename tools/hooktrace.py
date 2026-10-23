"""Generic debugger-free call tracer for guest functions (generalises hook_events.py).
Each target's first >=14 bytes are decoded with capstone and relocated into a stub that logs
{id, rdi, rsi, rdx, rcx, r8, rdtsc} into a ring buffer, then jumps back. Supported stolen instructions:
anything position-independent, plus `mov r64, [rip+d]` (rewritten to movabs + load). Functions whose
prologue has other rip-relative operands or branches are skipped (reported).
usage: python -I hooktrace.py install <targets.txt>   (lines: "name hexaddr", eboot-relative or absolute)
       python -I hooktrace.py show [N]                (last N events, default 60)
       python -I hooktrace.py mark                    (remember the current event count; show prints only newer)
State: runs/hooktrace.json (pid, page, names)."""
import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
from pathlib import Path

import capstone
from capstone import x86

sys.path.insert(0, r"C:\madden20_online\tools")
from memscan import pid_of  # noqa: E402

B = 0x800000000
STATE = Path(r"C:\madden20_online\runs\hooktrace.json")
RING = 131072   # 16 MB ring (10-17)
REC = 128   # id, rdi, rsi, rdx, rcx, r8, tsc, retaddr, r9, stack args 1..3 (10-17; was 64 bytes x 16K)

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
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
md.detail = True


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        raise OSError(f"read {a:#x}: {ctypes.get_last_error()}")
    return b.raw[:g.value]


def wr(a, data, code=False):
    old = wt.DWORD()
    if code and not k32.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), 0x40, ctypes.byref(old)):
        raise OSError(f"protect {a:#x}: {ctypes.get_last_error()}")
    g = ctypes.c_size_t()
    if not k32.WriteProcessMemory(h, ctypes.c_void_p(a), data, len(data), ctypes.byref(g)):
        raise OSError(f"write {a:#x}: {ctypes.get_last_error()}")
    if code:
        k32.VirtualProtectEx(h, ctypes.c_void_p(a), len(data), old.value, ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(a), len(data))


def jmp_abs(dst):
    return b"\xff\x25\x00\x00\x00\x00" + struct.pack("<Q", dst)


REG64 = {x86.X86_REG_RAX: 0, x86.X86_REG_RCX: 1, x86.X86_REG_RDX: 2, x86.X86_REG_RBX: 3, x86.X86_REG_RSP: 4,
         x86.X86_REG_RBP: 5, x86.X86_REG_RSI: 6, x86.X86_REG_RDI: 7, x86.X86_REG_R8: 8, x86.X86_REG_R9: 9,
         x86.X86_REG_R10: 10, x86.X86_REG_R11: 11, x86.X86_REG_R12: 12, x86.X86_REG_R13: 13, x86.X86_REG_R14: 14,
         x86.X86_REG_R15: 15}


def relocate(fn):
    """-> (replayed bytes, stolen length) or (None, reason)."""
    code = rd(fn, 64)
    out = bytearray()
    n = 0
    for ins in md.disasm(code, fn):
        if n >= 14:
            break
        grp = set(ins.groups)
        if grp & {capstone.CS_GRP_JUMP, capstone.CS_GRP_CALL, capstone.CS_GRP_RET, capstone.CS_GRP_BRANCH_RELATIVE}:
            return None, f"branch in prologue: {ins.mnemonic} {ins.op_str}"
        riprel = any(op.type == x86.X86_OP_MEM and op.mem.base == x86.X86_REG_RIP for op in ins.operands)
        if riprel:
            ops = ins.operands
            if (ins.mnemonic == "mov" and len(ops) == 2 and ops[0].type == x86.X86_OP_REG and ops[0].size == 8
                    and ops[0].reg in REG64 and ops[1].type == x86.X86_OP_MEM):
                r = REG64[ops[0].reg]
                tgt = ins.address + ins.size + ops[1].mem.disp
                rex = 0x48 | (1 if r >= 8 else 0)
                out += bytes([rex, 0xB8 + (r & 7)]) + struct.pack("<Q", tgt)          # movabs r, tgt
                # mov r, [r]  (rex.w + 8b /r with mod=00; rsp/r12 need SIB, rbp/r13 need disp8)
                rexb = 0x48 | (0x4 if r >= 8 else 0) | (0x1 if r >= 8 else 0)
                low = r & 7
                if low == 4:
                    out += bytes([rexb, 0x8B, 0x04 | (low << 3), 0x24])
                elif low == 5:
                    out += bytes([rexb, 0x8B, 0x45 | (low << 3), 0x00])
                else:
                    out += bytes([rexb, 0x8B, (low << 3) | low])
            elif (ins.mnemonic == "lea" and len(ops) == 2 and ops[0].type == x86.X86_OP_REG and ops[0].size == 8
                    and ops[0].reg in REG64):
                r = REG64[ops[0].reg]
                tgt = ins.address + ins.size + ops[1].mem.disp
                out += bytes([0x48 | (1 if r >= 8 else 0), 0xB8 + (r & 7)]) + struct.pack("<Q", tgt)   # movabs
            else:
                return None, f"rip-relative operand: {ins.mnemonic} {ins.op_str}"
        else:
            out += ins.bytes
        n += ins.size
    if n < 14:
        return None, "too short"
    return bytes(out), n


def install(targets_file):
    names = []
    tgts = []
    for line in Path(targets_file).read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name, addr = line.split()[:2]
        a = int(addr, 16)
        tgts.append((name, a if a >= B else B + a))
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if st.get("pid") == pid:
        page = st["page"]
        names = st["names"]
        code = st["code"]
        hooked = set(st.get("hooked", []))
    else:
        page = k32.VirtualAllocEx(h, None, 0x1200000, 0x3000, 0x40)
        if not page:
            raise OSError(f"alloc: {ctypes.get_last_error()}")
        code = page + 0x1100000
        hooked = set()
    for name, fn in tgts:
        if fn in hooked:
            continue
        rep, stolen = relocate(fn)
        if rep is None:
            print(f"SKIP {name} @ {fn:#x}: {stolen}")
            continue
        idx = len(names) + 1
        s = bytearray()
        s += b"\x50\x52\x41\x53"                                     # push rax; push rdx; push r11
        s += b"\x49\xbb" + struct.pack("<Q", page)                   # movabs r11, page
        s += b"\xb8\x01\x00\x00\x00"                                 # mov eax, 1
        s += b"\xf0\x49\x0f\xc1\x03"                                 # lock xadd [r11], rax
        s += b"\x25" + struct.pack("<I", RING - 1)                   # and eax, RING-1
        s += b"\xc1\xe0\x07"                                         # shl eax, 7  (REC = 128)
        s += b"\x49\x01\xc3"                                         # add r11, rax
        s += b"\x49\x81\xc3" + struct.pack("<I", 0x100)              # add r11, 0x100
        s += b"\x49\xc7\x03" + struct.pack("<i", idx)                # mov qword [r11], idx
        s += b"\x49\x89\x7b\x08\x49\x89\x73\x10"                     # [r11+8]=rdi [r11+16]=rsi
        s += b"\x48\x8b\x44\x24\x08"                                 # mov rax, [rsp+8]  (saved rdx)
        s += b"\x49\x89\x43\x18\x49\x89\x4b\x20\x4d\x89\x43\x28"     # [+24]=rdx [+32]=rcx [+40]=r8
        s += b"\x0f\x31"                                             # rdtsc (edx:eax)
        s += b"\x48\xc1\xe2\x20\x48\x09\xd0\x49\x89\x43\x30"         # shl rdx,32; or rax,rdx; [+48]=tsc
        s += bytes.fromhex("488b442418" "49894338")                 # mov rax,[rsp+24] (ret addr); [+56]=ret
        s += bytes.fromhex("4d894b40")                               # [+64]=r9
        s += bytes.fromhex("488b442420" "49894348")                 # [+72]=stack arg 1
        s += bytes.fromhex("488b442428" "49894350")                 # [+80]=stack arg 2
        s += bytes.fromhex("488b442430" "49894358")                 # [+88]=stack arg 3
        s += bytes.fromhex("488b442410" "49894360")                 # [+96]=rax (saved; = return value
                                                                     #   when hooking right after a call)
        s += b"\x41\x5b\x5a\x58"                                     # pop r11; pop rdx; pop rax
        s += rep
        s += jmp_abs(fn + stolen)
        wr(code, bytes(s), code=True)
        wr(fn, jmp_abs(code) + b"\x90" * (stolen - 14), code=True)
        names.append(name)
        hooked.add(fn)
        code += (len(s) + 15) & ~15
        print(f"hooked {idx:3} {name} @ {fn:#x} (stolen {stolen})")
    STATE.write_text(json.dumps({"pid": pid, "page": page, "names": names, "code": code,
                                 "hooked": sorted(hooked), "mark": st.get("mark", 0) if st.get("pid") == pid else 0}))


def show(n=60):
    st = json.loads(STATE.read_text())
    page = st["page"]
    names = st["names"]
    seq = struct.unpack("<Q", rd(page, 8))[0]
    start = max(st.get("mark", 0), seq - n, seq - RING)
    raw = rd(page + 0x100, RING * REC)
    print("events so far:", seq, "showing from", start)
    t0 = None
    for s in range(start, seq):
        ev, rdi, rsi, rdx, rcx, r8, tsc, ret, r9, a1, a2, a3, rax = struct.unpack_from("<13Q", raw, (s % RING) * REC)
        t0 = t0 or tsc
        name = names[ev - 1] if 1 <= ev <= len(names) else f"?{ev}"
        line = (f"#{s:5} +{(tsc - t0) / 3.0e9:8.3f}s {name:28} this={rdi:#x} rsi={rsi:#x} rdx={rdx:#x} "
                f"rcx={rcx:#x} r8={r8:#x} r9={r9:#x} s1={a1:#x} s2={a2:#x} s3={a3:#x} rax={rax:#x} ret={ret:#x}")
        if QFMT and B <= rcx < B + 0x8000000:   # TDB query executor: rcx = format string
            try:
                q = rd(rcx, 200).split(b"\0")[0].decode("latin1").replace("\n", "")
                q = q.encode("ascii", "backslashreplace").decode()   # format codes are 0x80+ bytes
            except OSError:
                q = "?"
            if QFILTER and not any(f in q for f in QFILTER):
                continue
            line += "  " + q
        print(line)


QFMT = "--q" in sys.argv                                    # show: decode rcx as a TDB query format string
QFILTER = [a for a in sys.argv[2:] if not a.isdigit() and a != "--q"]   # keep only queries containing these


def mark():
    st = json.loads(STATE.read_text())
    st["mark"] = struct.unpack("<Q", rd(st["page"], 8))[0]
    STATE.write_text(json.dumps(st))
    print("mark", st["mark"])


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "install":
        install(sys.argv[2])
    elif cmd == "mark":
        mark()
    else:
        show(int(sys.argv[2]) if len(sys.argv) > 2 else 60)

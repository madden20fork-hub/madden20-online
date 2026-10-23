"""Disassemble Madden eboot code from the live-memory dump, naming PLT imports.
usage: python dis.py <va_hex> [--back N] [--len N] [--func]
  va may be absolute (0x8xxxxxxxx) or eboot-relative.  --func: start at nearest prologue before va.
Imports: PLT stub `jmp [rip+d]` -> GOT slot -> relocs.txt NID -> aerolib name."""
import re
import sys
from pathlib import Path

import capstone

BASE = 0x800000000
DUMP = Path(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin")
GOTN = Path(r"C:\madden20_online\dump\got_names.txt")
AERO = Path(r"C:\madden20_online\core_src\src\core\aerolib\aerolib.inl")

data = DUMP.read_bytes()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

_aero = None
_slots = None


def names():
    global _slots
    if _slots is None:
        _slots = {}
        for line in GOTN.read_text(errors="ignore").splitlines():
            a, _, n = line.partition(" ")
            _slots[int(a, 16) + BASE] = n
    return _slots


def rd(va, n):
    off = va - BASE
    return data[off:off + n]


def plt_target(va):
    """If va is a PLT stub (ff 25 disp32), return import name."""
    b = rd(va, 6)
    if len(b) == 6 and b[0] == 0xFF and b[1] == 0x25:
        disp = int.from_bytes(b[2:6], "little", signed=True)
        slot = va + 6 + disp
        return names().get(slot, f"GOT[{slot:#x}]")
    return None


def find_prologue(va, limit=0x4000):
    for a in range(va, va - limit, -1):
        b = rd(a, 4)
        if b == b"\x55\x48\x89\xe5" and rd(a - 1, 1) in (b"\xcc", b"\xc3", b"\x90", b"\x00"):
            return a
    return va - 0x80


def dis(start, length, mark=None):
    for ins in md.disasm(rd(start, length), start):
        note = ""
        if ins.mnemonic in ("call", "jmp") and ins.op_str.startswith("0x"):
            t = int(ins.op_str, 16)
            name = plt_target(t)
            if name:
                note = f"   ; -> {name}"
        m = re.search(r"\[rip ([+-]) (0x[0-9a-f]+)\]", ins.op_str)
        if m:
            tgt = ins.address + ins.size + (int(m.group(2), 16) * (1 if m.group(1) == "+" else -1))
            note += f"   ; [{tgt - BASE:#x}]"
        flag = ">>" if mark is not None and ins.address <= mark < ins.address + ins.size + 1 and ins.address + ins.size == mark else "  "
        print(f"{flag} {ins.address - BASE:08x}: {ins.mnemonic:6} {ins.op_str}{note}")
        if ins.mnemonic == "ret" and mark is not None and ins.address > mark:
            break


if __name__ == "__main__":
    va = int(sys.argv[1], 16)
    if va < BASE:
        va += BASE
    back = int(sys.argv[sys.argv.index("--back") + 1], 16) if "--back" in sys.argv else 0x60
    ln = int(sys.argv[sys.argv.index("--len") + 1], 16) if "--len" in sys.argv else 0x100
    start = find_prologue(va) if "--func" in sys.argv else va - back
    if "--func" in sys.argv:
        ln = max(ln, va - start + 0x80)
    print(f"; start {start - BASE:#x} (mark {va - BASE:#x})")
    dis(start, ln, mark=va)

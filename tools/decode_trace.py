"""Decode a hooktrace dump: OSDK log format strings (sesgLog rdx) resolved, noise filtered.
usage: python -I decode_trace.py <trace.txt>"""
import re, sys
d = open(r"C:\madden20_online\dump\eboot_mem_0x800000000.bin", "rb").read()
NOISE = ("op38", "op28", "op68", "op70", "dh0b0")
QUIET = ("GetChatPermission", "ticker", "GetMessages", "LoginSlotConcrete::GetName")


def cs(x):
    o = x - 0x800000000
    if 0 < o < len(d):
        e = d.find(b"\0", o, o + 240)
        s = d[o:e]
        if s and all(32 <= c < 127 or c in (9, 10) for c in s):
            return s.decode()


prev = None
for l in open(sys.argv[1]):
    m = re.match(r"#\s*(\d+) \+\s*([\d.]+)s (\S+)\s+this=(\S+) rsi=(\S+) rdx=(\S+) rcx=(\S+) r8=(\S+)(?: ret=\S+)?", l)
    if not m:
        continue
    i, t, name, this, rsi, rdx, rcx, r8 = m.groups()
    if name in NOISE:
        continue
    if name == "sesgLog":
        s = cs(int(rdx, 16))
        if not s or any(q in s for q in QUIET):
            continue
        a1, a2 = cs(int(rcx, 16)), cs(int(r8, 16))
        out = f"{t:>8} LOG {s!r}" + (f" | {a1!r}" if a1 else f" | {rcx}") + (f" | {a2!r}" if a2 else "")
    else:
        out = f"{t:>8} {name} this={this} rsi={rsi} rdx={rdx}"
    if out != prev:
        print(out[:240])
    prev = out

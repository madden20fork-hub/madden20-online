"""Find every in-memory TDB directory that has a PLAY table and report its record counts.
Writes the best one (most PLAY records) to dump/tdb_dir_live.json for tdb_live.py.
usage: python -I tdb_find.py"""
import json
import re
import struct
import sys

sys.path.insert(0, r"C:\madden20_online\tools")
import memscan as ms  # noqa: E402

ALNUM = re.compile(rb"[0-9A-Za-z]{4}")


def walk_dir(h, hit):
    d = ms.read(h, hit - 0x2000, 0x4000)
    j = 0x2000
    e = j
    while e - 8 >= 0 and ALNUM.fullmatch(d[e - 8:e - 4]):
        e -= 8
    start, ents = e, []
    while e + 8 <= len(d) and ALNUM.fullmatch(d[e:e + 4]):
        ents.append((d[e:e + 4][::-1].decode(), struct.unpack(">I", d[e + 4:e + 8])[0]))
        e += 8
    return hit - 0x2000 + start, hit - 0x2000 + e, ents


def main():
    h = ms.open_proc(ms.pid_of())
    hits = ms.scan(h, [b"YALP"], max_hits=400)[b"YALP"]
    seen, found = set(), []
    for a in hits:
        start, end, ents = walk_dir(h, a)
        if len(ents) < 5 or start in seen:
            continue
        seen.add(start)
        tables = dict(ents)
        if "PLAY" not in tables:
            continue
        t = end + tables["PLAY"]
        hd = ms.read(h, t, 30)
        if len(hd) < 30:
            continue
        rec_bytes, = struct.unpack(">I", hd[8:12])
        max_rec, cur_rec = struct.unpack(">HH", hd[20:24])
        nf = hd[28]
        ok = rec_bytes < 4096 and 0 < nf < 255
        found.append({"dir_start": start, "dir_end": end, "tables": ents, "play_cur": cur_rec if ok else -1,
                      "play_max": max_rec, "rec_bytes": rec_bytes, "nfields": nf})
        print(f"dir {start:#x} tables={len(ents)} PLAY rec={rec_bytes} max={max_rec} cur={cur_rec} fields={nf}"
              f"{'' if ok else '  (bad header)'}")
    best = max(found, key=lambda f: f["play_cur"], default=None)
    if best:
        json.dump(best, open(r"C:\madden20_online\dump\tdb_dir_live.json", "w"))
        print(f"-> using {best['dir_start']:#x} (PLAY cur={best['play_cur']})")


main()

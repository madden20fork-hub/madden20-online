"""Read Madden 20's in-memory TDB (table database) from the live shadps4 process.
Layout measured 10-14 (all big-endian):
  directory: 8-byte entries {4CC name byte-reversed, u32 offset}; offsets are relative to the directory end.
  table header (40 bytes): u32 prio, u32 ?, u32 recBytes, u32 recBits, u32 0, u16 maxRecords, u16 curRecords,
                           u32 ?, u8 fieldCount, u8 indexCount, u16 0, u32 0, u32 crc
  field def (16 bytes):    u32 type (0=string, 2=signed, 3=unsigned, 4=float?), u32 bitOffset, 4CC reversed, u32 bits
  records follow the field defs: maxRecords * recBytes, bit-packed MSB-first.
usage: python -I tdb_live.py <TABLE> [--fields] [--n N] [--json out.json]"""
import json
import struct
import sys

sys.path.insert(0, r"C:\madden20_online\tools")
import memscan as ms  # noqa: E402

DIR_JSON = r"C:\madden20_online\dump\tdb_dir_live.json"


def load_dir():
    j = json.load(open(DIR_JSON))
    return j["dir_end"], dict(j["tables"])


def table(h, name):
    dir_end, tables = load_dir()
    t = dir_end + tables[name]
    hd = ms.read(h, t, 40)
    prio, unk, rec_bytes, rec_bits, z, max_rec, cur_rec, unk3, nfields, nidx = struct.unpack(">IIIIIHHIBB", hd[:30])
    fd = ms.read(h, t + 40, nfields * 16)
    fields = []
    for i in range(nfields):
        typ, off, nm, bits = struct.unpack(">II4sI", fd[i * 16:i * 16 + 16])
        fields.append({"name": nm[::-1].decode("latin1"), "type": typ, "off": off, "bits": bits})
    data_at = t + 40 + nfields * 16
    return {"addr": t, "rec_bytes": rec_bytes, "rec_bits": rec_bits, "max": max_rec, "cur": cur_rec,
            "fields": fields, "data": data_at}


def get_bits(rec, off, n):
    v = int.from_bytes(rec, "big")
    total = len(rec) * 8
    return (v >> (total - off - n)) & ((1 << n) - 1)


def decode(rec, fields):
    out = {}
    for f in fields:
        if f["type"] == 0:
            raw = rec[f["off"] // 8:(f["off"] + f["bits"]) // 8]
            out[f["name"]] = raw.split(b"\0")[0].decode("latin1")
        else:
            v = get_bits(rec, f["off"], f["bits"])
            if f["type"] == 2 and v >> (f["bits"] - 1):
                v -= 1 << f["bits"]
            out[f["name"]] = v
    return out


def records(h, tb, n=None):
    n = tb["max"] if n is None else n
    raw = ms.read(h, tb["data"], n * tb["rec_bytes"])
    return [decode(raw[i * tb["rec_bytes"]:(i + 1) * tb["rec_bytes"]], tb["fields"]) for i in range(n)]


if __name__ == "__main__":
    a = sys.argv[1:]
    h = ms.open_proc(ms.pid_of())
    tb = table(h, a[0])
    print(f"{a[0]} @{tb['addr']:#x} recBytes={tb['rec_bytes']} max={tb['max']} cur={tb['cur']} "
          f"fields={len(tb['fields'])}")
    if "--fields" in a:
        for f in sorted(tb["fields"], key=lambda f: f["off"]):
            print(f"  {f['name']} type={f['type']} off={f['off']} bits={f['bits']}")
    n = int(a[a.index("--n") + 1]) if "--n" in a else 3
    recs = records(h, tb, None if "--json" in a else n)
    if "--json" in a:
        json.dump(recs, open(a[a.index("--json") + 1], "w"))
        print("wrote", len(recs))
    else:
        for r in recs:
            print(r)

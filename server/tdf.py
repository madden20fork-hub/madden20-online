"""EA Blaze TDF codec (heat2-style: 3-byte packed tag + 1-byte type)."""
import struct

INT, STRING, BLOB, STRUCT, LIST, MAP, UNION, VAR, OBJTYPE, OBJID, FLOAT, TIMEVALUE, GENERIC = range(13)


def tag_to_str(b):
    v = (b[0] << 16) | (b[1] << 8) | b[2]
    out = ""
    for i in range(4):
        c = (v >> (18 - 6 * i)) & 0x3F
        out += chr(c + 32) if c else ""
    return out.rstrip()


def str_to_tag(s):
    s = s.upper().ljust(4)[:4]
    v = 0
    for ch in s:
        v = (v << 6) | ((ord(ch) - 32) & 0x3F)
    return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


def read_varint(b, i):
    x = b[i]
    neg = x & 0x40
    val = x & 0x3F
    shift = 6
    i += 1
    while x & 0x80:
        x = b[i]
        val |= (x & 0x7F) << shift
        shift += 7
        i += 1
    return (-val if neg else val), i


def write_varint(v):
    neg = v < 0
    v = -v if neg else v
    first = (v & 0x3F) | (0x40 if neg else 0)
    v >>= 6
    out = bytearray()
    if v:
        first |= 0x80
    out.append(first)
    while v:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
    return bytes(out)


def _read_value(t, b, i):
    if t == INT:
        return read_varint(b, i)
    if t == STRING:
        n, i = read_varint(b, i)
        s = b[i:i + n].rstrip(b"\0").decode("utf-8", "replace")
        return s, i + n
    if t == BLOB:
        n, i = read_varint(b, i)
        return b[i:i + n], i + n
    if t == STRUCT:
        fields = []
        while True:
            if b[i] == 0:
                return fields, i + 1
            f, i = _read_field(b, i)
            fields.append(f)
    if t == LIST:
        et = b[i]
        n, i = read_varint(b, i + 1)
        items = []
        for _ in range(n):
            v, i = _read_value(et, b, i)
            items.append(v)
        return ("list", et, items), i
    if t == MAP:
        kt, vt = b[i], b[i + 1]
        n, i = read_varint(b, i + 2)
        items = []
        for _ in range(n):
            k, i = _read_value(kt, b, i)
            v, i = _read_value(vt, b, i)
            items.append((k, v))
        return ("map", kt, vt, items), i
    if t == UNION:
        active = b[i]
        i += 1
        if active == 0x7F:
            return ("union", active, None), i
        f, i = _read_field(b, i)
        return ("union", active, f), i
    if t == VAR:
        # variable TDF: tdfid varint, then struct body
        present = b[i]
        i += 1
        if not present:
            return ("var", None), i
        tid, i = read_varint(b, i)
        v, i = _read_value(STRUCT, b, i)
        return ("var", tid, v), i
    if t == OBJTYPE:
        a, i = read_varint(b, i)
        c, i = read_varint(b, i)
        return ("objtype", a, c), i
    if t == OBJID:
        a, i = read_varint(b, i)
        c, i = read_varint(b, i)
        d, i = read_varint(b, i)
        return ("objid", a, c, d), i
    if t == FLOAT:
        return struct.unpack(">f", b[i:i + 4])[0], i + 4
    if t == TIMEVALUE:
        return read_varint(b, i)
    if t == GENERIC:
        # GenericTdfType (e.g. matchmaking scenario attribute values): present u8, tdfId varint, the raw value
        # of whatever type tdfId names, then 0x00. The type table is not decoded, so try the likely encodings
        # and keep the first one that lands on the terminator.
        present = b[i]
        i += 1
        if not present:
            return ("generic", None, None), i
        tid, i = read_varint(b, i)
        for vt in (INT, LIST, STRING, MAP, STRUCT):
            try:
                v, j = _read_value(vt, b, i)
            except (ValueError, IndexError):
                continue
            if j < len(b) and b[j] == 0:
                return ("generic", tid, v), j + 1
        raise ValueError(f"undecodable generic tdf {tid:#x} at {i}")
    raise ValueError(f"unknown tdf type {t} at {i}")


def _read_field(b, i):
    tag = tag_to_str(b[i:i + 3])
    t = b[i + 3]
    v, i = _read_value(t, b, i + 4)
    return (tag, t, v), i


def decode_tdf(b):
    i = 0
    fields = []
    while i < len(b):
        if b[i] == 0 and i == len(b) - 1:
            break
        f, i = _read_field(b, i)
        fields.append(f)
    return fields


def fmt_tdf(fields, ind=0):
    pad = "  " * ind
    out = []
    for tag, t, v in fields:
        if t == STRUCT:
            out.append(f"{pad}{tag}: {{")
            out.append(fmt_tdf(v, ind + 1))
            out.append(f"{pad}}}")
        elif t == UNION and v[2] is not None:
            out.append(f"{pad}{tag}: union[{v[1]}] {{")
            out.append(fmt_tdf([v[2]], ind + 1))
            out.append(f"{pad}}}")
        elif t == BLOB:
            out.append(f"{pad}{tag}: blob[{len(v)}] {v[:48].hex()}")
        else:
            out.append(f"{pad}{tag}: {v!r}")
    return "\n".join(x for x in out if x)


# ---------------- encoder ----------------
def enc_int(tag, v):
    return str_to_tag(tag) + bytes([INT]) + write_varint(v)


def enc_str(tag, s):
    raw = s.encode() + b"\0"
    return str_to_tag(tag) + bytes([STRING]) + write_varint(len(raw)) + raw


def enc_blob(tag, data):
    return str_to_tag(tag) + bytes([BLOB]) + write_varint(len(data)) + data


def body(*fields):
    """Concatenate encoded fields in tag order (Blaze decoders expect ascending tags)."""
    return b"".join(sorted(fields, key=lambda f: f[:3]))


def enc_struct(tag, *fields):
    return str_to_tag(tag) + bytes([STRUCT]) + body(*fields) + b"\0"


def enc_union(tag, active, inner=b""):
    return str_to_tag(tag) + bytes([UNION, active]) + inner


def enc_list_int(tag, vals):
    return str_to_tag(tag) + bytes([LIST, INT]) + write_varint(len(vals)) + b"".join(write_varint(v) for v in vals)


def enc_list_str(tag, vals):
    body = b""
    for s in vals:
        raw = s.encode() + b"\0"
        body += write_varint(len(raw)) + raw
    return str_to_tag(tag) + bytes([LIST, STRING]) + write_varint(len(vals)) + body


def enc_list_struct(tag, structs):
    """structs: list of bytes, each the concatenated fields of one struct (without terminator)."""
    return (str_to_tag(tag) + bytes([LIST, STRUCT]) + write_varint(len(structs))
            + b"".join(s + b"\0" for s in structs))


def enc_map_str_str(tag, d):
    body = b""
    for k, v in d.items():
        for s in (k, v):
            raw = s.encode() + b"\0"
            body += write_varint(len(raw)) + raw
    return str_to_tag(tag) + bytes([MAP, STRING, STRING]) + write_varint(len(d)) + body


def enc_objtype(tag, comp, typ):
    return str_to_tag(tag) + bytes([OBJTYPE]) + write_varint(comp) + write_varint(typ)


def enc_objid(tag, comp, typ, oid):
    return str_to_tag(tag) + bytes([OBJID]) + write_varint(comp) + write_varint(typ) + write_varint(oid)


def enc_map_str_struct(tag, d):
    """d: {key: bytes of struct fields (no terminator)}"""
    body = b""
    for k, v in d.items():
        raw = k.encode() + b"\0"
        body += write_varint(len(raw)) + raw + v + b"\0"
    return str_to_tag(tag) + bytes([MAP, STRING, STRUCT]) + write_varint(len(d)) + body


def enc_time(tag, usec):
    # This client's Heat2Decoder takes TimeValue members as wire type INT (kind-14 case @0x5519b89: type must be 0).
    # Type 11 fails the member and loses the following members of the struct (DraftEvent TOTR/TYPE -> "ROUND x OF -1").
    return str_to_tag(tag) + bytes([INT]) + write_varint(usec)


def enc_list_u16(tag, vals):
    return enc_list_int(tag, vals)


# Fire2 frame (BlazeSDK 15): u32 len, u16 metaLen, u16 comp, u16 cmd, u24 msgNum, u8 type<<5, u8 opt, u8 res
MSG, REPLY, NOTIFY, ERROR_REPLY, PING, PING_REPLY = range(6)


def parse_fire2(buf):
    if len(buf) < 16:
        return None
    ln, meta, comp, cmd = struct.unpack(">IHHH", buf[:10])
    if len(buf) < 16 + meta + ln:
        return None
    hdr = {"len": ln, "meta": meta, "comp": comp, "cmd": cmd,
           "seq": int.from_bytes(buf[10:13], "big"), "type": buf[13] >> 5, "typebyte": buf[13],
           "opt": buf[14], "res": buf[15]}
    return hdr, buf[16 + meta:16 + meta + ln], 16 + meta + ln


def frame(comp, cmd, seq, payload, mtype=REPLY, opt=0):
    return (struct.pack(">IHHH", len(payload), 0, comp, cmd) + seq.to_bytes(3, "big")
            + bytes([mtype << 5, opt, 0]) + payload)

"""Card art for the client's NetResCache (OSDK_MADSET NETRESOURCE_IMAGE_BASE_URL = <HTTP_BASE>netres/).
Hot-reloaded per request by http_server. Images: mutdata/art/{cards,programs}/<asset>.png|.jpg, downloaded from
EA's own textures by tools/art_download.py (asset = 'lgnd-00052129', 'swap-26-10100112', 'pgrm-00001023', ...).

The exact URL the client builds from a netres id is not known yet, so any path whose last component contains a
known asset name (case-insensitive, extension ignored) is served; misses are logged with the full path."""
import re
from pathlib import Path

ART = Path(__file__).resolve().parent.parent / "mutdata" / "art"


def _load():
    """Asset index, built once into a fresh dict and published atomically on the (never reloaded) `sys` module.
    10-17: the old module-level dict was reset by every per-request reload while other request threads were still
    filling/reading it -> random MISSes for files that exist (card shows the silhouette)."""
    import sys
    subs = ("cards", "programs", "ui")           # ui = generated store/pack tiles (tools/pack_art.py)
    key = tuple((ART / s).stat().st_mtime_ns if (ART / s).exists() else 0 for s in subs)
    cached = getattr(sys, "_madden_netres_index2", None)   # (key, index); "_madden_netres_index" = old dict form
    if cached is None or cached[0] != key:       # rebuilt when files are added/removed in any art folder
        idx = {}
        for sub in subs:
            d = ART / sub
            if d.exists():
                for p in d.iterdir():
                    if p.suffix in (".png", ".jpg"):
                        idx[p.stem.lower()] = p
        cached = (key, idx)
        sys._madden_netres_index2 = cached
    return cached[1]


ASSET_RE = re.compile(r"([a-z0-9]{4}-\d{8}|swap-\d+-\d+)", re.I)


def handle(path, log):
    """Return (status, headers, body) or None if the path is not an art request."""
    idx = _load()
    tail = path.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    stem = tail.rsplit(".", 1)[0].lower()
    hit = idx.get(stem)
    if not hit:
        m = ASSET_RE.search(path)
        hit = idx.get(m.group(1).lower()) if m else None
    if not hit:
        if "/netres/" in path or ASSET_RE.search(path):
            log(f"  -> netres MISS {path}")
            return 404, {"Content-Type": "text/plain"}, b""
        return None
    ctype = "image/png" if hit.suffix == ".png" else "image/jpeg"
    log(f"  -> netres {hit.parent.name}/{hit.name}")
    return 200, {"Content-Type": ctype}, hit.read_bytes()

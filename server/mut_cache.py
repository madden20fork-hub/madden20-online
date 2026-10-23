"""Process-lifetime cache for the MUT catalog. NOT hot-reloaded (handlers/mut/mut_cards are reloaded on every
Blaze frame, and the client sends hundreds of frames a second)."""
import json
from pathlib import Path

_cache = {}


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    m = p.stat().st_mtime
    hit = _cache.get(str(p))
    if hit and hit[0] == m:
        return hit[1]
    v = json.loads(p.read_text())
    _cache[str(p)] = (m, v)
    return v

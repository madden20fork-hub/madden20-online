"""Collect every player preset asset name (<Name>_<playerId>) visible in the live game's memory.
Merges into mutdata/asset_names.json ({playerId: assetName}) so repeated runs (menus, gameplay) accumulate.
usage: python -I asset_names.py"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r"C:\madden20_online\tools")
import memscan as ms  # noqa: E402

OUT = Path(r"C:\madden20_online\mutdata\asset_names.json")
PAT = re.compile(rb"players/([A-Za-z][A-Za-z0-9]*?)_(\d{3,6})_")


def main():
    names = json.loads(OUT.read_text()) if OUT.exists() else {}
    before = len(names)
    h = ms.open_proc(ms.pid_of())
    for base, size in ms.regions(h):
        off = 0
        while off < size:
            n = min(64 << 20, size - off)
            data = ms.read(h, base + off, n + 128)
            for m in PAT.finditer(data):
                names.setdefault(m.group(2).decode(), m.group(1).decode() + "_" + m.group(2).decode())
            off += n
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(names, indent=0, sort_keys=True))
    print(f"asset names: {len(names)} (+{len(names) - before})")


main()

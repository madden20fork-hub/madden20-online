"""Re-encode oversized card/program art so it fits the client's NetRes download buffer.
Some archived EA textures (e.g. Free Agency free-000538xx.jpg) are 512x512 JPEGs carrying ~8 MB of extra data; the
client never shows them (only the silhouette) although the request is served. Files above LIMIT are re-saved as
plain JPEG/PNG (same name, same pixels); originals are kept in mutdata/art/_orig/<sub>/.
usage: python -I tools/art_shrink.py [limit_kb=512]"""
import io
import shutil
import sys
from pathlib import Path

from PIL import Image

ART = Path(__file__).resolve().parent.parent / "mutdata" / "art"
LIMIT = int(sys.argv[1]) * 1024 if len(sys.argv) > 1 else 512 * 1024

for sub in ("cards", "programs"):
    for p in sorted((ART / sub).iterdir()):
        if p.suffix not in (".png", ".jpg") or p.stat().st_size <= LIMIT:
            continue
        keep = ART / "_orig" / sub / p.name
        keep.parent.mkdir(parents=True, exist_ok=True)
        if not keep.exists():
            shutil.copy2(p, keep)
        im = Image.open(keep)
        im.load()
        buf = io.BytesIO()
        if p.suffix == ".jpg":
            im.convert("RGB").save(buf, "JPEG", quality=92)
        else:
            im.save(buf, "PNG", optimize=True)
        p.write_bytes(buf.getvalue())
        print(f"{sub}/{p.name}: {keep.stat().st_size:,} -> {len(buf.getvalue()):,}  {im.size} {im.mode}")

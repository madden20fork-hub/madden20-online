"""Probe the muthead MUT 20 asset CDN for asset ids: prints status, size, content type.
usage: python -I tools/cdn_probe.py <id> [...]       (id like stor-00000002; .png appended)
       python -I tools/cdn_probe.py --range stor 0 40  (stor-00000000 .. stor-00000039)
       add --save to store hits in mutdata/art/ui/<id>.<png|jpg>"""
import sys
import urllib.error
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
BASE = "https://cdn.muthead.com/media/20/assets/"
OUT = Path(r"C:\madden20_online\mutdata\art\ui")
args = sys.argv[1:]
save = "--save" in args
args = [a for a in args if a != "--save"]
if args and args[0] == "--range":
    pre, lo, hi = args[1], int(args[2]), int(args[3])
    ids = [f"{pre}-{i:08d}" for i in range(lo, hi)]
else:
    ids = args
for i in ids:
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + i + ".png", headers={"User-Agent": UA}),
                                    timeout=20) as r:
            data = r.read()
        kind = "png" if data.startswith(b"\x89PNG") else "jpg" if data.startswith(b"\xff\xd8") else "?"
        print(f"{i}: 200 {len(data)} {kind}")
        if save and kind != "?":
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{i}.{kind}").write_bytes(data)
    except urllib.error.HTTPError as e:
        print(f"{i}: {e.code}")
    except Exception as e:  # noqa: BLE001
        print(f"{i}: ERR {e}")

"""Download MUT 20 card art from the muthead CDN (EA's own 512x512 card textures).

    python -I tools/art_download.py [--workers 4]

Sources (from mutdata/cards.json, the archived EA item records):
  card['image']            -> mutdata/art/cards/<asset>.png|.jpg   (asset = 'swap-26-10100112', 'core-10109774', ...)
  card['program']['image'] -> mutdata/art/programs/<asset>.png|.jpg
Resumable: files already on disk are skipped. Writes mutdata/art/index.json {card external_id: asset file}.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS = os.path.join(ROOT, "mutdata", "cards.json")
OUT = os.path.join(ROOT, "mutdata", "art")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def asset_of(url):
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def fetch(job):
    url, path = job
    for ext in (".png", ".jpg"):
        if os.path.exists(path + ext) and os.path.getsize(path + ext) > 0:
            return "skip", url
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if data.startswith(b"\x89PNG"):
                path += ".png"
            elif data.startswith(b"\xff\xd8"):
                path += ".jpg"   # some muthead assets are JPEG despite the .png URL
            else:
                return "notimage", url
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            return "ok", url
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "404", url
            time.sleep(2 ** attempt)
        except Exception:  # noqa: BLE001
            time.sleep(2 ** attempt)
    return "fail", url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cards = json.load(open(CARDS, encoding="utf-8"))
    os.makedirs(os.path.join(OUT, "cards"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "programs"), exist_ok=True)
    jobs, index = {}, {}
    for c in cards:
        if c.get("image"):
            asset = asset_of(c["image"])
            jobs[c["image"]] = os.path.join(OUT, "cards", asset)
            index[str(c["external_id"])] = "cards/" + asset
        p = c.get("program")
        if isinstance(p, dict) and p.get("image"):
            jobs[p["image"]] = os.path.join(OUT, "programs", asset_of(p["image"]))
    print(f"{len(cards)} cards, {len(jobs)} unique images", flush=True)
    stats = {}
    with ThreadPoolExecutor(a.workers) as ex:
        for i, (st, url) in enumerate(ex.map(fetch, jobs.items()), 1):
            stats[st] = stats.get(st, 0) + 1
            if st not in ("ok", "skip"):
                print(st, url, flush=True)
            if i % 250 == 0:
                print(i, stats, flush=True)
    for k, rel in index.items():   # resolve the extension actually saved
        for ext in (".png", ".jpg"):
            if os.path.exists(os.path.join(OUT, rel + ext)):
                index[k] = rel + ext
                break
    json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=0)
    print("done", stats, flush=True)
    return 0 if not stats.get("fail") else 1


if __name__ == "__main__":
    sys.exit(main())

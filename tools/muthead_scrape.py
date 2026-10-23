"""Scrape the Madden 20 MUT card archive from muthead.com/20/players (server-rendered HTML).
Phase 1: list pages -> card ids. Phase 2: every card page. Everything is cached under mutdata/raw/ so a rerun
resumes; a polite rate (THREADS workers, DELAY s between requests each).
usage: python -I muthead_scrape.py [--pages N]"""
import concurrent.futures as cf
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "mutdata"
RAW = ROOT / "raw"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
THREADS, DELAY = 3, 0.6


def get(url, path, tries=4):
    if path.exists() and path.stat().st_size > 5000:
        return path.read_text(encoding="utf8")
    for t in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode("utf8", "replace")
            path.write_text(b, encoding="utf8")
            time.sleep(DELAY)
            return b
        except Exception as e:  # noqa: BLE001
            print("retry", url, e, flush=True)
            time.sleep(5 * (t + 1))
    return ""


def main():
    a = sys.argv[1:]
    pages = int(a[a.index("--pages") + 1]) if "--pages" in a else 277
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "list").mkdir(exist_ok=True)
    (RAW / "card").mkdir(exist_ok=True)
    ids = []
    with cf.ThreadPoolExecutor(THREADS) as ex:
        urls = [(f"https://www.muthead.com/20/players/?page={p}", RAW / "list" / f"p{p:03d}.html")
                for p in range(1, pages + 1)]
        for n, b in enumerate(ex.map(lambda u: get(*u), urls), 1):
            ids += re.findall(r'href="/20/players/(\d+)/"', b)
            if n % 25 == 0:
                print(f"list {n}/{pages} ids={len(set(ids))}", flush=True)
    ids = sorted(set(ids), key=int)
    (ROOT / "card_ids.txt").write_text("\n".join(ids))
    print("card ids:", len(ids), flush=True)
    done = 0
    with cf.ThreadPoolExecutor(THREADS) as ex:
        futs = [ex.submit(get, f"https://www.muthead.com/20/players/{i}/", RAW / "card" / f"{i}.html") for i in ids]
        for f in cf.as_completed(futs):
            done += 1
            if done % 200 == 0:
                print(f"cards {done}/{len(ids)}", flush=True)
    print("DONE", len(ids), flush=True)


main()

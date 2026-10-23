"""Parse cached Muthead Madden 20 card pages (mutdata/raw/card/*.html) -> mutdata/cards.json.
Each page carries the card's full item record as JSON in the `mut-card` element's data-props
(external_id = EA card id, external_player_id = EA player/asset id, all ratings, traits, program, team).
usage: python -I muthead_parse.py"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "mutdata"


def parse(text):
    for m in re.finditer(r'data-props="([^"]*)"', text):
        s = html.unescape(m.group(1))
        if '"external_player_id"' not in s:
            continue
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            continue
    return None


def main():
    cards, bad = [], []
    for p in sorted((ROOT / "raw" / "card").glob("*.html"), key=lambda p: int(p.stem)):
        j = parse(p.read_text(encoding="utf8"))
        if j:
            j.pop("chemistry_maps", None)
            j.pop("stats", None)
            cards.append(j)
        else:
            bad.append(p.stem)
    (ROOT / "cards.json").write_text(json.dumps(cards))
    print(f"cards={len(cards)} unparsed={len(bad)} {bad[:10]}")
    progs = {}
    for c in cards:
        progs[c["program"]["name"]] = progs.get(c["program"]["name"], 0) + 1
    print("programs:", len(progs), sorted(progs.items(), key=lambda x: -x[1])[:15])


main()

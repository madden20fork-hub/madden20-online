"""MUT team state for the single local user: owned card instances + depth chart, persisted to
mutdata/user_state.json. Starter squad: STARTER_MODE (see build_starter)."""
import json
import random
from pathlib import Path

import mut_cards

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "mutdata" / "user_state.json"

# Blaze::Mut::PlayerPositionEnum (= depth chart slot ids)
POS = {n: i for i, n in enumerate("QB HB FB WR TE LT LG C RG RT LE RE DT LOLB MLB ROLB CB FS SS K P KR PR KOS LS "
                                  "3DRB PWHB SLWR RLE RRE RDT SUBLB SLCB".split())}
# depth per base position (starters first). MUT 20 lineup: QB HB FB 3WR TE OL5 / LE RE 2DT 3LB 3CB FS SS / K P
DEPTH = {"QB": 2, "HB": 2, "FB": 1, "WR": 5, "TE": 2, "LT": 1, "LG": 1, "C": 1, "RG": 1, "RT": 1, "LE": 2, "RE": 2,
         "DT": 3, "LOLB": 1, "MLB": 2, "ROLB": 1, "CB": 4, "FS": 1, "SS": 1, "K": 1, "P": 1}
# special-team / package slots filled from base positions: slot -> (source position, count)
PACKAGES = {"KR": ("WR", 1), "PR": ("WR", 1), "KOS": ("K", 1), "LS": ("C", 1), "3DRB": ("HB", 1),
            "PWHB": ("HB", 1), "SLWR": ("WR", 1), "RLE": ("LE", 1), "RRE": ("RE", 1), "RDT": ("DT", 1),
            "SUBLB": ("MLB", 1), "SLCB": ("CB", 1)}
OFFENSE = {"QB", "HB", "FB", "WR", "TE", "LT", "LG", "C", "RG", "RT"}
DEFENSE = {"LE", "RE", "DT", "LOLB", "MLB", "ROLB", "CB", "FS", "SS"}

# "best": highest-OVR card per slot from the whole archive. "team:<abbr>": that NFL team's cards first.
STARTER_MODE = "best"
FIRST_IID = 100_000_001     # < 2**31: the UI handles ids as signed 32-bit ints


def _pos(c):
    return c["position"]["abbreviation"]


def build_starter(mode=STARTER_MODE, seed=0, first_iid=FIRST_IID):
    cards = list(mut_cards.catalog().values())
    rnd = random.Random(seed)
    team = mode.split(":", 1)[1] if mode.startswith("team:") else None
    picks, used_players = {}, set()
    for p, n in DEPTH.items():
        pool = [c for c in cards if _pos(c) == p]
        if team:
            pool.sort(key=lambda c: ((c.get("team") or {}).get("abbreviation") != team, -c["overall"], rnd.random()))
        else:
            pool.sort(key=lambda c: (-c["overall"], rnd.random()))
        chosen = []
        for c in pool:
            if c["external_player_id"] in used_players:
                continue  # one version of each real player
            chosen.append(c["external_id"])
            used_players.add(c["external_player_id"])
            if len(chosen) == n:
                break
        picks[p] = chosen
    st = {"next_iid": first_iid, "cards": {}, "depth": {}}
    by_card = {}
    for p, ids in picks.items():
        for cid in ids:
            iid = st["next_iid"]
            st["next_iid"] += 1
            st["cards"][str(iid)] = cid
            by_card[cid] = iid
        st["depth"][str(POS[p])] = [by_card[c] for c in ids]
    for slot, (src, n) in PACKAGES.items():
        st["depth"][str(POS[slot])] = st["depth"].get(str(POS[src]), [])[:n]
    return st


def load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    if not mut_cards.catalog():
        return {"next_iid": FIRST_IID, "cards": {}, "depth": {}}
    st = build_starter()
    save(st)
    return st


def save(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def card_of(st, iid):
    return mut_cards.catalog().get(st["cards"].get(str(iid)))


def ratings(st):
    """(overall, offense, defense) = mean OVR of the starters."""
    starters = {"WR": 3, "DT": 2, "CB": 3}
    off, de = [], []
    for name in OFFENSE | DEFENSE:
        for iid in st["depth"].get(str(POS[name]), [])[:starters.get(name, 1)]:
            c = card_of(st, iid)
            if c:
                (off if name in OFFENSE else de).append(c["overall"])
    o = round(sum(off) / len(off)) if off else 0
    d = round(sum(de) / len(de)) if de else 0
    return round((o + d) / 2), o, d

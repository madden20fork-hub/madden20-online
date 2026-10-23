"""MUT 20 non-player items = the Lineup screen's "Team Strategy" (coach, offensive + defensive playbook) and
"Team Visuals" (home/dark + away/light uniform, stadium) groups (client list @0x46f9394: group 8 / 9).

Built from the game's OWN database tables, dumped from live memory 10-17 into mutdata/team_items/ (the Muthead
archive has no MUT 20 items):
  tdb_COCH.json  coaches  - CCID coachId, CFNM/CLNM, TGID team (1..32 = NFL, BGID + 1), CHCB 1 = head coach
  tdb_PLAB.json  playbooks- BGID playbookId (0..31 team books in nickname order Bears..Texans, 32+ generic),
                            BOFF offense flag, BNAM display name ("KC - A. Reid"), PBAN asset, PBVI visible
  tdb_TUNI.json  uniforms - TGID team, UANM asset ("Bears_HOME_Uni"), UDSC description ("Bears Throwback")
  tdb_STAD.json  stadiums - SGID stadiumId (= StadiumCardData.STDM; 40 = Madden Championship Series Stadium),
                            SDNA display name, SNAM stadium name, STAA asset
The user owns one of every item; the active ones per lineup slot live in user_state.json "items".
Hot-reloaded via mut.py."""
import json
import re
from pathlib import Path

from tdf import VAR, STRUCT, body, enc_int, enc_str, str_to_tag, write_varint

DATA = Path(__file__).resolve().parent.parent / "mutdata" / "team_items"

CARDTYPE_COACH, CARDTYPE_PLAYBOOK, CARDTYPE_STADIUM, CARDTYPE_UNIFORM = 2, 3, 4, 5
CARDSTATE_ACTIVE, CONTRACT_GAMES = 1, 999
COACH_TDFID, PLAYBOOK_TDFID, STADIUM_TDFID, UNIFORM_TDFID = 0x05578D39, 0xB881F01C, 0xA5CFBE0A, 0xD9060387
OFFICIAL_TYPE = "Default"       # UniformCardData.OFTP: empty = NULL name lookup crash @0x3257490 (10-16)
# OFTP is looked up (FNV-1a of the string, 0x2f8b2b0) in the team's MixMatchOfficialTypeNameList; "Default" is not
# in it -> index 0 -> free-agent kit (10-17 evening). Test: OFTP = the uniform asset name ("Bears_AWAY_Uni").
OFTP_IS_ASSET = True
SEND_TMID = True
# Blaze::Mut::NonPlayerItemType (SetNonPlayerItemToActive NPIT) -> our slot name
SLOTS = {0: "coach", 1: "stadium", 2: "away_uni", 3: "home_uni", 4: "def_pb", 5: "off_pb"}
# card id ranges (instance id = card id + IID_OFFSET; players use 100_000_001+, CPU squads 200M/300M+)
COACH_BASE, PLAYBOOK_BASE, UNIFORM_BASE, STADIUM_BASE = 9_110_000, 9_200_000, 9_400_000, 9_500_000
IID_OFFSET = 50_000_000
# stadiums that are not MUT items (practice field, Longshot high school, college playoff copies, combine)
SKIP_STADIUMS = {34, 50, 55, 61, 64}
DEFAULT_TEAM = "CHI"
# Uniform textures live in content/characters/player/parts/uniforms/<team folder>/<year>/<prefix>_jersey_...
# (asset catalog in live memory, 10-17). UniformCardData = the TEAM row's TASN "Bears" / TPFN+TUFP "BEA". With
# TPFX "Bears" + UPFX "HOME", or TASN "bears", BOTH teams fell back to the free-agent uniform
# (uniforms/freeagent/2019/fre_jersey_2019_whi).
UNIFORM_PREFIX = {"49ers": "nin", "bears": "bea", "bengals": "ben", "bills": "bil", "broncos": "bro", "browns": "brn",
                  "buccaneers": "buc", "cardinals": "car", "chargers": "cha", "chiefs": "chi", "colts": "col",
                  "cowboys": "cow", "dolphins": "dol", "eagles": "eag", "falcons": "fal", "giants": "gia",
                  "jaguars": "jag", "jets": "jet", "lions": "lio", "packers": "pac", "panthers": "pan",
                  "patriots": "pat", "raiders": "rai", "rams": "ram", "ravens": "rav", "redskins": "red",
                  "saints": "sai", "seahawks": "sea", "steelers": "ste", "texans": "tex", "titans": "tit",
                  "vikings": "vik"}            # the user's squad shows the Bears identity (Season Home / lineup, 10-17)

_cache = {}


def _load(name):
    p = DATA / f"tdb_{name}.json"
    key = (name, p.stat().st_mtime)
    if key not in _cache:
        _cache[key] = json.loads(p.read_text())
    return _cache[key]


def _var(tag, tdfid, struct_body):
    # Heat2 variable TDF as this client decodes it (see mut_cards.enc_var)
    return (str_to_tag(tag) + bytes([VAR, 1]) + write_varint(tdfid)
            + str_to_tag(tag) + bytes([STRUCT]) + struct_body + b"\0" + b"\0")


def teams():
    """BGID order (0..31) -> {abbr, nick, tgid}: from the team playbooks ("CHI - M. Nagy", "Madden_Bears")."""
    out = {}
    for p in _load("PLAB"):
        if p.get("BOFF") == 1 and 0 <= p.get("BGID", -1) <= 31 and p.get("PBAN", "").startswith("Madden_"):
            out[p["BGID"]] = {"abbr": p["BNAM"].split(" - ")[0].strip(), "nick": p["PBAN"][len("Madden_"):],
                              "tgid": p["BGID"] + 1}
    return out


def _team_by_abbr(abbr):
    for b, t in teams().items():
        if t["abbr"] == abbr:
            return b, t
    return 0, teams()[0]


def catalog():
    """card id -> item dict. Cached per data-file mtimes."""
    key = ("catalog",) + tuple((DATA / f"tdb_{n}.json").stat().st_mtime for n in ("COCH", "PLAB", "TUNI", "STAD"))
    if key in _cache:
        return _cache[key]
    tm = teams()
    by_tgid = {t["tgid"]: t for t in tm.values()}
    items = {}
    for c in _load("COCH"):
        t = by_tgid.get(c.get("TGID"))
        if t and c.get("CHCB") == 1 and c.get("CLNM"):
            ovr = max(60, min(99, max(c.get("COFF", 0), c.get("CDEF", 0))))
            items[COACH_BASE + c["CCID"]] = dict(type=CARDTYPE_COACH, slot="coach", team=t["abbr"], coach=c["CCID"],
                                                  first=c["CFNM"], last=c["CLNM"], ovr=ovr,
                                                  name=f"{c['CFNM']} {c['CLNM']}")
    for p in _load("PLAB"):
        if not p.get("PBAN") or not p.get("PBVI") or p["PBAN"].startswith("Longshot"):
            continue
        off = bool(p.get("BOFF"))
        t = tm.get(p["BGID"]) if p["BGID"] <= 31 else None
        name = (f"{t['nick']} {'Offense' if off else 'Defense'}" if t else p["BNAM"])
        items[PLAYBOOK_BASE + p["BGID"] * 2 + int(off)] = dict(
            type=CARDTYPE_PLAYBOOK, slot="off_pb" if off else "def_pb", team=t["abbr"] if t else "",
            pbid=p["BGID"], offensive=off, name=name, desc=p["BNAM"])
    seen = set()
    for u in _load("TUNI"):
        t = by_tgid.get(u.get("TGID"))
        a = u.get("UANM") or ""
        if not t or a in seen or not a.startswith(t["nick"] + "_"):
            continue
        seen.add(a)
        prefix = a[len(t["nick"]) + 1:-len("_Uni")]                    # HOME / AWAY / ALT0..
        desc = (u.get("UDSC") or prefix).strip()
        light = prefix == "AWAY" or desc.lower().startswith("white")
        items[UNIFORM_BASE + u["UFID"]] = dict(type=CARDTYPE_UNIFORM, slot="away_uni" if light else "home_uni",
                                                team=t["abbr"], nick=t["nick"], asset=a, prefix=prefix, light=light,
                                                tgid=t["tgid"],
                                                name=desc if desc.startswith(t["nick"]) else f"{t['nick']} {desc}")
    for s in _load("STAD"):
        # rows past the table's live record count are garbage (SQL text etc.): require a clean asset name
        if s.get("SGID") in SKIP_STADIUMS or not re.fullmatch(r"[a-z0-9_]+", s.get("STAA") or ""):
            continue
        name = s["SNAM"].replace("\x99", "").replace("\xae", "").strip()
        variant = re.search(r"\((Open|Closed)\)", s.get("SDNA", ""))
        if variant:
            name += f" ({variant.group(1)})"
        if any(it["name"] == name for it in items.values() if it["type"] == CARDTYPE_STADIUM):
            name += f" ({s.get('SDNA', s['STAA'])})"           # MetLife Stadium: Giants and Jets
        team = next((t["abbr"] for t in tm.values() if s["STAA"] == t["nick"].lower()), "")
        items.setdefault(STADIUM_BASE + s["SGID"], dict(type=CARDTYPE_STADIUM, slot="stadium", team=team,
                                                         stadium=s["SGID"], name=name, desc=s.get("SDNA", "")))
    _cache[key] = items
    return items


def iid_of(cid):
    return cid + IID_OFFSET


def cid_of_iid(iid):
    cid = int(iid) - IID_OFFSET
    return cid if cid in catalog() else None


def card(cid, iid=None):
    """Blaze::Mut::Card body for one item."""
    it = catalog()[cid]
    iid = iid_of(cid) if iid is None else iid
    if it["type"] == CARDTYPE_COACH:
        data, tdfid = body(enc_int("COCH", it["coach"]), enc_str("CFST", it["first"]), enc_str("CLST", it["last"]),
                           enc_int("OVR", it["ovr"])), COACH_TDFID
        n1, n2 = it["first"], it["last"]
    elif it["type"] == CARDTYPE_PLAYBOOK:
        data, tdfid = body(enc_int("PBID", it["pbid"]), enc_int("ISOF", int(it["offensive"]))), PLAYBOOK_TDFID
        n1, n2 = it["name"], ""
    elif it["type"] == CARDTYPE_UNIFORM:
        # exactly the in-game TEAM row values (live TEAM table, 10-17): TUAN/TASN "Bears", TPFN/TUFP "BEA",
        # TLGO = team index 0..31
        pfx = UNIFORM_PREFIX.get(it["nick"].lower(), it["nick"][:3]).upper()
        data, tdfid = body(enc_int("ISLT", int(it["light"])), enc_str("TASN", it["nick"]), enc_str("TPFX", pfx),
                           enc_int("TLGO", it["tgid"] - 1), enc_str("UASN", it["asset"]), enc_str("UPFX", pfx),
                           enc_str("OFTP", it["asset"] if OFTP_IS_ASSET else OFFICIAL_TYPE)), UNIFORM_TDFID
        n1, n2 = it["name"], ""
    else:
        data, tdfid = body(enc_int("STDM", it["stadium"])), STADIUM_TDFID
        n1, n2 = it["name"], ""
    # Card.TMID (teamId, Card+0xb0): the uniform setup 0x476fa40 hands it to the uniform manager as the team whose
    # kits are loaded (slot +0 at [0xa9c8468]+8 / +0x58). Unsent = 0 -> both teams wore the free-agent kit (10-17).
    tmid = [enc_int("TMID", it["tgid"])] if it.get("tgid") and SEND_TMID else []
    return body(enc_int("CIID", iid), enc_int("ID", cid), *tmid, enc_int("TYPE", it["type"]), enc_int("TIER", 3),
                enc_int("CSTE", CARDSTATE_ACTIVE), enc_str("NAM1", n1), enc_str("NAM2", n2),
                enc_str("CNAM", it["name"]), enc_str("DESC", it.get("desc", "")), enc_int("AQMT", 5),
                enc_int("CNTR", CONTRACT_GAMES), _var("DATA", tdfid, data), _var("STDT", tdfid, data))


def team_selection(abbr):
    """The NFL team's own items: its head coach, playbooks, home/away uniforms, home stadium."""
    b, t = _team_by_abbr(abbr)
    cat = catalog()
    sel = {}
    for cid, it in cat.items():
        if it["team"] != t["abbr"]:
            continue
        if it["slot"] == "coach" or it["slot"] in ("off_pb", "def_pb") or it["slot"] == "stadium":
            sel.setdefault(it["slot"], cid)
        elif it["slot"] == "home_uni" and it["prefix"] == "HOME":
            sel["home_uni"] = cid
        elif it["slot"] == "away_uni" and it["prefix"] == "AWAY":
            sel["away_uni"] = cid
    for slot in SLOTS.values():                      # anything missing: fall back to the default team's item
        if slot not in sel and abbr != DEFAULT_TEAM:
            sel[slot] = team_selection(DEFAULT_TEAM)[slot]
    return sel


def selection(t):
    """Active items of a team dict (user_state / drafted / CPU squad): t["items"] overrides the team default."""
    sel = team_selection(t.get("items_team") or DEFAULT_TEAM)
    sel.update({k: v for k, v in (t.get("items") or {}).items() if v in catalog()})
    return sel


def active_cards(t):
    return [card(cid) for cid in selection(t).values()]


def lineup_fields(t, with_coach=True, team_ids=False):
    """LineupInfo fields equipping the active items (CCH/CCI coach, OFFP/OFFI, DEFP/DEFI, UNFA/UNFI light,
    UNFH/UNI dark, STDM/STDI)."""
    s = selection(t)
    f = [enc_int("OFFP", s["off_pb"]), enc_int("OFFI", iid_of(s["off_pb"])),
         enc_int("DEFP", s["def_pb"]), enc_int("DEFI", iid_of(s["def_pb"])),
         enc_int("UNFA", s["away_uni"]), enc_int("UNFI", iid_of(s["away_uni"])),
         enc_int("UNFH", s["home_uni"]), enc_int("UNI", iid_of(s["home_uni"])),
         enc_int("STDM", s["stadium"]), enc_int("STDI", iid_of(s["stadium"]))]
    if team_ids:
        # LineupInfo HTID/ATID: the team whose assets the dark / light uniform resolve against (TGID). Unsent (0)
        # the game dressed BOTH teams in the free-agent uniform (uniforms/freeagent/2019/fre_*, 10-17).
        # Only in the game data: in the Season Home / StartDraft lineup the client then stalled after IN_GAME
        # (never asked Dc_GetGameAndRenderData, 10-17).
        f += [enc_int("HTID", catalog()[s["home_uni"]]["tgid"]), enc_int("ATID", catalog()[s["away_uni"]]["tgid"])]
    if with_coach:
        f = [enc_int("CCH", s["coach"]), enc_int("CCI", iid_of(s["coach"]))] + f
    return f


def owned(slot=None):
    """Card ids the user owns (every item), optionally of one slot, sorted by name."""
    cat = catalog()
    ids = [cid for cid, it in cat.items() if slot is None or it["slot"] == slot]
    return sorted(ids, key=lambda c: (cat[c]["type"], cat[c]["name"]))

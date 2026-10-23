"""Madden 20 MUT card catalog (archived Muthead item records, mutdata/cards.json) -> Blaze::Mut::Card TDF.
Muthead's per-card data-props is EA's item record: external_id = EA cardId, external_player_id = EA player id
(= the asset suffix, e.g. MahomesIIPatrick_12635). Field mapping: snake_case -> camelCase member names of
Blaze::Mut::PlayerCardData (dump/playercarddata_schema.txt) plus the explicit table below."""
import json
import re
from pathlib import Path

from tdf import INT, MAP, STRUCT, VAR, body, enc_int, enc_list_struct, enc_str, enc_struct, str_to_tag, write_varint

ROOT = Path(__file__).resolve().parent.parent
PLAYER_CARD_DATA_TDFID = 0x2E29456A        # typeinfo before the PlayerCardData descriptor: {kind 11, id}
PLAYBOOK_CARD_DATA_TDFID = 0xB881F01C      # Blaze::Mut::PlaybookCardData {PBID playbookId, ISOF isOffensive}
CARDTYPE_PLAYER, CARDTYPE_PLAYBOOK, CARDSTATE_ACTIVE = 1, 3, 1
CONTRACT_GAMES = 100                       # Card.CNTR contractLength
# Every lineup needs an offensive and a defensive playbook item (LineupInfo OFFP/OFFI, DEFP/DEFI) or the client
# refuses to start a game ("The lineup does not have a valid defensive playbook item").
# (card id, instance id, playbookId, offensive). playbookId values are UNVERIFIED guesses.
PLAYBOOKS = [(9_200_001, 9_300_001, 1, True), (9_200_002, 9_300_002, 1, False)]

_schema = [ln.split() for ln in (ROOT / "dump" / "playercarddata_schema.txt").read_text().splitlines() if ln.strip()]
_by_lc = {name.lower(): (tag, ty) for tag, name, ty in _schema}
_types = {tag: ty for tag, name, ty in _schema}

EXPLICIT = {
    "overall": "OVR", "external_player_id": "PLID", "short_route_running": "SRRN",
    "medium_route_running": "RRUN", "deep_route_running": "PDRR", "short_throw_accuracy": "TACS",
    "medium_throw_accuracy": "TACM", "deep_throw_accuracy": "TACD", "throwing_on_the_run": "TOTR",
    "salary_cap_cost": "SLRY", "trait_throw_ball_away": "UHAW", "trait_throws_tight_spiral": "USPI",
    "trait_forces_passes": "GORP", "trait_covers_the_ball": "DBAL", "trait_plays_ball_in_the_air": "QBAL",
    "trait_possession_catches": "QOCA", "trait_rac_catches": "ZACA", "trait_aggressive_catches": "IPCA",
    "trait_makes_sideline_catches": "JNBO", "trait_drops_open_passes": "PPAS",
    "trait_fights_for_extra_yards": "GIGH", "trait_strips_ball": "TTBA", "trait_utilizes_swim_moves": "ELSW",
    "trait_utilizes_spin_moves": "ELSP", "trait_utilizes_bull_rush_moves": "ELBU",
}
# trait value tag -> its "IsActive" companion
TRAIT_ACTIVE = {"UHAW": "UHAA", "USPI": "USPA", "GORP": "GORA", "DBAL": "DBAA", "QBAL": "QBAA", "QOCA": "QOCB",
                "ZACA": "ZACB", "IPCA": "IPCB", "JNBO": "JNBA", "PPAS": "PPAA", "GIGH": "GIGA", "TTBA": "TTBB",
                "ELSW": "ELSA", "ELSP": "ELSB", "ELBU": "ELBA", "DHIT": "DHIA", "DLUT": "DLUA", "IMOT": "IMOA",
                "UQBS": "UQBA", "TPRE": "TPRA", "MBST": "MBSA", "QENA": "QENB"}
SKIP = {"team_id", "id"}  # muthead-internal ids (TEAM comes from team.external_id)

import mut_cache  # noqa: E402  (not reloaded)


def catalog():
    """{EA cardId: archive record}, cached across hot reloads (keyed on cards.json mtime)."""
    raw = mut_cache.load_json(ROOT / "mutdata" / "cards.json", [])
    key = ("by_id", id(raw))
    if key not in mut_cache._cache:
        mut_cache._cache[key] = {c["external_id"]: c for c in raw}
    return mut_cache._cache[key]


def asset_name(c):
    pid = str(c["external_player_id"])
    assets = mut_cache.load_json(ROOT / "mutdata" / "asset_names.json", {})
    if pid in assets:
        return assets[pid]
    last = re.sub(r"[^A-Za-z]", "", c.get("last_name") or "")
    first = re.sub(r"[^A-Za-z]", "", c.get("first_name") or "")
    return f"{last}{first}_{pid}"  # fallback; Frostbite name lookups are case-insensitive


def player_card_fields(c):
    out = {}
    for k, v in c.items():
        if k in SKIP or v is None or isinstance(v, (dict, list)):
            continue
        tag = EXPLICIT.get(k) or _by_lc.get(k.replace("_", "").lower(), (None,))[0]
        if not tag:
            continue
        out[tag] = int(v) if isinstance(v, bool) else v
    for t, a in TRAIT_ACTIVE.items():
        if t in out:
            out[a] = 1
    out["POS"] = c["position"]["external_id"]
    out["TEAM"] = c["team"]["external_id"] if c.get("team") else 0
    out["MARC"] = c["archetype"]["external_id"] if c.get("archetype") else 0
    out["PLAN"] = asset_name(c)
    return out


def enc_fields(fields):
    """-> list of encoded fields (callers pass them to body() together with any extra fields so ALL are sorted;
    a pre-joined blob is sorted as one unit and puts later tags out of order -> the client skips them)."""
    enc = []
    for tag, v in fields.items():
        ty = _types.get(tag, "")
        if ty == "string" or isinstance(v, str):
            enc.append(enc_str(tag, str(v)))
        elif isinstance(v, (int, float)) and not ty.startswith("ti@"):
            enc.append(enc_int(tag, max(0, int(v))))
    return enc


def position_ovrs(c):
    """OVRM positionOvrRatings: map<uint8 PlayerPositionEnum, uint8 ovr>. The archive's position_ovr_json is keyed
    by Muthead position id = EA id + 1 (QB 1 -> 0). Without it the client shows the card OVR as 255."""
    try:
        raw = json.loads(c.get("position_ovr_json") or "{}")
    except json.JSONDecodeError:
        raw = {}
    m = {int(k) - 1: int(v) for k, v in raw.items() if str(k).isdigit() and int(k) >= 1}
    m.setdefault(c["position"]["external_id"], c["overall"])
    body_ = b"".join(write_varint(k) + write_varint(v) for k, v in sorted(m.items()))
    return str_to_tag("OVRM") + bytes([MAP, INT, INT]) + write_varint(len(m)) + body_


def enc_var(tag, tdfid, struct_body):
    """Heat2 variable TDF as this client decodes it (Heat2Decoder @0x5518720, kind-7 case @0x55198ca):
    present byte, varint tdfId, then the value as ONE struct member carrying the variable's own tag, then the
    variable's terminator. Unwrapped fields are skipped by the decoder -> an all-zero PlayerCardData (OVR 0/255)."""
    return (str_to_tag(tag) + bytes([VAR, 1]) + write_varint(tdfid)
            + str_to_tag(tag) + bytes([STRUCT]) + struct_body + b"\0" + b"\0")


def playbook_card(card_id, iid, pbid, offensive):
    data = body(enc_int("PBID", pbid), enc_int("ISOF", int(offensive)))
    name = "Offensive Playbook" if offensive else "Defensive Playbook"
    return body(enc_int("CIID", iid), enc_int("ID", card_id), enc_int("TYPE", CARDTYPE_PLAYBOOK), enc_int("TIER", 3),
                enc_int("CSTE", CARDSTATE_ACTIVE), enc_str("NAM1", name), enc_str("NAM2", ""), enc_str("CNAM", name),
                enc_int("AQMT", 5), enc_int("CNTR", CONTRACT_GAMES), enc_var("DATA", PLAYBOOK_CARD_DATA_TDFID, data),
                enc_var("STDT", PLAYBOOK_CARD_DATA_TDFID, data))


UNIFORM_CARD_DATA_TDFID = 0xD9060387       # Blaze::Mut::UniformCardData
CARDTYPE_UNIFORM = 5
# Every lineup also needs a light (away) and a dark (home) uniform item ("does not have a valid away uniform item").
# (card id, instance id, team asset, uniform asset, uniform prefix, isLight). Asset naming from live memory
# ("Patriots_Home_Uni"); the away name follows the same pattern - UNVERIFIED in game.
# officialType (OFTP) is looked up by name in the game's officials-uniform list; an EMPTY string is passed on as
# NULL and crashes the lookup (@0x3257490 via 0x476fcdf, 10-16). Exact valid names still unverified.
OFFICIAL_TYPE = "Default"
UNIFORMS = [(9_200_011, 9_300_011, "Patriots", "Patriots_Away_Uni", "Away", True),
            (9_200_012, 9_300_012, "Patriots", "Patriots_Home_Uni", "Home", False)]


def uniform_card(card_id, iid, team, asset, prefix, light):
    data = body(enc_int("ISLT", int(light)), enc_str("TASN", team), enc_str("TPFX", team), enc_str("UASN", asset),
                enc_str("UPFX", prefix), enc_str("OFTP", OFFICIAL_TYPE))
    name = f"{team} {prefix}"
    return body(enc_int("CIID", iid), enc_int("ID", card_id), enc_int("TYPE", CARDTYPE_UNIFORM), enc_int("TIER", 3),
                enc_int("CSTE", CARDSTATE_ACTIVE), enc_str("NAM1", name), enc_str("NAM2", ""), enc_str("CNAM", name),
                enc_int("AQMT", 5), enc_int("CNTR", CONTRACT_GAMES), enc_var("DATA", UNIFORM_CARD_DATA_TDFID, data),
                enc_var("STDT", UNIFORM_CARD_DATA_TDFID, data))


STADIUM_CARD_DATA_TDFID = 0xA5CFBE0A       # Blaze::Mut::StadiumCardData {STDM stadiumId}
CARDTYPE_STADIUM = 4
# ...and a stadium item. stadiumId = first u16 of the game's stadium table records (live memory, 10-15):
# 10 State Farm, 14 Arrowhead, 16 Lucas Oil, 28 MetLife (NYG), 40 Gillette, 46 M&T Bank, 52 CenturyLink, ...
STADIUM = (9_200_021, 9_300_021, 40, "Gillette Stadium")


def stadium_card(card_id, iid, stadium_id, name):
    data = body(enc_int("STDM", stadium_id))
    return body(enc_int("CIID", iid), enc_int("ID", card_id), enc_int("TYPE", CARDTYPE_STADIUM), enc_int("TIER", 3),
                enc_int("CSTE", CARDSTATE_ACTIVE), enc_str("NAM1", name), enc_str("NAM2", ""), enc_str("CNAM", name),
                enc_int("AQMT", 5), enc_int("CNTR", CONTRACT_GAMES), enc_var("DATA", STADIUM_CARD_DATA_TDFID, data),
                enc_var("STDT", STADIUM_CARD_DATA_TDFID, data))


def playbook_cards():
    """The non-player items every lineup equips: off/def playbook, away/home uniform, stadium."""
    return [playbook_card(*p) for p in PLAYBOOKS] + [uniform_card(*u) for u in UNIFORMS] + [stadium_card(*STADIUM)]


def playbook_lineup_fields():
    """LineupInfo fields that equip the playbooks and uniforms (UNFA/UNFI light, UNFH/UNI dark)."""
    (ocid, oiid, _, _), (dcid, diid, _, _) = PLAYBOOKS
    (acid, aiid, *_), (hcid, hiid, *_) = UNIFORMS
    return [enc_int("OFFP", ocid), enc_int("OFFI", oiid), enc_int("DEFP", dcid), enc_int("DEFI", diid),
            enc_int("UNFA", acid), enc_int("UNFI", aiid), enc_int("UNFH", hcid), enc_int("UNI", hiid),
            enc_int("STDM", STADIUM[0]), enc_int("STDI", STADIUM[1])]


# The UI resolves images as "swap:<a>:<b>|netres:<id>" (format @0x6576dc6, game's own "swap:400:40|netres:dcpi-
# 00000106"): swap = local swappable texture slot, netres id = NetResCache download <NETRESOURCE_IMAGE_BASE_URL><id>.
# The archive keeps Muthead's compact form "32,1|lgnd-00052129" / "26,10100112", which the client never turned into
# a request (10-14..10-17: only dcpi/mthb/stor/kdfu ids were fetched). IMAGE_FORM "raw" sends the archive string.
IMAGE_FORM = "swap"


def image_ref(s):
    s = s or ""
    if IMAGE_FORM == "raw" or not s or s.startswith("swap:"):
        return s
    if "|" not in s and "," not in s:                    # bare netres id, e.g. "pgrm-00001028"
        s = "|" + s
    swap, _, net = s.partition("|")
    a, _, b = swap.partition(",")
    out = f"swap:{a}:{b or 0}" if a else "swap:32:1"     # "|pgrm-00001023": no swap part -> card-art default
    if not net and SWAP_NETRES_FALLBACK and a in ("25", "26"):
        # Core cards ("26,10100112") name a local swappable texture that this build doesn't have (silhouette, 10-17);
        # tools/art_download.py saved EA's texture as mutdata/art/cards/swap-26-10100112.* -> serve it via netres.
        net = f"swap-{a}-{b}"
    return f"{out}|netres:{net}" if net else out


SWAP_NETRES_FALLBACK = True


def program(c):
    p = c.get("program") or {}
    color = int((p.get("hex_color") or "#000000")[1:], 16)
    return enc_struct("PRGM", enc_int("PCOL", color), enc_str("PRDS", p.get("description") or ""),
                      enc_int("PRID", p.get("external_id") or 0), enc_str("PRNM", p.get("name") or ""),
                      enc_str("SIMG", image_ref(p.get("external_image_name"))))


def card(c, instance_id):
    """Blaze::Mut::Card body (no terminator) for one owned card instance."""
    pcd = player_card_fields(c)
    data = body(*enc_fields(pcd), position_ovrs(c))
    return body(
        enc_int("CIID", instance_id), enc_int("ID", c["external_id"]), enc_int("TYPE", CARDTYPE_PLAYER),
        enc_int("TIER", c.get("tier") or 0), enc_int("TMID", pcd.get("TEAM", 0)), enc_int("CSTE", CARDSTATE_ACTIVE),
        enc_str("NAM1", c.get("first_name") or ""), enc_str("NAM2", c.get("last_name") or ""),
        enc_str("CNAM", f"{(c.get('first_name') or ' ')[0]}. {c.get('last_name') or ''}"),
        enc_str("DESC", c.get("description") or ""), enc_str("LDSC", c.get("long_description") or ""),
        enc_int("CVLU", c.get("quicksell_amount") or 0), enc_int("DVLU", c.get("quicksell_amount") or 0),
        enc_int("IAUC", int(bool(c.get("can_auction")))), enc_int("ITRD", int(bool(c.get("can_trade")))),
        enc_int("ICOL", int(bool(c.get("is_collectible")))), enc_int("ICEX", int(bool(c.get("is_unlimited_use")))),
        enc_int("ISUP", int(bool(c.get("is_upgradeable")))), enc_int("AQMT", 5),
        # games left on the contract: 0 = "players without games" -> the lineup is invalid and no game starts
        enc_int("CNTR", CONTRACT_GAMES),
        # EA image reference, e.g. "32,1|lgnd-00052129" (= muthead's .../assets/lgnd-00052129.png)
        enc_str("MIMG", image_ref(c.get("external_image_name"))),
        program(c), enc_var("DATA", PLAYER_CARD_DATA_TDFID, data),
        # STDT staticCardData: the client reads POS/positionOvrRatings from here (NULL -> crash @0x46ed0f7,
        # [card+0x1d0] = STDT object; DATA's is [card+0x1b0]).
        enc_var("STDT", PLAYER_CARD_DATA_TDFID, data),
    )

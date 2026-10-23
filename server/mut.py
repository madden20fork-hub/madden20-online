"""Madden 20 Ultimate Team — Blaze component 0x802 (MutComponent). Hot-reloaded with handlers.py.
Command ids: the client's name switch @0x266abe0 (`add esi,-8`, so id = index + 8) -> dump/mut_cmds.txt.
Schemas: tools/tdfrefl.py Blaze::Mut::<Class>; enum values: tools/enumvals.py Blaze::Mut::<Enum>."""
import importlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import draft
import mut_cards
import mut_team
import store
import team_items
from tdf import INT, MAP, REPLY, body, enc_int, enc_list_struct, enc_str, enc_struct, frame, str_to_tag, write_varint

importlib.reload(mut_cards)
importlib.reload(mut_team)
importlib.reload(draft)
importlib.reload(store)
importlib.reload(team_items)

MUT = 0x802
USER_ID = 1000000001
import platform_cfg as plat  # noqa: E402

TEAM_NAME = plat.PERSONA_NAME

# Blaze::Mut::NewUserFlowState
NUF_COMPLETE, NUF_NOTSTARTED, NUF_VIEWLINEUP, NUF_SETPACKS, NUF_IMPROVELINEUP = 4, 5, 6, 7, 8
NUF_WINSOLOCHALLENGE, NUF_MAINMENU, NUF_SKILLCHECK = 9, 10, 11
# Blaze::Mut::CurrencyType (used as the bank currency id until the real BankCurrencyEntry ids are known)
COIN, POINT, TICKET = 1, 2, 3
WALLET = {COIN: 1_000_000, POINT: 0, TICKET: 0}

COMMANDS = {}
_names = Path(__file__).resolve().parent.parent / "dump" / "mut_cmds.txt"
if _names.exists():
    for line in _names.read_text().splitlines():
        cid, _, name = line.partition(" ")
        if cid.startswith("0x") and name:
            COMMANDS[(MUT, int(cid, 16))] = f"Mut.{name}"


def reply(hdr, payload):
    return [frame(hdr["comp"], hdr["cmd"], hdr["seq"], payload, REPLY)]


def enc_map_int_int(tag, d):
    # TDF maps are sorted vector maps on the client (looked up by binary search) -> always emit keys ascending
    raw = b"".join(write_varint(k) + write_varint(v) for k, v in sorted(d.items()))
    return str_to_tag(tag) + bytes([MAP, INT, INT]) + write_varint(len(d)) + raw


def enc_map_int_struct(tag, d):
    """d: {int key: bytes of struct fields (no terminator)}"""
    from tdf import STRUCT
    raw = b"".join(write_varint(k) + v + b"\0" for k, v in sorted(d.items()))  # keys ascending (sorted map)
    return str_to_tag(tag) + bytes([MAP, INT, STRUCT]) + write_varint(len(d)) + raw


def enc_map_int_list_int(tag, d):
    """d: {int key: [ints]} -> map<int, list<int>> (each value = elem type, count, elems)."""
    from tdf import LIST
    raw = b"".join(write_varint(k) + bytes([INT]) + write_varint(len(v)) + b"".join(write_varint(x) for x in v)
                   for k, v in sorted(d.items()))
    return str_to_tag(tag) + bytes([MAP, INT, LIST]) + write_varint(len(d)) + raw


# Blaze::Mut::ActiveAbilityEnableGroup
ABILITY_GROUP_OFFENSE, ABILITY_GROUP_DEFENSE = 1, 2


SEND_PAGM = False   # 10-17: off while testing crash 3 (PAGM marks players as active-ability players)


def pagm(t):
    return [ability_groups(t)] if SEND_PAGM else []


def ability_groups(t, n=3):
    """LineupInfo.PAGM playerAbilityGroupMap: map<ActiveAbilityEnableGroup, list<uint64 card instance id>>.
    Guess (10-17): the game's per-team 3-slot player list at MutGameManager+0x50/+0x70 (written to TDB 'PMSB' as
    PGIDs, read unconditionally -> crash @0x61173b4 when empty) is built from this. Top-OVR starters per side."""
    groups = {}
    for gid, side in ((ABILITY_GROUP_OFFENSE, mut_team.OFFENSE), (ABILITY_GROUP_DEFENSE, mut_team.DEFENSE)):
        seen = {}
        for name in side:
            for iid in t["depth"].get(str(mut_team.POS[name]), [])[:1]:
                c = mut_team.card_of(t, iid)
                if c:
                    seen[int(iid)] = c["overall"]
        groups[gid] = sorted(seen, key=lambda i: -seen[i])[:n]
    return enc_map_int_list_int("PAGM", groups)


def wallet(tag="UBNK"):
    # Blaze::Mut::UserBank { BCMP balances: map<uint32 bank currency id, int32> }
    return enc_struct(tag, enc_map_int_int("BCMP", {**WALLET, COIN: store.coins()}))


# Blaze::Mut::BankCurrencyCategory GRIND=1 PREMIUM=2; BankCurrencyDisplayMode MUT=1 FUSE=2 ALL=3
# Points/Training are built into the client's user bar (served ones showed up twice, 10-14) -> coins only.
CURRENCIES = {COIN: ("Coins", COIN, 1)}


def bank_currencies():
    # GetConfigurationInfoResponse.BCYM: map<uint32 id, Blaze::Mut::BankCurrencyShared>
    return enc_map_int_struct("BCYM", {
        cid: body(enc_str("BCCA", title.upper()), enc_int("BCCG", cat), enc_int("BCCT", ctype),
                  enc_int("BCDM", 3), enc_int("BCDP", n), enc_str("BCDS", title), enc_int("BCID", cid),
                  enc_str("BCTL", title))
        for n, (cid, (title, ctype, cat)) in enumerate(CURRENCIES.items())})


BINDER_SOFT_CAP, BINDER_HARD_CAP = 2_000, 3_000


def get_configuration_info(hdr, payload, st):
    # Blaze::Mut::GetConfigurationInfoResponse (42 members; filled as the client shows what it reads)
    # RSCG ReservesConfig = item binder capacity: the UI's GetCardCountLimit (native 0x47d6f10 -> 0x46fdf80) reads
    # ADSC (+0xc soft cap) / ADHC (+0x10 hard cap) from MutManager config +0x1d40. Unset = 0 -> the store refuses
    # with "Your binder has a maximum capacity of 0 items" (10-17).
    rscg = enc_struct("RSCG", enc_int("ADSC", BINDER_SOFT_CAP), enc_int("ADHC", BINDER_HARD_CAP))
    return reply(hdr, body(bank_currencies(), rscg, enc_int("CTYP", COIN), enc_int("MAXL", 5), enc_int("MAXS", 5),
                           enc_int("MCPC", 500), enc_int("MPGS", 100), enc_int("DCPS", 50),
                           enc_int("MCPG", 2000)))


def get_new_user_flow_state(hdr, payload, st):
    # Blaze::Mut::GetNewUserFlowStateResponse: tour already done -> straight to the hub.
    # SKIP canSkip=1 with an empty SKDS skipInfo shows a blank YES/NO dialog, so 0.
    return reply(hdr, body(enc_int("ATGC", 1), enc_list_struct("FLOW", []), enc_int("SKIP", 0),
                           enc_int("STAT", NUF_COMPLETE)))


def complete_new_user_flow_state(hdr, payload, st):
    # Blaze::Mut::CompleteNewUserFlowStateResponse (an empty reply = state INVALID -> tour screen again)
    return reply(hdr, body(enc_int("SKIP", 0), enc_int("STAT", NUF_COMPLETE)))


def team_info():
    # Blaze::Mut::TeamInfo
    t = mut_team.load()
    ovr, o, d = mut_team.ratings(t)
    return enc_struct("PNL", enc_int("BLAZ", USER_ID), enc_int("MLAL", 0), enc_int("TCAR", len(t["cards"])),
                      enc_int("TFND", 1), enc_str("UEST", "2026"), enc_str("UNAM", TEAM_NAME),
                      enc_int("OOVR", o), enc_int("DOVR", d), enc_int("SOVR", o), enc_int("SDVR", d),
                      enc_int("SKIL", ovr), enc_int("USKL", ovr),
                      enc_int("UCLR", 0), wallet(), enc_int("WINZ", 0), enc_int("LOSZ", 0), enc_int("TIEZ", 0))


def get_team_info(hdr, payload, st):
    return reply(hdr, body(team_info()))


def get_hub_data(hdr, payload, st):
    # Blaze::Mut::GetHubDataResponse
    return reply(hdr, body(wallet(), enc_int("NPAC", len(store.state()["packs"])), enc_int("NCOL", 0), enc_int("CCOL", 0)))


# ---------------- cards / lineup ----------------
def req_fields(payload):
    from tdf import decode_tdf
    try:
        return {t: v for t, _, v in decode_tdf(payload)}
    except Exception:  # noqa: BLE001
        return {}


def depth_map(t, tag="DMAP"):
    # map<int32 PlayerPositionEnum, Blaze::Mut::DepthChartEntityArray{DLST list<DepthChartEntity>}>
    out = {}
    for slot, iids in t["depth"].items():
        ents = []
        for depth, iid in enumerate(iids):
            c = mut_team.card_of(t, iid)
            if not c:
                continue
            ents.append(body(enc_int("CID", c["external_id"]), enc_int("DPTH", depth),
                             enc_int("EOVR", c["overall"]), enc_int("PID", c["external_player_id"]),
                             enc_int("SEOV", c["overall"]), enc_int("UID", int(iid))))
        out[int(slot)] = enc_list_struct("DLST", ents)
    return enc_map_int_struct(tag, out)


def lineup_info(t, coach=None, team_ids=False):
    ovr, o, d = mut_team.ratings(t)
    cf = [enc_int("CCH", coach["cid"]), enc_int("CCI", coach["iid"])] if coach else []
    tids = [enc_int("HTID", team_identity(t)), enc_int("ATID", team_identity(t))] if SEND_TEAM_IDS else []
    return enc_struct("LINE", enc_int("MLID", 0), enc_str("MLNA", "Lineup 1"), enc_int("OVRL", ovr),
                      enc_int("OOVR", o), enc_int("DOVR", d), enc_int("BOVR", ovr), enc_int("BOOV", o),
                      enc_int("BDOV", d), *pagm(t), *cf, *tids,
                      *team_items.lineup_fields(t, with_coach=not cf, team_ids=team_ids))


SEND_TEAM_IDS = False   # 10-17: tried for crash 3, no effect; values unverified


def team_identity(t):
    """LineupInfo HTID/ATID (home/away team id; never sent before 10-17 -> game-load away TGID was 0). Guess: the
    squad's most common card TEAM id (archive external ids, unverified against the game's TGIDs)."""
    import collections
    c = collections.Counter()
    for iids in t["depth"].values():
        for i in iids:
            cd = mut_team.card_of(t, i)
            if cd and cd.get("team"):
                c[cd["team"]["external_id"]] += 1
    return c.most_common(1)[0][0] if c else 1


def team_coach(t):
    """Coach item of a game team. The game-load lineup check (@0x3399b60, "The lineup does not have a valid coach
    item.") fails without one -> error code [0xabeb9bc] = 1 home / 2 away -> no rosters built -> crash @0x61173b4.
    Drafted teams have their own; CPU / plain MUT squads get a fixed coach with an unused instance id."""
    if t.get("coach"):
        return t["coach"]
    cid = team_items.selection(t)["coach"]            # the active Team Strategy coach (user / CPU team's HC)
    return {"cid": cid, "iid": team_items.iid_of(cid)}


def item_cards(t):
    """Active Team Strategy / Team Visuals cards except the coach (sent separately as the lineup coach)."""
    return [team_items.card(cid) for slot, cid in team_items.selection(t).items() if slot != "coach"]


def lineup_iids(t):
    seen = []
    for iids in t["depth"].values():
        for iid in iids:
            if iid not in seen:
                seen.append(iid)
    return seen


def deck(t, iids, tag="DECK"):
    return enc_list_struct(tag, [mut_cards.card(mut_team.card_of(t, i), int(i)) for i in iids
                                 if mut_team.card_of(t, i)])


def get_deck_page(hdr, payload, st):
    # GetDeckPageRequest {OFST offset, NUM count, FLTR filterBase(2 = ACTIVE_LINEUP)} -> {DECK, TOT, CIDL}
    # DeckPageFilterType: 0 ALL, 2 ACTIVE_LINEUP, 3 ACTIVE_ITEMS, 4 LIGHT_UNIFORM, 5 DARK_UNIFORM, 6 OFF_PLAYBOOK,
    # 7 DEF_PLAYBOOK (the Lineup screen's Team Strategy / Team Visuals pickers). Item cards = team_items.
    q = req_fields(payload)
    t = mut_team.load()
    flt = q.get("FLTR", 0)
    off, num = q.get("OFST", 0), q.get("NUM", 50) or 50
    if flt in DECK_ITEM_FILTERS:
        slot = DECK_ITEM_FILTERS[flt]
        # The coach / stadium pickers ask ACTIVE_ITEMS with OMID = the equipped instance (10-17): list every owned
        # item of that instance's type instead of the 6 equipped ones.
        omid = team_items.cid_of_iid(q.get("OMID", 0)) if q.get("OMID") else None
        if slot == "active" and omid:
            slot = team_items.catalog()[omid]["slot"]
        ids = list(team_items.selection(t).values()) if slot == "active" else team_items.owned(slot)
        if flt in (4, 5):                  # both uniform slots ask filter 5 (measured): offer every uniform
            ids = team_items.owned("away_uni" if flt == 4 else "home_uni") + \
                  team_items.owned("home_uni" if flt == 4 else "away_uni")
        page = ids[off:off + num]
        st["log"](f"   deck page filter={flt} ({slot}) {off}+{num} -> {len(page)}/{len(ids)} "
                  f"FNLT={q.get('FNLT')!r:.120}")
        return reply(hdr, body(enc_list_struct("DECK", [team_items.card(c) for c in page]), enc_int("TOT", len(ids))))
    iids = lineup_iids(t) if flt == 2 else sorted(t["cards"], key=int)
    # the binder (0): players, then every team item; the active lineup (2): players + the equipped items
    items = team_items.owned() if flt == 0 else list(team_items.selection(t).values()) if flt == 2 else []
    total = len(iids) + len(items)
    page = iids[off:off + num]
    extra = items[max(0, off - len(iids)):max(0, off + num - len(iids))]
    st["log"](f"   deck page filter={flt} {off}+{num} -> {len(page)}+{len(extra)}/{total} FNLT={q.get('FNLT')!r:.120}")
    cards = [mut_cards.card(mut_team.card_of(t, i), int(i)) for i in page if mut_team.card_of(t, i)]
    return reply(hdr, body(enc_list_struct("DECK", cards + [team_items.card(c) for c in extra]),
                           enc_int("TOT", total)))


DECK_ITEM_FILTERS = {3: "active", 4: "away_uni", 5: "home_uni", 6: "off_pb", 7: "def_pb"}


def set_non_player_item_to_active(hdr, payload, st):
    # SetNonPlayerItemToActiveRequest {CIID cardInstanceId, NPIT NonPlayerItemType (0 coach, 1 stadium, 2 away uni,
    # 3 home uni, 4 def playbook, 5 off playbook), MLID lineupId, ISPR isPreview, CITM cosmetic, LRST}
    # -> {MSG, IPIA newItemName, IRIA oldItemName, TCCP newCard, LINE lineup, SLRY}
    q = req_fields(payload)
    t = mut_team.load()
    slot = team_items.SLOTS.get(q.get("NPIT", -1))
    cid = team_items.cid_of_iid(q.get("CIID", 0))
    cat = team_items.catalog()
    if slot is None or cid is None:
        st["log"](f"   set item: unknown slot/card {q}")
        return reply(hdr, body(ok_msg()))
    old = team_items.selection(t)[slot]
    if not q.get("ISPR"):
        t.setdefault("items", {})[slot] = cid
        mut_team.save(t)
    st["log"](f"   set item {slot}: {cat[old]['name']} -> {cat[cid]['name']}{' (preview)' if q.get('ISPR') else ''}")
    return reply(hdr, body(ok_msg(), enc_str("IPIA", cat[cid]["name"]), enc_str("IRIA", cat[old]["name"]),
                           enc_struct("TCCP", team_items.card(cid)), lineup_info(t, team_coach(t)),
                           enc_int("SLRY", 0)))


def get_depth_chart(hdr, payload, st):
    t = mut_team.load()
    n = sum(len(v) for v in t["depth"].values())
    return reply(hdr, body(depth_map(t), lineup_info(t), enc_int("DCPC", n), enc_int("FLEX", 0)))


# ---------------- solo games vs CPU ----------------
CATEGORY_ID, SEQUENCE_ID = 1, 1


def cpu_team(game_id):
    """Opponent built from the archive: NFL team of the game id, seeded so it is stable."""
    teams = sorted({(c.get("team") or {}).get("abbreviation") for c in mut_cards.catalog().values()} - {None})
    abbr = teams[(game_id - 1) % len(teams)] if teams else "KC"
    t = mut_team.build_starter(f"team:{abbr}", seed=game_id, first_iid=200_000_001 + game_id * 1000)
    t["items_team"] = abbr
    return abbr, t


def cpu_game(game_id):
    abbr, t = cpu_team(game_id)
    ovr, o, d = mut_team.ratings(t)
    return body(enc_int("GMID", game_id), enc_str("TITL", f"Ultimate Challenge: {abbr}"),
                enc_str("CPUN", f"MUT {abbr}"), enc_str("DESC", f"Beat the MUT {abbr} squad."),
                enc_str("AILV", "All-Pro"), enc_int("STAT", 2), enc_int("QTRL", 5), enc_int("STYL", 0),
                enc_int("FRMT", 0), enc_int("PRES", 4), enc_int("WEID", 0), enc_int("UIHM", 1),
                enc_int("TOVR", ovr), enc_int("OOVR", o), enc_int("DOVR", d), enc_int("CONT", 0))


def get_cpu_team_game_categories(hdr, payload, st):
    n = len({(c.get("team") or {}).get("abbreviation") for c in mut_cards.catalog().values()}) or 1
    cat = body(enc_int("CTID", CATEGORY_ID), enc_str("TITL", "Ultimate Challenges"),
               enc_str("DESC", "Solo games against MUT squads"), enc_int("NGAV", n), enc_int("NGCO", 0))
    dflt = enc_struct("DFLT", enc_int("CTID", CATEGORY_ID), enc_int("SQID", SEQUENCE_ID), enc_int("GMID", 1),
                      enc_str("TITL", "Ultimate Challenges"), enc_str("DESC", ""))
    return reply(hdr, body(enc_list_struct("CATL", [cat]), dflt))


def get_cpu_team_games_for_sequence(hdr, payload, st):
    n = len({(c.get("team") or {}).get("abbreviation") for c in mut_cards.catalog().values()}) or 1
    games = [cpu_game(i) for i in range(1, n + 1)]
    seq = enc_struct("GAML", enc_int("SQID", SEQUENCE_ID), enc_str("TITL", "Ultimate Challenges"),
                     enc_str("DESC", "Beat every MUT squad"), enc_list_struct("GAML", games),
                     enc_int("NGAM", n), enc_int("NGUN", n), enc_int("NGWN", 0), enc_int("RGCN", n))
    return reply(hdr, body(seq))


def team_game_data(tag, t, name):
    cards = [mut_cards.card(mut_team.card_of(t, i), int(i)) for i in lineup_iids(t) if mut_team.card_of(t, i)]
    coach = team_coach(t)
    cards.append(draft.coach_card(coach["cid"], coach["iid"]))
    return enc_struct(tag, enc_list_struct("DECK", cards + item_cards(t)), depth_map(t),
                      lineup_info(t, coach, team_ids=True), enc_str("UNAM", name))


def get_game_data(hdr, payload, st):
    # GetGameDataRequest {GMID cpuTeamGameGameId, HPER, APER, SEAS}
    q = req_fields(payload)
    gid = q.get("GMID", 1) or 1
    abbr, cpu = cpu_team(gid)
    st["log"](f"   game data: game {gid} vs {abbr}")
    return reply(hdr, body(team_game_data("HINF", mut_team.load(), TEAM_NAME),
                           team_game_data("AINF", cpu, f"MUT {abbr}"), enc_int("PRES", 4)))


def get_render_data(hdr, payload, st):
    # GetRenderDataResponse {HRDA, ARDA}: same RenderData as Dc_GetGameAndRenderData (see render_data)
    q = req_fields(payload)
    abbr, cpu = cpu_team(q.get("GMID", 1) or 1)
    return reply(hdr, body(render_data("HRDA", mut_team.load()), render_data("ARDA", cpu)))


_GENERIC_HEADS = None


def generic_heads():
    """[(GenericHead enum value 1..407, skin digit)] from the game's GenericHead_<skin>_* enum (mutdata file)."""
    global _GENERIC_HEADS
    if _GENERIC_HEADS is None:
        _GENERIC_HEADS = json.loads((ROOT / "mutdata" / "generic_heads.json").read_text())
    return _GENERIC_HEADS


def enc_float(tag, v):
    from tdf import FLOAT
    return str_to_tag(tag) + bytes([FLOAT]) + struct.pack(">f", v)


MORPHS = ["MBTA", "MBTT", "MCFA", "MCFT", "MCHA", "MCHT", "MFTA", "MFTT", "MGTA", "MGTT", "MSHA", "MSHT", "MTHA",
          "MTHT", "MUAA", "MUAT", "MWRA", "MWRT"]


def render_data(tag, t):
    """Blaze::Mut::RenderData {PCRD list<PlayerCardRenderData>, CCRD map<uint32, CoachCardRenderData>}.
    REQUIRED (10-17): the MUT roster commit (0x476d970) runs, per PCRD entry, `update <temp> set ... 'PGHE' =
    GNHD ... where 'POID' = PLID` (0x476dd50), then `delete from <temp> where 'PGHE' = 0` -> without an entry with a
    non-zero genericHead every player is dropped, PLGA ends up empty, nobody gets ability-hub entries / field slots
    -> crash @0x20e2ff6. Appearance is not archived: deterministic generic head + matching skin, neutral morphs."""
    heads = generic_heads()
    ents = []
    for iid in lineup_iids(t):
        c = mut_team.card_of(t, iid)
        if not c:
            continue
        pid = int(c["external_player_id"])
        head, skin = heads[pid % len(heads)]
        ents.append(body(enc_int("PLID", pid), enc_int("GNHD", head), enc_int("SKIN", skin - 1),
                         *[enc_float(m, 0.5) for m in MORPHS]))
    return enc_struct(tag, enc_list_struct("PCRD", ents))


def empty_ok(hdr, payload, st):
    return reply(hdr, b"")


# ---------------- event system (Mut.Dc_*): MUT "Challenges" AND Draft Champions run on it ----------------
# PLAY > Challenges sends Dc_GetEventGroups with EVGT gameMode 4 (SOLOCHALLENGES) — not GetCpuTeamGame*.
GAMEMODE_SOLOCHALLENGES = 4
DRAFTEVENTTYPE_CPU_MUT, DRAFTSTATE_AVAILABLE, EVENTAVAILABILITY_PLAYABLE, SKILL_ALLPRO = 14, 1, 3, 2
EVENT_GROUP_ID = 1
FAR_FUTURE_US = 4_102_444_800 * 1_000_000      # 2100-01-01
from tdf import enc_time  # noqa: E402


def nfl_teams():
    return sorted({(c.get("team") or {}).get("abbreviation") for c in mut_cards.catalog().values()} - {None})


def access_rule(tag):
    return enc_struct(tag, enc_int("ACRI", 0), enc_int("CURV", 1), enc_str("DESC", ""), enc_str("SDES", ""))


def event_group(n_events):
    return body(enc_int("EGID", EVENT_GROUP_ID), enc_int("EVGM", GAMEMODE_SOLOCHALLENGES),
                enc_str("TITL", "Ultimate Challenges"), enc_str("DESC", "Beat every MUT squad, one NFL team at a time."),
                enc_int("NGAV", n_events), enc_int("NGCO", 0), enc_int("PRIO", 1),
                from_ids("EIDL", list(range(1, n_events + 1))),
                enc_time("VSTM", 0), enc_time("PSTM", 0), enc_time("VETM", FAR_FUTURE_US), enc_time("PETM", FAR_FUTURE_US),
                access_rule("PACR"), access_rule("VACR"))


def from_ids(tag, ids):
    from tdf import enc_list_int
    return enc_list_int(tag, ids)


def draft_event(eid, abbr):
    return body(enc_int("DFID", eid), enc_str("NAME", f"vs MUT {abbr}"), enc_str("DESC", f"Beat the MUT {abbr} squad."),
                enc_int("TYPE", DRAFTEVENTTYPE_CPU_MUT), enc_int("STAT", DRAFTSTATE_AVAILABLE),
                enc_int("AVAL", EVENTAVAILABILITY_PLAYABLE), enc_int("CPU", 1), enc_int("CPUS", SKILL_ALLPRO),
                enc_int("ATLP", 1), enc_int("FREE", 1), enc_int("QTRL", 5), enc_int("NGAM", 1), enc_int("NGWN", 0),
                enc_int("MXGM", 1), enc_int("TOTR", 0), enc_int("EVGI", EVENT_GROUP_ID), enc_int("ISRK", 0),
                enc_int("SESO", 0), enc_int("SGEB", 1), enc_int("VSBL", 1),
                # win/loss progress: default winsNeeded=0 makes the client mark the event COMPLETE (0 wins needed).
                enc_int("WIN", 0), enc_int("WINN", 1), enc_int("LOSS", 0), enc_int("LOSN", 0),
                enc_time("STRT", 0), enc_time("ENDT", FAR_FUTURE_US), access_rule("PACR"))


def dc_get_event_groups(hdr, payload, st):
    q = req_fields(payload)
    st["log"](f"   event groups for gameMode {q.get('EVGT')}")
    return reply(hdr, body(enc_list_struct("EVGL", [event_group(len(nfl_teams()))])))


def dc_get_events_in_group(hdr, payload, st):
    teams = nfl_teams()
    return reply(hdr, body(enc_list_struct("SEQL", [draft_event(i + 1, t) for i, t in enumerate(teams)])))


DRAFTSTATE_IN_PROGRESS, EVENTSCENARIOSTATUS_ACTIVE = 4, 1


def home_team(eid):
    """The user's side of an event game: the drafted team for a draft event, otherwise the MUT team."""
    if draft.is_draft_event(eid):
        return draft.drafted_team() or mut_team.load()
    return mut_team.load()


def event_team(eid):
    import h2h
    importlib.reload(h2h)
    hev = h2h.event_of_instance(eid)
    if hev:                                    # H2H Seasons game: this week's CPU-controlled opponent squad
        return h2h.opponent(hev)
    teams = nfl_teams()
    if draft.is_draft_event(eid):
        d = draft.load() or {}
        eid = d.get("instance", 0) % 97 + d.get("wins", 0) + 1     # a new CPU squad each round of the run
    abbr = teams[(eid - 1) % len(teams)] if teams else "KC"
    t = mut_team.build_starter(f"team:{abbr}", seed=eid, first_iid=200_000_001 + eid * 1000)
    t["items_team"] = abbr
    return abbr, t


def ok_msg():
    # Blaze::Mut::ResponseData {RCDE uiErrorCode=0 = success}
    return enc_struct("MSG", enc_int("RCDE", 0))


def dc_start_draft(hdr, payload, st):
    # StartDraftRequest {DFID, FTID, POID, PAMT, TAMT} -> StartDraftResponse {MSG, DRFT DraftInfo, TKTS, PNTS}
    q = req_fields(payload)
    eid = q.get("DFID", 1) or 1
    if draft.is_draft_event(eid):
        return draft.dc_start_draft(hdr, payload, st)
    t = mut_team.load()
    st["log"](f"   start draft/event {eid}")
    # The client caches this DraftInfo as the event's lineup; PLAY GAME validates it (coach, off/def playbook,
    # uniforms, stadium, contracts) -> send the full deck incl. coach + team items (10-17 H2H: without them
    # "Invalid Lineup Warning ... valid defensive playbook item" and an empty event lineup editor).
    coach = team_coach(t)
    cards = [mut_cards.card(mut_team.card_of(t, i), int(i)) for i in lineup_iids(t) if mut_team.card_of(t, i)]
    cards.append(draft.coach_card(coach["cid"], coach["iid"]))
    info = enc_struct("DRFT", enc_int("DFID", eid), enc_int("INST", 50_000 + eid),
                      enc_int("STAT", DRAFTSTATE_IN_PROGRESS),
                      enc_list_struct("DECK", cards + item_cards(t)), depth_map(t, "DEPC"),
                      lineup_info(t, coach))
    return reply(hdr, body(ok_msg(), info, enc_int("TKTS", 0), enc_int("PNTS", 0)))


# Blaze::Mut::HouseRule -> value: standard NFL rules. The client reads these while writing the game setup into
# its database; with no houseRuleMap the rules object is NULL and the game crashes on load (@0x61173b4, 10-16).
HOUSE_RULES = {
    1: 10, 2: 4,                                    # first-down yardage, max downs
    3: 3, 4: 3, 5: 40, 6: 3, 7: 50,                 # field goal points (default/medium/long) + distances
    8: 6, 9: 6, 10: 20, 11: 6, 12: 40,              # passing TD points + distances
    13: 6, 14: 6, 15: 2, 16: 1, 17: 1, 18: 2,       # def/ST TD, safety, safety on PAT, kick PAT, 2-pt conversion
    19: 0, 20: 0, 21: 0, 22: 0, 23: 0,              # audibles / hot routes allowed, default OT rules
    24: 0, 25: 0, 26: 0, 27: 0,                     # QB scramble, pre-play movement, player switch allowed
    28: 6, 29: 6, 30: 20, 31: 6, 32: 40,            # rushing TD points + distances
    33: 0, 34: 25,                                  # kickoffs on, (skip-kickoff spot)
}


def game_settings():
    # Blaze::Mut::MutGameSettings: All-Pro, arcade, 5-minute quarters, standard house rules
    return enc_struct("STGS", enc_int("SKIL", SKILL_ALLPRO), enc_int("STYL", 0), enc_int("QTRL", 5),
                      enc_int("PCLL", 20), enc_int("ACCE", 1), enc_int("ACCT", 20), enc_int("FATE", 1),
                      enc_int("INJE", 0), enc_map_int_int("HSRL", HOUSE_RULES))


def team_preview(tag, t, title):
    # Blaze::Mut::Dc::CustomTeamPreviewData {TITL teamTitle, LINE lineup, DECK previewCardDeck}
    return enc_struct(tag, enc_str("TITL", title), lineup_info(t), deck(t, lineup_iids(t)))


def scenario_preview(eid):
    # Blaze::Mut::Dc::EventScenarioPreview: one scenario (the single game of this event)
    abbr, cpu = event_team(eid)
    # SCND = Blaze::Mut::Dc::ScenarioPreviewData {TITL, DESC, UIHM, HTPV, ATPV (CustomTeamPreviewData), STGS}
    scnd = enc_struct("SCND", enc_str("TITL", f"vs MUT {abbr}"), enc_str("DESC", f"Beat the MUT {abbr} squad."),
                       enc_int("UIHM", 1), team_preview("HTPV", home_team(eid), TEAM_NAME),
                       team_preview("ATPV", cpu, f"MUT {abbr}"), game_settings())
    return body(enc_struct("SEQI", enc_int("SEQI", eid), enc_int("GMID", 1)), enc_int("MATP", 99), enc_int("FEAT", 0),
                scnd, enc_struct("USDA", enc_int("GSTS", EVENTSCENARIOSTATUS_ACTIVE)),
                access_rule("PACC"), access_rule("VACC"), enc_time("SAVD", 0), enc_time("EAVD", FAR_FUTURE_US))


def dc_get_available_scenarios(hdr, payload, st):
    # GetAvailableScenariosForEventResponse {MSG, GAML list<EventScenarioPreview>, TUNS}
    q = req_fields(payload)
    eid = q.get("DFID", 1) or 1
    st["log"](f"   scenarios for event {eid}")
    return reply(hdr, body(ok_msg(), enc_list_struct("GAML", [scenario_preview(eid)])))


def dc_can_play_scenario(hdr, payload, st):
    # CanPlayScenarioResponse {MSG, PACR, VACR} — both access rules unrestricted = may play
    return reply(hdr, body(ok_msg(), access_rule("PACR"), access_rule("VACR")))


def start_of_game():
    # FootballTdf::StartOfGameConditions: 1st quarter, 0-0, 1st & 10 at own 25, home has the ball
    return enc_struct("STRT", enc_int("CDID", 1), enc_int("QTER", 1), enc_int("SINQ", 300),
                      enc_int("HSCR", 0), enc_int("ASCR", 0), enc_int("HOTO", 3), enc_int("AWTO", 3),
                      enc_int("DOWN", 1), enc_int("DIST", 10), enc_int("SCRM", 25), enc_int("IHIP", 1),
                      enc_int("ISCR", 0), enc_int("ISOT", 0))


def end_condition():
    # Blaze::Mut::EndConditionScenario: win the game (empty compare rules = play it out, higher score wins)
    return enc_struct("ENDC", enc_int("ESID", 1), enc_str("HDSC", "Win the game"), enc_str("ADSC", "Win the game"))


def presentation():
    # Blaze::Mut::GamePresentationDetails: let the engine pick stadium/weather (0 = default)
    return enc_struct("PRES", enc_int("CSTD", 0), enc_int("GTOD", 0), enc_int("WTHI", 0), enc_int("TEMP", 70))


def dc_get_game_and_render_data(hdr, payload, st):
    # GetGameAndRenderDataResponse: the data that actually launches the MUT game vs the CPU squad.
    q = req_fields(payload)
    eid = q.get("DFID", q.get("CRID", 1)) or 1
    abbr, cpu = event_team(eid)
    import h2h
    # STRT (StartOfGameConditions, CDID 1 = 1st & 10 at the 25, home ball) + ENDC ("Win the game") turn the game
    # into a challenge scenario - the owner 10-17: H2H "starts with me on offense at the opponent's 25, it should be a real
    # MUT game sequence". H2H and Draft games send neither, so the engine plays a normal game (coin toss, kickoff);
    # only the MUT solo Challenges (events 1..32) keep their scenario.
    real_game = (bool(h2h.event_of_instance(eid)) or draft.is_draft_event(eid)) and H2H_REAL_GAME
    st["log"](f"   GET GAME+RENDER for event {eid} vs {abbr}{' (full game, no scenario)' if real_game else ''}")
    scenario = [] if real_game else [start_of_game(), end_condition()]
    return reply(hdr, body(
        ok_msg(),
        team_game_data("HINF", home_team(eid), TEAM_NAME), team_game_data("AINF", cpu, f"MUT {abbr}"),
        render_data("HRDA", home_team(eid)), render_data("ARDA", cpu),
        game_settings(), *scenario, presentation(),
        enc_int("CGID", EVENT_GROUP_ID), enc_int("CRID", eid), enc_struct("CRGP", *[scenario_preview(eid)])))


H2H_REAL_GAME = True


CURRENT_GAME = ROOT / "mutdata" / "current_game.json"


def dc_process_start_of_game(hdr, payload, st):
    # ProcessStartOfGameRequest {DFID draftInstanceId, GRID, MSAB}. The end-of-game request has no event id,
    # so remember which event this game belongs to.
    # A quit sends no end-of-game, so the game is booked as a loss here and corrected by Dc_ProcessEndOfGame.
    import h2h
    importlib.reload(h2h)
    q = req_fields(payload)
    dfid = q.get("DFID", 0)
    CURRENT_GAME.write_text(json.dumps({"dfid": dfid, "grid": q.get("GRID", 0)}))
    hev = h2h.event_of_instance(dfid)
    if hev:
        opp, s = h2h.begin(hev)
        st["log"](f"   H2H start of game {len(s['games'])} vs {opp} (provisional loss, season {s['wins']}-{s['losses']})")
    elif dfid and (draft.load() or {}).get("instance") == dfid:
        draft.begin_game()
        st["log"](f"   Draft start of game (provisional loss)")
    else:
        st["log"](f"   Dc start of game: DFID {dfid}")
    return reply(hdr, body(ok_msg()))


def dc_process_end_of_game(hdr, payload, st):
    # ProcessEndOfGameRequest {SCDT scoreDelta (user - opponent), QTRS quartersPlayed, SCNI, ECIL, MSAB}
    import h2h
    importlib.reload(h2h)
    q = req_fields(payload)
    delta, quarters = q.get("SCDT", 0), q.get("QTRS", 0)
    try:
        dfid = json.loads(CURRENT_GAME.read_text()).get("dfid", 0)
    except (OSError, ValueError):
        dfid = 0
    hev = h2h.event_of_instance(dfid)
    if hev:
        won, s = h2h.record(hev, delta, quarters)
        st["log"](f"   H2H end of game: delta {delta}, {quarters} qtrs -> {'WIN' if won else 'LOSS'}, "
                  f"season {s['wins']}-{s['losses']}")
    elif dfid and (draft.load() or {}).get("instance") == dfid:
        draft.record_result(delta > 0)
        st["log"](f"   Draft end of game: delta {delta} -> {'WIN' if delta > 0 else 'LOSS'}")
    else:
        st["log"](f"   end of game for unknown DFID {dfid}: delta {delta}")
    return reply(hdr, body(ok_msg()))


HANDLERS = {(MUT, 0x9): get_configuration_info, (MUT, 0xB): get_team_info, (MUT, 0x5B): get_hub_data,
            (MUT, 0x145): get_new_user_flow_state, (MUT, 0x14C): complete_new_user_flow_state,
            (MUT, 0x47): get_deck_page, (MUT, 0x22C): set_non_player_item_to_active, (MUT, 0x1A): get_depth_chart,
            (MUT, 0x15F): get_cpu_team_game_categories, (MUT, 0x162): get_cpu_team_games_for_sequence,
            (MUT, 0x4A): get_game_data, (MUT, 0x5F): get_render_data,
            (MUT, 0x2D): empty_ok, (MUT, 0x2E): empty_ok,
            (MUT, 0x2C3): dc_process_start_of_game, (MUT, 0x2C5): dc_process_end_of_game,
            (MUT, 0x2E8): dc_get_event_groups, (MUT, 0x2E9): dc_get_events_in_group,
            (MUT, 0x2BE): dc_start_draft, (MUT, 0x2E6): dc_get_available_scenarios,
            (MUT, 0x2EA): dc_can_play_scenario, (MUT, 0x2D0): dc_get_game_and_render_data}
HANDLERS.update({(MUT, cid): fn for cid, fn in draft.HANDLERS.items()})
HANDLERS.update({(MUT, cid): fn for cid, fn in store.HANDLERS.items()})

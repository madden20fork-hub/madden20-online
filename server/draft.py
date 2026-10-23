"""Madden 20 MUT Draft (Draft Champions) - the Mut.Dc_* draft commands of component 0x802. Hot-reloaded via mut.py.
Schemas: tools/tdfrefl.py Blaze::Mut::Dc::<Class>. One local draft at a time, persisted to mutdata/draft_state.json
(delete it to start over). A draft = a coach round, then one pick per ROUNDS slot (3 archived cards of that
position per round); the bench is filled automatically after the last pick, then the drafted team plays CPU squads.

Client facts this relies on (measured 10-14/15, see handoff):
- every id the client sees must stay < 2**31 (the draft UI passes ids through signed 32-bit ints);
- the draft UI shows exactly 3 options (numPicks = 3 hard-coded @0x46e1858);
- the header reads "ROUND <RNUM-1> OF <TOTR-1>": round 1 is the coach round (not counted), players start at RNUM 2;
- DEPC must list every lineup slot (empty until drafted), the board builds its slot grid from it;
- the event's INST must already be in the GetDraftEvents list (the client caches that list)."""
import importlib
import json
import random
from pathlib import Path

import mut_cards
import mut_team
from tdf import STRUCT, VAR, body, enc_int, enc_list_int, enc_list_struct, enc_str, enc_struct, enc_time, str_to_tag
from tdf import write_varint

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "mutdata" / "draft_state.json"

# Blaze::Mut::Dc enums
DRAFTEVENTTYPE_CPU, DRAFTEVENTTYPE_H2H_UNRANKED, DRAFTEVENTTYPE_H2H_RANKED, DRAFTEVENTTYPE_H2H_FRIEND = 1, 2, 3, 4
DS_AVAILABLE, DS_DRAFTING, DS_IN_PROGRESS, DS_COMPLETED = 1, 3, 4, 6
AVAIL_PLAYABLE = 3
ROUNDTYPE_PLAYER, ROUNDTYPE_COACH = 0, 1
DRAFTGENSTYLE_PREGEN, DRAFTGENSTYLE_DYNAMIC = 1, 2   # 0 = INVALID (the default when unset)
DCNUF_COMPLETE = 1
SKILL_ALLPRO = 2
CARDTYPE_COACH, CARDSTATE_ACTIVE = 2, 1
COACH_CARD_DATA_TDFID = 0x05578D39                    # Blaze::Mut::CoachCardData (typeinfo high dword)

SOLO_DRAFT_ID = 1001          # event ids >= 1000 are drafts; 1..32 are the MUT Challenges (mut.py)
FAR_FUTURE_US = 4_102_444_800 * 1_000_000
INSTANCE_BASE = 10_000
IID_BASE = 1_000_000_000      # card instance ids: IID_BASE + (instance - INSTANCE_BASE) * 10_000 + round * 10 + i
WINS_NEEDED = 4               # Draft Champions solo: win 4 games or lose once

# one pick per starting slot, in PlayerPositionEnum order (the board's slot order); backups are filled automatically
ROUNDS = ["QB", "HB", "FB", "WR", "WR", "WR", "TE", "LT", "LG", "C", "RG", "RT",
          "LE", "RE", "DT", "DT", "LOLB", "MLB", "ROLB", "CB", "CB", "CB", "FS", "SS", "K", "P"]
SCHEDULE = ["COACH"] + ROUNDS
OPTIONS_PER_ROUND = 3
MIN_OPTION_OVR = 80
# coach round: (card id, coachId, first, last, ovr) = the game's 32 NFL head coaches (team_items, COCH table).
# 10-17 before that: 6 made-up entries 9_100_001..6 with wrong coachIds -> LEGACY_COACHES maps old saved picks.
import team_items  # noqa: E402

importlib.reload(team_items)
COACHES = [(cid, it["coach"], it["first"], it["last"], it["ovr"])
           for cid, it in sorted(team_items.catalog().items()) if it["slot"] == "coach"]
COACH_BY_ID = {c[0]: c for c in COACHES}
LEGACY_COACHES = {9_100_001: 12, 9_100_003: 378, 9_100_004: 92, 9_100_005: 328, 9_100_006: 228}  # -> CCID
for _old, _ccid in LEGACY_COACHES.items():
    if team_items.COACH_BASE + _ccid in COACH_BY_ID:
        COACH_BY_ID[_old] = COACH_BY_ID[team_items.COACH_BASE + _ccid]


def is_draft_event(eid):
    return 1000 <= (eid or 0) < 2000      # 2000+ = H2H events (h2h.py), no draft


# ---------------- state ----------------
def load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return None


def save(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def new_draft(eid, started=True):
    inst = INSTANCE_BASE + random.randrange(1, 99_999)
    st = {"event": eid, "instance": inst, "started": started, "round": 0, "options": {}, "picks": [], "wins": 0,
          "losses": 0, "team": None}
    save(st)
    return st


def current_or_pending(eid):
    """The event's draft record. The instance id is allocated when the event is first listed (not at StartDraft),
    so the client's cached GetDraftEvents list already carries the INST the draft will use."""
    st = load()
    if not st or st["event"] != eid or st.get("finished"):
        st = new_draft(eid, started=False)
    return st


def _pos(c):
    return c["position"]["abbreviation"]


def round_options(st, r):
    """3 card ids for round r (stable once generated): coaches in round 0, then distinct, not yet drafted players of
    the round's position spread over the OVR range (an elite option, a solid one, a value pick)."""
    key = str(r)
    if key in st["options"]:
        return st["options"][key]
    rnd = random.Random(st["instance"] * 100 + r)
    if SCHEDULE[r] == "COACH":
        picks = [c[0] for c in rnd.sample(COACHES, OPTIONS_PER_ROUND)]
    else:
        cat = mut_cards.catalog()
        taken = {cat[cid]["external_player_id"] for cid in st["picks"] if cid in cat}
        pool = [c for c in cat.values()
                if _pos(c) == SCHEDULE[r] and c["overall"] >= MIN_OPTION_OVR and c["external_player_id"] not in taken]
        rnd.shuffle(pool)
        pool.sort(key=lambda c: -c["overall"])
        picks, seen, n = [], set(), len(pool)
        for q in range(OPTIONS_PER_ROUND):
            band = pool[q * n // OPTIONS_PER_ROUND:(q + 1) * n // OPTIONS_PER_ROUND] or pool
            rnd.shuffle(band)
            for c in band:
                if c["external_player_id"] not in seen:
                    picks.append(c["external_id"])
                    seen.add(c["external_player_id"])
                    break
    st["options"][key] = picks
    save(st)
    return picks


def option_iid(st, r, i):
    return IID_BASE + (st["instance"] - INSTANCE_BASE) * 10_000 + r * 10 + i


def pick_iid(st, r):
    return option_iid(st, r, st["options"][str(r)].index(st["picks"][r]))


# ---------------- cards ----------------
def coach_card(cid, iid):
    """Blaze::Mut::Card body for a coach item: the real head-coach card from team_items (legacy ids resolve too)."""
    return team_items.card(COACH_BY_ID[cid][0], iid)


def card_body(cid, iid):
    return coach_card(cid, iid) if cid in COACH_BY_ID else mut_cards.card(mut_cards.catalog()[cid], iid)


def deck(iids_cids):
    # + the user's active Team Strategy / Team Visuals items except the coach (the draft has its own)
    items = [team_items.card(cid) for slot, cid in team_items.selection(mut_team.load()).items() if slot != "coach"]
    return enc_list_struct("DECK", [card_body(cid, iid) for iid, cid in iids_cids] + items)


def lineup(t):
    """LineupInfo of a draft team: ratings from the players, CCH/CCI = the drafted coach."""
    import mut
    ovr, o, d = mut_team.ratings(t)
    coach = t.get("coach") or {}
    return enc_struct("LINE", enc_int("MLID", 0), enc_str("MLNA", "Draft"), enc_int("OVRL", ovr), enc_int("OOVR", o),
                      enc_int("DOVR", d), enc_int("BOVR", ovr), enc_int("BOOV", o), enc_int("BDOV", d),
                      enc_int("CCH", coach.get("cid", 0)), enc_int("CCI", coach.get("iid", 0)),
                      *mut.pagm(t), *team_items.lineup_fields(mut_team.load(), with_coach=False))


def build_team(st):
    """Drafted starters + coach + automatic backups -> a mut_team-style {"cards", "depth", "coach"} dict."""
    cat = mut_cards.catalog()
    rnd = random.Random(st["instance"])
    team = {"next_iid": option_iid(st, 0, 0) + 5000, "cards": {}, "depth": {}, "coach": None}
    by_pos = {}
    for r, cid in enumerate(st["picks"]):
        iid = pick_iid(st, r)
        if SCHEDULE[r] == "COACH":
            team["coach"] = {"cid": cid, "iid": iid}
            continue
        team["cards"][str(iid)] = cid
        by_pos.setdefault(SCHEDULE[r], []).append(iid)
    used = {cat[cid]["external_player_id"] for cid in st["picks"] if cid in cat}
    for pos, n in mut_team.DEPTH.items():
        have = by_pos.setdefault(pos, [])
        if len(have) >= n:
            continue
        pool = [c for c in cat.values() if _pos(c) == pos and 70 <= c["overall"] <= 79
                and c["external_player_id"] not in used]
        if not pool:
            pool = [c for c in cat.values() if _pos(c) == pos and c["external_player_id"] not in used]
        rnd.shuffle(pool)
        for c in pool[:n - len(have)]:
            iid = team["next_iid"]
            team["next_iid"] += 1
            team["cards"][str(iid)] = c["external_id"]
            have.append(iid)
            used.add(c["external_player_id"])
    for pos, iids in by_pos.items():
        team["depth"][str(mut_team.POS[pos])] = iids
    for slot, (src, n) in mut_team.PACKAGES.items():
        team["depth"][str(mut_team.POS[slot])] = team["depth"].get(str(mut_team.POS[src]), [])[:n]
    return team


def drafted_team():
    st = load()
    if not st or not st.get("team"):
        return None
    return st["team"]


# ---------------- encoders ----------------
def ok_msg():
    return enc_struct("MSG", enc_int("RCDE", 0))


def access_rule(tag):
    return enc_struct(tag, enc_int("ACRI", 0), enc_int("CURV", 1), enc_str("DESC", ""), enc_str("SDES", ""))


def draft_state_of(st):
    if not st or not st.get("started", True):
        return DS_AVAILABLE
    if st.get("team"):
        return DS_IN_PROGRESS
    return DS_DRAFTING


def draft_event(eid=SOLO_DRAFT_ID):
    st = current_or_pending(eid)
    return body(enc_int("DFID", eid), enc_str("NAME", "Solo Draft"),
                enc_str("DESC", f"Draft a team from every era of MUT 20, then win {WINS_NEEDED} games against CPU squads."),
                enc_int("TYPE", DRAFTEVENTTYPE_CPU), enc_int("STAT", draft_state_of(st)), enc_int("INST", st["instance"]),
                enc_int("AVAL", AVAIL_PLAYABLE), enc_int("CPU", 1), enc_int("CPUS", SKILL_ALLPRO), enc_int("FREE", 1),
                enc_int("QTRL", 5), enc_int("TOTR", len(SCHEDULE)), enc_int("MXGM", WINS_NEEDED + 1),
                enc_int("WINN", WINS_NEEDED), enc_int("LOSN", 1), enc_int("WIN", st["wins"]), enc_int("LOSS", st["losses"]),
                enc_int("NGAM", WINS_NEEDED), enc_int("NGWN", st["wins"]),
                enc_int("VSBL", 1), enc_int("RSTD", 1), enc_int("SGEB", 0), enc_int("ISRK", 0),
                enc_int("DSTY", DRAFTGENSTYLE_DYNAMIC),
                enc_time("STRT", 0), enc_time("ENDT", FAR_FUTURE_US), access_rule("PACR"), access_rule("VACR"))


def wallet(tag="UBNK"):
    import mut
    return mut.wallet(tag)


def round_option(st, r, i, cid):
    if cid in COACH_BY_ID:
        _, _, first, last, ovr = COACH_BY_ID[cid]
        disp = enc_struct("DROD", enc_str("FTTL", f"{first} {last}"), enc_str("ATTL", last),
                          enc_str("STTL", "Head Coach"), enc_str("SLTL", ""))
    else:
        c = mut_cards.catalog()[cid]
        prog = (c.get("program") or {}).get("name") or ""
        disp = enc_struct("DROD", enc_str("FTTL", c.get("name") or ""), enc_str("ATTL", c.get("last_name") or ""),
                          enc_str("STTL", f"{c['overall']} OVR {_pos(c)} - {prog}"),
                          enc_str("SLTL", (c.get("archetype") or {}).get("name") or ""))
    return body(enc_struct("OPTI", card_body(cid, option_iid(st, r, i))), disp, rating_deltas(st, r, cid))


def picked_team(st, extra=None):
    """mut_team-style {"cards", "depth"} of the players picked so far (+ an optional hypothetical (round, cid))."""
    t = {"cards": {}, "depth": {}}
    picks = list(enumerate(st["picks"])) + ([extra] if extra else [])
    for r, cid in picks:
        if SCHEDULE[r] == "COACH":
            continue
        iid = str(option_iid(st, r, 9))
        t["cards"][iid] = cid
        t["depth"].setdefault(str(mut_team.POS[SCHEDULE[r]]), []).append(int(iid))
    return t


def rating_deltas(st, r, cid):
    """RoundOption.DELT {OVR, OFF, DEF}: how the pick would move the team ratings. The draft summary screen adds
    these up (no DELT -> "0 OVR 0 DEF 0 OFF")."""
    if SCHEDULE[r] == "COACH":
        return enc_struct("DELT", enc_int("OVR", 0), enc_int("OFF", 0), enc_int("DEF", 0))
    before = mut_team.ratings(picked_team(st))
    after = mut_team.ratings(picked_team(st, (r, cid)))
    return enc_struct("DELT", enc_int("OVR", after[0] - before[0]), enc_int("OFF", after[1] - before[1]),
                      enc_int("DEF", after[2] - before[2]))


def current_round(st):
    r = st["round"]
    opts = round_options(st, r)
    rtype = ROUNDTYPE_COACH if SCHEDULE[r] == "COACH" else ROUNDTYPE_PLAYER
    title = "Choose your Head Coach" if rtype == ROUNDTYPE_COACH else f"Round {r} of {len(ROUNDS)}: {SCHEDULE[r]}"
    return enc_struct("CRND", enc_int("RNUM", r + 1), enc_int("RTYP", rtype), enc_str("TITL", title),
                      enc_int("TIME", 0),
                      enc_list_struct("ROPL", [round_option(st, r, i, cid) for i, cid in enumerate(opts)]))


def draft_info(st, tag="DRFT"):
    import mut
    if st.get("team"):
        t = st["team"]
        cards = [(int(i), t["cards"][str(i)]) for i in mut.lineup_iids(t)]
        if t.get("coach"):
            cards.append((t["coach"]["iid"], t["coach"]["cid"]))
        return enc_struct(tag, enc_int("DFID", st["event"]), enc_int("INST", st["instance"]),
                          enc_int("STAT", DS_IN_PROGRESS), deck(cards), mut.depth_map(t, "DEPC"), lineup(t))
    # still drafting: every lineup slot (empty until drafted) + the picks so far
    picked = {"cards": {}, "depth": {str(mut_team.POS[p]): [] for p in list(mut_team.DEPTH) + list(mut_team.PACKAGES)},
              "coach": None}
    cards = []
    for r, cid in enumerate(st["picks"]):
        iid = pick_iid(st, r)
        cards.append((iid, cid))
        if SCHEDULE[r] == "COACH":
            picked["coach"] = {"cid": cid, "iid": iid}
        else:
            picked["cards"][str(iid)] = cid
            picked["depth"][str(mut_team.POS[SCHEDULE[r]])].append(iid)
    return enc_struct(tag, enc_int("DFID", st["event"]), enc_int("INST", st["instance"]), enc_int("STAT", DS_DRAFTING),
                      current_round(st), deck(cards), mut.depth_map(picked, "DEPC"), lineup(picked))


# ---------------- handlers ----------------
def reply(hdr, payload):
    import mut
    return mut.reply(hdr, payload)


def req(payload):
    import mut
    return mut.req_fields(payload)


def dc_handshake(hdr, payload, st):
    return reply(hdr, body(ok_msg()))


def dc_get_configuration_info(hdr, payload, st):
    import mut
    return reply(hdr, body(ok_msg(), mut.bank_currencies(), enc_int("DCPS", 50), enc_int("MPGS", 100),
                           enc_int("MCPG", 2000), enc_int("MAXL", 5), enc_int("MAXS", 5), enc_int("STUB", 0),
                           enc_time("DPCM", 0), enc_time("DRCS", 0)))


def dc_get_new_user_flow_state(hdr, payload, st):
    return reply(hdr, body(ok_msg(), enc_int("STAT", DCNUF_COMPLETE)))


def dc_get_landing_page_data(hdr, payload, st):
    q = req(payload)
    st["log"](f"   DC landing page (ranked type {q.get('RDET')})")
    types = [DRAFTEVENTTYPE_CPU, DRAFTEVENTTYPE_H2H_UNRANKED, DRAFTEVENTTYPE_H2H_RANKED, DRAFTEVENTTYPE_H2H_FRIEND]
    return reply(hdr, body(ok_msg(), enc_list_int("EVTY", types), enc_struct("RDRE", draft_event()), wallet()))


def _filter_list(v):
    """decode_tdf list value ('list', elemtype, [items]) -> [items]."""
    if isinstance(v, tuple) and len(v) == 3 and v[0] == "list":
        return list(v[2])
    return list(v) if isinstance(v, list) else []


def dc_get_draft_events(hdr, payload, st):
    import h2h
    importlib.reload(h2h)
    q = req(payload)
    filters = _filter_list(q.get("FILT"))
    st["log"](f"   DC draft events filters={filters} gameMode={q.get('GMOD')} ids={q.get('EIDL')}")
    hev = h2h.events_for(filters)
    if hev:                                       # H2H Seasons (7) / Salary Cap Ranked (8): h2h.py
        return reply(hdr, body(ok_msg(), enc_list_struct("DRTS", hev)))
    return reply(hdr, body(ok_msg(), enc_list_struct("DRTS", [draft_event()])))


PAYMENT_OPTION_ID = 1


def dc_get_event_payment_options(hdr, payload, st):
    # "Choose Reward Structure": list<Blaze::Mut::Dc::PaymentOption {ALOW, PODE PaymentOptionDetails, POPM}>.
    # An empty list leaves the screen blank; one free option = no ticket/point cost.
    q = req(payload)
    opt = body(enc_int("ALOW", 1), enc_str("POPM", ""),
               enc_struct("PODE", enc_int("POID", PAYMENT_OPTION_ID), enc_str("TITL", "Free Entry"),
                          enc_str("DESC", f"No entry cost. Win {WINS_NEEDED} games to finish the run."),
                          enc_int("ENAB", 1), enc_int("TAMT", 0), enc_int("PAMT", 0)))
    return reply(hdr, body(ok_msg(), enc_int("DFID", q.get("DFID", SOLO_DRAFT_ID) or SOLO_DRAFT_ID),
                           enc_list_struct("OPTS", [opt])))


def dc_start_draft(hdr, payload, st):
    q = req(payload)
    eid = q.get("DFID", SOLO_DRAFT_ID) or SOLO_DRAFT_ID
    d = current_or_pending(eid)
    if not d.get("started", True):
        d["started"] = True
        save(d)
        st["log"](f"   NEW draft {d['instance']} for event {eid}")
    else:
        st["log"](f"   resuming draft {d['instance']} round {d['round'] + 1}")
    return reply(hdr, body(ok_msg(), draft_info(d), enc_int("TKTS", 0), enc_int("PNTS", 0)))


def dc_resume_draft(hdr, payload, st):
    d = load() or new_draft(SOLO_DRAFT_ID)
    st["log"](f"   resume draft {d['instance']} round {d['round'] + 1} team={'yes' if d.get('team') else 'no'}")
    return reply(hdr, body(ok_msg(), draft_info(d)))


def dc_make_draft_pick(hdr, payload, st):
    q = req(payload)
    d = load()
    if not d or d.get("team"):
        return reply(hdr, body(ok_msg(), draft_info(d or new_draft(SOLO_DRAFT_ID), "PICK")))
    r = d["round"]
    opts = round_options(d, r)
    cid = q.get("CDID")
    if cid not in opts:
        st["log"](f"   pick {cid} not offered in round {r + 1} {opts} -> taking first option")
        cid = opts[0]
    d["picks"].append(cid)
    if cid in COACH_BY_ID:
        st["log"](f"   round {r + 1}/{len(SCHEDULE)} COACH: picked {COACH_BY_ID[cid][2]} {COACH_BY_ID[cid][3]}")
    else:
        c = mut_cards.catalog()[cid]
        st["log"](f"   round {r + 1}/{len(SCHEDULE)} {SCHEDULE[r]}: picked {c['name']} {c['overall']} "
                  f"({(c.get('program') or {}).get('name')})")
    d["round"] += 1
    if d["round"] >= len(SCHEDULE):
        d["team"] = build_team(d)
        st["log"](f"   draft complete: {len(d['team']['cards'])} cards, OVR {mut_team.ratings(d['team'])}")
    save(d)
    return reply(hdr, body(ok_msg(), draft_info(d, "PICK")))


def team_cards(st):
    """(iid, cid) of the finished draft team's lineup players + coach."""
    import mut
    t = st["team"]
    cards = [(int(i), t["cards"][str(i)]) for i in mut.lineup_iids(t)]
    if t.get("coach"):
        cards.append((t["coach"]["iid"], t["coach"]["cid"]))
    return cards


def dc_get_hub_data(hdr, payload, st):
    """Draft Home of an event with a finished draft (Dc_GetHubData 0x2ca, request {DFID draftInstanceId}):
    the draft team (DECK/DEPC/LINE), the event, the two best players. Asked when the event is entered again."""
    import mut
    import h2h
    importlib.reload(h2h)
    hev = h2h.event_of_instance(req(payload).get("DFID"))
    if hev:
        return reply(hdr, h2h.hub_data(hev, st))
    d = load()
    if not d or not d.get("team"):
        st["log"](f"   DC hub data: no finished draft ({'none' if not d else 'round ' + str(d['round'] + 1)})")
        return reply(hdr, body(ok_msg(), enc_struct("DRTS", draft_event())))
    t = d["team"]
    cat = mut_cards.catalog()
    best = sorted(((cat[cid]["overall"], iid, cid) for iid, cid in team_cards(d) if cid in cat), reverse=True)[:2]
    st["log"](f"   DC hub data: draft {d['instance']} {d['wins']}-{d['losses']}, OVR {mut_team.ratings(t)}")
    return reply(hdr, body(ok_msg(), deck(team_cards(d)), mut.depth_map(t, "DEPC"), lineup(t),
                           enc_struct("DRTS", draft_event(d["event"])),
                           enc_list_struct("TTWO", [card_body(cid, iid) for _, iid, cid in best])))


def begin_game():
    """Start of a draft game: book a provisional loss - a quit sends no Dc_ProcessEndOfGame (measured 10-17 on
    H2H, same client code) and real Draft Champions counts a quit as the run-ending loss."""
    d = load()
    if not d:
        return
    if d.get("pending_game"):                  # previous game never reported back: its loss stands
        d["finished"] = True
    d["losses"] += 1
    d["pending_game"] = True
    save(d)


def record_result(won):
    d = load()
    if not d:
        return
    if d.pop("pending_game", None):
        d["losses"] -= 1
    d["wins" if won else "losses"] += 1
    if d["wins"] >= WINS_NEEDED or d["losses"] >= 1:
        d["finished"] = True
    save(d)


HANDLERS = {
    0x2C6: dc_handshake, 0x2C7: dc_get_configuration_info, 0x2C8: dc_get_new_user_flow_state,
    0x2EE: dc_get_landing_page_data, 0x2BC: dc_get_draft_events, 0x2F2: dc_get_event_payment_options,
    0x2BD: dc_resume_draft, 0x2BF: dc_make_draft_pick, 0x2CA: dc_get_hub_data,
}

"""MUT Head-to-Head (H2H Seasons / Salary Cap Ranked) on the Mut.Dc_* event system, with a CPU-controlled opponent
standing in for the matchmade player (the owner, 10-17: "regular MUT matchmaking ... it's just a CPU controlled team").
Hot-reloaded via draft.py / mut.py.

Measured flow (10-17): PLAY > H2H SEASON -> Dc_GetLandingPageData (RDET 8 = H2H_MUT_RANKED) -> SEASONS tile ->
Dc_GetDraftEvents {FILT [7] = H2H_MUT_UNRANKED, GMOD 1}. Event types: Blaze::Mut::Dc::DraftEventType."""
import json
from pathlib import Path

from tdf import body, enc_int, enc_list_struct, enc_str, enc_struct, enc_time

H2H_UNRANKED, H2H_RANKED = 7, 8              # DRAFTEVENTTYPE_H2H_MUT_UNRANKED / _RANKED
SEASONS_ID, SALARY_CAP_ID = 2001, 2002       # our event ids (>= 2000 = H2H)
DS_AVAILABLE, AVAIL_PLAYABLE, SKILL_ALLPRO = 1, 3, 2
FAR_FUTURE_US = 4_102_444_800 * 1_000_000
SEASON_GAMES = 10                            # MUT 20 H2H Seasons: 10-game regular season
# DraftEvent.CPU: the Solo Draft sends 1 and its PLAY GAME takes the CPU-game path (NVID DC_CPUGAME -> createGame).
# With 0 the H2H event goes DC_MATCHMAKING -> startMatchmakingScenario and the UI (BaseSessionHelper.
# _AttemptStartGame) then waits forever: "isH2HMatchReady: false, isValidCpuMatch: false" (no peer exists).
CPU_OPPONENT = 1

EVENTS = {
    SEASONS_ID: dict(type=H2H_UNRANKED, name="Seasons", ranked=0,
                     desc="Take your team all the way in H2H Seasons. Win games to reach the Super Bowl."),
    SALARY_CAP_ID: dict(type=H2H_RANKED, name="Salary Cap Ranked", ranked=1,
                        desc="Ranked head-to-head with a salary-capped lineup."),
}


def is_h2h_event(eid):
    return (eid or 0) in EVENTS


def access_rule(tag):
    return enc_struct(tag, enc_int("ACRI", 0), enc_int("CURV", 1), enc_str("DESC", ""), enc_str("SDES", ""))


STATE = Path(__file__).resolve().parent.parent / "mutdata" / "h2h_state.json"


def load_state():
    """{event id (str): {"wins", "losses", "games": [{"opp", "delta"}]}} - the current season of each event."""
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def season(eid):
    s = load_state().get(str(eid)) or {}
    return {"wins": s.get("wins", 0), "losses": s.get("losses", 0), "games": s.get("games", [])}


def _save(eid, s):
    states = load_state()
    states[str(eid)] = s
    STATE.write_text(json.dumps(states, indent=1))


def begin(eid):
    """Dc_ProcessStartOfGame: book the game as a LOSS right away. Quitting ("Quitting will give you a loss in
    this event") sends no Dc_ProcessEndOfGame at all (measured 10-17), so a game that never reports back stays
    lost - the same as EA's server. A full season (10 games) starts over."""
    s = season(eid)
    if len(s["games"]) >= SEASON_GAMES:
        s = {"wins": 0, "losses": 0, "games": []}
    opp = opponent_abbr(eid)
    s["losses"] += 1
    s["games"].append({"opp": opp, "delta": None, "pending": True})
    _save(eid, s)
    return opp, s


def record(eid, delta, quarters):
    """Dc_ProcessEndOfGame: settle the pending game (scoreDelta > 0 = win)."""
    s = season(eid)
    g = next((g for g in reversed(s["games"]) if g.get("pending")), None)
    if g is None:                                  # no start-of-game seen: count it as a new game
        _, s = begin(eid)
        g = s["games"][-1]
    won = delta > 0
    g.update(delta=delta, quarters=quarters, pending=False)
    if won:
        s["losses"] -= 1
        s["wins"] += 1
    _save(eid, s)
    return won, s


def opponent_abbr(eid):
    """A different CPU-controlled MUT squad for every game of the season (seeded by event + game number)."""
    import mut
    teams = mut.nfl_teams() or ["KC"]
    n = len(season(eid)["games"]) % SEASON_GAMES
    return teams[(eid * 7 + n * 11) % len(teams)]


def opponent(eid):
    import mut_team
    abbr = opponent_abbr(eid)
    n = len(season(eid)["games"])
    t = mut_team.build_starter(f"team:{abbr}", seed=eid * 100 + n, first_iid=300_000_001 + n * 1000)
    t["items_team"] = abbr                         # the opponent wears its own uniforms / coach / playbooks
    return abbr, t


def event(eid):
    e = EVENTS[eid]
    s = season(eid)
    return body(enc_int("DFID", eid), enc_str("NAME", e["name"]), enc_str("DESC", e["desc"]),
                enc_int("TYPE", e["type"]), enc_int("STAT", DS_AVAILABLE), enc_int("INST", 0),
                enc_int("AVAL", AVAIL_PLAYABLE), enc_int("CPU", CPU_OPPONENT), enc_int("CPUS", SKILL_ALLPRO), enc_int("FREE", 1),
                enc_int("ATLP", 1), enc_int("QTRL", 5), enc_int("ISRK", e["ranked"]), enc_int("VSBL", 1),
                enc_int("SGEB", 1), enc_int("MXGM", SEASON_GAMES), enc_int("NGAM", SEASON_GAMES),
                enc_int("NGWN", s["wins"]), enc_int("WINN", SEASON_GAMES), enc_int("LOSN", SEASON_GAMES),
                enc_int("WIN", s["wins"]), enc_int("LOSS", s["losses"]),
                enc_int("MMOD", 0), enc_int("SCAP", 1000 if e["ranked"] else 0),
                enc_time("STRT", 0), enc_time("ENDT", FAR_FUTURE_US), access_rule("PACR"), access_rule("VACR"))


INSTANCE_BASE = 50_000                       # mut.dc_start_draft gives non-draft events INST = 50_000 + event id


def event_of_instance(inst):
    eid = (inst or 0) - INSTANCE_BASE
    return eid if eid in EVENTS else ((inst or 0) if (inst or 0) in EVENTS else None)


def hub_data(eid, st):
    """Dc_GetHubData for an H2H event: the user's MUT lineup (DECK incl. coach + playbook/uniform/stadium items,
    DEPC depth chart, LINE) + the event. Without it the PLAY GAME lineup check fails ("does not have a valid
    defensive playbook item ... players without games")."""
    import mut
    import mut_cards
    import mut_team
    t = mut_team.load()
    coach = mut.team_coach(t)
    import draft
    cards = [mut_cards.card(mut_team.card_of(t, i), int(i)) for i in mut.lineup_iids(t) if mut_team.card_of(t, i)]
    cards.append(draft.coach_card(coach["cid"], coach["iid"]))
    st["log"](f"   H2H hub data: event {eid}, {len(cards)} lineup cards")
    return body(enc_struct("MSG", enc_int("RCDE", 0)),
                enc_list_struct("DECK", cards + mut.item_cards(t)), mut.depth_map(t, "DEPC"),
                mut.lineup_info(t, coach), enc_struct("DRTS", event(eid)))


def events_for(filters):
    """GetDraftEvents FILT -> our H2H events of those types ([] if none match)."""
    want = set(filters or [])
    return [event(eid) for eid, e in EVENTS.items() if e["type"] in want]

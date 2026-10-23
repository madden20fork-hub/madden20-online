"""Blaze GameManager (component 4) for single-player MUT / Draft games. Hot-reloaded with handlers.py.
The client creates a 1-player Blaze game for a CPU game (gameType35, PMAX 1, NTOP 130) and waits for
NotifyGameSetup before it loads the game. Schemas: tools/tdfrefl.py Blaze::GameManager::<Class>.
Ids VERIFIED 10-16 against the client's name switches (dump/gm_cmds.txt; notification switch @0x54b53b0,
id = index + 3): NotifyGameSetup 20, NotifyPlayerJoinCompleted 30, NotifyPlayerRemoved 40, NotifyGameRemoved 16,
NotifyGameStateChange 100. Commands: 1 createGame 2 destroyGame 3 advanceGameState 0xb removePlayer
0xf finalizeGameCreation 0x1a updateGameSession 0x41/0x42/0x43 meshEndpointsConnected/Disconnected/ConnectionLost."""
import itertools
import time

from tdf import (LIST, MAP, STRING, UNION, body, decode_tdf, enc_int, enc_list_int, enc_map_str_str, enc_str,
                 enc_struct, enc_time, frame, str_to_tag, write_varint)

GM = 0x4
USER_ID = 1000000001
import platform_cfg as plat  # noqa: E402

PERSONA = plat.PERSONA_NAME
NOTIFY_GAME_SETUP, NOTIFY_GAME_STATE_CHANGE, NOTIFY_PLAYER_JOIN_COMPLETED, NOTIFY_GAME_REMOVED = 20, 100, 30, 16
NOTIFY_PLAYER_REMOVED = 40
GS_INITIALIZING, GS_PRE_GAME, GS_IN_GAME, GS_POST_GAME = 1, 130, 131, 4
PS_ACTIVE_CONNECTED = 4
CREATE_GAME_SETUP_CONTEXT = 0

_ids = itertools.count(int(time.time()) % 100000 * 10 + 1)
GAMES = {}      # gid -> request fields (survives only while this module isn't reloaded; enough for one game)


def fields(payload):
    try:
        return {t: (ty, v) for t, ty, v in decode_tdf(payload)}
    except Exception:  # noqa: BLE001
        return {}


def sub(struct_fields, tag, default=None):
    for t, ty, v in struct_fields or []:
        if t == tag:
            return v
    return default


def reply(hdr, payload):
    from tdf import REPLY
    return frame(hdr["comp"], hdr["cmd"], hdr["seq"], payload, REPLY)


def notify(nid, payload):
    from tdf import NOTIFY
    return frame(GM, nid, 0, payload, NOTIFY)


def enc_map_ss(tag, items):
    return enc_map_str_str(tag, dict(items))


def network_address(tag, pnet):
    """Echo the client's NetworkAddress union (IpPairAddress, member 2) back as the player's address."""
    if not pnet or pnet[0] != "union" or pnet[2] is None:
        return str_to_tag(tag) + bytes([UNION, 0x7F])
    _, active, (mtag, _, val) = pnet

    def ip(t, s):
        return enc_struct(t, enc_int("IP", sub(s, "IP", 0)), enc_int("MACI", sub(s, "MACI", 0)),
                          enc_int("PORT", sub(s, "PORT", 0)))
    inner = enc_struct(mtag, ip("EXIP", sub(val, "EXIP")), ip("INIP", sub(val, "INIP")),
                       enc_int("MACI", sub(val, "MACI", 0)))
    return str_to_tag(tag) + bytes([UNION, active]) + inner


def host_info(tag):
    return enc_struct(tag, enc_int("HPID", USER_ID), enc_int("HSES", USER_ID), enc_int("HSLT", 0),
                      enc_int("CONG", 0), enc_int("CSID", 0))


# GameNetworkTopology for the 1-player CPU games. The client asks for 130 PEER_TO_PEER_FULL_MESH; with that, the
# time from createGame to meshEndpointsConnected varies 1 s ... 129 s (measured 10-16/10-17) and past ~90 s the
# Blaze connection drops right after it, so the game never loads. 255 = NETWORK_DISABLED: no peer mesh at all.
# None = echo the client's value.
CPU_GAME_TOPOLOGY = 255


def game_data(gid, req):
    gmcd = req.get("GMCD", (0, []))[1]
    attr = sub(gmcd, "ATTR", ("map", 1, 1, []))[3]
    crit = sub(gmcd, "CRIT", ("map", 1, 1, []))[3]
    tids = sub(gmcd, "TIDS", ("list", 0, [65534]))[2]
    pcap = req.get("PCAP", (0, ("list", 0, [1, 0, 0, 0])))[1][2]
    gtyp = req.get("GTYP", (0, "gameType35"))[1]
    return enc_struct(
        "GAME", enc_int("GID", gid), enc_str("GNAM", sub(gmcd, "GNAM", "") or f"{PERSONA} MUT"),
        enc_int("GSTA", GS_INITIALIZING), enc_int("GSET", sub(gmcd, "GSET", 0)),
        enc_int("NTOP", CPU_GAME_TOPOLOGY if CPU_GAME_TOPOLOGY is not None and sub(gmcd, "PMAX", 1) == 1
                else sub(gmcd, "NTOP", 130)),
        enc_int("VOIP", sub(gmcd, "VOIP", 2)), enc_int("PRES", sub(gmcd, "PRES", 2)),
        enc_int("MCAP", sub(gmcd, "PMAX", 1)), enc_int("MNCP", sub(gmcd, "PMIN", 1)), enc_int("QCAP", 0),
        enc_list_int("CAP", pcap), enc_list_int("TIDS", tids), enc_map_ss("ATTR", attr), enc_map_ss("CRIT", crit),
        enc_str("GTYP", gtyp), enc_int("GSID", gid), enc_int("GGTY", sub(req.get("CMGD", (0, []))[1], "GGTY", 0)),
        enc_str("VSTR", sub(req.get("CMGD", (0, []))[1], "GVER", "") or ""), enc_int("GPVH", 0),
        host_info("THST"), host_info("PHST"), host_info("DHST"), enc_int("SEED", gid & 0x7FFFFFFF),
        enc_time("CTIM", int(time.time() * 1_000_000)), enc_str("UUID", f"madden20-local-{gid}"),
        enc_int("PSEU", 0), enc_int("NRES", 0))


def game_player(gid, req):
    pnet = sub(req.get("CMGD", (0, []))[1], "PNET")
    return body(enc_int("GID", gid), enc_int("PID", USER_ID), enc_int("UID", USER_ID), enc_str("NAME", PERSONA),
                enc_str("NASP", plat.NAMESPACE), enc_int("EXID", plat.EXTERNAL_ID), enc_int("LOC", 1701729619),
                enc_int("CNTY", 21843), enc_int("STAT", PS_ACTIVE_CONNECTED), enc_int("SID", 0), enc_int("SLOT", 0),
                enc_int("TIDX", 0), enc_int("CSID", 0), enc_int("CONG", 0), enc_str("ROLE", ""),
                enc_time("TIME", int(time.time() * 1_000_000)), network_address("PNET", pnet))


def create_game(hdr, payload, st):
    req = fields(payload)
    gid = next(_ids)
    GAMES[gid] = req
    st["log"](f"   GM createGame -> gid {gid} type {req.get('GTYP', (0, '?'))[1]}")
    roster = str_to_tag("PROS") + bytes([LIST, 3]) + write_varint(1) + game_player(gid, req) + b"\0"
    reas = str_to_tag("REAS") + bytes([UNION, 0]) + enc_struct("DLSC", enc_int("DCTX", CREATE_GAME_SETUP_CONTEXT))
    setup = body(game_data(gid, req), roster, reas, enc_int("QOSV", 0), enc_int("LFPJ", 0))
    return [reply(hdr, body(enc_int("GID", gid))), notify(NOTIFY_GAME_SETUP, setup)]


REAS_MATCHMAKING = 3          # GameSetupReason union member order: DLSC 0, IJGS 1, IMSC 2, MMSC 3, RDSC 4 (measured)
MM_SUCCESS_CREATED_GAME = 0
NOTIFY_MATCHMAKING_ASYNC_STATUS = 12
_mm_ids = itertools.count(int(time.time()) % 100000 * 10 + 7)


def start_matchmaking_scenario(hdr, payload, st):
    """MUT H2H "find opponent" (Blaze startMatchmakingScenario 0x10). There is no other player: answer with a scenario
    id, then report success via NotifyGameSetup (reason = MatchmakingSetupContext) for a game that holds just the
    local user - the opponent is CPU-controlled (the owner, 10-17). Request: {SCNM scenarioName, SCNA attributes,
    CMGD commonGameData (PNET...), PLJD playerJoinData}."""
    req = fields(payload)
    scen = next(_mm_ids)
    gid = next(_ids)
    GAMES[gid] = req
    st["log"](f"   GM startMatchmakingScenario '{req.get('SCNM', (0, '?'))[1]}' -> scenario {scen}, gid {gid}")
    roster = str_to_tag("PROS") + bytes([LIST, 3]) + write_varint(1) + game_player(gid, req) + b"\0"
    mmsc = enc_struct("MMSC", enc_int("RSLT", MM_SUCCESS_CREATED_GAME), enc_int("MSCD", scen), enc_int("MSID", scen),
                      enc_int("USID", USER_ID), enc_int("FIT", 100), enc_int("MAXF", 100), enc_int("GENT", 0),
                      enc_time("TTM", 3_000_000), enc_time("ETTM", 5_000_000), enc_time("TOUT", 60_000_000),
                      enc_int("TUGM", 2), enc_int("TUMM", 2), enc_int("TUSR", 2))
    reas = str_to_tag("REAS") + bytes([UNION, REAS_MATCHMAKING]) + mmsc
    setup = body(game_data(gid, req), roster, reas, enc_int("QOSV", 0), enc_int("LFPJ", 0))
    if "send_later" in st:
        st["send_later"](2.5, notify(NOTIFY_GAME_SETUP, setup))
        return [reply(hdr, body(enc_int("MSID", scen), enc_time("ETTM", 3_000_000)))]
    return [reply(hdr, body(enc_int("MSID", scen))), notify(NOTIFY_GAME_SETUP, setup)]


def _gid(payload):
    f = fields(payload)
    return f.get("GID", (0, 0))[1] or (max(GAMES) if GAMES else 0)


def state_change(gid, state):
    return notify(NOTIFY_GAME_STATE_CHANGE, body(enc_int("GID", gid), enc_int("GSTA", state)))


def join_completed(gid):
    return notify(NOTIFY_PLAYER_JOIN_COMPLETED, body(enc_int("GID", gid), enc_int("PID", USER_ID),
                                                     enc_time("TIME", int(time.time() * 1_000_000))))


def advance_game_state(hdr, payload, st):
    f = fields(payload)
    gid, new = _gid(payload), f.get("GSTA", (0, GS_PRE_GAME))[1]
    st["log"](f"   GM advanceGameState gid {gid} -> {new}")
    out = [reply(hdr, b""), state_change(gid, new)]
    # The draft/MUT CPU-game UI (BaseSessionHelper._AttemptStartGame) waits for "game session started",
    # which it only gets from an IN_GAME state change; the client never asks for it itself in a CPU game.
    # Pushing IN_GAME after PRE_GAME makes it request Dc_GetGameAndRenderData and load the game (10-16).
    if new == GS_PRE_GAME and "send_later" in st:
        st["log"](f"   GM IN_GAME push in 3 s")
        st["send_later"](3.0, state_change(gid, GS_IN_GAME))
    return out


def finalize_game_creation(hdr, payload, st):
    gid = _gid(payload)
    # The OSDK GameSession service only attaches to the game (SetCurrentGame) when the createGame callback
    # fires, which is on this reply - a PRE_GAME notification sent together with it is processed before the
    # session listens and is missed. Push the state change a little later instead.
    st["log"](f"   GM finalizeGameCreation gid {gid} -> join completed; PRE_GAME deferred 2 s")
    if "send_later" in st:
        st["send_later"](2.0, state_change(gid, GS_PRE_GAME))
        return [reply(hdr, b""), join_completed(gid)]
    return [reply(hdr, b""), state_change(gid, GS_PRE_GAME), join_completed(gid)]


def mesh_connected(hdr, payload, st):
    gid = _gid(payload)
    st["log"](f"   GM meshEndpointsConnected gid {gid} {[(t, v) for t, _, v in decode_tdf(payload)][:6]}")
    return [reply(hdr, b""), join_completed(gid)]


def destroy_game(hdr, payload, st):
    gid = _gid(payload)
    st["log"](f"   GM destroyGame gid {gid}")
    GAMES.pop(gid, None)
    return [reply(hdr, body(enc_int("GID", gid))),
            notify(NOTIFY_GAME_REMOVED, body(enc_int("GID", gid), enc_int("REAS", 0)))]


PLAYER_LEFT, SYS_GAME_ENDING = 7, 0       # PlayerRemovedReason / GameDestructionReason


def remove_player(hdr, payload, st):
    # The local user is the only player, so leaving empties the game: echo the client's reason (was 0 =
    # PLAYER_JOIN_TIMEOUT) and destroy the game like Blaze does. Without NotifyGameRemoved the client kept the
    # old game's mesh up and the NEXT game waited ~90 s for it to time out (meshEndpointsDisconnected), after
    # which the Blaze connection dropped and the second MUT game of a session never loaded (10-17).
    f = fields(payload)
    gid = _gid(payload)
    reas = f.get("REAS", (0, PLAYER_LEFT))[1]
    st["log"](f"   GM removePlayer gid {gid} reason {reas} -> player removed + game removed")
    GAMES.pop(gid, None)
    return [reply(hdr, b""),
            notify(NOTIFY_PLAYER_REMOVED, body(enc_int("GID", gid), enc_int("PID", USER_ID), enc_int("REAS", reas),
                                               enc_int("CNTX", f.get("CNTX", (0, 0))[1]))),
            notify(NOTIFY_GAME_REMOVED, body(enc_int("GID", gid), enc_int("REAS", SYS_GAME_ENDING)))]


def log_only(name):
    def h(hdr, payload, st):
        st["log"](f"   GM {name} (empty reply) {[(t, v) for t, _, v in decode_tdf(payload)][:6]}")
        return [reply(hdr, b"")]
    return h


HANDLERS = {(GM, 0x1): create_game, (GM, 0x2): destroy_game, (GM, 0x3): advance_game_state,
            (GM, 0xB): remove_player, (GM, 0xF): finalize_game_creation, (GM, 0x41): mesh_connected,
            (GM, 0x10): start_matchmaking_scenario}
# leaveGameByGroup (0x16, REAS 8 GROUP_LEFT) is sent when the user quits a MUT game. Keep it a plain reply:
# answering it with PlayerRemoved + GameRemoved made the exit to the menus wait ~78 s for the mesh teardown
# (measured 10-17); the game is torn down by the removePlayer that comes with the next createGame instead.
for _cid in range(0x2, 0x80):
    HANDLERS.setdefault((GM, _cid), log_only(f"0x{_cid:x}"))

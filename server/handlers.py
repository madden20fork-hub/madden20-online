"""Blaze command handlers for Madden 20 (hot-reloaded by blaze_server.py on every frame).
Schemas come from the eboot's TDF reflection (tools/tdfrefl.py), not from other games."""
import importlib as _importlib

import tdf as _tdf

_importlib.reload(_tdf)  # codec fixes apply without restarting blaze_server.py (it keeps its own parse_fire2)
from tdf import (  # noqa: E402
    REPLY, body, enc_int, enc_list_int, enc_list_str, enc_map_str_str, enc_map_str_struct, enc_str, enc_struct,
    enc_time, frame)

COMPONENTS = {0x1: "Authentication", 0x4: "GameManager", 0x5: "Redirector", 0x7: "Stats",
              0x9: "Util", 0xF: "Messaging", 0x19: "AssociationLists", 0x1C: "GameReporting",
              0x23: "ConsoleAuth?", 0x7802: "UserSessions"}
COMMANDS = {(0x9, 0x1): "FetchClientConfig", (0x9, 0x2): "Ping", (0x9, 0x5): "GetTelemetryServer",
            (0x9, 0x7): "PreAuth", (0x9, 0x8): "PostAuth"}

import platform_cfg as plat  # noqa: E402  (not reloaded: caches the client's PreAuth CINF)

SERVER_VERSION = "Blaze 15.1.1.7.5 (madden20-private)"
QOS_HOST = "127.0.0.1"


def command_name(comp, cmd):
    return COMMANDS.get((comp, cmd), f"{COMPONENTS.get(comp, hex(comp))}/{cmd:#x}")


def reply(hdr, payload):
    return frame(hdr["comp"], hdr["cmd"], hdr["seq"], payload, REPLY)


# ---------------- Util ----------------
def util_preauth(hdr, payload, st):
    from tdf import decode_tdf
    seen = plat.observe_preauth({t: v for t, _, v in decode_tdf(payload)})
    st["log"](f"   client info {seen}")
    qos = [enc_struct("QCNF", enc_int("DPSP", 17502), enc_str("QCA", QOS_HOST), enc_int("QCP", 17499),
                      enc_str("QPR", "standard")),
           enc_time("CQRR", 3_600_000_000), enc_time("CQFR", 300_000_000), enc_time("SQRR", 3_600_000_000),
           enc_map_str_struct("LTPS", {"local": body(enc_str("PSA", QOS_HOST), enc_int("PSP", 17502))})]
    # Keys the client reads from this map (strings next to ConnectionManager @0x664f1f7).
    # The voip STT/TTS ones are mandatory: missing -> profile -1 and NULL url/key -> crash @0x54c6470.
    conf = enc_map_str_str("CONF", {
        "pingPeriod": "15s",
        "connIdleTimeout": "90s",
        "defaultRequestTimeout": "80s",
        "autoReconnectEnabled": "true",
        "maxReconnectAttempts": "5",
        "voipHeadsetUpdateRate": "1000",
        "voipSTTProfile": "0",
        "voipSTTUrl": "",
        "voipSTTKey": "",
        "voipTTSProvider": "0",
        "voipTTSUrl": "",
        "voipTTSKey": "",
    })
    out = (enc_str("ASRC", "303107")
            + enc_list_int("CIDS", sorted(k for k in COMPONENTS if k != 0x23))
            + enc_str("CLID", plat.CLIENT_ID)
            + enc_struct("CONF", conf)
            + enc_str("ESRC", "303107")
            + enc_str("INST", plat.SERVICE)
            + enc_int("MAID", 0)
            + enc_int("MINR", 0)
            + enc_str("NASP", "cem_ea_id")
            + enc_str("PILD", "")
            + enc_str("PLAT", plat.PLAT)
            + enc_struct("QOSS", *qos)
            + enc_str("RSRC", "303107")
            + enc_str("SVER", SERVER_VERSION))
    return [reply(hdr, out)]


def util_ping(hdr, payload, st):
    import time
    return [reply(hdr, enc_int("STIM", int(time.time())))]


# FetchClientConfig sections (CFID -> CONF map). Filled in as the game shows which keys it reads.
CLIENT_CONFIG = {
    "OSDK_CORE": {},
    "OSDK_CLIENT": {},
    "OSDK_NUCLEUS": {},
    "OSDK_WEBOFFER": {},
    "OSDK_ABUSE_REPORTING": {},
    # 181-key enum table @0x75c3e00 (dump/madset_keys.txt). DP_*: "CHECKING ONLINE TUNING DATA" -> the
    # tuning download URL; empty = instant "error downloading the latest tuning data" dialog.
    # Host must be *.ea.com so EAREDIRECT sends it to the local :443. Values = probes to see the URL shape.
    # PC: no EAREDIRECT, so every URL points straight at the local plain-HTTP side server (platform_cfg).
    # NETRESOURCE_IMAGE_BASE_URL: card art ("32,1|lgnd-00052129" netres ids) is downloaded from here by the
    # client's NetResCache (empty on PS4 = no image request was ever made). Served from mutdata/art (netres.py).
    "OSDK_MADSET": {"DP_BASE_URL": plat.HTTP_BASE + "base/",
                    "DP_RSTR_URL": "rstr/", "DP_CUSTRSTR_URL": "custrstr/", "DP_TUNING_URL": "tuning/",
                    "DP_LCUBASE_URL": plat.HTTP_BASE + "lcu/", "DP_LCUDIR_FILE": "lcudir.txt",
                    "NETRESOURCE_IMAGE_BASE_URL": plat.HTTP_BASE + "netres/"},
}


def util_fetch_client_config(hdr, payload, st):
    from tdf import decode_tdf
    cfid = next((v for t, _, v in decode_tdf(payload) if t == "CFID"), "")
    return [reply(hdr, enc_map_str_str("CONF", CLIENT_CONFIG.get(cfid, {})))]


# ---------------- Authentication (component 1) ----------------
# Command ids from the client's own switch @0x54b4040 (tools/cmdnames.py).
COMMANDS.update({(0x1, 0xA): "Auth.login", (0x1, 0xB): "Auth.trustedLogin", (0x1, 0x3C): "Auth.expressLogin",
                 (0x1, 0x46): "Auth.logout", (0x1, 0x24): "Auth.getAuthToken",
                 (0x1, 0x1D): "Auth.listUserEntitlements2", (0x1, 0x5A): "Auth.getPersona",
                 (0x1, 0x64): "Auth.listPersonas", (0x1, 0x1E): "Auth.getAccount",
                 (0x1, 0x27): "Auth.grantEntitlement2", (0x1, 0x30): "Auth.listPersonaEntitlements2",
                 (0x1, 0x104): "Auth.getOriginPersona", (0x1, 0xE6): "Auth.createWalUserSession",
                 (0x9, 0x8): "PostAuth", (0x9, 0x5): "GetTelemetryServer", (0x9, 0x6): "GetTickerServer",
                 (0x9, 0xA): "UserSettingsLoad", (0x9, 0xB): "UserSettingsSave",
                 (0x9, 0xC): "UserSettingsLoadAll", (0x9, 0x15): "FetchQosConfig",
                 (0x9, 0x17): "SetConnectionState", (0x9, 0x19): "GetUserOptions",
                 (0x9, 0x1C): "SetClientState", (0x9, 0x3): "SetClientData"})

USER_ID = 1000000001          # Blaze user id == persona id (nucleus.PERSONA_ID)
NUCLEUS_ID = 1000000000001    # nucleus.PID
PERSONA_NAME = plat.PERSONA_NAME
PERSONA_ACTIVE = 2


def persona_details():
    import time
    return enc_struct("PDTL", enc_str("DSNM", PERSONA_NAME), enc_int("LAST", int(time.time())),
                      enc_int("PID", USER_ID), enc_int("PLAT", plat.client_platform()),
                      enc_int("STAS", PERSONA_ACTIVE), enc_int("XREF", plat.EXTERNAL_ID))


SESSION_KEY = "madden20-local-session-key"
USERSESSIONS = 0x7802
COMMANDS.update({(USERSESSIONS, 0x1): "US.validateSessionKey", (USERSESSIONS, 0x3): "US.fetchExtendedData",
                 (USERSESSIONS, 0x5): "US.updateExtendedDataAttribute", (USERSESSIONS, 0x8): "US.updateHardwareFlags",
                 (USERSESSIONS, 0xC): "US.lookupUser", (USERSESSIONS, 0xD): "US.lookupUsers",
                 (USERSESSIONS, 0x14): "US.updateNetworkInfo", (USERSESSIONS, 0x19): "US.updateUserSessionClientData",
                 (USERSESSIONS, 0x1A): "US.setUserInfoAttribute", (USERSESSIONS, 0x2D): "US.getUniqueDeviceId",
                 (USERSESSIONS, 0x37): "US.updateLocalUserGroup", (USERSESSIONS, 0x3A): "US.getQosPingSites"})


def user_identification(tag):
    return enc_struct(tag, enc_int("AID", NUCLEUS_ID), enc_int("ALOC", 1701729619), enc_int("CNTY", 21843),
                      enc_int("EXID", plat.EXTERNAL_ID), enc_int("ID", USER_ID), enc_str("NAME", PERSONA_NAME),
                      enc_str("NASP", plat.NAMESPACE), enc_int("ORIG", 0), enc_int("PIDI", NUCLEUS_ID))


def extended_data(tag):
    return enc_struct(tag, enc_str("BPS", "local"), enc_str("CTY", "US"), enc_str("TZ", "America/Chicago"),
                      enc_int("UATT", 0))


def notify(comp, nid, payload):
    from tdf import NOTIFY
    return frame(comp, nid, 0, payload, NOTIFY)


def auth_login(hdr, payload, st):
    import time
    now = int(time.time())
    sess = enc_struct("SESS", enc_int("1CON", 0), enc_int("BUID", USER_ID), enc_int("FRST", 0),
                      enc_int("GEO", 1), enc_str("KEY", SESSION_KEY),
                      enc_int("LLOG", now), enc_str("MAIL", "player@local"),
                      persona_details(), enc_int("UID", NUCLEUS_ID))
    out = body(enc_int("ANON", 0), sess, enc_int("SPAM", 1), enc_int("UNDR", 0))
    added = body(extended_data("DATA"), user_identification("USER"))
    ext = body(extended_data("DATA"), enc_int("SUBS", 1), enc_int("USID", USER_ID))
    authed = body(enc_int("1CON", 0), enc_int("ALOC", 1701729619), enc_int("BUID", USER_ID),
                  enc_int("CNTY", 21843), enc_str("DSNM", PERSONA_NAME), enc_int("FRST", 0),
                  enc_str("KEY", SESSION_KEY), enc_int("LAST", now), enc_int("LLOG", now),
                  enc_str("MAIL", "player@local"), enc_str("NASP", plat.NAMESPACE), enc_int("PID", USER_ID),
                  enc_int("PLAT", plat.client_platform()), enc_int("UID", NUCLEUS_ID), enc_int("USTP", 0),
                  enc_int("XREF", plat.EXTERNAL_ID))
    return [reply(hdr, out),
            notify(USERSESSIONS, 0x2, added),
            notify(USERSESSIONS, 0x1, ext),
            notify(USERSESSIONS, 0x8, authed)]


def util_postauth(hdr, payload, st):
    from http_server import HOST_IP
    from tdf import enc_blob
    tele = enc_struct("TELE", enc_str("ADRS", HOST_IP), enc_int("ANON", 0), enc_blob("BKEY", b""),
                      enc_int("CTRY", 21843), enc_str("DISA", ""), enc_int("EDCT", 0), enc_str("FILT", ""),
                      enc_int("LOC", 1701729619), enc_int("MINR", 0), enc_str("NOOK", ""),
                      enc_str("PENV", "prod"), enc_int("PORT", 9988),
                      enc_str("PURL", plat.HTTP_BASE + "pinEvents"), enc_int("SDLY", 15000),
                      enc_str("SESS", "madden20-local-telemetry"), enc_str("SKEY", "madden20-local"),
                      enc_int("SPCT", 0), enc_str("STIM", ""), enc_str("SVNM", plat.SERVICE))
    tick = enc_struct("TICK", enc_str("ADRS", HOST_IP), enc_int("PORT", 8999), enc_str("SKEY", ""))
    urop = enc_struct("UROP", enc_int("TMOP", 0), enc_int("UID", USER_ID))
    return [reply(hdr, body(tele, tick, urop))]


# ---------------- OSDKSettings (component 0x8c9) ----------------
# cmd 1 fetchSettings / cmd 2 fetchSettingsGroups (getter @0x370eac0). Without groups the client
# dereferences NULL for group O_SG_TCKR (crash @0x37492e8). Types: "integer" or string (default).
OSDKSETTINGS = 0x8C9
COMMANDS.update({(OSDKSETTINGS, 0x1): "OSDKSettings.fetchSettings",
                 (OSDKSETTINGS, 0x2): "OSDKSettings.fetchSettingsGroups"})
SETTING_IDS = (
    "O_AI O_CP O_DNF O_DSR O_EGstat O_FWD_EMAIL O_GEO O_GM O_HM O_HV O_JS O_LN O_MAX O_MIN O_MXS O_MYPT "
    "O_MYT O_NT O_OPPT O_OPT O_PM O_PR O_RK O_SD O_SPAMEA O_SPAMPART O_SS O_TELEMETRY O_TKfilter O_TKfriend "
    "O_TKsport O_WO_NEWS UGEN UACCT INV OSDK_coop OSDK_playerMyTeam OSDK_playerOppTeam OSDK_matchRelax "
    "OSDK_language").split()
MATCHUP_SETTINGS = (
    "MMFTG MMINJ MMEVT MMQTRL MMSKL MMFP MMACCLK MMWTHR MMSKLSTD MMVSN MMGMFLOW MMPP MM_GAMETYPE "
    "MM_MAXPLAYERS MM_MINPLAYERS MM_MAXSPECTATORS MM_DESPLAYERS MM_GAMEFLOW MM_FATIGUE MM_INJURIES "
    "MM_EVEN_TEAMS MM_QTR_LEN MM_GAME_SKILL MM_FAIRPLAY MM_ACC_CLOCK MM_RANKED_TYPE MM_WEATHER MM_INVITE "
    "MM_SKILL_STD MM_VERSION").split()
SETTING_IDS = SETTING_IDS + MATCHUP_SETTINGS
SETTING_GROUPS = "O_SG_USER O_SG_TCKR O_SG_QMSG O_SG_SYSS MUPSET SG_MATCHUP INV OSDK_ANY".split()
# Matchup view table the client walks (qword table @0x75c5b90): looked up in MUPSET and SG_MATCHUP.
MATCHUP_VIEWS = ("QM_STD QM_SCR QM_OTP QM_MUT QM_MUT_SHORT CLQMV CLH2H TNQMV SPEVR SPEVUR SEASONS_H2H_QMV "
                 "SEA_H2H_TRN_QMV DC_QM DCR_QM CM_STD CM_SCR CM_OTP ARENA_H2H_CM CS_STD CS_SCR CS_OTP CS_UCM "
                 "CS_MUT ARENA_H2H_CS CS_DC QM_MUT_SVS QM_MUT_SVC").split()
# Views per group. SG_MATCHUP: the client's matchup view table (a missing MUPSET view is created by
# the client, 0x245866c). O_SG_USER: UGEN / UACCT (crash @0x24b30dc: UACCT view, reads O_TELEMETRY).
GROUP_VIEWS = {"SG_MATCHUP": MATCHUP_VIEWS, "O_SG_USER": ["UGEN", "UACCT"], "O_SG_SYSS": ["UGEN", "UACCT"]}


def setting_view(view_id, members):
    from tdf import enc_list_struct
    data = [body(enc_str("DEFS", "0"), enc_int("ENAB", 1), enc_str("HLAB", ""), enc_str("ID", sid),
                 enc_int("PERS", 1), enc_str("VAL", "0"), enc_int("VIS", 1)) for sid in members]
    return body(enc_str("ID", view_id), enc_list_struct("LVDS", data))


def setting_value(sid):
    from tdf import STRUCT
    return body(enc_str("DEF", "0"), enc_int("ENAB", 1), enc_str("HLAB", ""), enc_str("ID", sid),
                enc_str("LABL", sid), enc_int("LOCF", 0), enc_int("LOCL", 0), enc_int("LOHL", 0),
                enc_int("LOVL", 0), enc_int("PERS", 1), enc_list_int("PVAL", [0, 1]),
                enc_list_str("PVLL", ["Off", "On"]), enc_str("TYPE", "integer"), enc_int("VIS", 1))


def osdk_fetch_settings(hdr, payload, st):
    from tdf import enc_list_struct
    return [reply(hdr, enc_list_struct("LSIN", [setting_value(s) for s in SETTING_IDS]))]


# Realistic membership (an everything-in-every-group reply corrupted the client heap, crash @0x35f9e71).
# Matchup/invite preference settings: client string table order O_JS..O_OPPT (@0x6592d30), read from
# the INV group (crash @0x35ea725 looked up O_PR there).
PREF_SETTINGS = ("O_JS O_HM O_AI O_PR O_SS O_SD O_CP O_NT O_GEO O_MIN O_MAX O_MXS O_DSR O_DNF O_GM O_MYT "
                 "O_OPT O_LN O_HV O_PM O_MYPT O_OPPT").split()
GROUP_MEMBERS = {
    "O_SG_USER": ("O_FWD_EMAIL O_EGstat O_JS O_HM O_AI O_PR O_SS O_SD O_CP O_NT O_GEO O_MIN O_MAX O_MXS O_DSR "
                  "O_DNF O_GM O_MYT O_OPT O_LN O_HV O_PM O_MYPT O_OPPT O_RK O_SPAMEA O_SPAMPART O_TELEMETRY").split(),
    "O_SG_TCKR": "O_TKfilter O_TKfriend O_TKsport".split(),
    "O_SG_QMSG": ["O_WO_NEWS"],
    "O_SG_SYSS": ["O_TELEMETRY"],
    "MUPSET": PREF_SETTINGS + "OSDK_coop OSDK_playerMyTeam OSDK_playerOppTeam OSDK_matchRelax OSDK_language".split(),
    "SG_MATCHUP": MATCHUP_SETTINGS,
    "INV": PREF_SETTINGS + ["INV"],
    "OSDK_ANY": [],
}


def osdk_fetch_settings_groups(hdr, payload, st):
    from tdf import enc_list_struct
    groups = [body(enc_str("ID", g), enc_list_str("LSET", GROUP_MEMBERS[g]),
                   enc_list_struct("LVWS", [setting_view(v, GROUP_MEMBERS[g]) for v in GROUP_VIEWS.get(g, [])]))
              for g in SETTING_GROUPS]
    return [reply(hdr, enc_list_struct("LGRP", groups))]


HANDLERS = {(0x9, 0x7): util_preauth, (0x9, 0x2): util_ping, (0x9, 0x1): util_fetch_client_config,
            (0x1, 0xA): auth_login, (0x1, 0xB): auth_login, (0x1, 0x3C): auth_login,  # PC login variant: TBD
            (0x9, 0x8): util_postauth,
            (OSDKSETTINGS, 0x1): osdk_fetch_settings, (OSDKSETTINGS, 0x2): osdk_fetch_settings_groups}

# ---------------- request-loop killers (perf) ----------------
# Empty replies made the client re-send these ~40x/s for the whole session (10-14: 3,104 getLists +
# 1,543 census subscribes in 2 minutes). Answer them properly.
COMPONENTS.update({0xA: "CensusData"})
COMMANDS.update({(0x19, 0x6): "AssociationLists.getLists", (0xA, 0x5): "CensusData.subscribeToCensusDataUpdates"})


def assoc_get_lists(hdr, payload, st):
    # Blaze::Association::Lists {LMAP list<ListMembers{INFO ListInfo, MEML [], TOCT 0, OFRC 0}>}: every
    # requested list (OSDKPlatformFriendList) exists and is empty.
    from tdf import decode_tdf, enc_list_struct, enc_objid
    req = {t: v for t, _, v in decode_tdf(payload)}
    out = []
    for info in (req.get("ALST") or ("list", 3, []))[2]:
        f = {t: v for t, _, v in info}
        lid = {t: v for t, _, v in f.get("LID", [])}
        info_b = enc_struct("INFO", enc_objid("BOID", 0, 0, 0), enc_int("FLGS", f.get("FLGS", 1)),
                            enc_struct("LID", enc_str("LNM", lid.get("LNM", "")), enc_int("TYPE", lid.get("TYPE", 1))),
                            enc_int("LMS", f.get("LMS", 0) or 100), enc_str("PNAM", ""), enc_int("PRID", 0),
                            enc_int("PRMS", 0))
        out.append(body(info_b, enc_list_struct("MEML", []), enc_int("OFRC", 0), enc_int("TOCT", 0)))
    return [reply(hdr, enc_list_struct("LMAP", out))]


def census_subscribe(hdr, payload, st):
    # SubscribeToCensusDataUpdatesResponse: TimeValues in microseconds (0 = resubscribe immediately)
    return [reply(hdr, body(enc_time("CNP", 60_000_000), enc_time("NTMT", 120_000_000),
                            enc_time("RTMT", 300_000_000)))]


HANDLERS.update({(0x19, 0x6): assoc_get_lists, (0xA, 0x5): census_subscribe})

# Ultimate Team (0x802) lives in mut.py; reloaded together with this module on every frame.
import importlib  # noqa: E402

import mut  # noqa: E402

importlib.reload(mut)
HANDLERS.update(mut.HANDLERS)
COMMANDS.update(mut.COMMANDS)

# GameManager (4): single-player MUT/Draft games create a 1-player Blaze game (gamemanager.py).
import gamemanager  # noqa: E402

importlib.reload(gamemanager)
HANDLERS.update(gamemanager.HANDLERS)

# Unknown commands get an empty reply (default-constructed response TDF) instead of a timeout;
# blaze_server logs each one so it can get a real handler.
DEFAULT_EMPTY_REPLY = True


INJECT = __import__("pathlib").Path(__file__).with_name("inject.py")


def _injected(st):
    """One-shot server pushes for live experiments: drop server/inject.py defining OUT = [frames...] (gm =
    gamemanager, st = connection state in scope); it runs on the next client frame and is renamed to inject.done."""
    if not INJECT.exists():
        return []
    code = INJECT.read_text()
    INJECT.replace(INJECT.with_suffix(".done"))
    ns = {"gm": gamemanager, "st": st}
    try:
        exec(code, ns)
    except Exception as e:  # noqa: BLE001
        st["log"](f"   INJECT failed: {e!r}")
        return []
    st["log"](f"   INJECT {len(ns.get('OUT', []))} frame(s)")
    return list(ns.get("OUT", []))


def dispatch(hdr, payload, st):
    from tdf import PING, PING_REPLY
    if hdr["type"] == PING:
        return [frame(hdr["comp"], hdr["cmd"], hdr["seq"], b"", PING_REPLY)] + _injected(st)
    pushes = _injected(st)
    h = HANDLERS.get((hdr["comp"], hdr["cmd"]))
    if h:
        return h(hdr, payload, st) + pushes
    if DEFAULT_EMPTY_REPLY and hdr["type"] == 0:
        st["log"](f"   DEFAULT empty reply for {command_name(hdr['comp'], hdr['cmd'])}")
        return [reply(hdr, b"")] + pushes
    return pushes

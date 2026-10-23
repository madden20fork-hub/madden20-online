"""Client platform identity (PC by default; the shadPS4/PS4 build is retired). NOT hot-reloaded on purpose:
`observe_preauth` caches what the client itself reports, so later handlers can echo its exact values.

MADDEN_PLATFORM=ps4 restores the PS4 identity (old runs)."""
import os

PLATFORM = os.environ.get("MADDEN_PLATFORM", "pc")

if PLATFORM == "ps4":
    CLIENT_ID = "MADDEN_2020_PS4"
    SERVICE = "madden-2020-ps4"
    PLAT = "ps4"
    NAMESPACE = "ps4"
    CLIENT_PLATFORM = 20            # CINF.CPFT measured on PS4
    EXTERNAL_ID = 0xE3C9D3C9537D6CE8
    PERSONA_NAME = "shadPS4"
else:
    CLIENT_ID = "MADDEN_2020_PC"
    SERVICE = "madden-2020-pc"
    PLAT = "pc"
    NAMESPACE = "cem_ea_id"
    CLIENT_PLATFORM = None          # taken from the client's PreAuth CINF.CPFT
    EXTERNAL_ID = 1000000000001     # PC: external id = Nucleus pid
    PERSONA_NAME = os.environ.get("MADDEN_PERSONA", "Player")


# Plain-HTTP side server (http_server.py --plain): DP tuning data, telemetry sink, card art (netres).
HTTP_PORT = int(os.environ.get("MADDEN_HTTP_PORT", "42240"))
HTTP_HOST = "127.0.0.1"
HTTP_BASE = f"http://{HTTP_HOST}:{HTTP_PORT}/"

_seen = {}


def observe_preauth(fields):
    """fields: decoded PreAuth request {tag: value}. CINF = Blaze::ClientInfo struct (list of (tag, type, value))."""
    cinf = fields.get("CINF") or []
    for t, _, v in cinf if isinstance(cinf, list) else []:
        _seen[t] = v
    return _seen


def client_platform():
    if CLIENT_PLATFORM is not None:
        return CLIENT_PLATFORM
    return _seen.get("CPFT", 1)

"""EA Nucleus (accounts.ea.com) endpoints for Madden 20 — hot-reloaded per request by http_server.
Shapes come from the client's own strings (eboot @0x6580f80): /connect/auth must 302 with the code
in Location; /connect/token and /connect/tokeninfo return JSON with the listed fields."""
import json
import time

# One local identity, used everywhere (Nucleus + Blaze).
PID = 1000000000001          # Nucleus pid / user_id
PERSONA_ID = 1000000001      # Blaze persona / user id
import platform_cfg as plat  # noqa: E402

PERSONA_NAME = plat.PERSONA_NAME
DEVICE_ID = "shadps4-local-device"
CLIENT_ID = "MADDEN-20-PS4-CLIENT" if plat.PLATFORM == "ps4" else "MADDEN-20-PC-CLIENT"
AUTH_CODE = "QUOxAAEAAQcMADEyMzQ1Njc4OTAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
ACCESS_TOKEN = "QVQwOjIuMDozLjA6NjA6bWFkZGVuMjAtbG9jYWwtYWNjZXNzLXRva2VuOg"
REFRESH_TOKEN = "UlQwOjIuMDozLjA6bWFkZGVuMjAtbG9jYWwtcmVmcmVzaC10b2tlbg"


def _json(obj):
    return 200, {"Content-Type": "application/json;charset=UTF-8"}, json.dumps(obj).encode()


def handle(method, path, query, headers, body):
    """Return (status, headers, body) or None if not a Nucleus path."""
    if path == "/connect/auth":
        loc = f"qrc:/html/login_successful.html?code={AUTH_CODE}"
        return 302, {"Location": loc, "Content-Type": "text/html"}, b""
    if path == "/connect/token":
        return _json({
            "access_token": ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 14400,
            "refresh_token": REFRESH_TOKEN,
            "refresh_token_expires_in": 86400 * 30,
            "id_token": "eyJhbGciOiJub25lIn0.eyJpc3MiOiJhY2NvdW50cy5lYS5jb20ifQ.",
        })
    if path == "/connect/tokeninfo":
        return _json({
            "client_id": CLIENT_ID,
            "scope": "basic.identity offline signin basic.entitlement basic.persona",
            "expires_in": 14400,
            "pid_id": str(PID),
            "pid_type": "NUCLEUS",
            "user_id": str(PID),
            "persona_id": PERSONA_ID,
            "device_id": DEVICE_ID,
            "connection_type": "PS4",
            "is_underage": False,
            "stopProcess": "OFF",
            "authenticators": [{"authenticator_type": "PS4", "authenticator_pid_id": PID}],
            "issued_at": int(time.time()),
        })
    # Madden "DP" content host (OSDK_MADSET DP_BASE_URL / DP_LCUBASE_URL in handlers.py).
    # /base/tuning/ = "CHECKING ONLINE TUNING DATA": 200 "{}" was accepted (10-14 run tune1, no error dialog).
    # /lcu/<build>/<region>/lcudir.txt = list of live-content files; the client fetched each entry of a
    # "{}" body as a file name (GET /{}) -> serve an empty list.
    if path.startswith("/lcu/") and path.endswith("lcudir.txt"):
        return 200, {"Content-Type": "text/plain"}, b""
    if path in ("/base/tuning/", "/base/custrstr/", "/base/rstr/"):
        return _json({})
    return None

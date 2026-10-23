"""MUT Store + packs (component 0x802). Hot-reloaded via mut.py.
Schemas (tools/tdfrefl.py, 10-17):
  GetStoreCategoryInfo 0x35  -> {DLST list<StoreCategory{CTID, NAME, PRTY, TYPE, LIST list<StoreItem>}>, DECK, MSG}
  StoreItem {SID id, DID dimeId, CPID packId, OID offerId, CDID cardId, TYPE StoreItemType, NAME, SBTL, DESC, IMG,
             FIMG, MBGI, LBGI, USNR useNetres, MCUR/ACUR BankCurrencyEntry{BCID, BCVL}, WIDT/HIGT StoreItemSize,
             NUMI, PRTY, MNUP/MNP/MNGP/MNPG purchase limits/counts, LOCK, LMSG, COMN, SECR, SSC, DATE, DL, COLR}
  GetListStoreItems 0x36 {SIIL ids} -> {LIST, MSG}
  CreatePack 0x8 {TYPE packId, CDID cardId, RCUR payment} -> {ALST list<NewAwardItem>, MSG}
  PurchaseCardOffer 0x33 {OID offerId, RCUR payment} -> {ALST, MSG}
  GetMyPacks 0x138 -> {PCKS list<Card>, MSG};  OpenPack 0x139 {CIID} -> {ALST, MSG}
  GetPackInfo 0x6c {PAKS ids, PAGE} -> {PACK list<PackInfo>, MPAG, MSG}
  NewAwardItem {TITL, CIDS list<Card>, COIN, TICK, CURM, PSDS, PRPG, DRPK}
  Card of TYPE 8 CARDTYPE_CARDPACK carries DATA/STDT = CardPackCardData {PACK cardPackId} (tdf id 0x4eb43a48).
Enums: StoreItemType 1 SINGLEPACK 2 MULTIPACK 3 SINGLECARD 4 CATEGORY; CardPackType 1 PACK 2 BUNDLE 3 STARTER;
StoreItemSize 0 1/4 1 1/3 2 1/2 3 2/3 4 3/4 5 WHOLE.

Pack contents come from the archived card catalog (mutdata/cards.json), drawn by program. Owned unopened packs
and the coin balance persist in mutdata/user_state.json ("packs", "coins")."""
import random

import mut_cards
import mut_team
from tdf import body, enc_int, enc_list_struct, enc_str, enc_struct

CARD_PACK_DATA_TDFID = 0x4EB43A48
CARDTYPE_CARDPACK = 8
STOREITEMTYPE_SINGLEPACK = 1
CARDPACKTYPE_PACK = 1
COIN = 1
START_COINS = 1_000_000
PACK_CARD_ID_BASE = 9_400_000          # Card.ID of a pack card = base + pack id

# ---------------- pack table ----------------
# Slot = dict(n=count, lo=min OVR, hi=max OVR (optional), programs=[...] (default CORE), odds=[(OVR threshold,
# P(card >= threshold))] for the headline slot). Odds slots draw a band from the cumulative probabilities and then a
# uniform card in that band; plain slots draw from [lo, hi] weighted towards lo (FILL_DECAY per OVR point).
CORE = ["Core Bronze", "Core Silver", "Core Gold", "Core Elite", "Core Rookie"]
FILL_DECAY = 0.6


def S(n, lo, hi=None, programs=None, odds=None):
    return {"n": n, "lo": lo, "hi": hi, "programs": programs or CORE, "odds": odds}


# REAL Madden 20 launch store (GamingBolt MUT 20 guide, odds = the in-game "View Info" table; 10-17 research).
# points = the real Points price; Gridiron was Points-only -> its coin price is DERIVED (500 pts x ~60 coins/pt,
# the ratio of the other packs).
LAUNCH = {
    1: dict(name="Get A Player", coins=500, points=None, desc="One 62+ Silver or better player",
            slots=[S(1, 62, 79, odds=[(62, 1.0), (66, .31), (70, .078), (72, .031)])]),
    2: dict(name="Get A Gold Player", coins=5_000, points=100, desc="One 70+ Gold or better player",
            slots=[S(1, 70, 88, odds=[(70, 1.0), (75, .35), (80, .09), (82, .043)])]),
    3: dict(name="Gridiron Pack", coins=30_000, points=500,
            desc="One 75+ Gold or better, three 70+ Gold or better, two 62+ Silver or better players",
            slots=[S(1, 75, 88, odds=[(75, 1.0), (80, .39), (83, .13), (85, .052)]), S(3, 70, 79), S(2, 62, 74)]),
    4: dict(name="Superstars Pack", coins=18_000, points=300,
            desc="One 77+ Gold or better Superstar, one 66+ Silver or better, three 62+ Silver or better players",
            slots=[S(1, 77, 88, odds=[(77, 1.0), (80, .16), (83, .15), (85, .049)]), S(1, 66, 79), S(3, 62, 74)]),
    5: dict(name="All-Pro Pack", coins=30_000, points=500,
            desc="Two 75+ Gold or better, one 70+ Gold or better, one 66+ Silver or better, "
                 "three 62+ Silver or better players",
            slots=[S(1, 75, 88, odds=[(75, 1.0), (80, .42), (83, .14), (85, .052)]), S(1, 75, 79), S(1, 70, 79),
                   S(1, 66, 79), S(3, 62, 74)]),
    6: dict(name="Clutch Pack", coins=40_000, points=700,
            desc="One 80+ Elite player, five 62+ Silver or better players",
            slots=[S(1, 80, 88, odds=[(80, 1.0), (82, .45), (84, .18), (86, .058)]), S(5, 62, 74)]),
    7: dict(name="Elite Player Pack", coins=50_000, points=900,
            desc="One 80+ Elite, two 70+ Gold or better, two 66+ Silver or better, two 62+ Silver or better players",
            slots=[S(1, 80, 88, odds=[(80, 1.0), (83, .33), (85, .12), (87, .034)]), S(2, 70, 79), S(2, 66, 79),
                   S(2, 62, 74)]),
    8: dict(name="Legends Fantasy Pack", coins=120_000, points=1_500,
            desc="One 81+ Legend guaranteed, one 83+ Elite, two Gold or better, three Silver or better players",
            slots=[S(1, 81, 88, programs=["Legends"]), S(1, 83, 88, odds=[(83, 1.0), (85, .20), (87, .072), (88, .037)]),
                   S(2, 70, 79), S(3, 62, 69)]),
}
PROMO_PRICE = 10_000        # nominal: the owner plays with unlimited coins (UNLIMITED_COINS)


def promo_packs():
    """One pack per promo program (every archive program except Core), in MUT 20 calendar order (first card's
    release date). Each pack = one uniformly random card of that promo. Real MUT 20 promo pack odds/prices were never
    published. Ids 101.. follow the calendar order (stable as long as cards.json is unchanged)."""
    progs = {}
    for c in mut_cards.catalog().values():
        name = (c.get("program") or {}).get("name")
        if name and name not in CORE:
            d, lo, hi = progs.get(name, ("9999", 99, 0))
            progs[name] = (min(d, c.get("release_date") or "9999"), min(lo, c["overall"]), max(hi, c["overall"]))
    out = {}
    for i, (name, (d, lo, hi)) in enumerate(sorted(progs.items(), key=lambda kv: (kv[1][0], kv[0]))):
        label = name if name.lower().endswith("pack") else f"{name} Pack"
        ovr = f"{lo}" if lo == hi else f"{lo}-{hi}"
        out[101 + i] = dict(name=label, coins=PROMO_PRICE, desc=f"One {name} player ({ovr} OVR)", program=name,
                            slots=[S(1, 0, programs=[name])])
    return out


PROMO = promo_packs()
PACKS = {**LAUNCH, **PROMO}
CATEGORIES = [(1, "Packs", list(LAUNCH)), (2, "Promo Packs", list(PROMO))]


def ok_msg():
    return enc_struct("MSG", enc_int("RCDE", 0))


def err_msg(text, code=1):
    return enc_struct("MSG", enc_int("RCDE", code), enc_str("RSTR", text))


# ---------------- persistence ----------------
def state():
    t = mut_team.load()
    t.setdefault("packs", {})          # {iid: pack id}
    t.setdefault("coins", START_COINS)
    return t


UNLIMITED_COINS = True      # the owner, 10-17: unlimited coins - balance shown as UNLIMITED_BALANCE, purchases are free
UNLIMITED_BALANCE = 999_999_999   # BankCurrencyEntry.BCVL is int32


def coins():
    return UNLIMITED_BALANCE if UNLIMITED_COINS else state()["coins"]


def new_iid(t):
    iid = t["next_iid"]
    t["next_iid"] += 1
    return iid


# ---------------- TDF ----------------
def price(tag, amount):
    return enc_struct(tag, enc_int("BCID", COIN), enc_int("BCVL", amount))


def numi(p):
    return sum(s["n"] for s in p["slots"])


def store_item(pid):
    p = PACKS[pid]
    # Category item builder 0x472b940 keeps an item only if exactly one of CPID packId (+0x14) / OID offerId (+0x18)
    # is set: pack = CPID!=0 && OID==0, offer = CPID==0 && OID!=0. Both set -> item silently dropped (blank store).
    return body(enc_int("SID", pid), enc_int("DID", pid), enc_int("CPID", pid), enc_int("OID", 0),
                enc_int("TYPE", STOREITEMTYPE_SINGLEPACK), enc_str("NAME", p["name"]),
                enc_str("SBTL", f"{p['coins']:,} coins"), enc_str("DESC", p["desc"]), price("MCUR", p["coins"]),
                enc_int("NUMI", numi(p)), enc_int("WIDT", 1), enc_int("HIGT", 2), enc_int("PRTY", pid),
                enc_str("IMG", pack_image(pid)), enc_int("USNR", 1))


def category(cid, name, pids):
    return body(enc_int("CTID", cid), enc_str("NAME", name), enc_int("PRTY", cid), enc_int("TYPE", 0),
                enc_list_struct("LIST", [store_item(p) for p in pids]))


def pack_card(iid, pid):
    name, desc = PACKS[pid]["name"], PACKS[pid]["desc"]
    data = body(enc_int("PACK", pid))
    return body(enc_int("CIID", iid), enc_int("ID", PACK_CARD_ID_BASE + pid), enc_int("TYPE", CARDTYPE_CARDPACK),
                enc_int("TIER", 3), enc_int("CSTE", 1), enc_str("NAM1", name), enc_str("NAM2", ""),
                enc_str("CNAM", name), enc_str("DESC", desc), enc_int("AQMT", 1),
                mut_cards.enc_var("DATA", CARD_PACK_DATA_TDFID, data),
                mut_cards.enc_var("STDT", CARD_PACK_DATA_TDFID, data))


PACK_ART_VERSION = 3      # bump after regenerating tiles: the client's NetResCache keeps an id for the whole session


def pack_asset(pid):
    return f"pk{PACK_ART_VERSION:02d}-{pid:08d}"


def pack_image(pid):
    """Store tile / pack image: generated art mutdata/art/ui/<pack_asset>.jpg (tools/pack_art.py, served by netres.py).
    The program logos ("swap:86:…" local textures) do not render on store tiles (10-17)."""
    return f"swap:32:1|netres:{pack_asset(pid)}"


def pack_info(pid):
    """PackInfo. URLS imageUrls must be NON-EMPTY: the My Packs builder (0x474c020) looks each owned pack card up
    in the GetPackInfo list by PACK id and drops it when URLS is empty (then picks a random URL as its image) ->
    "You do not currently own any unopened packs" (10-17). The New Items (open now / open later) screen after a
    purchase uses the same lookup."""
    p = PACKS[pid]
    from tdf import enc_list_str
    return body(enc_int("TYPE", pid), enc_str("NAME", p["name"]), enc_str("DESC", p["desc"]),
                price("MCUR", p["coins"]), enc_int("CPTY", CARDPACKTYPE_PACK), enc_int("ISPO", 1), enc_int("ISVI", 1),
                enc_int("DUID", pid), enc_int("RPOD", int(bool(odds_rows(pid)))),
                enc_list_str("URLS", [pack_image(pid)]))


def odds_rows(pid):
    """[(threshold, probability)] of the pack's headline (odds) slot, or []."""
    for s in PACKS[pid]["slots"]:
        if s["odds"]:
            return s["odds"]
    return []


def award(title, cards):
    return body(enc_str("TITL", title), enc_list_struct("CIDS", cards))


# ---------------- pack opening ----------------
def _pool(slot, lo, hi, players):
    progs = set(slot["programs"])
    return [c for c in mut_cards.catalog().values() if (c.get("program") or {}).get("name") in progs
            and lo <= c["overall"] <= hi and c["external_player_id"] not in players]


def _band(odds, rnd, slot_hi):
    """Pick an OVR band from cumulative odds [(thr, P(>=thr))]: the highest threshold whose P beats the roll."""
    u = rnd.random()
    ths = sorted(odds)
    for i in range(len(ths) - 1, -1, -1):
        thr, p = ths[i]
        if u < p:
            return thr, (ths[i + 1][0] - 1 if i + 1 < len(ths) else slot_hi)
    return ths[0][0], (ths[1][0] - 1 if len(ths) > 1 else slot_hi)


def draw(pid, rnd):
    """-> list of archive card records for one pack (one version per real player)."""
    got, players = [], set()
    for slot in PACKS[pid]["slots"]:
        hi = slot["hi"] or 99
        for _ in range(slot["n"]):
            if slot["odds"]:
                lo_b, hi_b = _band(slot["odds"], rnd, hi)
                pool = _pool(slot, lo_b, hi_b, players) or _pool(slot, slot["lo"], hi, players)
                c = rnd.choice(pool) if pool else None
            else:
                pool = _pool(slot, slot["lo"], hi, players)
                c = rnd.choices(pool, [FILL_DECAY ** (x["overall"] - slot["lo"]) for x in pool])[0] if pool else None
            if c:
                got.append(c)
                players.add(c["external_player_id"])
    got.sort(key=lambda c: c["overall"])            # best card revealed last
    return got


def open_into(t, pid, rnd):
    """Draw a pack's cards and add them to the user's collection. -> encoded Card list."""
    out = []
    for c in draw(pid, rnd):
        iid = new_iid(t)
        t["cards"][str(iid)] = c["external_id"]
        out.append(mut_cards.card(c, iid))
    return out


# ---------------- handlers ----------------
def _reply(hdr, payload):
    import mut
    return mut.reply(hdr, payload)


def _q(payload):
    import mut
    return mut.req_fields(payload)


def get_store_category_info(hdr, payload, st):
    st["log"](f"   store: {len(PACKS)} packs, {coins():,} coins")
    return _reply(hdr, body(ok_msg(), enc_list_struct("DLST", [category(*c) for c in CATEGORIES])))


def get_list_store_items(hdr, payload, st):
    q = _q(payload)
    ids = [i for i in (q.get("SIIL") or []) if isinstance(i, int) and i in PACKS] or list(PACKS)
    return _reply(hdr, body(ok_msg(), enc_list_struct("LIST", [store_item(i) for i in ids])))


def get_pack_info(hdr, payload, st):
    q = _q(payload)
    ids = [i for i in (q.get("PAKS") or []) if isinstance(i, int) and i in PACKS] or list(PACKS)
    return _reply(hdr, body(ok_msg(), enc_list_struct("PACK", [pack_info(i) for i in ids]), enc_int("MPAG", 1)))


def buy(hdr, payload, st, pid):
    """Shared by CreatePack / PurchaseCardOffer: charge, then add an unopened pack card to My Packs."""
    if pid not in PACKS:
        st["log"](f"   buy: unknown pack {pid}")
        return _reply(hdr, body(err_msg("That pack is not available.")))
    t = state()
    cost = 0 if UNLIMITED_COINS else PACKS[pid]["coins"]
    if t["coins"] < cost:
        return _reply(hdr, body(err_msg("Not enough coins.")))
    t["coins"] -= cost
    iid = new_iid(t)
    t["packs"][str(iid)] = pid
    mut_team.save(t)
    name = PACKS[pid]["name"]
    st["log"](f"   bought {name} (iid {iid}) for {cost:,}; "
              + ("unlimited coins" if UNLIMITED_COINS else f"{t['coins']:,} coins left"))
    return _reply(hdr, body(ok_msg(), enc_list_struct("ALST", [award(name, [pack_card(iid, pid)])])))


def create_pack(hdr, payload, st):
    q = _q(payload)
    st["log"](f"   CreatePack {q}")
    return buy(hdr, payload, st, q.get("TYPE") or q.get("CDID", 0) - PACK_CARD_ID_BASE)


def purchase_card_offer(hdr, payload, st):
    q = _q(payload)
    st["log"](f"   PurchaseCardOffer {q}")
    return buy(hdr, payload, st, q.get("OID", 0))


def get_my_packs(hdr, payload, st):
    t = state()
    cards = [pack_card(int(i), p) for i, p in sorted(t["packs"].items(), key=lambda kv: int(kv[0]))]
    st["log"](f"   my packs: {len(cards)}")
    return _reply(hdr, body(ok_msg(), enc_list_struct("PCKS", cards)))


def open_pack(hdr, payload, st):
    q = _q(payload)
    t = state()
    iid = str(q.get("CIID", 0))
    pid = t["packs"].pop(iid, None)
    if pid is None:
        st["log"](f"   OpenPack: no pack {iid} (owned {list(t['packs'])})")
        return _reply(hdr, body(err_msg("Pack not found.")))
    if pid not in PACKS:
        st["log"](f"   OpenPack: pack id {pid} no longer exists; refunding nothing, dropping it")
        mut_team.save(t)
        return _reply(hdr, body(err_msg("This pack is no longer available.")))
    cards = open_into(t, pid, random.Random())
    mut_team.save(t)
    st["log"](f"   opened {PACKS[pid]['name']} iid {iid} -> {len(cards)} cards")
    return _reply(hdr, body(ok_msg(), enc_list_struct("ALST", [award(PACKS[pid]["name"], cards)])))


PACKODDS_CATEGORY_OVR = 1        # Blaze::Mut::PackOddsTierCategory


def tier_name(ovr):
    return "Elite" if ovr >= 80 else "Gold" if ovr >= 70 else "Silver" if ovr >= 62 else "Bronze"


def pct(p):
    return "100%" if p >= 1 else f"{p * 100:.1f}".rstrip("0").rstrip(".") + "%"


def pack_odds(pid):
    """Blaze::Mut::PackOdds {PACK, ROWS list<PackOddsTier{ROW, TEXT, SBTX, PTCE, ODDS, TMIN, TMAX, IMGE, POOL,
    DPOL}>, DESC, LDSC, POOL, DPOL} - the in-game "View Info" table (the real MUT 20 numbers for launch packs)."""
    rows = []
    odds = sorted(odds_rows(pid))
    for i, (thr, p) in enumerate(odds):
        hi = odds[i + 1][0] - 1 if i + 1 < len(odds) else 99
        rows.append(body(enc_int("ROW", i), enc_str("TEXT", f"{tier_name(thr)} {thr}+"), enc_str("SBTX", "OVR"),
                         enc_int("PTCE", PACKODDS_CATEGORY_OVR), enc_str("ODDS", pct(p)), enc_int("TMIN", thr),
                         enc_int("TMAX", hi), enc_int("DPOL", 0)))
    desc = PACKS[pid]["desc"] + (". Odds are for the pack's best player." if rows else ". Odds not published.")
    return body(enc_int("PACK", pid), enc_list_struct("ROWS", rows), enc_str("DESC", desc),
                enc_str("LDSC", "Each pack opening is an independent event."), enc_int("DPOL", 0))


def get_pack_odds(hdr, payload, st):
    # GetPackOdds = 0x802/0xfa0 (2nd command range, measured 10-17 from View Info): {PACK packId} ->
    # {MSG, POMP map<uint32 packId, PackOdds>}
    import mut
    pid = _q(payload).get("PACK", 0)
    st["log"](f"   pack odds for {pid}: {odds_rows(pid) if pid in PACKS else 'unknown pack'}")
    m = {pid: pack_odds(pid)} if pid in PACKS else {}
    return _reply(hdr, body(ok_msg(), mut.enc_map_int_struct("POMP", m)))


HANDLERS = {0x35: get_store_category_info, 0x36: get_list_store_items, 0x6C: get_pack_info, 0x8: create_pack,
            0x33: purchase_card_offer, 0x138: get_my_packs, 0x139: open_pack, 0xFA0: get_pack_odds}

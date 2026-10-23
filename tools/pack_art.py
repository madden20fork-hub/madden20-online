"""Generate store-tile / pack images from real EA card art: mutdata/art/ui/pack-<pack id 8 digits>.png.
Each image = pack-colour gradient + diagonal stripes, three of the pack's best possible cards fanned (portrait crop of
the 512x512 card textures), program logo top-right. Served to the client by server/netres.py ("ui" subdir); the
store/PackInfo image strings come from store.pack_image(). Re-run after changing store.PACKS.
usage: python -I tools/pack_art.py"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import mut  # noqa: E402,F401
import mut_cards  # noqa: E402
import store  # noqa: E402

ART = Path(__file__).resolve().parent.parent / "mutdata" / "art"
OUT = ART / "ui"
W, H = 640, 640           # the store tile draws the image into a ~square box (16:10 came out squashed, 10-17)
# launch packs: (colour, logo asset)
THEME = {1: ("#8f99a3", "swap-86-1000002"), 2: ("#c9971f", "swap-86-1000003"), 3: ("#2f7d32", "swap-86-1000003"),
         4: ("#6a2c9a", "swap-86-1000003"), 5: ("#1d5fb8", "swap-86-1000003"), 6: ("#b3261e", "swap-86-1000004"),
         7: ("#12345a", "swap-86-1000004"), 8: ("#8a6a1e", "swap-86-1000004")}


def find(asset):
    for sub in ("cards", "programs", "ui"):
        for ext in (".png", ".jpg"):
            p = ART / sub / (asset + ext)
            if p.exists():
                return p
    return None


def card_file(c):
    ref = mut_cards.image_ref(c.get("external_image_name"))
    net = ref.partition("|netres:")[2]
    return find(net) if net else None


def top_cards(pid, k=3, top=24):
    """k distinct players picked (seeded by pack id, so tiles differ) from the `top` best cards of the pack's
    showcase slot: a non-Core slot (e.g. the Legends slot) if any, else the odds slot."""
    import random
    p = store.PACKS[pid]
    slot = (next((s for s in p["slots"] if s["programs"] != store.CORE), None)
            or next((s for s in p["slots"] if s["odds"]), p["slots"][0]))
    pool = [c for c in store._pool(slot, slot["lo"], slot["hi"] or 99, set()) if card_file(c)]
    best, seen = [], set()
    for c in sorted(pool, key=lambda c: -c["overall"]):
        if c["external_player_id"] not in seen:
            best.append(c)
            seen.add(c["external_player_id"])
        if len(best) == top:
            break
    pick = random.Random(pid).sample(best, min(k, len(best)))
    return sorted(pick, key=lambda c: -c["overall"])


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def background(rgb):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):                                   # dark top-left -> colour bottom-right (diagonal-ish)
        t = y / H
        col = tuple(int(c * (0.35 + 0.65 * t)) for c in rgb)
        d.line([(0, y), (W, y)], fill=col)
    stripes = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(stripes)
    for x in range(-H, W, 46):
        sd.polygon([(x, H), (x + 18, H), (x + 18 + H, 0), (x + H, 0)], fill=38)
    img.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0), stripes)
    return img


def portrait(path, h, border):
    im = Image.open(path).convert("RGB")
    im = im.crop((0, 0, int(im.width * 0.707), im.height))   # card face = left ~70.7% of the texture
    im = im.resize((int(im.width * h / im.height), h), Image.LANCZOS)
    framed = Image.new("RGBA", (im.width + 12, im.height + 12), border + (255,))
    framed.paste(im, (6, 6))
    return framed


def shadowed(base, card, xy, angle):
    card = card.rotate(angle, expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 150), (0, 0), card.split()[3])
    sh = sh.filter(ImageFilter.GaussianBlur(12))
    x, y = xy[0] - card.width // 2, xy[1] - card.height // 2
    base.alpha_composite(sh, (x + 6, y + 8))
    base.alpha_composite(card, (x, y))


def make(pid):
    p = store.PACKS[pid]
    if pid in THEME:
        colour, logo = THEME[pid]
    else:                                                   # promo: the program's own colour + logo
        prog = p["slots"][0]["programs"][0]
        rec = next((c["program"] for c in mut_cards.catalog().values()
                    if (c.get("program") or {}).get("name") == prog), {})
        colour = rec.get("hex_color") or "#444444"
        logo = mut_cards.image_ref(rec.get("external_image_name")).partition("|netres:")[2]
    rgb = hex_rgb(colour)
    img = background(rgb).convert("RGBA")
    cards = top_cards(pid)
    border = tuple(min(255, int(c * 1.25) + 30) for c in rgb)
    places = [((W // 2 - 150, H // 2 + 40), 10, 380), ((W // 2 + 150, H // 2 + 40), -10, 380),
              ((W // 2, H // 2 + 25), 0, 450)]
    order = cards[1:3] + cards[:1]                          # best card in front, centre
    for c, (xy, ang, h) in zip(order, places[-len(order):] if len(order) < 3 else places):
        shadowed(img, portrait(card_file(c), h, border), xy, ang)
    lp = find(logo) if logo else None
    if lp:
        lg = Image.open(lp).convert("RGBA").resize((120, 120), Image.LANCZOS)
        img.alpha_composite(lg, (W - 132, 10))
    OUT.mkdir(parents=True, exist_ok=True)
    for old in list(OUT.glob(f"pack-{pid:08d}.*")) + list(OUT.glob(f"pk??-{pid:08d}.*")):
        old.unlink()
    out = OUT / f"{store.pack_asset(pid)}.jpg"              # JPEG ~120 KB: keep well under the NetRes buffer
    img.convert("RGB").save(out, "JPEG", quality=88)
    return out, [f"{c['first_name']} {c['last_name']} {c['overall']}" for c in cards]


if __name__ == "__main__":
    for pid in store.PACKS:
        out, who = make(pid)
        print(f"{pid:>4} {store.PACKS[pid]['name']:24s} {out.name} {out.stat().st_size:,}  {', '.join(who)}")

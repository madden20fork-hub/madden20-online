"""Simulate pack openings and compare the best-card OVR rates against each pack's published odds table.
usage: python -I tools/pack_sim.py [N=20000]
Note: the published MUT 20 odds are P(headline card >= threshold). Filler slots can also land a card above a
threshold, so measured >= published is expected for low thresholds; the headline slot alone is reported too."""
import random
import sys

sys.path.insert(0, r"C:\madden20_online\server")
import mut  # noqa: E402,F401  (initialises module reload chain)
import store  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
r = random.Random(7)
for pid, p in store.LAUNCH.items():
    odds = store.odds_rows(pid)
    head = next(s for s in p["slots"] if s["odds"])
    hs = []
    for _ in range(N):
        lo, hi = store._band(head["odds"], r, head["hi"] or 99)
        pool = store._pool(head, lo, hi, set()) or store._pool(head, head["lo"], head["hi"] or 99, set())
        hs.append(r.choice(pool)["overall"])
    cards = store.draw(pid, r)
    assert len(cards) == store.numi(p), (pid, len(cards), store.numi(p))
    cells = "  ".join(f"{t}+ {pr:.3f}/{sum(h >= t for h in hs) / N:.3f}" for t, pr in odds)
    print(f"{p['name']:22s} n={store.numi(p)}  published/measured: {cells}")

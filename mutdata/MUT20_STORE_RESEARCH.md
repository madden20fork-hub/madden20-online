# MUT 20 store, pack odds and promo calendar (research 2026-10-17)

## 1. Real Madden 20 launch store — implemented in `server/store.py` (`LAUNCH`)
Source: [GamingBolt MUT 20 guide](https://gamingbolt.com/madden-nfl-20-ultimate-team-guide-tips-pack-prices-and-card-chances)
(the odds are the in-game "View Info" numbers; the same 85+ figures are quoted from Muthead's "Madden 20 Pack Odds"
thread, which is no longer online or archived).

| Pack | Coins | Points | Contents |
|---|---|---|---|
| Get A Player | 500 | – | One 62+ Silver or better player |
| Get A Gold Player | 5,000 | 100 | One 70+ Gold or better player |
| Gridiron Pack | *(Points only — server uses 30,000, derived)* | 500 | One 75+ Gold+, three 70+ Gold+, two 62+ Silver+ |
| Superstars Pack | 18,000 | 300 | One 77+ Gold+ Superstar, one 66+ Silver+, three 62+ Silver+ |
| All-Pro Pack | 30,000 | 500 | Two 75+ Gold+, one 70+ Gold+, one 66+ Silver+, three 62+ Silver+ |
| Clutch Pack | 40,000 | 700 | One 80+ Elite, five 62+ Silver+ |
| Elite Player Pack | 50,000 | 900 | One 80+ Elite, two 70+ Gold+, two 66+ Silver+, two 62+ Silver+ |
| Legends Fantasy Pack | 120,000 | 1,500 | Fantasy pick: 3 Silver+, 2 Gold+, 1 83+ Elite; 81+ Legend guaranteed |

Odds = chance the pack's best player is at least that band (not cumulative across packs; each opening independent):

| Pack | Band 1 | Band 2 | Band 3 | Band 4 |
|---|---|---|---|---|
| Get A Player | Silver 62+ 100% | Silver 66+ 31% | Gold 70+ 7.8% | Gold 72+ 3.1% |
| Get A Gold Player | Gold 70+ 100% | Gold 75+ 35% | Elite 80+ 9% | Elite 82+ 4.3% |
| Gridiron | Gold 75+ 100% | Elite 80+ 39% | Elite 83+ 13% | Elite 85+ 5.2% |
| Superstars | Gold 77+ 100% | Elite 80+ 16% | Elite 83+ 15% | Elite 85+ 4.9% |
| All-Pro | Gold 75+ 100% | Elite 80+ 42% | Elite 83+ 14% | Elite 85+ 5.2% |
| Clutch | Elite 80+ 100% | Elite 82+ 45% | Elite 84+ 18% | Elite 86+ 5.8% |
| Elite Player | Elite 80+ 100% | Elite 83+ 33% | Elite 85+ 12% | Elite 87+ 3.4% |
| Legends Fantasy | Elite 83+ 100% | Elite 85+ 20% | Elite 87+ 7.2% | Elite 88+ 3.7% |

Verified: `tools/pack_sim.py` (20,000 openings per pack) reproduces every band within sampling error; the in-game
View Info screen shows these tables (GetPackOdds 0x802/0xfa0).
Pool = Core programs (Bronze/Silver/Gold/Elite/Rookie; Core Elite tops out at 88, matching the 88+ top band).
Not modelled: "Superstar" X-Factor requirement (Superstars Pack headline is any 77+), Legends Fantasy is a straight
pack (no pick screen).

## 2. Newer Maddens
EA publishes odds only in-game (Store > View Info). EA's MUT 23/24 posts describe the system (per-pack, independent,
100% rows guaranteed, higher OVR bands rarer) but contain no tables:
[MUT pack probability](https://www.ea.com/games/madden-nfl/news/madden-ultimate-team-pack-probability),
[MUT 24 pack probability](https://ea.com/ea-play/news/madden-ultimate-team-24-pack-probability).
No Madden 21/22/23 tables were found online.

## 3. MUT 20 promo calendar (from the archived card records; dates = Muthead import date ≈ release)
Promo pack odds/prices were never published; the server's "Promo Packs" tab (`store.PROMO`) is a placeholder set:
one random card of the promo, prices made up. the owner to choose which promos get packs.

| First card | Last card | Program | Cards | OVR |
|---|---|---|---|---|
| 2019-07-22 | 2019-07-22 | Core Elite | 161 | 80-88 |
| 2019-07-22 | 2019-07-22 | Core Gold | 748 | 70-82 |
| 2019-07-22 | 2019-07-22 | Core Rookie | 252 | 62-77 |
| 2019-07-22 | 2019-07-22 | Core Silver | 912 | 62-69 |
| 2019-07-22 | 2019-07-22 | M20 Pre-Order | 10 | 82-82 |
| 2019-07-22 | 2019-07-22 | Theme Builders | 11 | 86-86 |
| 2019-07-22 | 2019-07-22 | Ultimate Trainers | 37 | 72-85 |
| 2019-07-22 | 2019-07-26 | Core Bronze | 58 | 60-61 |
| 2019-07-22 | 2020-03-20 | Power Up | 416 | 68-78 |
| 2019-07-26 | 2020-01-25 | Legends | 143 | 82-96 |
| 2019-07-26 | 2020-03-20 | Master | 4 | 70-98 |
| 2019-08-09 | 2019-08-09 | MUT Superstars | 5 | 85-90 |
| 2019-08-12 | 2020-01-31 | Veterans | 6 | 84-90 |
| 2019-08-16 | 2020-02-07 | Theme Diamonds | 4 | 88-98 |
| 2019-08-23 | 2019-10-18 | Madden Ultimate Team 10 | 8 | 91-93 |
| 2019-08-30 | 2020-01-07 | Team of the Week | 128 | 75-93 |
| 2019-09-12 | 2019-09-12 | Ultimate Kickoff | 23 | 85-93 |
| 2019-09-20 | 2020-05-01 | Series Redux | 100 | 86-98 |
| 2019-10-06 | 2020-01-12 | Football Outsiders | 20 | 86-93 |
| 2019-10-07 | 2019-10-07 | Flashbacks | 2 | 89-89 |
| 2019-10-07 | 2019-10-11 | MUT Heroes | 23 | 80-92 |
| 2019-10-18 | 2019-10-27 | Most Feared | 5 | 92-93 |
| 2019-11-21 | 2019-11-21 | Harvest | 1 | 94-94 |
| 2019-11-22 | 2019-12-27 | NFL 100 | 39 | 84-95 |
| 2019-11-28 | 2019-12-01 | Blitz | 22 | 86-94 |
| 2019-12-16 | 2019-12-30 | Zero Chill | 36 | 78-95 |
| 2019-12-20 | 2019-12-27 | Out of Position | 10 | 85-95 |
| 2019-12-25 | 2020-01-01 | Ghosts of Madden - Past | 6 | 95-96 |
| 2019-12-29 | 2020-01-01 | Ghosts of Madden - Present | 4 | 94-95 |
| 2019-12-31 | 2020-01-01 | Ghosts of Madden - Future | 4 | 93-95 |
| 2020-01-04 | 2020-01-04 | NFL Playoffs | 32 | 83-96 |
| 2020-01-14 | 2020-01-14 | Team of the Year | 19 | 95-96 |
| 2020-01-24 | 2020-02-03 | Super Bowl Past | 20 | 82-96 |
| 2020-01-27 | 2020-02-04 | Madden Challenge | 3 | 92-95 |
| 2020-01-29 | 2020-02-03 | Super Bowl Present | 7 | 89-99 |
| 2020-02-04 | 2020-02-06 | NFL Honors | 6 | 96-98 |
| 2020-02-08 | 2020-06-27 | Ultimate Legends | 188 | 86-99 |
| 2020-02-21 | 2020-02-21 | Theme Builders 2 | 127 | 85-97 |
| 2020-02-28 | 2020-03-06 | NFL Combine | 24 | 85-97 |
| 2020-03-18 | 2020-03-25 | Free Agency | 32 | 87-98 |
| 2020-03-20 | 2020-03-20 | Gauntlet III | 2 | 96-96 |
| 2020-04-03 | 2020-04-03 | Color Smash | 18 | 87-96 |
| 2020-04-09 | 2020-05-28 | Golden Ticket | 15 | 99-99 |
| 2020-04-17 | 2020-04-17 | Draft Picks | 6 | 90-98 |
| 2020-04-17 | 2020-04-23 | Draft Heroes | 32 | 97-99 |
| 2020-04-23 | 2020-05-08 | Draft Class '20 | 43 | 90-98 |
| 2020-06-12 | 2020-06-12 | M20 Rookie Premiere | 17 | 93-99 |

Dates are approximate: Golden Ticket's in-game challenges ran March 10/13 2020
([RealSport101](https://realsport101.com/article/madden-20-ultimate-team-mut-golden-ticket-promo-release-date-ultimate-challenges-times-packs-ltd-items-coins-hack-cheap-ovr)),
while Muthead imported the cards from April 9.

## 4. Pack art
No real MUT 20 store/pack artwork is reachable: EA's store/hub images (`stor-`, `mthb-`, `dcpi-`, `kdfu-` netres ids
the client requests) are not on Muthead's CDN, and Muthead had no pack pages for 20. Tiles are generated by
`tools/pack_art.py` from real EA card art (pack colour, three of its top cards, program logo).

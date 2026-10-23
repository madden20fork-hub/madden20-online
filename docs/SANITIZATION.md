# Sanitization record

The repo was built by a **whitelist** (`build_release.py` in the owner's workspace): nothing was copied unless a rule
named it, then every text file went through a substitution pass and a leak scan (positive-controlled: the scan was
checked to catch a planted path, name and IP before it was trusted).

## Not in this repo
| What | Why |
|---|---|
| The game, any game file, memory dumps of it, shader dumps, frame captures | Copyrighted. You supply your own extracted CUSA13265. |
| MUT 20 card catalog (`cards.json`) and card/program art | EA content mirrored on Muthead. The launcher's **Download card data** runs the included scraper on your PC. |
| TLS keys/certificates | Generated on your PC at install (`server/make_cert.py`). |
| Player save state (`user_state`, `draft_state`, `h2h_state`), logs, screenshots, network captures | Per-player and identifying. Created fresh at runtime. |
| PC-version tooling and notes | That work targeted an unlicensed PC copy; only the PS4 path ships. |

## Shipped although game-derived
Small tables read from the game's own database in memory: coach / playbook / uniform / stadium rows
(`mutdata/team_items/`), the generic-head list, harvested asset names, the MUT command-name and PlayerCardData schema
tables (`dump/`). They are names and IDs the server needs to answer the client; the tools that produced them are in
`tools/`.

## Substituted
| Was | Now |
|---|---|
| The owner's local paths | `C:\madden20_online`, `C:\games\CUSA13265`, `C:\Users\<USER>` |
| The owner's LAN IP | `192.168.1.10` (the server detects the real one at runtime) |
| The owner's first name in comments / docs | "the owner" (player names such as Matt Ryan untouched) |
| Default persona name | `Player` (PC path; the PS4 path uses the emulator's `shadPS4` identity) |

The PS4 account id `0xE3C9D3C9537D6CE8` in `server/platform_cfg.py` is the client identity the emulator reports and
is left as-is because the protocol echoes it.

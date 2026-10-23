# AI_README — for AI assistants helping someone with this project

Read this before changing anything or answering a user's question. It is the map; `docs/RESEARCH.md` is the full
research log (newest first) with every measured address, protocol fact and dead end.

## What this is
A private server that brings Madden NFL 20 **Ultimate Team** back online for the **PS4 version running on a patched
shadPS4** (PS4 emulator) on Windows. Nothing contacts EA. The user supplies their own extracted game; **the game files
are never modified** — every fix lives in the emulator build, its config, or the local server.

Three parts:
1. **Patched shadPS4** (`emulator/`, full source; upstream shadPS4 + the NLSC 2K14 compatibility runtime + the
   Madden fixes). Madden-specific fixes are gated by flag files in `modroot/flags/` (found via env
   `NBA2K14_MOD_ROOT`; the name is historical — the flag API came from the 2K14 runtime).
2. **Local servers** (`server/`, Python): `http_server.py` = EA redirector + Nucleus login (HTTPS :42230, :443) and a
   plain-HTTP side server (:42240: tuning data, telemetry sink, card art "netres"); `blaze_server.py` = Blaze
   (Fire2 framing, TCP :10041 on the LAN IP). Handlers in `handlers.py`, `mut.py`, `draft.py`, `h2h.py`, `store.py`,
   `gamemanager.py` are **hot-reloaded on every frame** — edit and the next request uses the new code.
3. **Installer/launcher** (`installer/madden20_online.py`, built into one exe with PyInstaller). First run = setup;
   installed copy = launcher (starts both servers, runs shadPS4, stops servers when the game exits). The same exe runs
   the servers/tools with its bundled Python: `--serve http|blaze`, `--tool NAME`.

## Install layout (what the setup exe creates)
```
Madden20Online\
  Madden20Online.exe     launcher (copy of the setup exe)
  settings.json          game_eboot path, fullscreen
  core\shadps4.exe       patched emulator; core\user\ = PORTABLE shadPS4 user dir (config.json, custom_configs\
                         CUSA13265.json, savedata, logs) - never touches %APPDATA%\shadPS4
  modroot\flags\         Madden core flags (see below)
  server\                Python servers; server\certs\ generated at install (make_cert.py); server\logs\
  mutdata\               shipped tables + downloaded cards.json / art\ ; per-player state (user_state.json,
                         draft_state.json, h2h_state.json) is created here at runtime
  tools\                 card scraper/parser + art tools (run by the launcher's "Download card data")
```

## Hard facts (measured — don't re-derive)
- Game: **CUSA13265, APP_VER 01.00**, eboot.bin md5 `c973befec7acd462d31d084743d1b513`. Shader hashes and eboot
  addresses in the core + tools assume this build.
- The redirector must hand out the **LAN IP** (DirtySDK binds to it); 127.0.0.1 fails. Windows will show a firewall
  prompt for the launcher — allow it.
- Servers run with `MADDEN_PLATFORM=ps4` (PS4 client identity). `MADDEN_VERBOSE=0` (launcher default) = no per-frame
  logs; set `1` to log every Blaze frame decoded + raw captures (huge).
- Card data is NOT shipped (it is EA content): `tools/muthead_scrape.py` → `mutdata/raw/` cache →
  `tools/muthead_parse.py` → `mutdata/cards.json`; `tools/art_download.py` → `mutdata/art/`; then `art_shrink.py`,
  `pack_art.py`. All resumable. Requires muthead.com to be up.
- Shipped game tables (`mutdata/team_items/tdb_*.json`, `generic_heads.json`, `asset_names.json`) were read from the
  game's own database in memory; regenerating them needs the RE tools in `tools/` and a running game.
- Gameplay is capped at 30 FPS by the game; menus 60. PS4 Pro mode (`neo_mode`) is OFF: it renders but a 1440p
  render-scale experiment corrupted gameplay frames — see RESEARCH.md before enabling.
- A quit counts as a loss in H2H/Draft (the client sends no end-of-game on quit — same as EA's server).

## Core flags (`modroot/flags/`, all required)
`LOCALONLINE` (signed-in NP state), `EAREDIRECT` (all `*.ea.com` HTTP → 127.0.0.1), `HTTPBEFORESEND` (DirtySDK
pending-state code), `UIMASKFILL` (black-screen fix: UI coverage mask from CMASK), `MADDENMETAEXEC` (run meta-clear
fills), `MADDENDEPTHGPU` (no guest re-upload of depth), `MADDENBUFSYNC` (write GPU-written buffers back to guest
memory — fixes cars/trees on the field), `TEX1DSHADOW` (1D views of 2D targets; was a device-lost source),
`AJMNULLSKIP` (audio job on a destroyed instance), `MODULEUNLOAD` (real module unload so EAWebKit reloads between
games). Ungated core fixes in that branch: coarse-derivative samples, 1D-tiled small mips of 2D textures
(the "pixelated grass" bug), image-overlap expand.

## Common problems
| Symptom | Cause / fix |
|---|---|
| Ports in use | Another copy of the servers, or IIS/VMware on :443. Close it. |
| "Controller Disconnected" that won't clear | Restart the game. |
| Stuck on LOADING GAME (~1 in 3) | Mesh-connect stall; restart the game. |
| Black screen > 15 s at boot | Intermittent boot hang; restart. |
| Cards show silhouettes | Card art not downloaded (launcher checkbox). |
| Free-agent white/navy kits | Uniform cards missing `Card.TMID` — see `server/team_items.py`. |
| "Connection Lost" on the very first run, after Welcome to Madden 20 | Seen once in 5 fresh-profile tests, cause not found (client sent `Auth.logout`). Close the game and press Play again; the profile is kept. |

## Dev workflow (from source, no exe)
`python -I installer/madden20_online.py` runs setup/launcher unfrozen. Servers by hand (from `server/`):
`python http_server.py 42230 443 --plain 42240` and `python blaze_server.py 10041` with `MADDEN_PLATFORM=ps4`.
Build the emulator: clone with `--recursive` (the `emulator/externals/*` submodules are pinned upstream commits),
then from `emulator/` with the VS 2022 x64 tools, clang-cl, Ninja and the Vulkan SDK:
`cmake -S . -B Build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_C_COMPILER=clang-cl
-DCMAKE_CXX_COMPILER=clang-cl -DENABLE_NBA_2K14_COMPATIBILITY=ON -DENABLE_UPDATER=OFF` then
`cmake --build Build --target shadps4`. `ENABLE_NBA_2K14_COMPATIBILITY=ON` is required — it compiles the flag API and
every Madden fix. Build the exe: `python -I installer/build_exe.py --core emulator/Build/shadps4.exe` (needs
PyInstaller, cryptography, Pillow). RE tools in `tools/` (`dis.py`, `hooktrace.py`, `tdfrefl.py`, `live.py`, …) read a
live process or a memory dump you make yourself with `dump_image.py`; paths in them assume `C:\madden20_online`.

## License and credits
GPL-2.0 (`LICENSE`), because the emulator is shadPS4 (GPL-2.0-or-later; third-party licenses in
`emulator/LICENSES/`). The emulator is [shadPS4](https://github.com/shadps4-emu/shadPS4) plus the NLSC NBA 2K14
compatibility runtime it was forked from; the Madden fixes, server, installer and tools are this project's.
Madden NFL 20 is © Electronic Arts; no game content is in this repo. Card data comes from muthead.com at runtime.

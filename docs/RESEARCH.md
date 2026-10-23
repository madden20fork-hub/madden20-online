# Madden NFL 20 private server — research log (newest first)

## ⭐ 10-17 21:00 — MADDEN CORE IS NOW SEPARATE FROM 2K14 (the owner: "build this separate from 2k14")
- **Madden core source = `C:\madden20_online\core_src`** (full copy of the 2K14 tree incl. .git, branch
  `madden20-core`, all Madden changes uncommitted on it). Build: `tools\build_core.bat` → 
  `core_src\Build\madden-RelWithDebInfo\shadps4.exe` (fresh Ninja/clang-cl configure, ENABLE_NBA_2K14_COMPATIBILITY=ON,
  abseil/fmt from `core_src\_deps_src`). `run_madden.ps1`, `run_cdb*.sh`, `dis.py` point there
  (old runner backup `run_madden.ps1.bak_2k14core`).
- **2K14 tree** (`C:\madden20_online\core_src`): today's ungated Madden changes were
  REMOVED (CD derivatives, MipOf micro mips, detiler micro mask + tiling.comp, ResolveOverlap expand, DETILE log) —
  those files are back to HEAD / pre-session; backups `*.bak_madden1017`. Its older flag-gated Madden code
  (MADDEN* flags, BUFSYNC etc., flags read from the mod root) is still in that tree, inert for 2K14. Its `Build\...\
  shadps4.exe` is still the last Madden build until 2K14's tree is rebuilt; the owner's 2K14 core
  (`C:\other_project\core\nba2k14-core.exe`) was never touched.
- From now on: **edit only `core_src` for Madden**; never rebuild the 2K14 tree for Madden work.
- **One-click play:** desktop "Madden 20 (Private Server).lnk" → `C:\madden20_online\Play_Madden20.bat` (starts both
  servers with MADDEN_PLATFORM=ps4 if their ports aren't listening, then `run_madden.ps1 -Play` = borderless fullscreen
  on the main 2560×1440 monitor, no move to monitor 2). Game still RENDERS 1080p; per-game config now
  `"GPU": {"fsr_enabled": true}` to upscale to 1440p (title verified).
- ⛔ **10-20: Pro mode + 1440p poke REVERTED (neo_mode false)** — the owner's gameplay showed the 3D scene squeezed into the
  top-left ~half of the frame with magenta/cyan garbage (HUD fine): some pass still sized for the 1800p/4K layout after
  the boot-time scale write. Untested whether plain Pro (no poke) shows it in that scene. Config backup
  `CUSA13265.json.bak_neo1440`. Back to base 1080p + FSR.
- ⭐ **Native 1440p in Pro mode (10-17 22:00):** live `GameRenderSettings` pointer = global `[0x807a6a9a0]`
  (set by the settings getter @0x84d5ff; class info `GameRenderSettings`, field table @0x80aaf1790). Pro defaults:
  ResolutionScale/ForwardMin/ForwardMax = 0.8333 (3200×1800 of the 4K output), DeferredMin/Max 0.6667, dyn-res OFF.
  The scale is read ONCE at render-target creation (live writes later do nothing; Frostbite ignores `-GameRender.*`
  argv). `tools\res_poke.py` writes 2560/3840 into +0x68/+0x98/+0x54 the moment the pointer appears (~0.2–2 s into
  boot) → scene viewports + scene colour target 2560×1440 (verified title + gameplay). Pacing vs 1800p: >40 ms
  30–70/600 (was 51–81), >50 ms 0–7 (was 14–25), no >100 ms. `run_madden.ps1` starts it automatically when the per-game
  config has `neo_mode: true` (log `runs\res_poke.log`). Draw list now logs `vp=WxH` per draw.
- `to_monitor2.py` (non-`-Play` runs only) re-asserts the window onto monitor 2 for ~20 s; `-Play` never runs it and
  SDL creates the window centred on the primary (1440p) monitor.
- ✅ `neo_mode` (PS4 Pro) WORKS since 10-17 21:00: renders 3200×1800 (dyn-res) and presents 3840×2160 via the same
  present cs 0xa21a9123; its UI mask is 0xfd20 bytes (1080p: 0x3f48) → UIMASKFILL now fills the buffer cs 0xf403f253
  last wrote (any size). Title, menus, gameplay verified on monitor 2. Toggle: per-game config `"General":
  {"neo_mode": true|false}`.
- ⚠️ Pro mode pacing (new `MADDENPACE` log, every 600 flips, always on): avg still 30 fps (game cap) but 8–13% of
  frames >40 ms and 14–25 >50 ms vs 1–6% / 1–7 in 1080p mode. GPU only ~25% busy → CPU-bound: one guest thread
  ~100% (60% kernel) + GameSimulationLoop 83% (50% kernel) = page-fault write-tracking overhead (the memory-model
  cost bbport removes). Real fix = cut that kernel time.

## ★★★★ 10-17 18:50 — REAL UNIFORMS IN GAMEPLAY (runs uni1…uni4, shots uni4_k1/k3/k4)
**Verified in game (H2H Season, run uni4):** our squad in the real Bears dark kit (navy, orange sleeve stripes, GSH +
100-season patches, Bears helmets), CPU Eagles in their white away kit (midnight-green helmets). Intro graphic shows
"BEARS"; scoreboard now shows the Eagles / Bears logos (abbreviations "MUT" / "sha" — still cosmetic).
- **Root cause (measured):** uniform setup `0x476fa40(isHome, Card*)` (called from `0x476a0f0`, which finds the
  uniform CARD whose `ID`/`CIID` matches LineupInfo UNFH/UNFA) writes a per-side slot in the uniform manager
  `[0xa9c8468]` (+8 home / +0x58 away): `+0 = Card.TMID` (**teamId, Card+0xb0**), `+4 isAway`, `+0x22` 4-char TPFX
  ("BEA"), `+0x1a` prefix index, then OFTP is FNV-1a-hashed and looked up (`0x2f8b2b0`) in the team's official-type
  map. **We never sent `TMID` on item cards → 0 → the free-agent kit.** Fix: `team_items.card()` sends
  `TMID = TUNI TGID` (Bears 1, Eagles 13 …) for uniform cards (`SEND_TMID`). Live slot after the fix: home tgid 1
  BEA, away tgid 13 EAG.
- Also changed (kept, not proven necessary): `OFTP` = the uniform asset name (`Bears_ALT1_Uni`) instead of
  "Default" (`OFTP_IS_ASSET`; "Default" is not in the map → index 0). Which uniform VARIANT shows (throwback vs home)
  is not yet confirmed by eye — the owner to check; if the dark/alt choice is ignored, look at OFTP/the map next.
- The game-level TGIDs `[0x807a0bb70/74]` (FNIG GTHG/GTAG) stay 33/0 in MUT — they are NOT what picks the kit.
- **Core fix (no flag):** `TextureCache::ResolveOverlap` — same address/format/type/tiling/mip count but larger
  guest size (image first registered single-level, later sampled with its full mip chain; a 512×512 RGBA8 8-mip
  texture in MUT game load) used to hit `UNREACHABLE` "Unresolvable image overlap" and kill the process (run uni1);
  now `ExpandImage`.
- Diagnostic core flags added (OFF): `MADDENSAMPLOG` (log point-filtered sampler/texture pairs once),
  `MADDENLINEARMIP` (force linear filtering when the texture has mips) — did NOT fix the grass.
- Test forfeits WIPED 20:2x: `mutdata/h2h_state.json` season 2001 = 0-0 (backup `h2h_state.json.bak_1017tests`).
  Verified across opponents: Eagles, Panthers, Jaguars all in their real away kits.
- Run notes: exiting a game to Season Home takes ~100 s (drive `up,500,n@100`), then Select Event → `n@12` → PLAY
  GAME `n@85`. Installing hooktrace hooks mid-game once preceded a Blaze disconnect; install right after boot.
  ~1 in 3 loads stall after createGame (client silent, even keepalives) → relaunch. Boot can hang black → relaunch.

## ★★★★ 10-17 20:20 — PIXELATED GRASS FIXED (runs grass1…grass15; before/after `shots\BEFORE_AFTER_uniforms_grass.png`)
**Verified in game:** the kickoff camera (same as `it5_k1`) now shows smooth turf like a real PS4 capture (YouTube
`ZOhrpfolbPM` thumbnail used as ground truth). Shots `lf3`, `le9`.
- **Field shader = `fs 3bef52ff`** (ni=792 DI, 15 textures). Base colour `fs_img92` = 2048×4096 BC1 at field UV
  (0.01378·X+0.5, 0.00689·Z+0.5) — smooth, not the problem. Turf detail = texture-bombing: per 1-yd cell (`floor(X·s)`)
  hash → random flip of a turf NORMAL TILE `fs_img76` (512×512 RGBA8, 8 mips, tm14 Thin2DThin).
- **Root cause (core, measured with mip-band shader patches):** the turf tile is GENERATED on the GPU at game load
  (mip0 + mips 1-2 as RTs/mip views of the chain image, mips 3-7 as STANDALONE 64×64…8×8 render targets at the mip
  addresses). Mips 3-7 of a 2D-tiled image are 1D (micro) tiled, so those RTs are `Array1DTiledThin1` while the parent
  is `Array2DTiledThin1`; `ImageInfo::MipOf` rejected any array-mode mismatch → separate images → the texture's real
  mips 3-7 stayed stale → every distant pixel (LOD ≥3) got garbage normals → per-cell blocks.
  **Fix:** `MipOf` accepts a 1D single-level image as mip N of a 2D parent when N is in the parent's
  `MicroTiledMipMask()` (new; same rule as `ImageSizeMacroTiled`'s downgrade). MADDENWATCH now shows `rt mip 3..7` on
  the chain image.
- Also fixed on the way (both ISA-correct, ungated): (1) `IMAGE_SAMPLE_CD*` (coarse derivatives) was decoded as a plain
  sample — the gradient VGPRs were read as coordinates (`vector_memory.cpp`, `has_derivatives` now includes
  `CoarseDerivative`); the turf tile is sampled with CD. (2) `tiling.comp` addressed every mip of a 2D-tiled image as
  2D; small mips now use micro addressing via `TilingInfo.micro_mask` (`tile_manager.cpp`, `image_info.*`).
- Diagnostics added (all OFF): `MADDENDETILELOG` (mip layout + micro mask per detile), draw list now logs 16 textures
  with mips/tile mode/pitch, `flags/watch.txt` now also catches storage-image (`imgw`) and render-target (`rt`) writes,
  `MADDENSAMPLOG`, `MADDENLINEARMIP`. Shader A/B method: per-game config `"GPU": {"dump_shaders": true}` →
  `%APPDATA%\shadPS4\shader\dumps`, edit via spirv-cross → glslangValidator → `shader\patch\fs_0x…_N.spv` +
  `"patch_shaders": true` (all 6 permutations of 3bef52ff are identical). Per-game config restored to the original.
- ⛔ The source has one change newer than the running binary (MADDENDETILELOG gate) — **rebuild before the next run**.
- ⚠️ These core changes are NOT flag-gated (MipOf, CD derivatives, detiler micro mips, ResolveOverlap). They are
  hardware-correct but untested on 2K14 — check 2K14 before building anything for it.

## ★★★★ 10-17 18:00 — TEAM STRATEGY / TEAM VISUALS WORK + REAL KICKOFF (runs it2…it5, shots it2_* / it3_* / it5_*)
the owner's order: (1) strategy + visuals updated and working, (2) kickoff change, (3) then native-PC port.
**Verified in game:**
- **Kickoff:** H2H games now start with a real kickoff, 1st qtr 5:00, 0-0, ball on the 35 (shots it3_k4, it5_k1).
- **Lineup > TEAM STRATEGY / TEAM VISUALS** tabs show real items (Matt Nagy, Bears Offense/Defense, Bears Away/Home,
  Soldier Field). Pickers ("Available Team Items") list all 32 head coaches, 40 off / 37 def playbooks, 136
  uniforms, 67 stadiums. **Substitution works and persists**: Defense → 3-4, Coach → Andy Reid, Stadium → Arrowhead,
  Dark → Bears Throwback (`user_state.json "items"`). The game is then played IN Arrowhead (shots it3_k1/it5_k1:
  Chiefs midfield logo, "EXPEDITION" board) → stadium item reaches gameplay.
- ⛔ **OPEN: uniforms don't reach gameplay.** Both teams wear the generic free-agent kit (white/navy, game loads
  `uniforms/freeagent/2019/fre_jersey_2019_whi`). The game's player rows DO carry real asset names (ours
  `Bears_AWAY_Uni`, CPU `Jaguars_HOME_Uni` — note the game picked our LIGHT one and ignored the dark selection),
  so the name isn't the problem; the asset resolve falls back. Tried on UniformCardData: TASN "Bears"/TPFX "Bears"/
  UPFX "HOME" (old), TASN "bears"+"BEA", TASN "Bears"+TPFX/UPFX "BEA"+TLGO (= exact in-game TEAM row values) —
  all generic. LineupInfo HTID/ATID (team TGIDs) in the Season Home/StartDraft lineup made the client STALL after
  IN_GAME (never asked Dc_GetGameAndRenderData) → now only sent inside GetGameAndRenderData's TeamGameData.LINE
  (`team_items.lineup_fields(team_ids=True)`); still generic. **Next idea:** the TUNI rows are keyed by TGID; the
  MUT game teams probably have their own TGIDs with no TUNI rows → find the MUT game teams in the live TEAM table
  (copy @~0x111300ab60, 128 rows, parse with scratch `tdb_at.py <addr> TUAN out.json`) and see what TGID/TUAN they
  get; real MUT may also need `BGPR/BGPS/CRPA` colors on UniformCardData. Unknown whether uniforms EVER rendered in
  MUT/Draft here (earlier runs: not checked).
- Not verified in game: coach and playbook effects (only the lineup UI), opponent's items.

**How it's built — `server/team_items.py` (new):** the game's own DB tables dumped from live memory into
`mutdata/team_items/` (Muthead never archived MUT 20 items):
- `tdb_COCH.json` 255 coaches → 32 NFL head coaches (CHCB 1, TGID 1..32): CCID = CoachCardData.COCH.
- `tdb_PLAB.json` **PLAB table = the playbook registry**: BGID = PlaybookCardData.PBID (0..31 team books in nickname
  order Bears..Texans, BOFF 1 offense / 0 defense; 32+ generics 4-3/3-4/46/Cover 2/Multiple D, Balanced/Spread/Run
  Heavy/West Coast/Run 'N' Gun/Pistol/Run and Shoot), BNAM "KC - A. Reid", PBAN asset. Found via the
  "Madden_Def_Bears" strings; table in a 104-table TDB directory (`tdb_dirs.py PLAB` scratch).
- `tdb_TUNI.json` uniforms (TGID, UANM asset, UDSC "Bears Throwback", UFID); `tdb_STAD.json` stadiums
  (SGID = StadiumCardData.STDM, 40 = MCS stadium); `tdb_TEAM.json` (template copy, mostly college/fictional).
- Card ids: coach 9_110_000+CCID, playbook 9_200_000+BGID*2+off, uniform 9_400_000+UFID, stadium 9_500_000+SGID;
  instance id = card id + 50_000_000. User owns every item. Selection = team default (CHI) overridden by
  `t["items"]`; CPU squads use their own team's items (`t["items_team"] = abbr`).
- `draft.COACHES` = the 32 real coaches (old fake ids 9_100_00x → `LEGACY_COACHES`; the owner's draft migrated to
  Harbaugh 9110092, backup `draft_state.json.bak_coachids`).
- mut.py: `get_deck_page` filters 3 ACTIVE_ITEMS (+OMID = equipped instance → list that item type: coach/stadium
  pickers), 4/5 uniforms (both uniform slots send 5 → all uniforms offered), 6/7 playbooks, 2 ACTIVE_LINEUP = 36
  players + 6 equipped items, 0 binder = players + every item. **`set_non_player_item_to_active` (0x22c)**: NPIT
  0 coach 1 stadium 2 away(light) 3 home(dark) 4 def 5 off → saves, returns {MSG, IPIA, IRIA, TCCP card, LINE}.
- Season test losses booked during these runs (h2h_state 0-4) — wipe `mutdata/h2h_state.json` before the owner plays.
- Controller: the owner's pad dropped ("Controller Disconnected", keyboard can't clear it) → restart fixed it.

### (earlier) 10-17 17:00 — real game start + research
- **the owner: "the game is never a real game, it starts with me on offense at the opponent's 25".** Cause: our
  Dc_GetGameAndRenderData sent `STRT` StartOfGameConditions (CDID 1 = scenario: 1st & 10 at the 25, home ball) +
  `ENDC` ("Win the game") = a Challenge scenario. Now omitted for H2H AND Draft events (`mut.H2H_REAL_GAME`);
  Challenges (events 1..32) keep them. ✅ verified in game 18:00 (kickoff).
- **Native PC port research (the owner asked; next after visuals):** bbport (github deadinside28/bloodborne_pc) runs the
  PS4 eboot natively: eboot converted offline to a flat image, libc/Fios2 linked in, ~5k-line runtime HLE-ing only
  what the game imports, shadPS4 renderer + shader recompiler vendored (~200 changes), new memory model (game memory
  in system RAM, GPU reads in place; WRITE_DATA/DMA/fences done by GPU in stream order), two-stage draw pipeline,
  90–150 FPS on RX 7800 XT. True static recompilers (XenonRecomp/N64Recomp/PS2Recomp) target non-x86 CPUs — n/a
  for PS4. Madden eboot imports ~798 distinct functions (dump/got_names.txt; Bloodborne ~660) incl. the whole
  online stack (NpWebApi, Http/Ssl, EAWebKit prx). Plan: bbport-style = our core minus generic emulation,
  Madden-only runtime + offline-linked eboot; or first port bbport's memory model / 2-stage pipeline into our core.
- the owner quit a Draft game after ~20 s (the scenario start) → the new provisional-loss rule ended his run 0-1. Restored
  to 0-0 (`draft_state.json.bak_1017quit` = the 0-1 copy).
- **"Team Strategy" / "Team Visuals"** are the client's Lineup-screen position groups (list built @0x46f9394:
  … 7 Specialists, 8 Team Strategy = coach + off/def playbook, 9 Team Visuals = uniforms + stadium). Were all
  placeholders (draft.COACHES ids 1-6, PBID 1, Patriots uniforms, Gillette) — replaced, see 18:00. First notes:
  * Uniforms: real asset names `<Team>_HOME_Uni`, `_AWAY_Uni`, `_ALT0…7_Uni` (+AFC/NFC/FA/PRAC/Hologram) →
    `mutdata/team_items/uniform_assets.txt` (148). Our placeholder used `Patriots_Home_Uni` (not canonical case).
  * Playbooks: game files `common/database/playbooks/Madden_<Team>.db` (off) / `Madden_Def_<Team>.db` (def) for all
    32 + generics (West Coast, Run n Gun, Power Run, Air Raid, Pistol, Balanced/Pass/Run, Spread?, 4-3, 3-4, 46,
    Multiple D, Cover 2, Elites, Legends) — list near live 0x102c37e000. PBID ↔ book mapping still unknown.
  * Coaches: no plain-string coach table in memory (only our own card) → need the TDB coach table (tdb_live.py).
  * Muthead never archived MUT 20 items (Wayback: /20/players, /compare, /team-builder only; team builder = players
    + HC only). So items come from the game's own data.

## ★★★★ 10-17 16:30 — MUT H2H SEASONS vs CPU WORKS + back-to-back games in one session (runs h2h5…h2h13)
**Verified in game:** PLAY > H2H SEASON > SEASONS > START NOW > Season Home > PLAY GAME > "vs MUT JAX / Win the
game!" > live gameplay (your MUT lineup vs a CPU MUT squad). Quit → Season Home shows the forfeit (crossed football,
0-1). Then games 2 (PHI) and 3 (CAR) in the SAME session, each loading in ~8 s from PLAY GAME (shots h2h13_*).
1. **H2H = CPU game:** real H2H matchmaking can't work (no peer): with `DraftEvent.CPU 0` PLAY GAME goes
   `NVID DC_MATCHMAKING` → GM `startMatchmakingScenario` (handled, "SEARCHING FOR OPPONENT") and the AS3 UI
   (`fb_logic_fe.service.BaseSessionHelper._AttemptStartGame`) waits forever — its live log string said
   "isH2HMatchReady: false, isValidCpuMatch: false". **`h2h.CPU_OPPONENT = 1`** → the client takes the Draft solo path
   (`DC_CPUGAME` → createGame → Dc_GetGameAndRenderData). UI = ION ActionScript VM, no raw ABC in memory (not decompiled).
2. **Season state** `mutdata/h2h_state.json` (h2h.py `begin/record/season/opponent`): a different CPU squad per game
   (`opponent_abbr`, JAX→PHI→CAR…), event WIN/LOSS/NGWN from it, 10-game season then reset.
   ⭐ **A quit sends NO Dc_ProcessEndOfGame** (measured) → `Dc_ProcessStartOfGame` (0x2c3, {DFID 52001, GRID})
   books a provisional LOSS; `Dc_ProcessEndOfGame` (0x2c5, {SCDT scoreDelta, QTRS, SCNI, ECIL} — no event id, so
   `mutdata/current_game.json` remembers DFID) settles it (SCDT>0 = win). Same for the Draft (`draft.begin_game`).
   **A full game to the final whistle (real end-of-game → win) is still UNTESTED.**
3. ⛔→✅ **2nd MUT game of a session always crashed** (3/3) @0x815bb57d7 on thread WebBrowser: EAWebKit.prx trap
   "Error: This API should be called on the same thread as EAWebKit thread." Cause: the game unloads EAWebKit at
   every game load (`sceKernelStopUnloadModule`, eboot @0x8059686ee; handle in [0xad3b608]) and reloads it in the
   menus; the core had StopUnload as a STUB and `LoadAndStartModule` returns an already-loaded module without
   running init → stale WebKit. **Core fix (flag `MODULEUNLOAD`, now ON):** process.cpp real
   `sceKernelStopUnloadModule` → `Linker::RetireModule` (module.h `retired`: skipped by FindByName + Resolve; every
   other module's resolved import slot pointing into the retired image gets its rela bit cleared so the reload
   relinks it — the eboot had 1 such import). Log: "retired, next load maps a fresh copy" / "reloading unloaded
   module … as handle 5/6". Old image stays mapped (~27 MB leaked per game; fine for a session).
   NIDs: `qiOZEn26Kds` = `CreateEAWebkitInstance` (scratch nid.py: SHA1(name+518D64A6…)[:8] base64 +-).
   Stub slots are exhausted (8192) → stubs log only "UnknownStub: Returning zero to <ra>"; map ra with
   `dis.py <ra> --back 8` (shows `STUB:<name>`).
4. **Next-game stall fixed (server, gamemanager.py):** the client removes the old game only at the next createGame
   (`removePlayer` REAS 7); we answered PlayerRemoved REAS 0 (=JOIN_TIMEOUT) and never removed the game → it waited
   12–93 s for its old mesh, and past ~90 s the Blaze connection dropped (10053) and the game never loaded. Now
   PlayerRemoved(echo REAS) + **NotifyGameRemoved**. `leaveGameByGroup` (0x16, sent at quit) stays a plain reply —
   answering it with the removals made the exit to menus take ~78 s. **`CPU_GAME_TOPOLOGY = 255` NETWORK_DISABLED**
   for PMAX-1 games (client asks 130 FULL_MESH): mesh step now ~1 s every time (was 1…129 s random).
5. Tooling: `tdf.py` decodes **GENERIC (type 12)** (present, tdfId varint, raw value, 0x00) — the matchmaking
   request's SCNA attributes; `handlers.py` **inject hook**: write `server/inject.py` defining `OUT = [frames]`
   (`gm`, `st` in scope) → sent on the next client frame, renamed `inject.done`.
   `natives.py` regex must fullmatch (use `.*x.*`). OS thread names don't show guest names (Unknown(Registered)).
**Open / cosmetic:** intro says "Difficulty Rating: 0"; scoreboard team abbreviations show "_"; opponent titled
"MUT JAX" (could be a fake user squad name); H2H season end (10 games / playoffs / rewards) not built; Salary Cap
Ranked (2002) untested; full-length game + real win never played. Core tree still dirty/uncommitted.
Run notes: `press_start.sh` hangs (waits for a log line the quiet filter hides) — drive with `drive.py` keys
`n,1500,enter,1500,n,2000,n@40` from the title; nav to Season Home = `right,600,right,800,n@25` `u@4`
`down,500,down,800,n@8` `n@6` `n@10`. In game: `b,b` then `enter` = pause; EXIT = `right×3,n` then `up,n`.

## ★★ 10-17 14:45 — MUT H2H (Seasons) vs a CPU opponent — superseded by 16:30 above
Goal (the owner): "regular MUT matchmaking ... play an online game but it's just a CPU controlled team".
**Works so far (verified in game, shots art1_t3 / u1 / w1):** PLAY > H2H SEASON > Head to Head Events landing
(SEASONS / SALARY CAP RANKED / PLAY A FRIEND / MY RANK) > SEASONS > Select Event shows our "Seasons" event >
START NOW > **Season Home** (PLAY GAME / ADJUST LINEUP / LEADERBOARD / SEASON PROGRESS).
- Flow measured: `Dc_GetLandingPageData` (RDET 8 = H2H_MUT_RANKED) → `Dc_GetDraftEvents {FILT [7] =
  DRAFTEVENTTYPE_H2H_MUT_UNRANKED, GMOD 1}` → `Dc_GetEventPaymentOptions` → `Dc_StartDraft {DFID 2001}` →
  `Dc_GetHubData {DFID = INST 52001}` → PLAY GAME.
- New **`server\h2h.py`**: events 2001 "Seasons" (type 7) / 2002 "Salary Cap Ranked" (type 8), `events_for(FILT)`,
  `hub_data()` = the MUT lineup (DECK incl. coach + playbook/uniform/stadium items, DEPC, LINE) + event.
  `draft.dc_get_draft_events` routes FILT 7/8 there; `draft.dc_get_hub_data` routes INST 50000+eid there.
- ⛔ BUG FIXED: `draft.is_draft_event` was `eid >= 1000`, so StartDraft for 2001 opened a DRAFT (coach round) and
  **overwrote `mutdata\draft_state.json` — the owner's earlier Draft Champions run is lost** (no backup). Now 1000–1999.
- ⛔ PLAY GAME first gave "Invalid Lineup Warning (no valid defensive playbook item / players without games)":
  the client caches the **StartDraft DraftInfo** as the event lineup. `mut.dc_start_draft` (non-draft branch) now
  sends the full deck incl. coach + team items + `lineup_info(t, coach)`. Needs a game restart to clear the cached
  bad lineup (the event lineup editor loops on the warning) → restarted as run **h2h1**.
- **Next (in progress):** PLAY GAME → expect GameManager `startMatchmakingScenario` (0x10). Added
  `gamemanager.start_matchmaking_scenario`: reply {MSID}, then 2.5 s later `NotifyGameSetup` (20) with REAS union
  **member 3 = MatchmakingSetupContext** (RSLT 0 SUCCESS_CREATED_GAME) and a 1-player roster (us). UNTESTED.
  Then see what the client asks for (opponent team / 2nd player / mesh). Risk: real H2H is peer-to-peer; if the
  game insists on a connected 2nd console the fallback is an H2H-styled event run as a CPU game.
- GM notification ids decoded with new `tools\notifnames.py` (switch @0x54b53b0): MatchmakingFailed 10,
  MatchmakingAsyncStatus 12, GameRemoved 16, GameSetup 20, PlayerJoining 21, PlayerJoinCompleted 30,
  PlayerRemoved 40, GameStateChange 100. GM cmds: startMatchmaking 0xd, startMatchmakingScenario 0x10,
  cancelMatchmakingScenario 0x11, joinGame 0x9.
- ✅ After the restart (run h2h1, shot h2h1_a6): Season Home reads the H2H event — SEASON PROGRESS **0 OF 10 WINS**,
  tile "ADJUST ACTIVE LINEUP" (= the MUT lineup, ATLP=1); H2H hub data served 37 lineup cards. The game is parked on
  Season Home with PLAY GAME focused — next press = the first matchmaking test.

## ★★★ 10-17 14:21 — EVERY PROMO HAS A PACK + UNLIMITED COINS (the owner: "all promos should have packs, price
doesn't matter, I'll have unlimited coins") — verified in game (shots art1_q3, r4)
- `store.promo_packs()` builds one pack per archive program except the 5 Core ones = **42 packs**, ids 101–142 in MUT 20
  calendar order (first card release date), each = one uniform random card of that promo, nominal 10,000 coins.
  Store tab "PROMO PACKS". Tiles regenerated (`PACK_ART_VERSION` = 3 → `pk03-*`).
- `store.UNLIMITED_COINS = True`: wallet shows 999,999,999 (int32 BCVL), purchases cost 0. Set False to restore the
  saved balance in user_state.json "coins".

## ★★★★ 10-17 14:12 — REAL MUT 20 STORE: launch packs + real odds + View Info + Open now/later + tile art
(verified in game, shots art1_g7 / h2 / i2 / j3 / l1 / m2 / n1)
- **Open now / Open later**: already the client's own flow once `PackInfo.URLS` is non-empty — after CreatePack the
  UI runs the "new award" screen (natives HaveNewAwardsInCache → NextNewAwards → GetCurrentNewAwardPacks) =
  **New Items: ✕ OPEN PACK / OPTIONS DISMISS ALL / ◯ OPEN LATER**. Open → OpenPack + reveal; later → Unopened Packs.
  (The first purchase in the session before the URLS fix just returned to the store.)
- **Store = the real MUT 20 launch store** (`store.LAUNCH`, tab "PACKS"): Get A Player 500 … Legends Fantasy 120,000
  with the real slot contents + odds (GamingBolt / in-game View Info). Gridiron was Points-only → coin price derived
  (30,000). `tools\pack_sim.py` reproduces every odds band (20k openings/pack). Pool = Core programs.
  Placeholder **"PROMO PACKS"** tab (`store.PROMO`, 1 card of a promo, made-up prices) — the owner to curate.
  Research write-up incl. the 47-program promo calendar: **`mutdata\MUT20_STORE_RESEARCH.md`**.
- **View Info** = `GetPackOdds` **0x802/0xfa0** (2nd command range) → `{MSG, POMP map<uint32 packId, PackOdds{PACK,
  ROWS list<PackOddsTier{ROW, TEXT, SBTX, PTCE 1=OVR, ODDS "39%", TMIN, TMAX}>, DESC, LDSC}>}`. Shows the real table.
- **Tile / pack art**: generated by `tools\pack_art.py` → `mutdata\art\ui\pk02-000000NN.jpg` (pack colour + 3 real
  card textures + program logo; 640×640 — the tile draws a ~square box, 16:10 got squashed). Served via netres
  `swap:32:1|netres:pk02-…` for StoreItem.IMG (USNR=1) and PackInfo.URLS. ⛔ The client's NetResCache keeps an id for
  the whole session → after regenerating bump `store.PACK_ART_VERSION` (id prefix pkNN). PackInfo is fetched only
  at MUT entry → re-enter MUT to see PackInfo changes. `swap:86:…` program logos do NOT render on tiles.
- netres index now also covers `art\ui` and rebuilds when an art folder changes (cache on `sys._madden_netres_index2`).
- Window: no 2nd monitor connected today → `tools\win_origin.py 0 0 1700 990` puts the whole game window on screen
  (default 2576×1479 is larger than the 1920×1080 desktop; buttons were cut off). `tools\cdn_probe.py` checks
  Muthead's MUT 20 CDN for asset ids (stor-/mthb-/dcpi-/kdfu- are NOT there).

## ★★★★ 10-17 13:46 — CARD ART + MUT STORE / PACKS WORK (verified in game, run art1, shots art1_*)
**Card art:** lineup, binder, Top Players and pack reveals show EA's real card art, served from `mutdata\art` over
NetRes (`http_server.py --plain 42240`, `/netres/<id>`). Four fixes:
1. `Card.MIMG` / `Program.SIMG` must be the UI image form **`swap:<a>:<b>|netres:<id>`** (format @0x6576dc6; game's own
   "swap:400:40|netres:dcpi-00000106"). The archive's Muthead form "32,1|lgnd-00052129" never produced a request.
   `mut_cards.image_ref()` converts (`IMAGE_FORM="raw"` reverts). Fetch code 0x3645320 strips an optional "netres:".
2. Core cards ("26,10100112"/"25,…", 2,234 cards) name local swappable textures this build does NOT have
   (silhouette) → `SWAP_NETRES_FALLBACK` appends `|netres:swap-26-10100112` = our downloaded EA texture. Verified.
3. 19 archive images were too big for the NetRes buffer (Free Agency free-000538xx.jpg = 512×512 JPEG with ~8.7 MB
   extra data → served but never shown). `tools\art_shrink.py` re-encoded them; originals in `mutdata\art\_orig\`.
4. `netres.py` index lived in a module dict reset by the per-request reload while other request threads read it →
   random MISSes for existing files. Index now built once and published on `sys._madden_netres_index`.
**Store + packs** (`server\store.py`, hooked into mut.py HANDLERS; persisted in `user_state.json` "coins"/"packs"):
- 9 packs (Gold 5k … Golden Ticket 500k) drawn from the archive by program — table `store.PACKS` (the owner can edit
  names/prices/slots). Flow verified: STORE → GET MORE PACKS → tile → BUY WITH COINS → confirm → `CreatePack`
  (0x8 {TYPE packId}) → coins deducted → UNOPENED PACKS shows 1 → open → `OpenPack` (0x139) → gold reveal animation →
  6 Core Gold cards in the binder with art. Wallet = saved coin balance (995,000 after one Gold Pack).
- Traps found (all measured on the consumer):
  * **Binder capacity**: store refused with "Your binder has a maximum capacity of 0 items" → `GetConfigurationInfo.
    RSCG` ReservesConfig {ADSC soft cap +0xc, ADHC hard cap +0x10} (UI native GetCardCountLimit 0x47d6f10 →
    0x46fdf80, MutManager config +0x1d40). Now 2000/3000.
  * **Store item filter** 0x472b940: an item is kept only if exactly ONE of `CPID` packId / `OID` offerId is set
    (pack: CPID≠0, OID=0). Both set → blank store page.
  * **My Packs filter** 0x474c020: each pack card (TYPE 8, `CardPackCardData{PACK}` tdf 0x4eb43a48) is matched to
    `GetPackInfo` PackInfo by id and DROPPED unless `PackInfo.URLS` (list<string>) is non-empty → "You do not
    currently own any unopened packs". PackInfo is fetched once at MUT entry (re-enter MUT after changing it).
- Buying returns to the store (pack goes to Unopened Packs); there is no "open now" prompt — unverified whether real
  MUT opened immediately.
**Open (cosmetic):** store tiles are plain grey (IMG = program logo "swap:86:…" doesn't render; tried USNR=1);
EA hub banners `stor-/mthb-/dcpi-/kdfu-` netres ids are not in the archive (404); Top Players OVR 255
(GetTeamPreviewData 0x1f8 still empty). Nothing committed.
**Tooling added (tools\):** `natives.py <regex> [targets.txt]` (UI-script native name → impl via "lea rdx,[impl];
lea rcx,[class]; lea r8,[name]" — feed the targets to `hooktrace.py install` to see which natives a screen calls),
`memstr.py <regex> [lo hi]` (live-memory strings), `live.py "<expr with Q()/D()/R()>"` (live reads),
`drive.py <tag> "keys@wait=shot" ...` (keys + screenshots + new netres/Mut log lines), `strs.py` (eboot strings),
`ti.py` (typeinfo / container element types), `art_shrink.py`.

## ★★★★ 10-17 06:05 — MUT DRAFT GAME IS PLAYABLE (crash 3 fixed: RenderData)
Draft Home → PLAY GAME → load → "vs MUT NO / Win the game!" → Continue → live gameplay (drafted squad on the field,
play calling, clock, penalties). Client then sends `Mut.Dc_ProcessStartOfGame` (0x2c3, answered empty — fine so far).
**Root cause of crash 3:** the MUT roster commit (0x476d970) does `update <temp> set <appearance…> 'PGHE' = GNHD
where 'POID' = PLID` for every `RenderData.PCRD` entry (0x476dd50), then `delete from <temp> where 'PGHE' = 0`
(0x6614d81). We sent empty HRDA/ARDA → every player deleted → PLGA empty → game-start registration loop
(0x20de8d0: `select PGID,SPEP,TGID from PLGA`, MUT branch → 0x20e08b0 per player) registers nobody → empty ability
hub + no on-field players → getter crash. **Fix:** `mut.render_data()` sends one PlayerCardRenderData per lineup card
(PLID = card external_player_id, GNHD = a GenericHead enum value 1..407 + matching SKIN, neutral 0.5 morphs) in both
Dc_GetGameAndRenderData and GetRenderData. Head table: `mutdata/generic_heads.json` (from the GenericHead_<skin>_*
enum in the eboot). Faces are generic (no appearance data archived).
How it was found (tooling worth keeping): `hooktrace.py` now records r9 + 3 stack args + rax (128-byte records,
131072-entry ring), `show N --q [filters]` decodes TDB query format strings at rcx; hook the TDB query executor
`0x44d3d30` to log every statement; hooking right after a call captures its return in rax; relocator handles
`lea r64,[rip]`. Exhibition comparison: ability hub has all 147 players there; MUT relies on PLGA.
Still open: (1) intermittent stall after the IN_GAME push — client sometimes never requests Dc_GetGameAndRenderData
(seen 1 of 3 runs; restart fixes); (2) end-of-game / Dc_ProcessEndOfGame + draft progression untested; (3) PAGM /
HTID-ATID experiments are behind off flags (`mut.SEND_PAGM`, `mut.SEND_TEAM_IDS`); (4) hardware watchpoints in cdb
make shadPS4 hit "Device lost" — don't use `ba`.

## ★★★ 10-17 (later) — crash 3 narrowed: no players are on the field when the per-player update runs
- Crash 3 @0x20e2ff6 reproduces every run now (dcgm24/26b/27/28/30), ~4 s after Dc_GetGameAndRenderData, on the
  normal "LOADING…" tip screen. Full guest stack (cdb-hold + guest_stack.py): MaddenPlayerEntity::Update 0x2f7aed0 →
  PlayerEntity::Update 0x3d90020 → vtable slot +0x260 (0x2f7bd20 → 0x3d93ec0, unconditional every update) → state
  gate (0x3d03170 state in 0x3e..0x4f etc.) → `0x20e2fa0` ability getter → FootballAbilityHub find-or-insert
  (0x20bd7e0, table [0xa770388]) → zeroed entry → [entry+8]=NULL deref.
- The entity's PGID comes from the on-field slot table `[0xab34a08] + team*0x2c + slot*4 + 0x90`: at the crash ALL
  11 slots of BOTH teams are 0x7fff (no player). So the real problem: players are never assigned to the field.
  (Roster build itself now works: 72 AddPlayerCard calls, featured filler runs — but featured lists are [0,0,0]
  for both teams, i.e. its PLGA query `where TGID=team` found nothing usable.)
- Game TGIDs at load: home `[0x7a0bb70]`=33, away `[0x7a0bb74]`=0 (set by 0x30fc3c0 from game-info FNIG GTHG/GTAG,
  which game init 0x2e77820 copies from team-selection table MTTS (UNLS 0/1)). Away 0 is suspicious.
- Ruled out (each tested with a run): PAGM (`mut.SEND_PAGM`, now False — still crashes); LineupInfo HTID/ATID =
  squad's dominant card TEAM id (`mut.SEND_TEAM_IDS`, now False — still crashes). Ability definitions can't be
  faked: GUIDs are djb2-hashed names checked against the game's 142-entry ability table [0xa7703e8]; an unknown GUID
  derefs the bucket sentinel. Exhibition (resumed game) has an EMPTY ability hub and never reaches the getter.
- Tool notes: big ReadProcessMemory spans fail on shadPS4-protected pages → read in ≤1 MB chunks. The TDB directory
  is in HOST memory (was 0x21ace6f6360 on 10-14); tdb_find.py found nothing this time (format/location changed?).
  Background keys: only numpad (kp2=Cross, kp6=Circle…) work unfocused; arrows/letters need the fresh-boot focus.
  Slow boots make boot_to_menu time out ("no window") — wait for the window before running dc_repro.
- **Next:** find who fills the field-slot table in a working mode (hardware write watch on `[0xab34a08]+0x90` in a
  fresh exhibition under cdb), then see why MUT never gets there; check MTTS/FNIG contents in MUT (fix TDB finder).

## ★★★ 10-17 — MUT DRAFT: crash 2 FIXED (missing coach item); crash 3 open
- **Crash 2 root cause (measured):** `teamBuild` 0x476a9a0 validates both lineups first (0x477a910 depth chart,
  0x3399b60 items). Failure sets global `[0x80abeb9bc]` = 1 home / 2 away and returns WITHOUT building rosters →
  `rosterCommit` 0x476d970 / featured-player filler 0x478f970 never run → MutGameManager+0x50/+0x70 stay empty →
  PMSB insert @0x61173b4 NULL deref. Live value was 2 (CPU team). 0x3399b60 checks coach, stadium, both playbooks,
  both uniforms ("The lineup does not have a valid coach item."). `mut.lineup_info` sent no CCH/CCI and the deck had
  no coach card. **Fix:** `mut.team_coach(t)` + coach card in DECK + CCH/CCI in LINE for both teams in
  `team_game_data` (drafted coach for the user, fixed `draft.COACHES` entry for CPU/plain-MUT squads).
- MutGameManager map: +0x50/+0x70 = per-team `vector<int>` of 3 "featured" PGIDs (filled by 0x478f970:
  `select PGID,POS,OVR from PLGA where TGID=team and POS not OL/FB/K/P/KOS/LS order by OVR desc`, PAGM members
  +100000 score) → TDB `PMSB` (read by Broadcast montage) and `indicatorManager` ring colour (card TIER via +0x1680).
  +0x90 map PGID→card (`AddPlayerCard` 0x478f3b0), +0x1610+team*0x40 = PAGM instance ids (0x478f1f0).
- Also added (not the crash-2 fix, kept): `LineupInfo.PAGM` playerAbilityGroupMap = map<ActiveAbilityEnableGroup
  1 OFF/2 DEF, list<uint64 iid>>, top-3 OVR starters per side (`mut.ability_groups`). Card `APAI` (active ability
  id) / `PPAL` are not sent; `Mut.GetPlayerAbilityData` 0x233 (PADM ability definitions) is answered EMPTY.
- **After the fix:** run dcgm23 loaded past the old crash (no exception), then ~90 s later the game went back to
  "PRESS ANY BUTTON" and closed its Blaze connection — cause unknown (no screenshots of the load). Run dcgm24 (same
  data) instead crashed 4 s after GetGameAndRenderData: **crash 3 @0x20e2ff6** — `0x20e2fa0(player)` takes the
  player's PGID, looks it up in the player-ability registry (0x20bd7e0) and derefs entry+8 → NULL. Registry entries
  are made in the player build (0x476f7ac…0x476f866) only for cards whose APAI is found in the ability definitions.
  Caller 0x3d94233 (per-player, condition `[x+0x1c]-0x50 < 0xf`). Suspects: empty PADM / missing APAI, or a
  race (dcgm23 didn't hit it). Next: capture the load with screenshots, and try serving GetPlayerAbilityData.
- Tooling: `tools\targets_feat.txt` (teamBuild/rosterCommit/featFill/…); `tools\run_cdb_hold.sh` = run_cdb.sh that
  keeps the process paused 15 min after a crash so `hooktrace.py show` / memory reads still work (cdb `.shell`
  is useless here: COMSPEC is Git Bash). `tools\guest_stack.py` works against the paused process (cdb -pvr).

## ★★★ 10-16 NIGHT — MUT DRAFT: PLAY GAME now reaches game load (in progress)
Flow that now works (Draft Home → PLAY GAME): `0x808/0xd NVID DC_CPUGAME` → **GameManager createGame** (gamemanager.py) →
NotifyGameSetup(20) → client `meshEndpointsConnected`(0x41) + `finalizeGameCreation`(0xF) → reply + NotifyPlayerJoinCompleted(30)
→ client `advanceGameState(PRE_GAME)` → NotifyGameStateChange(100) → **server pushes IN_GAME (131) 3 s later** → client sends
**`Mut.Dc_GetGameAndRenderData` (0x2d0)** (first time ever) → our 200 KB reply → `SetClientState MODE 2` → game load.
Key findings (all measured with the new tracer):
- GM ids verified from the client's name switches: commands `dump\gm_cmds.txt`, notifications switch @0x54b53b0 (id=idx+3).
- ⛔ Do NOT send NotifyGameStateChange(PRE_GAME) with the finalize reply: the OSDK GameSession service only attaches
  (SetActiveGameSession) when the createGame callback fires on that reply, so the notify is missed; the client then
  advances to PRE_GAME itself. `blaze_server.py` now has `state["send_later"](delay, frame)` for deferred pushes.
- ⭐ The CPU-game UI (`BaseSessionHelper._AttemptStartGame`: localReady && isValidCpuMatch && mGameSessionStarted) needs an
  IN_GAME state change it never requests itself → server pushes it after PRE_GAME (gamemanager.advance_game_state).
- Crash 1 FIXED: `UniformCardData.OFTP` (officialType) empty → NULL name lookup @0x3257490 (via 0x476fcdf). Now "Default"
  (`mut_cards.OFFICIAL_TYPE`; valid names unverified). Also added `MutGameSettings.HSRL` standard house rules (harmless).
- **Crash 2 OPEN** @0x61173b4: while writing game setup into the TDB (`use 'XPCB' insert into 'PMSB' set 'DIGP'=…'IPMF'=i`,
  i=0..2 per team) it reads 3 ints from `[[0x80abebb08]+0xa8]+0x50` = MutManager::mMutGameManager's TdfPrimitiveVector<int>
  (likely playbook ids: PMSB/DIGP = BSMP/PGID reversed 4CC) which is still EMPTY → NULL deref. Find what fills it
  (probably from GetGameAndRenderData/lineup playbooks; our PlaybookCardData PBID=1 is unverified).
- **Mesh flakiness OPEN**: time from createGame to meshEndpointsConnected varies 1 s … 68 s and once never came (3+ min).
Tooling: **`tools\hooktrace.py`** (generic debugger-free guest call tracer: capstone prologue relocation, 16K ring,
records rdi/rsi/rdx/rcx/r8/tsc/return addr; `install <targets.txt>`, `mark`, `show N`), target lists `tools\targets_*.txt`,
`tools\decode_trace.py` (resolves OSDK log format strings). ⭐ Hook the OSDK logger `0x35a9650` (`targets_log.txt`): it
gives OSDK's own trace (GameSession/CPreGame/BlazeCreateGameOperation…). `tools\settings_obj.py` dumps the game manager fields.
OSDK/draft map: DraftGameSetup adapter impl vtable 0x774ab28 (CreateCpuSession +0x38 → 'sesg' GameSession service
0x76b5838 → BlazeCreateGameOperation; CPU-session-created callback +0x50 posts DraftGameSetup.CreateCpuSession(bool));
draft helper listener vtable 0x7740b20 (+0x308 InitGameSetupFinished, +0x310 FinalizeGameSetupFinished, +0x3e0 game-sync ok).

## ★★★ 10-16 EVENING — shadPS4 GAMEPLAY RENDERING FIXED (cars/trees/white field/device-lost)
the owner asked to get PS4 gameplay rendering correct. **Done and verified**: wide pre-snap camera, kickoff/FG cameras,
in-play, replays, stadium exterior — 60+ screenshots over two cold boots + a 6-min continuous soak, zero cars/trees,
green field, end-zone text/logos, jumbotron, full crowd. No device-lost in any run since the fix. Gameplay 30–35 FPS
(game cap), menus 60 (`MADDENFPS` warning line every 600 flips).

**Two fixes (core, both flag-gated; flags in `C:\madden20_online\modroot\flags`):**
1. **`MADDENBUFSYNC` (new) — GPU→guest writeback of GPU-written buffers.** Frostbite moves mesh/instance data with a
   GPU memcpy compute (`cs 0x5b69b9f8`, cb[0] = dword count; verified byte-exact 20/20) and the CPU later reads /
   `memcpy`s / partially rewrites those pools. shadPS4 (readbacks off) never wrote GPU results to guest memory, so
   the CPU worked on stale bytes and whole-page re-uploads clobbered GPU-copied records → car/tree meshes drawn with
   other objects' transforms, far-field LOD chunks missing (gray/white field). Fix: `BufferCache::NoteWriteback` on
   every written buffer binding (+ CP DMA copy dst); `FlushWritebacks()` runs from `Rasterizer::ProcessDownloadImages`
   (called by liverpool right before every EOP/EOS fence write): one batched copy → download buffer → `Finish` →
   `TryWriteBacking`, skipping pages the CPU dirtied meanwhile and unmapped ranges. Optional filter
   `flags/bufsync_only.txt` (hex writer hashes; `d3a0` = CP DMA). ~115 MB/s written back; no FPS cost measured.
2. **`TEX1DSHADOW` bug fixed — this was the "Device lost during submit" crash.** NVIDIA logged Xid 13 *"WIDTH CT
   Violation"*; validation showed `vkCmdCopyImage` 2D→1D and B10G11R11 ↔ R16G16B16A16 (4 B vs 8 B texels) plus an
   incompatible image view. Cause: the 1D shadow of the auto-exposure 1×1/3×1 targets was keyed by ImageId and kept
   after Madden recycled the address for a different-format target. Now: shadow uses the requested format, is
   dropped when the source image is deleted (`TextureCache::DropShadow1D` from `DeleteImage`) or the format changes,
   copies only same-texel-size via a buffer (`CopyImageWithBuffer`). Readbacks/writeback simply made the game hit
   this path at boot; the old intermittent 3–15-min device-lost is the same bug.

**What was ruled out (measured, don't redo):** no CPU writes are missed by page tracking (per-page GPU-vs-guest
compare: 0 "missed" pages); no dynamic `ReadConst` (DMA setting irrelevant, and DMA-on stalls the game);
`SET_PREDICATION` / `COND_EXEC` / `COPY_DATA` never occur in gameplay; the 368 DMA_DATA/frame are L2 prefetches
(dst 0x3022c); synchronous submit deadlocks at the load screen (bounded version: `MADDENSYNCSUBMIT`, diagnostic only);
shadPS4 `readbacks_mode` 1/2 device-lost at boot (= the TEX1DSHADOW bug; may work now but BUFSYNC is cheaper).

**Diagnostic tooling added (all off unless flag present):** `MADDENDRAWPROBE` (+ `flags/DRAWLIST` → per-draw/dispatch/CP
event list `modroot/framedump/drawlistNN.txt` for 3 flips; `flags/drawskip.txt` hex shader hashes skipped live;
`flags/watch.txt` "start end" → logs GPU writers into a range; `flags/READTRAP` → no-access trap on recently
GPU-written pages, logs first CPU touch with guest RIP — noisy because the game recycles memory), `MADDENDRAWCMP`
(per-draw readback diff GPU copy vs guest, classifies race/stale/missed pages), `MADDENCOPYMIRROR` (superseded by
BUFSYNC). Driver: `tools\presnap.sh <tag>` (boot → Exhibition → Resume → pick play; uses numpad Cross `kp2`, which
works without window focus — letter keys need focus). Pause menu = `enter`; Instant Replay = down + kp2.

**Play config now:** flags AJMNULLSKIP EAREDIRECT HTTPBEFORESEND LOCALONLINE MADDENBUFSYNC MADDENDEPTHGPU
MADDENMETAEXEC RELOCLOG TEX1DSHADOW UIMASKFILL; per-game config = quiet log filter only (backup
`CUSA13265.json.bak_1016`). Servers for a PS4 run: `MADDEN_PLATFORM=ps4 python http_server.py 42230 443 --plain 42240`
and `MADDEN_PLATFORM=ps4 python blaze_server.py 10041`. Core tree is still uncommitted (dirty).
**Not yet checked:** other stadiums/teams, weather/night games, MUT/Draft games (createGame still unimplemented).

**10-16 late — live-play verification (the owner: "make sure gameplay works upon choosing a play"):** restarted a fresh
Exhibition and ran ~15 real plays (kickoffs, run/pass on offense incl. a 70-yd TD, defense, FG/PAT, penalties,
replays) across 5 boots, capturing ~13 frames per play from play-call → snap → whistle: no cars/trees, no missing
geometry, no device-lost, 31–41 FPS. One cars-on-field frame was seen on a cold boot BEFORE the extra fix below
(huddle camera) → added `ProcessDownloadImages()` (= BUFSYNC flush) before `WRITE_DATA` labels on gfx + compute
queues and writeback for CP fills (`NoteWriteback(...,0xf111)`); not seen since. Video/ribbon boards sometimes all go
white at once with a faint logo — looks like the board's own flash animation, not proven. Diagnostic flags
`MADDENRTLOG` / `MADDENRTGPU` (texture_cache RefreshImage: log / skip guest re-upload of GPU-rendered RTs) exist, OFF —
RTGPU did not change the board and touches R8 mask RTs (3072x3453, 2048x2526) the CPU may legitimately write.
Late-game frames look warmer/darker: that is the game's time-of-day (identical with RTGPU on and off).
Input: `liveplay.sh <tag>` = pick play + capture; snapping needs repeated Cross (kp2) — a single press lands in the
walk-up cutscene and the play clock runs out (delay of game).

# (PS4 / shadPS4 history)

## ★ 10-14 EVENING SESSION (read first) — MUT cards fixed, Draft Champions drafts end-to-end
**Direction (the owner, 10-14 18:40):** gameplay rendering on PS4 does NOT matter — he is moving to the **PC version**; the
goal is MUT + MUT Draft (Draft Champions) working with the cards, server logic that carries over to PC.
§10 (field render corruption) is parked; two diagnostic core flags were added there and are OFF (no flag files):
`MADDENVBFORCE` (buffer_cache: re-upload every non-GPU-written read-only buffer each bind — did NOT remove the
cars/trees, so it is not CPU-write coherence) and `MADDENMAPLOG` (memory.cpp: log direct mappings / aliases).

**State now:** MUT hub/team/lineup show the archived cards with real OVRs; a full Solo Draft runs
(Coach round + 26 player rounds → Draft Summary → Draft Home "0 OF 4 WINS") and PLAY GAME passes the client's lineup
validation and sends **GameManager createGame (comp 4 cmd 1)** — unimplemented → blank screen. That is the next step.

### Client wire facts learned (all measured; apply to PC too — same BlazeSDK)
1. **Variable TDF** (`DATA`/`STDT` cardData, type 7): `tag 07 01 <varint tdfId> [<same tag> 03 <fields> 00] 00`
   — the value is ONE struct member carrying the variable's own tag (Heat2Decoder @0x5518720, kind-7 case @0x55198ca).
   Unwrapped fields are silently skipped → all-zero PlayerCardData (this was the "OVR 255 / 0" bug). `mut_cards.enc_var`.
2. **TimeValue members go on the wire as INT (type 0)**, not 11 (kind-14 case @0x5519b89). Type 11 fails the member
   and drops the REST of the struct (DraftEvent TOTR/TYPE were lost → "ROUND x OF -1"; CensusData subscribe reply too).
   `tdf.enc_time` fixed; `handlers.py` now hot-reloads `tdf.py`.
3. **Fields must be globally tag-sorted**: `body()` sorts the chunks it gets — never pass a pre-joined multi-field blob
   next to other fields (`mut_cards.enc_fields` now returns a list).
4. **Maps are sorted vector maps** (binary-searched) → emit keys ascending (`mut.enc_map_int_*`).
5. **Every id the client sees must be < 2**31** — the UI scripts pass ids through signed 32-bit ints (draft instance
   7.1e9 came back as 18446744072219909004). MUT card iids now 100,000,001+ (`mut_team.FIRST_IID`; old
   `user_state.json` kept as `.bak_bigids`), draft iids 1,0xx,xxx,xxx.
6. Card image: `Card.MIMG mainImage` = archive `external_image_name` ("32,1|lgnd-00052129"), `Program.SIMG` likewise —
   sent, but art still shows the silhouette for most cards and NO HTTP image request is made (likely LCU content;
   some Core cards do render real art). Open.

### Draft Champions protocol (server/draft.py; event id 1001 "Solo Draft", type CPU)
- Landing `Dc_GetLandingPageData 0x2ee` (EVTY list, RDRE event, UBNK) → Solo Draft tile → `Dc_GetDraftEvents 0x2bc`
  → START NOW → `Dc_GetEventPaymentOptions 0x2f2` (needs ≥1 PaymentOption, else blank "Choose Reward Structure";
  with one option the client auto-picks it) → `Dc_StartDraft 0x2be` → `Dc_MakeDraftPick 0x2bf` × rounds.
- The event's **INST must already be in the GetDraftEvents list** (client caches it) → instance allocated at listing.
- **Round 1 is a COACH round** (RTYP 1, CARDTYPE_COACH cards w/ `CoachCardData` tdfid 0x05578d39); player rounds
  are RNUM 2…; header reads "ROUND <RNUM-1> OF <TOTR-1>". Without the coach round the UI stalls at RNUM 2.
- **Exactly 3 options/round** (numPicks hard-coded 3 @0x46e1858). DEPC must list **every** lineup slot (empty until
  drafted) or the board grid breaks. RoundOption.DELT {OVR,OFF,DEF} = rating change of the pick.
- Native UI events (listener vtable 0x7740b20): SlotPreviewReady is posted by fn 0x46e1170 when the UI focuses an
  option; PickComplete after a pick; NewPicksReady/UpdateDraftInfo never fire in this flow.
- After the last pick the client frees its DraftInfo and does NOT ask for the team; **re-entering the event** calls
  `Dc_GetHubData 0x2ca` {DFID=instance} → we return DECK/DEPC/LINE/DRTS/TTWO → Draft Home + lineup work. (OPEN: make
  the in-session hand-off work without backing out — find what the client expects after the final pick.)
- **Lineup validation before a game** (client-side): every card needs `CNTR` contract games (players AND coach),
  LINE needs an offensive + defensive playbook item (OFFP/OFFI, DEFP/DEFI; `PlaybookCardData` 0xb881f01c {PBID,
  ISOF}), light+dark uniform items (UNFA/UNFI, UNFH/UNI; `UniformCardData` 0xd9060387), a stadium item (STDM/STDI;
  `StadiumCardData` 0xa5cfbe0a {STDM}). All in `mut_cards.playbook_cards()/playbook_lineup_fields()` and used by the
  MUT lineup too. PBID=1 and uniform asset names ("Patriots_Home_Uni"/"Patriots_Away_Uni") are UNVERIFIED in game.
  Stadium ids = first u16 of the game's stadium table (live memory ~0x1043c01ca7, 208-byte records): 10 State Farm,
  14 Arrowhead, 16 Lucas Oil, 18 AT&T, 40 Gillette, 46 M&T, 52 CenturyLink, 54 Heinz, 60 U.S. Bank, ... (40 used).

### New tools (C:\madden20_online\tools)
`dc_repro.py <tag> [picks]` (boot→MUT→Draft→Solo→start→N picks; `DCSKIPBOOT=1`, `DCSLOW=2`) ·
`hook_events.py install|show` (**debugger-free guest function tracing**: patches 14-18 byte prologues with an
absolute jmp to a stub that logs args into a ring buffer; cdb runs kept dying with nvoglv64 present AVs / device
lost) · `uilog.py [regex]` (UI script log/assert strings in memory) · `dcstate.py` (live draft manager @[0x80abebb08]:
DraftInfo +0x2a0, cached event +0x288) · `memread.py` (`--card <CIID match>` decodes a client Card object) ·
`blazetail.py mark|show [--full]` · `montage.py` · `run_cdb_trace.sh` (hw-breakpoint logging; unstable).

### Next steps (in order)
1. **GameManager createGame (4/1)** reply + NotifyGameSetup etc. so a draft/MUT game actually starts (needed on PC).
2. In-session draft → hub hand-off; Draft Summary still shows 0 OVR (DELT sent — summary may read something else).
3. Verify playbook ids / uniform assets / stadium in a real game; card art (MIMG/LCU); MUT hub "Top Players" 255
   (GetTeamPreviewData 0x1f8 empty); the owner's starter-squad rule for the MUT team (still all-99 "best").

Last updated: **2026-10-14 15:25** (day session: main menu, MUT hub, card archive, perf 5→30 FPS, rendering fix). Goals (the owner, 10-14): **(1)** a private server that makes Madden 20 think it's online, like the 2K14/15/19/20 servers; **(2)** play **Ultimate Team (MUT)** and **Draft Champions** on it.

Stop condition for a session: *the owner can see and play MUT / Draft Champions against the local server.* Stop earlier only for a wall that needs his access.

Memory: `madden20-black-screen-solved-cmask` (current), plus older `madden20-shadps4-server-project`, `madden20-phase0-psn-auth-map`, `madden20-phase1-ea-endpoints`, `madden20-blaze-protocol-spec` (⚠️ the last two contain pre-10-14 guesses: :42127 TLS redirector, 12-byte header, ConsoleAuth — all **wrong** for this title, see §5).

---
## 0. START HERE — state in one screen

| Area | Status (measured 10-14) |
|---|---|
| Boot / rendering | ✅ Title screen + attract video + "Welcome to Madden 20" first-run setup **render** |
| Redirector | ✅ answered locally (sceHttp XML, :42230) |
| EA Nucleus login | ✅ /connect/auth → /connect/token → /connect/tokeninfo answered locally |
| Blaze login | ✅ PreAuth → configs → Auth.login → UserSessions notifies → PostAuth → ~70 post-login requests |
| OSDK settings crash | ✅ FIXED 10-14 day — `GROUP_VIEWS["O_SG_SYSS"] = ["UGEN","UACCT"]` (run ugen1, no crash) |
| Tuning data | ✅ FIXED — "Tuning Data Update: error downloading" came from EMPTY `OSDK_MADSET` config: needs `DP_BASE_URL`+`DP_TUNING_URL` (URL = concat; served by nucleus.py on *.ea.com, `200 {}` accepted). `lcudir.txt` must be an empty body (a `{}` body is parsed as a file list → GET `/{}`) |
| Gameplay load | ✅ FIXED — host assert "Attempting to execute job on null instance" in `AjmContext::ProcessBatch` (game destroys an AJM instance with a batch still queued). Core flag **`AJMNULLSKIP`** fails the job instead |
| Pro Bowl intro game + **main menu** | ✅ 10-14 run tune2: intro game plays, Quit → main menu "Hello, shadPS4" with Exhibition / Ultimate Team / Franchise / FotF tiles |
| **MUT hub** | ✅ 10-14 14:13 — `server\mut.py` (hot-reloaded via handlers.py): NUF state COMPLETE(4), TeamInfo teamFound, wallet `BCMP {1: 1,000,000}`, `BCYM` bank currencies → hub "Ultimate Team: MISSIONS/PLAY/STORE/TEAM/MORE", **1,000,000 COINS** shown. Empty-reply traps: `SKIP canSkip=1` + empty skipInfo = blank YES/NO dialog; empty CompleteNewUserFlowState reply = state INVALID → tour screen again |
| **MUT card catalog** | ✅ DONE 10-14 — the owner chose real archived MUT 20 data. Scraped **3,789 cards / 47 programs / 2,466 players** from muthead.com/20/players (`tools\muthead_scrape.py`, cached HTML `mutdata\raw\`, resumable) → `tools\muthead_parse.py` → **`mutdata\cards.json`**. Each card page's `mut-card` `data-props` JSON is EA's own item record: `external_id` = EA cardId, `external_player_id` = EA player id = asset suffix (`MahomesIIPatrick_12635`), every rating, traits, program/archetype/team external ids, tier, trade/auction flags, quicksell, salary. Top programs: Core Silver 912, Core Gold 748, Power Up 416, Core Rookie 252, Ultimate Legends 188, Core Elite 161, Legends 143, TOTW 128 |
| Card → TDF | ✅ `server\mut_cards.py`: archive record → `Blaze::Mut::Card` + `PlayerCardData` (TDF id **0x2e29456a** = high dword of the typeinfo qword at desc-8) in BOTH variables **`DATA` and `STDT`** (STDT missing → NULL deref crash @0x46ed0f7, client reads POS / positionOvrRatings from `[card+0x1d0]`). Field map: snake→camel against `dump\playercarddata_schema.txt` + explicit table. Catalog cached across hot reloads by `server\mut_cache.py` (mtime-keyed) |
| Asset names (faces) | 🔶 only **532 / 2,466** players have an exact `PLAN` name, harvested from memory by `tools\asset_names.py` → `mutdata\asset_names.json` (fixed set; does NOT grow in gameplay). Others get a constructed `LastFirst_id` (no Jr/II suffix). UNVERIFIED whether the client needs `PLAN` or resolves the head from `PLID` — check in the first MUT game |
| MUT team / games | 🔶 CODED, NOT YET VERIFIED IN GAME — `server\mut_team.py` (owned cards + depth chart persisted in `mutdata\user_state.json`; delete it to regenerate) and `mut.py` handlers: GetDeckPage 0x47, GetDepthChart 0x1a (DMAP = map<PlayerPositionEnum, DLST>), GetCpuTeamGameCategories 0x15f / ForSequence 0x162 (one "Ultimate Challenge" per NFL team), GetGameData 0x4a (home = your lineup, away = that team's best cards), GetRenderData 0x5f (empty), Process Start/EndOfGame 0x2d/0x2e. Last live test crashed on the missing STDT (fixed since, untested). **Starter squad rule = the owner's call** — `STARTER_MODE` "best" (all-99 sandbox: Golden Ticket / Ultimate Legends / Rookie Premiere) is only a plumbing test |
| MUT hub calls still empty | GetHubOptions 0x51, ProcessReturningMutUser 0x6d, GetTeamPreviewData 0x1f8, GetObjectivePanelData 0x14a, GetLineupPanelData 0x5c, GetStoreCategoryInfo 0x35, GetInfoPanel 0x5a, GetDirectPurchaseItems 0x37, 0x1004 (2nd switch range), GridironClub 0x938/2, MiscServiceGateway 0x808/0x3e8,0x3f2 |
| Draft Champions | 🔶 landing page renders (Unranked / Ranked / Solo Draft / Play a Friend / My Rank) via `Mut.Dc_*` (0x2c6 Handshake, 0x2c7 GetConfigurationInfo, 0x2c8 GetNewUserFlowState, 0x2ee GetLandingPageData) — all empty replies. Draft flow cmds: 0x2be StartDraft, 0x2bf MakeDraftPick, 0x2bd ResumeDraft, 0x2d0 GetGameAndRenderData, 0x2c3/0x2c5 Start/EndOfGame. Uses the same card catalog |
| Roster (local) | ✅ the launch roster IS on disc (Exhibition team select shows Colts/Patriots with portraits; LCU `lcudir.txt` only adds updates). In-memory TDB layout decoded (`tools\tdb_live.py`, `tdb_find.py`, `memscan.py`: BE 16-byte field defs {type, bitOffset, reversed 4CC, bits}) but the PLAY table found was an empty template — not needed now that cards come from the archive |

**First thing next session:** (1) read the crash-diagnostic dump if the `cdl1` run hit "Device lost" (`%APPDATA%\shadPS4\log\`); (2) live-test MUT PLAY → Challenges with the STDT fix — does a game launch, do faces come from `PLID` or need `PLAN`; (3) the owner's starter-squad rule.

**MUT RE tools:** command names `dump\mut_cmds.txt` (switch @0x266abe0, `add esi,-8` → id = index+8; a 2nd range for ids ≥0xfa0 is not decoded yet); enum values `tools\enumvals.py Blaze::Mut::<Enum>` (nodes {name*, value} 0x20 apart right before the descriptor); container types: typeinfo kind 2=map (+0x28 key ti, +0x30 value ti), 3=list (+0x28 elem), 11=struct, 20=int32, 21=uint32, 6=string, 5=enum.

**PERFORMANCE (measured 10-14, same scene Colts@Patriots, `--show-fps`):** gameplay **5 FPS under cdb + full logging → 30 FPS** (the game's own gameplay cap; menus 60) with `run_madden.ps1` + quiet per-game log filter (`%APPDATA%\shadPS4\custom_configs\CUSA13265.json` → `Log.filter`) + server answering `AssociationLists.getLists` / `CensusData.subscribe` (empty replies made the client resend them ~40×/s). ⛔ **Never play under cdb** — shadPS4's first-chance-AV page tracking round-trips the debugger. cdb only to catch a crash. Tools: `tools\perf_playnow.py` (scripted scene), `tools\fps_strip.py`, `tools\threadcpu.py` (per-thread CPU: GameSimulationLoop ~90% w/ ~55% kernel, GPU thread 15-40% → CPU-side, not GPU-bound). Open rendering bugs (not perf): blown-out white stadium half, grainy grass, black bar artifact.
**RENDERING (10-14):** missing/white geometry in gameplay traced to shadPS4 `IsComputeMetaClear` SKIPPING every dispatch of the fill shader `cs 0x3475fc53` that writes an address ever registered as CMASK/HTILE — `surface_metas` is never pruned and Madden reuses memory, so real buffers never got cleared. Flag **`MADDENMETAEXEC`** keeps the clear-tracking but runs the fill → huddles/close-ups/crowd render correctly (shots `metaexec1_*`, `cdl1_chk`). Diagnostic flag `MADDENMETALOG` (once per shader+surface). The 70k+/session "Unexpected metadata read by a shader (texture)" are FALSE positives (1600×1600 R16 shadow map sitting at a stale HTILE address). Still open: white speckle in grass shadows. **The "stadium-exterior white void / cars & trees on the field" is now root-caused + partially fixed — see §10 (NOT an HTILE bug; it is depth/color memory aliasing + stale vertex geometry; flag `MADDENDEPTHGPU`).**
**DEVICE LOST:** intermittent `vk_scheduler.cpp:194 SubmitExecution: Device lost during submit` (host int3, exit 0x80000003) after 3–15 min, also seen at quit-to-menu. RTX 5070 Ti. Hunting with `"Vulkan": {"vkcrash_diagnostic_enabled": true}` in the per-game config (dump → `%APPDATA%\shadPS4\log\`). Keep `"Log": {"sync": true}` so the assert text survives.
Core fixes this session: `AJMNULLSKIP` flag (job on destroyed AJM instance), MP3 OFL-probe bounds clamp in `ajm_mp3.cpp` (host AV reading "Xing" past input; ungated, pure OOB fix).

**Input / window (the owner works on the main monitor):** the game window is moved to monitor 2 by `tools\to_monitor2.py` (spawned by both runners). Drive input with **`tools\keys_bg.py`** (PostMessage, no focus steal) — `keys.py` (SendInput) needs the game focused and Windows blocks a background process from taking focus.

---
## 1. Files & layout

- Game (extracted, good): `C:\games\CUSA13265\eboot.bin` (CUSA13265, fw 6.70, BlazeSDK 15.1.1.7.5, DirtySDK 15.1.4.0.6).
- Server + tools: **`C:\madden20_online\`**
  - `server\http_server.py` — HTTPS :42230 (redirector) + :443 (Nucleus via `nucleus.py`, everything else `200 {}`). Logs `server\logs\http_server.log`, raw requests `server\logs\http\`.
  - `server\blaze_server.py` — Blaze TCP :10041 on the **LAN IP** (Fire2 framing). Logs every frame decoded to `server\logs\blaze_server.log`, raw bytes `server\logs\blaze\`.
  - `server\handlers.py` — all Blaze command handlers. **Hot-reloaded on every frame** (no restart needed). `nucleus.py` likewise per HTTP request. `blaze_server.py` / `http_server.py` themselves need a restart if edited.
  - `server\tdf.py` — TDF codec + Fire2 framing; `body()`/`enc_struct()` auto-sort fields by tag.
  - `server\redirector_response.xml` — `{HOST_IP}` / `{HOST_IP_U32}` substituted at request time.
  - `modroot\flags\` — Madden-only core feature flags (§3). `runs\` — logs, `crash_<tag>.txt`. `shots\` — screenshots. `dump\` — live image dump + RE tables.
- Core source: `C:\madden20_online\core_src` (branch `nba2k14-park-mod` @ d5a4ae37). Build: `C:\other_project\tools\build.bat` → `Build\x64-Clang-RelWithDebInfo\shadps4.exe`. ⛔ Never overwrite `C:\other_project\core\nba2k14-core.exe` (the owner's 2K14 core).
- Per-game shadPS4 config: `%APPDATA%\shadPS4\custom_configs\CUSA13265.json` — quiet `Log.filter`, `Log.sync: true`, and (while hunting device-lost) `Vulkan.vkcrash_diagnostic_enabled: true`; remove that last one for normal play. Shared 2K14 config untouched. Log: `%APPDATA%\shadPS4\log\shad_log.txt`.
- MUT data: `mutdata\cards.json` (catalog), `mutdata\raw\` (scrape cache), `mutdata\asset_names.json`, `mutdata\user_state.json` (your team).
- Driving tools: `tools\run_madden.ps1 -Seconds 0` (play session, no timeout), `tools\boot_to_menu.py <tag>`, `tools\keys_bg.py` (keys: n=Cross b=Circle c=Triangle v=Square enter=Options q/u=L1/R1, arrows).

## 2. Run procedure

```
# terminal 1 / 2 (cwd C:\madden20_online\server)
python http_server.py 42230 443
python blaze_server.py 10041
```
- Game under cdb with crash capture (recommended): `bash C:/madden20_online/tools/run_cdb.sh <tag>` → crash report `runs\crash_<tag>.txt` (breaks only on **second-chance** AV — shadPS4 uses first-chance AVs for page tracking).
- Plain run: `powershell -File tools\run_madden.ps1 -Seconds 3000 -Tag x [-Extra "--show-fps"]` (sets `NBA2K14_MOD_ROOT=C:\madden20_online\modroot`).
- Press Start: `bash tools/press_start.sh 30` (waits for window + `cas_02.cas` mount, then Cross/Options). `tools\keys.py` refuses to type unless the game window is focused (an earlier version typed "nn" into the owner's chat when the game had crashed).
- Crash triage: `python -I tools/triage.py <tag>` (fault insn, string args, disasm, last Blaze requests).
- Screenshot: `python -I tools/shot.py <name>` (desktop grab; PrintWindow returns black).
- Ports: 42230 & 443 bound on 127.0.0.1; 10041 on the LAN IP (192.168.1.10 at the time).

## 3. Core changes (all flag-gated except logging; flags live in `modroot\flags`, so 2K14 is unaffected)

| Flag | File | What / why |
|---|---|---|
| `LOCALONLINE` | np_manager.cpp, np_auth.cpp (existing 2K14 code) | Async NP calls (CheckNpAvailability, ParentalControl, AuthCode…) returned SIGNED_OUT → game retry-looped. Offline-identity patch only covered the getters. |
| `HTTPBEFORESEND` | http.cpp `sceHttpGetStatusCode` | DirtySDK ProtoHttp (`0x57f14fa`) treats **only** `0x80431065 BEFORE_SEND` as "pending"; core returned EAGAIN → request aborted. Under flag: pending → BEFORE_SEND, transport failure → NETWORK. |
| `EAREDIRECT` | http.cpp `RunRealHttpRequest` | every `*.ea.com` sceHttp request → 127.0.0.1 same port/scheme, cert verify off. |
| `UIMASKFILL` | vk_rasterizer.cpp `DispatchDirect` | **black-screen fix** (§4). Fills the 0x3f48-byte UI coverage mask with 0xFFFFFFFF before present shaders `0xb5f1cbd1`/`0xa21a9123`. Bounds-guarded (`IsInBounds`). |
| `TEX1DSHADOW` | texture_cache.cpp/.h | 1D texture bindings on 2D height-1 RTs (auto-exposure targets) get a private 1D copy — removes invalid-view Vulkan UB. Not the black-screen cause; kept. |
| `RELOCLOG` | linker.cpp | filter widened to log the 0x800000000 eboot relocs → `modroot\eboot_dump\relocs.txt`. |
| `DUMPFRAME` (off) | texture_cache.cpp | dumps every image bound in flip 2400 to `modroot\framedump\*.raw` (convert: `tools\framedump_to_png.py`). This is what found the black-screen cause. |
| (no flag) | sys_net.cpp | `sys_connect`/`sys_bind` log the sockaddr at INFO. |
| (no flag, probes) | driver.cpp, vk_rasterizer.cpp, texture_cache.cpp, image_view.cpp | `MADDENGFX` probes: flip/draw stats every 120 flips, display-buffer image lookups, present-cs buffer dump, detailed 1D-view error. Remove/gate before any 2K14 release build. |

Tree is **dirty** (8 files, ~300 lines). Earlier `MADDENPROBE2` sendto probe was reverted.

## 4. Black screen — SOLVED (how, so it isn't re-litigated)

The old claims "0 submitFlip / main thread parked in a kernel wait / server is the cause" were **never measured and are wrong**. Measured: game flips 60 fps from boot (RenderLoop's equeue wait is ordinary vsync throttle; flip counter advanced ~28k), issues ~50 draws + 30 dispatches/frame, and sits on an invisible "PRESS ANY BUTTON" screen.

Frame dump showed the title screen fully rendered in an RGBA8 RT; the final present compute (`cs 0xb5f1cbd1` 1920×1080 / `0xa21a9123` 1600×900 dyn-res) composites UI only on 4×4 tiles set in a coverage mask built by `cs 0xf403f253` from the UI target's **CMASK** metadata. shadPS4 doesn't emulate CMASK → mask all 0 → scene-only output = black. `UIMASKFILL` marks every tile covered (untouched tiles have UI alpha 0, so it's visually identical).

Dead ends recorded: `readbacks_mode`/`copy_gpu_buffers` in the per-game config **assert at ~10 s** on this core; libSceJson2 is stubbed (no LLE module on disk) but is only used by commerce response parsing — not blocking.

## 5. Online flow — what the game actually does (measured)

1. **Press Start** → `POST https://spring18.gosredirector.ea.com:42230/redirector/getServerInstance` (**sceHttp, XML**, not DirtySDK TLS :42127). Request body: `serverinstancerequest` (clientname Madden, skuid MADDEN_2020_PS4, connectionprofile standardSecure_v4, firstpartyid = PSN online id "shadPS4").
   Response schema from TDF reflection (`ServerInstanceInfo`): `<address member="0"><valu><hostname/><ip/><port/></valu></address><secure>0</secure><trialservicename/><defaultdnsaddress>0</defaultdnsaddress>`.
2. DirtySDK **binds its socket to the LAN IP** (netctl address) before connecting → redirector must hand out the LAN IP; 127.0.0.1 fails with WSAEADDRNOTAVAIL (10049).
3. Blaze over TCP, **secure=0** (plaintext). Framing = **Fire2 16-byte header**: `u32 len, u16 metaLen, u16 component, u16 command, u24 msgNum, u8 type<<5, u8 opt, u8 res`. Types: 0 request, 1 reply, 2 notify, 3 error reply, 4 ping (comp 0/cmd 0 keepalive every 15 s), 5 ping reply.
4. Sequence: Util.PreAuth(7) → Util.Ping(2) → Util.FetchClientConfig(1) ×6 (`OSDK_CORE/CLIENT/NUCLEUS/WEBOFFER/ABUSE_REPORTING/MADSET`) → sceNpAuth auth code ("AUTHCODE") → **Nucleus**: `GET /connect/auth` (header `ps4_ticket`) must return **302 `Location: qrc:/html/login_successful.html?code=…`** (non-http scheme so the core's redirect follower returns it unfollowed) → `POST /connect/token` (JSON access/refresh/id token) → `GET /connect/tokeninfo` (JSON pid/persona ids) → second `/connect/auth` for client_id `MADDEN_2020_PS4` → **Auth.login(0xA)** (authCode) → server pushes **UserSessions notify 2 UserAdded, 1 UserSessionExtendedDataUpdate, 8 UserAuthenticated** (client waits ~30 s then logs out without them) → **Util.PostAuth(8)** → more configs (`OSDK_TICKER`, `feed`, `maddenFriends`, `maddenshare`) → UserSettingsLoad(`AchievementCache`), US.updateNetworkInfo, Auth.getAccount, AssociationLists ×~40, Messaging, custom components (§6) → **OSDKSettings.fetchSettings(1)/fetchSettingsGroups(2)** → UserSettingsLoadAll(0xC) → crash (§7.1).
5. PreAuth `CONF` map **must** contain the VoIP keys or VoIP init copies NULL strings (crash @0x54c6470): `voipSTTProfile=0, voipSTTUrl="", voipSTTKey="", voipTTSProvider=0, voipTTSUrl="", voipTTSKey=""` (+ pingPeriod, connIdleTimeout, defaultRequestTimeout, autoReconnectEnabled, maxReconnectAttempts, voipHeadsetUpdateRate).
6. Identity used everywhere: Blaze user/persona id `1000000001`, Nucleus pid `1000000000001`, name `shadPS4`, namespace `ps4`, platform 20, PSN account id `0xe3c9d3c9537d6ce8`.
7. Telemetry (`pin-river.data.ea.com/pinEvents`, `rl.data.ea.com/bugsentry`) now goes to the local :443 catch-all, not EA.

## 6. Component / command map (from the binary)

| Comp | Name | Known commands |
|---|---|---|
| 0x1 | Authentication | 0xA login, 0xB trustedLogin, 0x1D listUserEntitlements2, 0x1E getAccount, 0x24 getAuthToken, 0x27 grantEntitlement2, 0x30 listPersonaEntitlements2, 0x3C expressLogin, 0x46 logout, 0x5A getPersona, 0x64 listPersonas, 0x104 getOriginPersona (switch @0x54b4040) |
| 0x9 | Util | 1 fetchClientConfig, 2 ping, 3 setClientData, 5 getTelemetryServer, 6 getTickerServer, 7 preAuth, 8 postAuth, 0xA userSettingsLoad, 0xB save, 0xC loadAll, 0x15 fetchQosConfig, 0x16 setClientMetrics, 0x17 setConnectionState, 0x19 getUserOptions, 0x1C setClientState (table @0x77af750) |
| 0x7802 | UserSessions | cmds: 0x14 updateNetworkInfo, 0x8 updateHardwareFlags, 0x3A getQosPingSites…; notifies: 1 ExtDataUpdate, 2 UserAdded, 3 UserRemoved, 5 UserUpdated, 8 UserAuthenticated, 9 Unauthenticated (tables @0x77af530 / @0x77af4d0) |
| 0x19 | AssociationLists | 6 (friend list `OSDKPlatformFriendList`, sent ~40×) |
| 0xF | Messaging | 2 |
| **0x802** | **MutComponent (Ultimate Team)** | 0x385 (CHIN{CTYP 234} + MSAB auth blob), 0x386 |
| 0x80C | CareerModeComponent | 1 (CHIN VERS 135), 2 |
| 0x808 | MiscServiceGateway | 0x34 / 0x35 (SORE 'SCEA') |
| **0x938** | **GridironClubComponent** | 0xD (MSAB blob) |
| 0x8C9 | OSDKSettingsComponent | 1 fetchSettings, 2 fetchSettingsGroups (@0x370eac0) |
| 0x8D6 | OsdkTicker2Component | — |
| 0xA | ? | 5 |
| 0x804 | Scouting (inferred) | — |

Unknown commands get an **empty default reply** (`DEFAULT_EMPTY_REPLY=True` in handlers.py) — logged as `DEFAULT empty reply for …`; each needs a real handler eventually.

## 7. Open work

### 7.1 CURRENT BLOCKER — OSDK settings groups/views
Served from `handlers.py` (OSDKSettings 0x8C9). Types: `integer` (explicit) or string (default). Crash history, each fixed in turn:
- `0x37492e8` NULL group `O_SG_TCKR` → added fetchSettings/fetchSettingsGroups.
- `0x2458692` NULL group `SG_MATCHUP` → added it + 27 matchup views (`QM_STD … DC_QM DCR_QM … QM_MUT_SVS QM_MUT_SVC`, table @0x75c5b90) with view-data for the 30 `MM*` settings.
- `0x35f9e71` heap corruption → caused by putting **every** setting in **every** group; replaced with realistic membership (`GROUP_MEMBERS`).
- `0x35ea725` NULL setting `O_PR` in group `INV` → `INV`/`MUPSET` get the 22 preference settings `O_JS … O_OPPT`.
- **`0x24b30dc` NULL view `UACCT`** (group vfn 0x78 = FindView over `[group+0xb0]`, count `[group+0xb8]`). cdb showed the group is **`O_SG_SYSS`** (it holds `O_TELEMETRY`) with **1 view only** — i.e. the server LVWS views did **not** attach. Last change (UNTESTED): `GROUP_VIEWS["O_SG_SYSS"] = ["UGEN","UACCT"]`.
  - If still NULL: views are probably created from persisted user settings in **UserSettingsLoadAll (Util 0xC)** — strings "SetValuesFromPersistedString - new view of [%s] with [%s]", "group[%s], view[%s], setting[%s], persistent value[%s]". Writer fn `0x35f8e10` (snprintf `"%d%c%s"` with `'&'`, then `'|'`), parser = group vtable slot @0x35f74c0 (vtable @0x76b01b8). Reconstruct the string format and return it in `SMAP`.
  - Cheap alternative to try first: move `O_TELEMETRY` out of `O_SG_SYSS` (the crashing branch only fires for group O_SG_USER or setting O_TELEMETRY).
- LVWS/LVDS encoding as **list** is verified (typeinfo kind 3 = list, 2 = map).

### 7.2 Then: MUT and Draft Champions
- Dump schemas with `tools\tdfrefl.py` for `Blaze::Mut::*` / GridironClub classes; map command names via the component's name-switch (`tools\cmdnames.py <fn>`; Mut name getter @0x266abd0, command switch @0x266abe0; GridironClub @0x3130260/0x3130270).
- Draft Champions matchup views already exist (`DC_QM`, `DCR_QM`, `CS_DC`).

### 7.3 Watch items
- Vulkan **"Device lost during submit"** hit twice (runs osdk5/osdk6) — before the `UIMASKFILL` bounds guard. Not seen since; if it returns, suspect the fill or `TEX1DSHADOW` CopyImage.
- Window opens partly off-screen (rect -328,-211) on some runs — cosmetic.
- Remove/gate `MADDENGFX` probes before building anything for 2K14.

## 8. RE toolkit (`C:\madden20_online\tools`, all read the live dump `dump\eboot_mem_0x800000000.bin`)
- `dump_image.py <pid> <out>` — sparse dump of the whole eboot image (re-dump if the game binary changes).
- `dis.py <va> [--func] [--back N --len N]` — disasm with import names (`dump\got_names.txt`: GOT slot → HLE fn or NID→aerolib name).
- `xref.py` (direct calls) · `riprefs.py` (rip-relative refs, numpy) · `tdfrefl.py <Class>` (exact TDF tag/name/type from reflection; class desc +0x28 members, +0x30 count, member rec 0x30 bytes) · `cmdnames.py <fn>` (RPC switch → id:name) · `rpcnames.py` · `components.py` · `guest_stack.py <ThreadName>` · `thread_names.py <pid>` · `framedump_to_png.py` · `triage.py` · `shot.py` · `keys.py`.
- Error codes are `(code<<16)|component` — the cheapest way to get a component id (cmp in its error-name getter).

## 9. Traps
- ⛔ Run on the custom core (`Build\...\shadps4.exe`), not stock v0.18.0, and **with `NBA2K14_MOD_ROOT`** set (runner does it) — without it no flags load and everything regresses.
- ⛔ Hand out the **LAN IP** in the redirector; never 127.0.0.1.
- ⛔ Don't trust the old protocol memory: no :42127, no 12-byte header, no ConsoleAuth on this title.
- ⛔ An empty reply is not "safe": missing strings/groups crash the client (VoIP keys, settings groups). Fill schemas from `tdfrefl.py`, not from other games.
- ⛔ Don't put every setting in every group — heap corruption.
- ⛔ `readbacks_mode` / `copy_gpu_buffers` assert on this core.
- ⛔ Use the Write tool (not heredocs) for files containing Windows paths or `\0`.
- ⛔ fpkg: integrated `PkgTool pkg_extract --passcode 000…0` only (2-step route zeros the SELF header).

---
## 10. GAMEPLAY FIELD-RENDER CORRUPTION — root cause + partial fix (10-14, this session)

**Symptom (what the owner sees):** in the WIDE gameplay camera (pre-play, during a play) the field is corrupted — the grass renders white/washed/over-bright and **real exterior-environment geometry (cars/SUVs, crates, trees, a brick building) renders on top of the playing field**, among the players. Close-ups, huddles, cutscenes and all menus render perfectly. It **FLICKERS**: the same build renders a frame mostly-correct (green field, yard lines) then a frame later is heavily corrupted — it is **nondeterministic**, which is the defining trait and what made it hard. This is the bug the older RENDERING note called "blown-out white stadium half".

**Repro (reliable):** boot → press Start → main menu (X-Factor tile highlighted on a fresh boot) → **Exhibition → Play Now → Resume** the in-progress IND@NE game → pick any play → the wide pre-play field shows it. Shots: `shots\depthfix_field.png` (a good frame, right ~60% green/correct), `shots\donly_field.png` / `shots\fix1_field.png` / `shots\d3_f0.png` (corrupted frames). ⚠️ Resuming a saved Play Now continues the AI sim, so the play auto-snaps within seconds — capture/screenshot FAST.

**ROOT CAUSE (measured, not guessed):**
1. **Memory aliasing at `0x111de00000`.** The main scene **depth buffer** (1920×1080 `D32SfloatS8Uint`) and a half-res **velocity/motion buffer** (960×540 `R8G8B8A8`, near-white = static) share the **same guest address** — Madden ping-pongs that memory. shadPS4 holds them as two separate VkImages. When the velocity buffer's bytes change, shadPS4 marks the depth's pages dirty and **re-uploads that aliased guest memory into the depth image**, overwriting part of it → half the depth was garbage/noise (`DEPTH_id251.png`: left ~40% noise, right ~60% valid). The depth is **reverse-Z** (0=far), valid values ~0–0.015; it is **NOT** a clear/HTILE failure — do not re-chase HTILE for this.
2. **Stale vertex geometry.** Even on frames where the depth comes back fully valid-range, the **cars/trees still render on the field** — so they are real meshes drawn at wrong screen positions (= **stale/aliased VERTEX-buffer data**, a buffer_cache coherence problem parallel to the image one). This is the REMAINING, unfixed layer.

**PARTIAL FIX (shipped, flag `MADDENDEPTHGPU`, src `video_core/texture_cache/texture_cache.cpp` `RefreshImage`):** depth buffers are GPU-only render targets and are never validly sourced from guest memory, so skip the guest re-upload for `info.props.is_depth` (clear Dirty/CpuDirty/MaybeCpuDirty and return). This removes the −1e20 float garbage and makes **many** frames render correctly (right field green, yard lines, players), but does **not** stop the flicker because of layer 2. ⚠️ Extending the skip to *all* GpuModified render targets was **too broad** — it starved a needed buffer and turned the field **gray** (regressed); that broadening was reverted, depth-only kept.

**EXPERIMENTAL, currently OFF (flag `MADDENRTINIT`, src `texture_cache.cpp` `FindImage` after RegisterImage):** clears every newly-created color image to 0 so a first-use LOAD reads 0 instead of undefined VRAM. It cleaned up −1e20 garbage *shading* (revealed the cars/trees are coherent meshes, not noise) but washed the field and didn't fix the core issue. Leave off unless revisiting uninitialized-buffer reads.

**NEXT STEP (the owner chose depth path; depth done → now the vertex layer):** drive the **vertex-buffer coherence** — find why the exterior meshes (cars/trees/building) are drawn at field positions (stale/aliased vertex buffers in `buffer_cache`), i.e. shadPS4 not tracking Madden's vertex-buffer updates / reusing stale guest memory. That is the fix that stops the cars/trees.

**DIAGNOSTIC TOOLING built this session (all in `texture_cache.cpp`, flag `DUMPFRAME`):** on-demand, **re-armable GPU frame dump** — create `modroot\flags\DUMPNOW`, it captures the next flip's large color buffers (width≥900) **and depth buffers** into `modroot\framedump\capNN\*.raw`, then deletes the trigger so a fresh `DUMPNOW` captures again without relaunching. Convert/stats: `tools\framedump_to_png.py <capdir>` (handles RGBA8/BGRA8/R16/HDR B10G11R11/A2B10G10R10; depth is raw float32 — analyze with numpy). Presented frame = the `…_115e600000`/`…_115ee00000` sRGB buffer (VideoOut range 0x115de00000–0x115f600000). ⚠️ Firing a dump during live gameplay can trip the PresentThread AV (the dump's `scheduler.Finish()` vs present) — tolerable for one-shots, risky for rapid bursts.

**TRAPS for this bug:**
- ⛔ The flicker means a single frame dump may land on a GOOD frame — a clean capture does NOT mean fixed. Capture several / confirm the on-screen state matches the dump.
- ⛔ Don't trust an A/B of a static-const flag across two runs as "no effect" when the output flickers — I wrongly dismissed `MADDENMETAEXEC` early for exactly this reason. Compare the SAME scene state.
- ⛔ The depth here is valid reverse-Z, NOT a broken clear — HTILE/meta-clear is not this bug.
- Input: on a fresh boot the window is focused and `keys_bg.py` face buttons work; a wedged/loading screen can ignore Cross/Circle while still accepting D-pad (that is game state, not an input-tool failure).

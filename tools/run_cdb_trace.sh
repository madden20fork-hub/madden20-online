#!/usr/bin/env bash
# Run Madden under cdb with up to 4 LOGGING hardware breakpoints on guest code (they never stop the game).
# usage: run_cdb_trace.sh <tag>   -> runs/trace_<tag>.txt
# Breakpoints: the draft UI listener events (vtable @0x7740b20): UpdateDraftInfo +0x2e8, NewPicksReady +0x2f0,
# SlotPreviewReady +0x2f8, PickComplete +0x300.  Edit BPS to trace something else.
TAG=${1:-trace}
EXE="C:/madden20_online/core_src/Build/madden-RelWithDebInfo/shadps4.exe"
GAME="C:/games/CUSA13265/eboot.bin"
OUT="/c/madden20_online/runs/trace_${TAG}.txt"
export NBA2K14_MOD_ROOT="C:/madden20_online/modroot"
BPS='ba e1 0x8046e7d80 ".echo EV UpdateDraftInfo; r rsi,rdx,rcx,r8; g"; ba e1 0x8046e7ea0 ".echo EV NewPicksReady; r rsi,rdx,rcx,r8; g"; ba e1 0x8046e7fc0 ".echo EV SlotPreviewReady; r rsi,rdx,rcx,r8; g"; ba e1 0x8046e8240 ".echo EV PickComplete; r rsi,rdx,rcx,r8; g"'
powershell.exe -NoProfile -Command "Get-Process shadps4 -ErrorAction SilentlyContinue | Stop-Process -Force"
sleep 1
cd "C:/madden20_online/core_src/Build/madden-RelWithDebInfo"
echo q | "/c/Program Files (x86)/Windows Kits/10/Debuggers/x64/cdb.exe" -g -G \
    -c "sxd av; sxd ibp; sxd eh; sxd ch; sxd sse; sxd ii; sxd dz; sxd c000041d; $BPS; g" \
    "$EXE" -g "$GAME" -f false > "$OUT" 2>&1
echo "cdb exited; output in $OUT"

#!/usr/bin/env bash
# Run Madden under cdb; on a second-chance AV (shadPS4 uses first-chance AVs for page tracking)
# dump registers + host/guest stack to runs/crash_<tag>.txt.  usage: [EXTRA="--show-fps"] run_cdb.sh <tag>
# NOTE: cdb costs speed — shadPS4 uses first-chance AVs for page tracking and each one round-trips the debugger.
# For play sessions use run_madden.ps1; use this only to catch a crash.
TAG=${1:-crash}
EXE="C:/madden20_online/core_src/Build/madden-RelWithDebInfo/shadps4.exe"
GAME="C:/games/CUSA13265/eboot.bin"
OUT="/c/madden20_online/runs/crash_${TAG}.txt"
export NBA2K14_MOD_ROOT="C:/madden20_online/modroot"
export _NT_SYMBOL_PATH="C:/madden20_online/core_src/Build/madden-RelWithDebInfo"
powershell.exe -NoProfile -Command "Get-Process shadps4 -ErrorAction SilentlyContinue | Stop-Process -Force"
sleep 1
# the owner works on the main monitor: the game window always goes to monitor 2 (no focus steal).
(python -I C:/madden20_online/tools/to_monitor2.py --wait 120 > /c/madden20_online/runs/monitor2_${TAG}.txt 2>&1 &)
cd"C:/madden20_online/core_src/Build/madden-RelWithDebInfo"
tail -n +1 -f C:/madden20_online/runs/cdbcmds.txt | \
  "/c/Program Files (x86)/Windows Kits/10/Debuggers/x64/cdb.exe" -g -G \
    "$EXE" -g "$GAME" -f false $EXTRA > "$OUT" 2>&1
echo "cdb exited; output in $OUT"

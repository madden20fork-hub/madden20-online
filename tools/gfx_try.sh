#!/usr/bin/env bash
# usage: gfx_try.sh <tag> '<json for custom_configs/CUSA13265.json>'
# Boots Madden with a per-game override, screenshots before/after pressing Start, prints brightness.
TAG=$1; JSON=$2
CFG="$APPDATA/shadPS4/custom_configs/CUSA13265.json"
T=/c/madden20_online/tools
echo "$JSON" > "$CFG"
powershell.exe -NoProfile -Command "Get-Process shadps4 -ErrorAction SilentlyContinue | Stop-Process -Force" ; sleep 2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:/madden20_online/tools/run_madden.ps1" -Seconds 3000 -Tag "gfx_$TAG" -Extra "--show-fps" > /c/madden20_online/runs/last_run_stdout.txt 2>&1 &
sleep 6
L="$APPDATA/shadPS4/log/shad_log.txt"
until python -I $T/shot.py boot_wait 2>/dev/null | grep -q rect; do sleep 3; done
for i in $(seq 1 90); do grep -q "cas_02.cas" "$L" 2>/dev/null && break; tasklist | grep -qi shadps4 || { echo "DIED"; cat /c/madden20_online/runs/last_run_stdout.txt; exit 1; }; sleep 2; done
grep -m3 -i -E "override|Game-specific" "$L" | cut -c1-160
sleep 25
python -I $T/shot.py "gfx_${TAG}_pre" | sed 's/title=.*rect/rect/'
python -I $T/keys.py n 1500 enter 1500 n > /dev/null
sleep 15
python -I $T/shot.py "gfx_${TAG}_post" | sed 's/title=.*rect/rect/'
python -I -c "
from PIL import Image, ImageStat
for s in ('pre','post'):
    im=Image.open(r'C:\madden20_online\shots\gfx_${TAG}_'+s+'.png').convert('L')
    w,h=im.size; c=im.crop((40,80,w-40,h-60))   # skip title bar + overlay row
    print(s, 'mean=%.2f'%ImageStat.Stat(c).mean[0], 'extrema', c.getextrema())
"

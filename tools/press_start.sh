#!/usr/bin/env bash
# Wait for the fresh Madden run to finish mounting superbundles, then press Start (Cross/Options).
L="$APPDATA/shadPS4/log/shad_log.txt"
T=/c/madden20_online/tools
sleep 6
until python -I $T/shot.py boot_wait 2>/dev/null | grep -q rect; do sleep 3; done
until grep -q "cas_02.cas" "$L" 2>/dev/null; do sleep 2; done
sleep ${1:-25}
# keys_bg = PostMessage to the game window, no focus steal (the owner works on the main monitor)
python -I $T/keys_bg.py n 1500 enter 1500 n 2000 n

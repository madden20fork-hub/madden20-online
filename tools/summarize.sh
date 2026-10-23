#!/usr/bin/env bash
# Summarize a Madden shad_log snapshot: NP gate, async results, net activity, flips.
L="$1"
echo "== lines: $(wc -l < "$L")"
echo "== localonline gate:"; grep -m3 -E "local-online|LOCALONLINE" "$L" | cut -c1-200
echo "== PollAsync/WaitAsync results:"; grep -oE "sce(Poll|Wait)Async: called req_id = 0x[0-9a-f]+, returning result = 0x[0-9a-f]+" "$L" | sort | uniq -c | sort -rn | head
echo "== NP calls that ran OK path:"; grep -oE "(sceNpCheck[A-Za-z]*|sceNpGet[A-Za-z]*A?|local (authorization|id-token)|sceNpAuth[A-Za-z]*)[^,]*req_id=0x[0-9a-f]+" "$L" | sed -E 's/req_id=0x[0-9a-f]+//' | sort | uniq -c | sort -rn | head -15
echo "== NpAuth/Ticket:"; grep -E "Lib.NpAuth|Ticket|NpCommerce|Entitlement" "$L" | cut -c1-220 | sort | uniq -c | sort -rn | head -15
echo "== flips:"; grep -cE "video_out.cpp:176|SubmitAndFlip|sceVideoOutSubmitFlip" "$L"
echo "== net (sys_*/resolver/ssl):"; grep -oE "\[Lib\.(Net|Ssl|Ssl2|Http|NetCtl)\] <[A-Za-z]*> \([^)]*\) [a-z_0-9]*\.cpp:[0-9]* [A-Za-z_0-9]*" "$L" | sed -E 's/\([^)]*\) //' | sort | uniq -c | sort -rn | grep -v -E "CheckCallback|GetState" | head -30
echo "== MADDENPROBE2:"; grep -A2 "MADDENPROBE2" "$L" | head -30
echo "== top NP lines:"; grep -oE "\[Lib\.Np[A-Za-z]*\] <[A-Za-z]*> \([^)]*\) [a-z_0-9]*\.cpp:[0-9]* [A-Za-z_0-9]*" "$L" | sed -E 's/\([^)]*\) //' | sort | uniq -c | sort -rn | head -20
echo "== last 15 non-render lines:"; grep -v -E "Render|Vulkan|NetCtl\] <Debug>|NpParty|duplicate" "$L" | tail -15 | cut -c1-220

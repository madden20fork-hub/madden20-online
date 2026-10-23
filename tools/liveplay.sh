# usage: liveplay.sh <tag> : pick play (Cross), wait for presnap, snap (Cross), shoot every ~0.7 s for 12 frames.
cd /c/madden20_online/tools
for h in a b c; do python -I shot.py ${1}_h$h >/dev/null; sleep 0.8; done
python -I keys_bg.py kp2 >/dev/null; sleep 5
python -I shot.py ${1}_pre >/dev/null
python -I keys_bg.py kp2 >/dev/null; sleep 0.4; python -I keys_bg.py kp2 >/dev/null; sleep 0.4; python -I keys_bg.py kp2 >/dev/null
for i in $(seq -w 1 12); do python -I shot.py ${1}_$i >/dev/null; sleep 0.3; done
python - "$1" <<'PY'
import sys
from PIL import Image
t=sys.argv[1]; names=[f"{t}_h{c}" for c in "abc"]+[f"{t}_pre"]+[f"{t}_{i:02d}" for i in range(1,13)]
ims=[]
for n in names:
    try: ims.append(Image.open(rf"C:\madden20_online\shots\{n}.png").convert('RGB').crop((328,210,2250,1290)).resize((480,270)))
    except Exception: pass
m=Image.new("RGB",(1920,270*((len(ims)+3)//4)))
for k,im in enumerate(ims): m.paste(im,((k%4)*480,(k//4)*270))
m.save(rf"C:\madden20_online\shots\{t}_sheet.png"); print("sheet", t)
PY

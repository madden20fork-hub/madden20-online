# boot -> menu -> Exhibition > Play Now > Resume, re-arming READTRAP every 5 s through the load, then pick play.
cd /c/madden20_online/tools
r=$(python -I boot_to_menu.py $1); echo "$r" | tail -1
python -I keys_bg.py right 800 n >/dev/null; sleep 8
python -I keys_bg.py n >/dev/null; sleep 8
python -I keys_bg.py n >/dev/null
for i in $(seq 1 16); do touch ../modroot/flags/READTRAP; sleep 5; done
python -I keys_bg.py kp2 600 kp2 >/dev/null; sleep 6
python -I keys_bg.py kp2 >/dev/null
for i in 1 2; do touch ../modroot/flags/READTRAP; sleep 5; done
python -I shot.py ${1}_presnap | tail -c 60

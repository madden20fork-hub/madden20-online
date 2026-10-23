# boot -> Exhibition > Play Now > Resume -> pick a play -> wide pre-snap field (waits for snap). usage: presnap.sh tag
cd /c/madden20_online/tools
python -I field_repro.py $1 6 | tail -2
python -I keys_bg.py kp2 600 kp2 > /dev/null
sleep 6
python -I keys_bg.py kp2 > /dev/null
sleep 8
python -I shot.py ${1}_presnap | tail -c 60

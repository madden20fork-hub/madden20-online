"""Grab N screenshots of the game a second apart and stack the FPS-overlay crops into one image.
usage: python -I fps_strip.py <name> [N]  -> shots/<name>_fps.png"""
import subprocess
import sys
import time

from PIL import Image

name, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5
crops = []
for i in range(n):
    subprocess.run([sys.executable, "-I", r"C:\madden20_online\tools\shot.py", f"{name}_{i}"], capture_output=True)
    im = Image.open(rf"C:\madden20_online\shots\{name}_{i}.png")
    crops.append(im.crop((im.width - 260, 30, im.width - 10, 75)))
    time.sleep(1)
out = Image.new("RGB", (250 * 2, 45 * n * 2))
for i, c in enumerate(crops):
    out.paste(c.resize((500, 90)), (0, i * 90))
out.save(rf"C:\madden20_online\shots\{name}_fps.png")
print("ok", n)

"""Contact sheet of screenshots: python -I montage.py <out.png> <shot1.png> <shot2.png> ... (3 per row, 640 wide each)"""
import sys

from PIL import Image

out, paths = sys.argv[1], sys.argv[2:]
W = 640
thumbs = []
for p in paths:
    im = Image.open(p).convert("RGB")
    thumbs.append(im.resize((W, int(im.height * W / im.width))))
H = max(t.height for t in thumbs)
cols = 3
rows = (len(thumbs) + cols - 1) // cols
sheet = Image.new("RGB", (W * cols, H * rows))
for i, t in enumerate(thumbs):
    sheet.paste(t, ((i % cols) * W, (i // cols) * H))
sheet.save(out)
print(out)

#!/usr/bin/env python3
"""contact_sheet.py <tour_dir> [cols]: tile <tour_dir>/*.png (labelled) into <tour_dir>/contact_sheet.jpg."""
import glob, os, sys
from PIL import Image, ImageDraw
d, cols = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4
fs = sorted(f for f in glob.glob(os.path.join(d, "*.png")))
W, H = 480, 300
sheet = Image.new("RGB", (cols * W, ((len(fs) + cols - 1) // cols) * (H + 22)), "white")
for i, f in enumerate(fs):
    im = Image.open(f).convert("RGB").resize((W, H))
    x, y = (i % cols) * W, (i // cols) * (H + 22)
    sheet.paste(im, (x, y + 22))
    ImageDraw.Draw(sheet).text((x + 4, y + 5), os.path.basename(f), fill="black")
sheet.save(os.path.join(d, "contact_sheet.jpg"), quality=85)
print(os.path.join(d, "contact_sheet.jpg"))

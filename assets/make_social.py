"""Render the 1280x640 GitHub social preview for nofakedone."""
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1] if len(sys.argv) > 1 else "social.png"
W, H = 1280, 640
BG, PANEL, FG, DIM = (13, 17, 23), (22, 27, 34), (230, 237, 243), (139, 148, 158)
RED, GRN, ORG = (248, 81, 73), (63, 185, 80), (217, 119, 87)
fnt = lambda name, size: ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size)
TITLE, HEAD, BODY, MONO, MONOB = fnt("consolab.ttf", 84), fnt("segoeuib.ttf", 46), fnt("segoeui.ttf", 28), fnt("consola.ttf", 25), fnt("consolab.ttf", 25)

im = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(im)
d.rectangle([0, 0, W, 10], fill=RED)

d.text((80, 70), "nofakedone", font=TITLE, fill=FG)
d.text((80, 180), "Your coding agent said \u201cdone.\u201d", font=HEAD, fill=FG)
d.text((80, 236), "The diff says otherwise.", font=HEAD, fill=RED)
d.text((80, 318), "A Claude Code Stop hook that blocks fake finished work.", font=BODY, fill=DIM)

px, py = 80, 384
d.rounded_rectangle([px, py, W - 80, py + 170], radius=14, fill=PANEL)
rows = [
    [("BLOCK ", RED, MONOB), ("STUB_NOT_IMPLEMENTED  ", ORG, MONO), ("raise NotImplementedError", DIM, MONO)],
    [("BLOCK ", RED, MONOB), ("TEST_SKIPPED          ", ORG, MONO), ("@pytest.mark.skip", DIM, MONO)],
    [("BLOCK ", RED, MONOB), ("TAUTOLOGY_ASSERT      ", ORG, MONO), ("assert True", DIM, MONO)],
    [("BLOCK ", RED, MONOB), ("SWALLOWED_ERROR       ", ORG, MONO), ("except Exception: pass", DIM, MONO)],
]
for i, row in enumerate(rows):
    x = px + 30
    for text, col, f in row:
        d.text((x, py + 22 + i * 34), text, font=f, fill=col)
        x += d.textlength(text, font=f)

d.text((80, 585), "zero dependencies  \u00b7  8 languages  \u00b7  plugin \u00b7 CLI \u00b7 GitHub Action", font=BODY, fill=DIM, anchor="lm")
d.text((W - 80, 585), "MIT", font=BODY, fill=GRN, anchor="rm")
im.save(OUT, optimize=True)
print(OUT)

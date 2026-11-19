"""Render the nofakedone README demo as a terminal-style animated GIF."""
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1]
W, H = 960, 410
PAD_X, TOP, LH = 26, 62, 23
F = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
FB = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 16)
SYM = ImageFont.truetype(r"C:\Windows\Fonts\seguisym.ttf", 16)
FS = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 13)

BG, BAR, FG, DIM = (13, 17, 23), (30, 36, 46), (220, 226, 234), (125, 135, 150)
RED, GRN, YEL, BLU, ORG = (248, 81, 73), (63, 185, 80), (210, 153, 34), (88, 166, 255), (217, 119, 87)

# (text, color, bold) — segments per line
def L(*segs):
    return [s if isinstance(s, tuple) else (s, FG, False) for s in segs]

scenes = [
    # scene 1: the fake done
    [L(("> ", ORG, True), ("fix the failing billing tests", FG, True)),
     L(""),
     L(("● ", ORG, False), "Update(src/billing.py)"),
     L(("    - ", RED, False), ("return gateway.charge(user.card, amount)", RED, False)),
     L(("    + ", GRN, False), ("raise NotImplementedError", GRN, False)),
     L(("● ", ORG, False), "Update(tests/test_billing.py)"),
     L(("    + ", GRN, False), ("@pytest.mark.skip(reason=\"flaky\")", GRN, False)),
     L(("    + ", GRN, False), ("assert True", GRN, False)),
     L(""),
     L(("● ", ORG, False), ("Done! All tests pass ✔", FG, True))],
    # scene 2: blocked
    [L(("■ Stop hook blocked: nofakedone", RED, True)),
     L(("  the diff still contains work that only looks finished:", FG, False)),
     L(""),
     L(("  BLOCK ", RED, True), ("STUB_NOT_IMPLEMENTED ", YEL, False), "src/billing.py:2"),
     L(("        raise NotImplementedError", DIM, False)),
     L(("  BLOCK ", RED, True), ("TEST_SKIPPED         ", YEL, False), "tests/test_billing.py:1"),
     L(("        @pytest.mark.skip(reason=\"flaky\")", DIM, False)),
     L(("  BLOCK ", RED, True), ("TAUTOLOGY_ASSERT     ", YEL, False), "tests/test_billing.py:3"),
     L(("        assert True", DIM, False)),
     L(""),
     L(("  Do not delete or weaken tests to get past this check.", FG, False))],
    # scene 3: real fix
    [L(("● ", ORG, False), "You're right, that was not done. Doing the real work."),
     L(""),
     L(("● ", ORG, False), "Update(src/billing.py)"),
     L(("    + ", GRN, False), ("return gateway.charge(user.card, amount)", GRN, False)),
     L(("● ", ORG, False), "Update(tests/test_billing.py)"),
     L(("    - ", RED, False), ("@pytest.mark.skip(reason=\"flaky\")", RED, False)),
     L(("    + ", GRN, False), ("assert charge(user, 0) is None", GRN, False)),
     L(("● ", ORG, False), "Bash(pytest)"),
     L(("    1 passed, 0 skipped", GRN, False)),
     L(""),
     L(("✓ nofakedone ", GRN, True), ("No fake-done patterns found.", FG, False)),
     L(("● ", ORG, False), ("Done. Charging works and the test really runs.", FG, True))],
]
CAPTIONS = ["1 · the agent fakes \"done\"", "2 · nofakedone blocks the stop", "3 · the agent does the real work"]


def draw_base(caption):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 38], fill=BAR)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 22, 13, 28 + i * 22, 25], fill=c)
    d.text((W // 2, 19), "claude  ·  nofakedone stop hook", font=FS, fill=DIM, anchor="mm")
    d.rectangle([0, H - 34, W, H], fill=BAR)
    d.text((PAD_X, H - 17), caption, font=FB, fill=FG, anchor="lm")
    d.text((W - PAD_X, H - 17), "staged session · real nofakedone rules", font=FS, fill=DIM, anchor="rm")
    return im, d


def draw_line(d, y, segs, upto=None):
    x = PAD_X
    left = upto
    for text, col, bold in segs:
        if left is not None:
            if left <= 0:
                break
            text = text[:left]
            left -= len(text)
        for ch in text:
            font = SYM if 0x2700 <= ord(ch) < 0x2800 else (FB if bold else F)
            d.text((x, y + (1 if font is SYM else 0)), ch, font=font, fill=col)
            x += d.textlength(ch, font=font)
    return x


frames, durs = [], []
def snap(im, ms):
    frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=64))
    durs.append(ms)

for si, lines in enumerate(scenes):
    for li, segs in enumerate(lines):
        full = sum(len(t) for t, _, _ in segs)
        typed = si == 0 and li == 0  # type the prompt, reveal the rest line by line
        steps = range(2, full + 1, 2) if typed else [full]
        for n in steps:
            im, d = draw_base(CAPTIONS[si])
            for pj in range(li):
                draw_line(d, TOP + pj * LH, lines[pj])
            x = draw_line(d, TOP + li * LH, segs, n)
            if typed:
                d.rectangle([x + 1, TOP + li * LH + 2, x + 9, TOP + li * LH + 19], fill=FG)
            snap(im, 45 if typed else (380 if segs != [("", FG, False)] else 120))
    durs[-1] = 2600 if si < 2 else 3600

frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durs, loop=0, optimize=True, disposal=1)
print(len(frames), "frames", sum(durs) / 1000, "s")

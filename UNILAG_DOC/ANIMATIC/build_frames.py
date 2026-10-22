# Audio padding + frame generation for the UNILAG animatic
import io, json, math, os, random, wave, sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
sc = json.load(io.open(os.path.join(BASE, "scenes.json"), encoding="utf-8"))

# ---------- 1. AUDIO PAD ----------
LEAD, TAIL, PAUSE = 0.5, 0.8, 1.0
durations = {}
for s in sc:
    n = s["no"]
    src = os.path.join(BASE, "audio", f"scene_{n:02d}.wav")
    dst = os.path.join(BASE, "audio", f"pad_{n:02d}.wav")
    w = wave.open(src, "rb")
    params = w.getparams()
    rate, width, ch = params.framerate, params.sampwidth, params.nchannels
    frames = bytearray(w.readframes(w.getnframes()))
    w.close()
    silence = lambda sec: bytearray(int(rate * sec) * width * ch)
    out = silence(LEAD)
    out += frames
    out += silence(s.get("pauses", 0) * PAUSE)
    out += silence(TAIL)
    wo = wave.open(dst, "wb")
    wo.setparams(params)
    wo.writeframes(bytes(out))
    wo.close()
    d = len(out) / (rate * width * ch)
    durations[n] = round(d, 3)
    print(f"pad_{n:02d}.wav  {d:6.2f}s  (voice {len(frames)/(rate*width*ch):5.2f}s + {s.get('pauses',0)} pause)")

io.open(os.path.join(BASE, "durations.json"), "w").write(json.dumps(durations, indent=1))
total = sum(durations.values()) + 5.0 + 8.0
print(f"narration-with-pauses total: {sum(durations.values()):.1f}s | plus title 5s + end 8s = {total:.1f}s")

# ---------- 2. FRAMES ----------
from PIL import Image, ImageDraw, ImageFont

W, H = 2400, 1350  # 16:9, slightly larger than 1920x1080 for the zoom-crop
CH_BW = {0: "bw", 1: "bw", 2: "bw", 3: "bw", 4: "bw", 5: "colour", 6: "colour", 7: "colour", 8: "colour"}

def font(name, size):
    cands = [name, "segoeuil.ttf", "segoeui.ttf", "arial.ttf"]
    for c in cands:
        p = os.path.join("C:\\Windows\\Fonts", c)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def vfont(name, size):
    cands = [name, "seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"]
    for c in cands:
        p = os.path.join("C:\\Windows\\Fonts", c)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

f_big = vfont("seguisb.ttf", 120)
f_med = vfont("seguisb.ttf", 66)
f_small = font("segoeui.ttf", 40)
f_tiny = font("segoeui.ttf", 30)
f_narr = font("segoeuil.ttf", 38)

INK, GOLD, TEAL, PAPER, RED = (10, 21, 38), (232, 184, 75), (14, 74, 92), (242, 232, 213), (178, 44, 44)

def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def base_card(top, bottom, mode="colour"):
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=lerp(top, bottom, y / H))
    if mode == "bw":
        img = img.convert("L").convert("RGB")
    # grain
    rnd = random.Random(7)
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(2600):
        x, y = rnd.randrange(W), rnd.randrange(H)
        a = rnd.randrange(6, 18)
        d.point((x, y), fill=(255, 255, 255, a) if rnd.random() < 0.5 else (0, 0, 0, a))
    return img

def chip(d, x, y, text, fg, bg):
    tw = d.textlength(text, font=f_tiny)
    d.rounded_rectangle([x, y, x + tw + 34, y + 52], radius=12, fill=bg)
    d.text((x + 17, y + 8), text, font=f_tiny, fill=fg)
    return tw + 34 + 14

def footer_narr(d, text, y0=H - 356):
    import textwrap
    lines = textwrap.wrap(text, 76)
    for i, ln in enumerate(lines[-6:]):
        d.text((150, y0 + i * 48), ln, font=f_narr, fill=PAPER)
        y0v = 0
    d.text((150, y0 - 54), "NARRATION", font=f_tiny, fill=GOLD)

def header(d, s):
    d.text((150, 90), f"SCENE {s['no']:02d}  ·  CH{s['chapter']}", font=f_med, fill=GOLD)
    d.text((150, 180), s["scene_title"].strip('"').upper(), font=f_big, fill=PAPER)
    x = 150
    x += chip(d, x, 340, ("DRAFT ANIMATIC"), INK, PAPER)
    truth = s.get("truth", "FACT")
    label = truth.split("(")[0].split(",")[0].strip()
    label = {"TITLE/FACT": "FACT"}.get(label, label) or "FACT"
    fg = PAPER if label != "CONTEXT-VERIFY" else INK
    bgx = TEAL if label == "FACT" else GOLD
    x += chip(d, x, 340, label, fg, bgx)
    if s["chapter"] >= 4:
        chip(d, x, 340, "Illustrative image", INK, PAPER)

def lamp(d, cx, cy, r, glow):
    d.ellipse([cx - r * 3, cy - r * 3, cx + r * 3, cy + r * 3], fill=lerp(INK, GOLD, 0.25) if glow else INK)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD)
    d.line([(cx, cy + r), (cx, cy + r * 2.2)], fill=PAPER, width=6)

def rects(d, boxes, fill, outline=None):
    for b in boxes:
        d.rectangle(b, fill=fill, outline=outline)

ART = {
    1: lambda d: (lamp(d, W * 0.5, H * 0.44, 34, True),),
    2: lambda d: (d.text((W * 0.5 - 560, H * 0.42), "IN DEED AND IN TRUTH", font=vfont("seguisb.ttf", 90), fill=PAPER),),
    3: lambda d: (rects(d, [(W*0.16, H*0.4, W*0.84, H*0.46), (W*0.16, H*0.46, W*0.5, H*0.52)], lerp(PAPER, PAPER, 0)), d.rectangle([W*0.16, H*0.4, W*0.35, H*0.52], fill=PAPER),),
    4: lambda d: rects(d, [(W*0.14+i*W*0.09, H*0.42, W*0.14+i*W*0.09+70, H*0.52) for i in range(11)], PAPER),
    5: lambda d: rects(d, [(W*0.2, H*0.35, W*0.8, H*0.6)], TEAL) or d.rectangle([W*0.23, H*0.38, W*0.55, H*0.57], fill=PAPER),
    6: lambda d: (d.rectangle([W*0.28, H*0.32, W*0.72, H*0.62], fill=PAPER), d.text((W*0.31, H*0.36), "ACT No. 11 · 1962", font=f_med, fill=INK),),
    7: lambda d: rects(d, [(W*0.14+i*W*0.09, H*0.4+i%2*26, W*0.14+i*W*0.09+74, H*0.54) for i in range(11)], lerp(PAPER, GOLD, 0.4)),
    8: lambda d: (d.rectangle([W*0.2, H*0.38, W*0.48, H*0.6], fill=TEAL), d.rectangle([W*0.52, H*0.38, W*0.8, H*0.6], fill=PAPER),),
    9: lambda d: (d.ellipse([W*0.26, H*0.4, W*0.4, H*0.56], fill=GOLD), d.polygon([(W*0.5, H*0.4), (W*0.62, H*0.56), (W*0.38, H*0.56)], fill=PAPER),),
    10: lambda d: (rects(d, [(W*0.2+ i*W*0.11, H*0.3+ (i%3)*60, W*0.2+i*W*0.11+90, H*0.38+(i%3)*60) for i in range(9)], PAPER),),
    11: lambda d: (d.rectangle([W*0.1, H*0.3, W*0.16, H*0.62], fill=GOLD), d.rectangle([W*0.2, H*0.3, W*0.26, H*0.62], fill=lerp(PAPER, GOLD, 0.35)), lamp(d, W*0.66, H*0.42, 26, True),),
    12: lambda d: ([d.rectangle([W*0.12, H*0.34, W*0.3, H*0.6], outline=PAPER, width=8), d.text((W*0.14, H*0.36), "56", font=f_big, fill=GOLD), d.rectangle([W*0.36, H*0.34, W*0.54, H*0.6], outline=PAPER, width=8), d.text((W*0.38, H*0.36), "46", font=f_big, fill=GOLD), d.rectangle([W*0.6, H*0.34, W*0.78, H*0.6], outline=PAPER, width=8), d.text((W*0.62, H*0.36), "28", font=f_big, fill=GOLD),],),
    13: lambda d: (d.polygon([(W*0.5, H*0.3), (W*0.3, H*0.62), (W*0.7, H*0.62)], fill=PAPER), d.text((W*0.36, H*0.64), "+4 FACULTIES · 1964", font=f_small, fill=GOLD),),
    14: lambda d: (rects(d, [(W*0.14, H*0.5, W*0.4, H*0.62), (W*0.44, H*0.44, W*0.62, H*0.62), (W*0.66, H*0.36, W*0.86, H*0.62)], SUB := PAPER), d.text((W*0.14, H*0.3), "AKOKA  1965", font=f_med, fill=GOLD),),
    15: lambda d: ([d.ellipse([W*0.3, H*0.3, W*0.7, H*0.7], fill=lerp(GOLD, TEAL, 0.5)), d.ellipse([W*0.38, H*0.38, W*0.62, H*0.62], fill=GOLD),],),
    16: lambda d: (d.rectangle([W*0.14, H*0.42, W*0.47, H*0.58], fill=TEAL), d.rectangle([W*0.53, H*0.42, W*0.86, H*0.58], fill=PAPER), d.rectangle([W*0.46, H*0.4, W*0.54, H*0.6], fill=GOLD),),
    17: lambda d: (d.rectangle([W*0.24, H*0.34, W*0.68, H*0.62], fill=PAPER), d.line([(W*0.3, H*0.5), (W*0.44, H*0.5)], fill=INK, width=6), lamp(d, W*0.78, H*0.5, 30, True),),
    18: lambda d: (d.rectangle([W*0.16, H*0.44, W*0.5, H*0.62], fill=lerp(INK, TEAL, 0.5)), d.rectangle([W*0.56, H*0.36, W*0.76, H*0.62], fill=lerp(INK, GOLD, 0.6)), d.polygon([(W*0.78, H*0.3), (W*0.9, H*0.3), (W*0.86, H*0.2)], fill=GOLD),),
    19: lambda d: (d.rectangle([W*0.2, H*0.3, W*0.8, H*0.4], fill=PAPER), d.rectangle([W*0.2, H*0.44, W*0.55, H*0.5], fill=RED), d.text((W*0.2, H*0.56), "HEADLINE SPACE LEFT BLANK", font=f_small, fill=PAPER),),
    20: lambda d: ([d.ellipse([W*0.14+i*W*0.09, H*0.5 - (i%3)*40, W*0.14+i*W*0.09+50, H*0.5 - (i%3)*40+50], fill=PAPER) for i in range(9)], d.rectangle([W*0.3, H*0.66, W*0.7, H*0.72], fill=GOLD),),
    21: lambda d: (d.rectangle([W*0.12, H*0.3, W*0.46, H*0.66], outline=GOLD, width=6), lamp(d, W*0.29, H*0.44, 28, True), d.rectangle([W*0.54, H*0.3, W*0.88, H*0.66], outline=PAPER, width=6), d.rectangle([W*0.62, H*0.4, W*0.8, H*0.54], fill=PAPER),),
    22: lambda d: (rects(d, [(W*0.12, H*0.42, W*0.3, H*0.62), (W*0.34, H*0.34, W*0.56, H*0.62), (W*0.6, H*0.4, W*0.82, H*0.62)], TEAL), d.text((W*0.12, H*0.28), "12 FACULTIES · 3 CAMPUSES · 13 VCs", font=f_small, fill=GOLD),),
    23: lambda d: (lamp(d, W * 0.5, H * 0.4, 34, True), (d.line([(W*0.0, H*0.72), (W, H*0.72)], fill=GOLD, width=6),), d.text((W*0.32, H*0.56), "22·10·1962 → TODAY", font=f_small, fill=PAPER),),
}

for s in sc:
    n = s["no"]
    mode = "bw" if CH_BW[s["chapter"]] == "bw" else "colour"
    top, bot = (INK, INK) if mode == "bw" else (INK, lerp(INK, TEAL, 0.55))
    if mode == "bw":
        top = lerp(INK, (40, 40, 44), 0.4)
    img = base_card(top, bot, mode)
    d = ImageDraw.Draw(img, "RGBA")
    art = ART.get(n)
    if art:
        try:
            art(d)
        except Exception as e:
            d.text((200, H * 0.5), f"(art placeholder {e})", font=f_small, fill=PAPER)
    header(d, s)
    footer_narr(d, s["spoken"])
    img.save(os.path.join(BASE, "frames", f"scene_{n:02d}.png"))

# title card
img = base_card(INK, lerp(INK, TEAL, 0.35))
d = ImageDraw.Draw(img, "RGBA")
d.text((330, 380), "IN DEED AND IN TRUTH", font=vfont("seguisb.ttf", 150), fill=PAPER)
d.text((330, 560), "The Birth of the University of Lagos, 1962", font=font("segoeuil.ttf", 64), fill=GOLD)
d.text((330, 700), "DRAFT ANIMATIC v1 — synthesised voice, illustrative frames; not for public release", font=f_tiny, fill=PAPER)
img.save(os.path.join(BASE, "frames", "title.png"))

# end card
img = base_card(lerp(INK, GOLD, 0.18), INK)
d = ImageDraw.Draw(img, "RGBA")
d.text((330, 400), "In deed. And in truth.", font=vfont("seguisb.ttf", 110), fill=PAPER)
d.text((330, 560), "University of First Choice — and the Nation's Pride", font=font("segoeuil.ttf", 52), fill=GOLD)
d.text((330, 680), "Sources: UNILAG official history · Akinyele & Adeboye (2012) · National Archives", font=f_tiny, fill=PAPER)
img.save(os.path.join(BASE, "frames", "end.png"))
print("frames written:", sorted(os.listdir(os.path.join(BASE, "frames"))))

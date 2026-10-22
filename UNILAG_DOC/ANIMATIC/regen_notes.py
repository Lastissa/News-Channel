# Regenerate VIDEO_NOTES.md with clean UTF-8 + real scene titles
import io, json, sys
sys.stdout.reconfigure(encoding="utf-8")

dur = {int(k): v / 1.30 for k, v in json.load(io.open(r"UNILAG_DOC\ANIMATIC\durations.json", encoding="utf-8")).items()}
scenes = json.load(io.open(r"UNILAG_DOC\ANIMATIC\scenes.json", encoding="utf-8"))

starts, t = {}, 5.0
for s in scenes:
    n = s["no"]
    starts[n] = t
    t += dur[n]

def fmt(x):
    x = round(x)
    return f"{x//60}:{x%60:02d}" if x >= 60 else f"0:{x:02d}"

CH_LABELS = {
    0: "A lamp in Surulere",
    1: "The Hunger",
    2: "The Law That Made a University",
    3: "The First Helmsman",
    4: "The First Morning",
    5: "From Borrowed Rooms to Akoka",
    6: "A University Comes of Age",
    7: "The Test of a Name",
    8: "In Deed and In Truth",
}

out = []
out.append("# UNILAG ANIMATIC v1 - VIDEO NOTES")
out.append("")
out.append(f"File: `UNILAG_DOC\\ANIMATIC_v1.mp4` | projected runtime ~ {fmt(t + 8.0)} (target 9-11 min: PASS)")
out.append("")
out.append("What this draft is: a structural animatic per the production script - 1920x1080, 25fps,")
out.append("Ken-Burns stills (labelled illustrative in-frame), synthesised narration voice at documentary")
out.append("pace, title + end cards. It is a paper-edit tool, NOT the release cut.")
out.append("")
out.append("CHAPTER TIMESTAMPS (YouTube-ready)")
out.append("```")
seen = set()
for s in scenes:
    ch = s["chapter"]
    if ch not in seen:
        seen.add(ch)
        out.append(f"{fmt(starts[s['no']])} - CH{ch} | {CH_LABELS[ch]}")
out.append("```")
out.append("")
out.append("SCENE MAP (measured)")
out.append("")
out.append("| Scene | Ch | Start | Audio dur |")
out.append("|---|---|---|---|")
for s in scenes:
    n = s["no"]
    out.append(f"| S{n:02d} | CH{s['chapter']} | {fmt(starts[n])} | {dur[n]:.1f}s |")
out.append("")
out.append("TO REACH RELEASE QUALITY")
out.append("1. Human VO (see VO_SCRIPT.md) replacing the synthesised voice.")
out.append("2. Swap illustrative frames for requested archival images (shot list in PRODUCTION_SCRIPT.md).")
out.append("3. Licensed music per cue sheet; ambience beds (lagoon, compound, lecture murmur).")
out.append("4. Scene-specific transitions per script (cross-dissolves, match cuts, light-leak flashes).")
out.append("5. Set release-date card + Scene 23 year count to match release date.")
out.append("6. No real-person likenesses anywhere; archival portraits only, from licensed sources.")
io.open(r"UNILAG_DOC\VIDEO_NOTES.md", "w", encoding="utf-8", newline="\n").write("\n".join(out))
print("VIDEO_NOTES.md regenerated:", len(out), "lines | total", fmt(t + 8.0))

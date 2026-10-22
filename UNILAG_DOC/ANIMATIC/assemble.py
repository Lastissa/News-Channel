# Assemble the animatic with ffmpeg (imageio-ffmpeg binary)
import io, json, os, subprocess, sys

sys.stdout.reconfigure(encoding="utf-8")
import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
BASE = os.path.dirname(os.path.abspath(__file__))
dur = {int(k): v for k, v in json.load(io.open(os.path.join(BASE, "durations.json"), encoding="utf-8")).items()}
if not dur:
    import wave
    # fall back: read padded wavs directly
    for n in range(1, 24):
        p = os.path.join(BASE, "audio", f"pad_{n:02d}.wav")
        if os.path.exists(p):
            w = wave.open(p, "rb")
            dur[n] = round(w.getnframes() / w.getframerate(), 3)
            w.close()
print("durations:", dur)

FPS = 25
os.makedirs(os.path.join(BASE, "clips"), exist_ok=True)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("FFMPEG FAIL:", " ".join(cmd[:8]), "...")
        print(r.stderr[-1600:])
        sys.exit(1)
    return


TEMPO = 1.30  # pitch-preserving speed-up; targets the 145wpm documentary pace


def kenburns(img, seconds, out, wav=None, fade_in=False, fade_out=False):
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        print("skip existing:", out, flush=True)
        return
    frames = max(2, int(seconds * FPS))
    vf = (
        f"scale=2400:1350,"
        f"zoompan=z='min(1.0+on*0.08/{frames},1.08)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
        f":d={frames}:s=1920x1080:fps={FPS},format=yuv420p"
    )
    if fade_in:
        vf += ",fade=t=in:d=0.8"
    if fade_out:
        vf += ",fade=t=out:d=1.0"
    inputs = [FF, "-y", "-loop", "1", "-i", img]
    if wav:
        inputs += ["-i", wav]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
    out_opts = [
        "-t", f"{seconds}",
        "-map", "0:v", "-map", "1:a",
        "-vf", vf, "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
    ]
    if wav:
        out_opts += ["-af", f"atempo={TEMPO}", "-c:a", "aac", "-b:a", "160k", "-ar", "44100"]
    else:
        out_opts += ["-c:a", "aac", "-b:a", "96k", "-ar", "44100"]
    out_opts += ["-f", "mp4", "-shortest", out + ".part"]
    run(inputs + out_opts)
    os.replace(out + ".part", out)
    print("clip ok:", out, flush=True)


clips = []
p = os.path.join(BASE, "frames", "title.png")
kenburns(p, 5.0, os.path.join(BASE, "clips", "c00_title.mp4"), fade_in=True)
clips.append(os.path.join(BASE, "clips", "c00_title.mp4"))

for n in sorted(dur):
    wav = os.path.join(BASE, "audio", f"pad_{n:02d}.wav")
    out = os.path.join(BASE, "clips", f"c{n:02d}.mp4")
    kenburns(os.path.join(BASE, "frames", f"scene_{n:02d}.png"), dur[n], out, wav=os.path.abspath(wav))
    clips.append(out)

kenburns(os.path.join(BASE, "frames", "end.png"), 8.0, os.path.join(BASE, "clips", "c99_end.mp4"), fade_out=True)
clips.append(os.path.join(BASE, "clips", "c99_end.mp4"))

listf = os.path.join(BASE, "concat.txt")
io.open(listf, "w", encoding="utf-8").write("\n".join(f"file '{c}'" for c in clips))
final = os.path.abspath(os.path.join(BASE, "..", "UNILAG_DOC", "ANIMATIC_v1.mp4"))
run([FF, "-y", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", final])
import wave
print("FINAL:", final)
io.open(os.path.join(BASE, "clips_order.json"), "w").write(json.dumps(clips))

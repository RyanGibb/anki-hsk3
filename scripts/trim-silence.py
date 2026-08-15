#!/usr/bin/env python3
"""Cut the silence off the ends of the clips, leaving only what was said.

A recording of one word is mostly not the word. Yue Tan's are 1.28 seconds with a
quarter of a second of room at each end, the syllable recordings run to more than half
the clip, and the synthesised ones are padded with digital nothing. On a card that is a
pause before the sound and a wait after it, heard thousands of times.

Silence is judged against each clip's own peak rather than an absolute level, because a
noise floor that looks flat beside a loud recording is not quiet in itself, and the
corpus was recorded at whatever level it was recorded at. Only the ends: what is between
two syllables is the speaking and stays.

Generous guards, since the start of a word is the quietest part of it. An aspirated 拼
begins with breath that carries little energy and is unmistakably part of the word, so
the cut is made well before the sound crosses the threshold, and later at the end where
a vowel is still decaying.

Originals are left where they are and trimmed copies written to .cache/trimmed, so the
corpus stays as it was downloaded and a bad guess costs a re-run rather than a re-fetch.
Frames are copied rather than re-encoded: what survives is bit for bit what it was.
"""
import argparse
import concurrent.futures as cf
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / ".cache/trimmed"
SOURCES = [ROOT / ".cache/audio-cmn/96k/hsk",
           ROOT / ".cache/audio-cmn/64k/syllabs",
           ROOT / ".cache/tts"]
RATE = 22050
FLOOR = 0.04        # of the clip's own loudest 20 ms, about -28 dB
HEAD_GUARD = 0.05   # seconds kept before the sound crosses it
TAIL_GUARD = 0.10
FLOOR_ABS = 24      # of 32767, for a clip that is silence and hiss throughout
EDGE = 0.25         # of the peak: louder than this at an edge is mid-sound


def loudness(path: pathlib.Path):
    """Loudness over each 20 ms of a clip, or None if there is too little to read."""
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE),
         "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if len(x) < RATE // 20:
        return None
    win = int(0.02 * RATE)
    n = len(x) // win
    return np.sqrt((x[:n * win].reshape(n, win) ** 2).mean(axis=1)), len(x) / RATE


def opens_loudly(rms) -> tuple:
    """Whether a clip begins or ends in the middle of the sound."""
    top = rms.max() or 1
    return rms[0] > top * EDGE, rms[-1] > top * EDGE


def sound(path: pathlib.Path):
    """(start, end, duration) of the speech in seconds, or None if there is none.

    Read as loudness over 20 ms rather than sample by sample. A single sample says
    nothing -- a vowel crosses zero eighty times a second and hiss has spikes -- while
    the energy in a window separates a voice from a room cleanly.
    """
    import numpy as np
    read = loudness(path)
    if read is None:
        return None
    rms, dur = read
    if rms.max() < FLOOR_ABS:
        return None
    loud = np.flatnonzero(rms > rms.max() * FLOOR)
    if not len(loud):
        return None
    win = 0.02
    return loud[0] * win, (loud[-1] + 1) * win, dur, rms


def trim(path: pathlib.Path) -> tuple:
    """(bytes before, bytes after, seconds cut). Anything doubtful is copied whole."""
    dst = OUT / path.name
    was = path.stat().st_size
    if dst.exists() and dst.stat().st_mtime >= path.stat().st_mtime:
        return was, dst.stat().st_size, 0.0
    found = sound(path)
    if found is None:
        shutil.copy2(path, dst)
        return was, dst.stat().st_size, 0.0
    start, end, dur, before_rms = found
    start = max(0.0, start - HEAD_GUARD)
    end = min(dur, end + TAIL_GUARD)
    if end - start >= dur - 0.05:            # nothing worth cutting
        shutil.copy2(path, dst)
        return was, dst.stat().st_size, 0.0
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-i", str(path), "-c", "copy", str(dst)], check=True)
    if not dst.exists() or dst.stat().st_size < 400:
        shutil.copy2(path, dst)              # a trim that emptied the clip is no trim
        return was, dst.stat().st_size, 0.0
    # Frames are copied whole, so the cut lands on a frame boundary and not where it
    # was asked for, which can take the start of the word with it. Read the result
    # back: a clip that now opens or closes mid-sound is given up on and kept entire.
    after = loudness(dst)
    if after is not None:
        was_loud = opens_loudly(before_rms)
        now_loud = opens_loudly(after[0])
        if (now_loud[0] and not was_loud[0]) or (now_loud[1] and not was_loud[1]):
            shutil.copy2(path, dst)
            return was, dst.stat().st_size, 0.0
    return was, dst.stat().st_size, dur - (end - start)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    files = [p for d in SOURCES if d.is_dir() for p in sorted(d.glob("*.mp3"))]
    if args.limit:
        files = files[:args.limit]
    print(f"{len(files)} clips from {sum(1 for d in SOURCES if d.is_dir())} sources")
    before = after = 0
    cut = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for n, (was, now, secs) in enumerate(ex.map(trim, files), 1):
            before += was
            after += now
            if secs:
                cut.append(secs)
            if n % 2000 == 0:
                print(f"  {n}/{len(files)}", flush=True)
    if not files:
        sys.exit("nothing to trim")
    print(f"{len(cut)} clips trimmed, {sum(cut):.0f} seconds of silence removed "
          f"({sum(cut)/max(len(cut), 1):.2f}s each)")
    print(f"{before/1e6:.0f} MB -> {after/1e6:.0f} MB "
          f"({(1 - after/max(before, 1))*100:.0f}% smaller)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

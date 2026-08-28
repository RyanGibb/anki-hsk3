#!/usr/bin/env python3
"""Photograph a card of each kind, from the package the build writes.

A screenshot taken by hand goes stale the first time the styling moves, and
nothing says it has. These come out of the built package itself -- its
notetypes, its fields, its media -- so running this again after a build says
what the cards look like now.

The page is dressed the way Anki dresses one: the styling is the deck's own,
and what is added here is only what the reviewer puts around a card and the
deck therefore never states -- the play button a [sound:] tag becomes, and the
width of a phone, since the cards are laid out for one. The exception is the
card that asks you to write: what you drew lives only in the session that drew
it, so a tracing stands where it would be, or the answer would show one pane
where a card in use shows two.

    python3 scripts/render-cards.py [--apkg PATH] [--out docs/cards] [--width N]

Wants chromium to take the picture and Pillow to trim it.
"""
import argparse
import base64
import io
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
APKG = ROOT / "build/HSK-3.0-2025.apkg"
MEDIA = ROOT / "build/media"
# The stroke medians, for the tracing that stands in for what somebody wrote.
GRAPHICS = pathlib.Path(
    os.environ.get("MAKEMEAHANZI", "~/projects/makemeahanzi")
).expanduser() / "graphics.txt"

# The notes the pictures show, named rather than picked by a score, so the same
# cards come back every time. The first three are ordinary cards of their kind:
# 电脑 is a word whose characters are worth glossing apart, 国 is simplified and
# met inside other words, and the sentence is long enough to gloss every word of.
#
# The three fronts after them are the exception rather than the rule -- fewer than
# two hundred words are written like another -- and are here for the question that
# raises: which of us are you asking for. 长's two are answered by the part of
# speech, 地方's by the tones, since both of those are nouns.
SAMPLES = [
    ("vocabulary", "HSK 3.0 Vocabulary", {"Simplified": "电脑"}, ("front", "back")),
    ("writing", "HSK 3.0 Character", {"Simplified": "国"}, ("front", "back")),
    ("sentence", "HSK 3.0 Sentence",
     {"Hanzi": "这个城市一共有三所大学。"}, ("front", "back")),
    ("homograph-chang", "HSK 3.0 Vocabulary",
     {"Simplified": "长", "Level": "2"}, ("front",)),
    ("homograph-zhang", "HSK 3.0 Vocabulary",
     {"Simplified": "长", "Level": "3"}, ("front",)),
    ("homograph-difang", "HSK 3.0 Vocabulary",
     {"Simplified": "地方", "Level": "3"}, ("front",)),
]

SECTION = re.compile(r"\{\{([#^])([^}]+)\}\}(.*?)\{\{/\2\}\}", re.S)
FIELD = re.compile(r"\{\{([^}#^/][^}]*)\}\}")
SOUND = re.compile(r"\[sound:[^]]+\]")

# What Anki puts in place of a [sound:] tag, and the styling the reviewer gives it.
# The deck styles where the button sits and not what it looks like, so without this
# the corner of a card would be empty in a picture and round in the hand.
PLAY = ('<a class="replay-button soundLink"><svg class="playImage" viewBox="0 0 64 64">'
        '<circle cx="32" cy="32" r="29"/>'
        '<path d="M56.502,32.301l-37.502,20.101l0.507,-40.804l36.995,20.703Z"/>'
        "</svg></a>")
REVIEWER_CSS = """
body { margin: 0; background: #fff; }
.replay-button svg { width: 40px; height: 40px; }
.replay-button circle { fill: #fff; stroke: #414141; }
.replay-button path { stroke: #414141; fill: #414141; }
"""


def fill(template: str, fields: dict) -> str:
    """A template with its fields in it, as Anki fills one: a name is replaced by
    what the note says, and a section is kept only where its field says anything."""
    def section(m):
        kind, name, body = m.groups()
        said = bool(fields.get(name.strip(), "").strip())
        return body if (said if kind == "#" else not said) else ""
    while True:
        done = SECTION.sub(section, template)
        if done == template:
            break
        template = done
    return FIELD.sub(lambda m: fields.get(m.group(1).strip().split(":")[-1], ""),
                     template)


def traced(char: str, size: int = 752, pen: int = 8) -> str:
    """What the box holds after somebody has written in it, as a data URL.

    A writing card's answer shows the strokes beside what you drew, and what you
    drew lives only in the session that drew it, so a picture taken from the
    package alone would answer with one pane where a card in use has two. This
    traces the character along the stroke medians makemeahanzi records -- the
    line a finger follows, not the printed shape -- and lays it on the same
    guides the box has, which is what the canvas hands the answer side.
    """
    from PIL import Image, ImageDraw
    if not GRAPHICS.exists():
        return ""
    line = next((l for l in GRAPHICS.read_text(encoding="utf-8").splitlines()
                 if l.startswith(f'{{"character":"{char}"')), None)
    if not line:
        return ""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    faint = (0, 0, 0, 89)                      # the card's ink at 0.35, as the box draws it
    d.line([(size / 2, 0), (size / 2, size)], fill=faint, width=2)
    d.line([(0, size / 2), (size, size / 2)], fill=faint, width=2)
    d.line([(0, 0), (size, size)], fill=faint, width=2)
    d.line([(size, 0), (0, size)], fill=faint, width=2)
    # makemeahanzi draws in a 1024 square whose y runs the other way, from 900
    at = lambda p: (p[0] * size / 1024, (900 - p[1]) * size / 1024)
    for median in json.loads(line)["medians"]:
        points = [at(p) for p in median]
        d.line(points, fill=(0, 0, 0, 255), width=pen, joint="curve")
        for x, y in (points[0], points[-1]):   # the round cap a pen leaves
            d.ellipse((x - pen / 2, y - pen / 2, x + pen / 2, y + pen / 2), fill="black")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def page(body: str, css: str, media: pathlib.Path, width: int, drawing: str = "") -> str:
    # The answer side reads what the question side put in the session; nothing else
    # here pretends to be the reviewer.
    seed = (f'<script>sessionStorage.setItem("anki-drawings",'
            f'JSON.stringify(["{drawing}"]))</script>') if drawing else ""
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<base href="file://{media}/">'
            f"<style>{REVIEWER_CSS}{css}</style>{seed}</head>"
            f'<body><div class="card" style="width:{width}px">{body}</div></body></html>')


def shoot(html: str, out: pathlib.Path, width: int, scale: int, chromium: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        src = pathlib.Path(td) / "card.html"
        src.write_text(html, encoding="utf-8")
        raw = pathlib.Path(td) / "raw.png"
        subprocess.run(
            [chromium, "--headless", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", "--default-background-color=ffffffff",
             f"--force-device-scale-factor={scale}",
             f"--window-size={width},4000", "--virtual-time-budget=4000",
             f"--screenshot={raw}", f"file://{src}"],
            check=True, capture_output=True)
        trim(raw, out)


def trim(raw: pathlib.Path, out: pathlib.Path, pad: int = 16) -> None:
    """The window is taller than any card; keep what was drawn and a margin.

    A card is text and a handful of flat colours, so a palette holds it: the file
    comes out under half the size and the strokes are the same strokes.
    """
    from PIL import Image, ImageChops
    im = Image.open(raw).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
    box = ImageChops.difference(im, bg).getbbox()
    if box:
        im = im.crop((0, max(0, box[1] - pad), im.width, min(im.height, box[3] + pad)))
    im.quantize(colors=256, dither=Image.Dither.FLOYDSTEINBERG).save(out, optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apkg", default=str(APKG))
    ap.add_argument("--out", default=str(ROOT / "docs/cards"))
    ap.add_argument("--width", type=int, default=414, help="a phone's, in CSS pixels")
    ap.add_argument("--scale", type=int, default=2)
    args = ap.parse_args()

    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if not chromium:
        raise SystemExit("no chromium to take the picture with")
    apkg = pathlib.Path(args.apkg)
    if not apkg.exists():
        raise SystemExit(f"no package to photograph: {apkg}")
    if not MEDIA.is_dir():
        raise SystemExit(f"no staged media beside it: {MEDIA}")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(apkg) as z:
            name = next(n for n in z.namelist() if n.startswith("collection.anki"))
            z.extract(name, td)
        con = sqlite3.connect(pathlib.Path(td) / name)
        models = {m["name"]: m
                  for m in json.loads(con.execute("select models from col")
                                      .fetchone()[0]).values()}
        notes = list(con.execute("select mid, flds from notes"))
        con.close()

    for label, model_name, match, sides in SAMPLES:
        model = models.get(model_name)
        if not model:
            raise SystemExit(f"the package has no {model_name} notetype")
        names = [f["name"] for f in model["flds"]]
        # genanki writes a notetype's id as a string and a note's as a number
        rows = [f.split("\x1f") for mid, f in notes if str(mid) == str(model["id"])]
        hit = next((r for r in rows
                    if all(re.sub("<[^>]+>", "", r[names.index(k)]) == v
                           for k, v in match.items())), None)
        if hit is None:
            raise SystemExit(f"{model_name} has no note where {match}")
        fields = dict(zip(names, hit))
        tmpl = model["tmpls"][0]
        drawn = {"front": SOUND.sub(PLAY, fill(tmpl["qfmt"], fields)),
                 "back": SOUND.sub(PLAY, fill(tmpl["afmt"], fields))}
        for side in sides:
            body = drawn[side]
            # only the card that asks you to write has anything written on it
            ink = (traced(match.get("Simplified", ""))
                   if side == "back" and model_name.endswith("Character") else "")
            png = out / (f"{label}-{side}.png" if len(sides) > 1 else f"{label}.png")
            shoot(page(body, model["css"], MEDIA, args.width, ink), png,
                  args.width, args.scale, chromium)
            print(f"  {png.relative_to(ROOT)}  {png.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

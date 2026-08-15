#!/usr/bin/env python3
"""Cut a font down to the rare characters the cards actually use.

A glyph origin names parts that ordinary fonts do not carry: 答 is built from 亼, and
the deck's etymologies reach 288 characters above the BMP, in CJK Extension B and above.
A desktop can be told to install Plangothic; a phone cannot, so the deck carries the
glyphs itself.

Only the supplementary planes are carried. Extension A is in the Noto CJK that Android
and most desktops already ship, and there is no reason to send what is already there.

Needs fontTools and the source font:

    nix-shell -p 'python3.withPackages(ps: with ps; [fonttools brotli zopfli])' \\
        --run 'python3 scripts/make-font-subset.py'
"""
import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data/fonts"
BUILD = ROOT / "build"
# The characters are read from the built cards rather than from the sources, because
# what needs a glyph is what a card shows.
CARDS = BUILD / "words.json"


def source_fonts(given: list) -> list:
    if given:
        return [pathlib.Path(x) for x in given]
    out = subprocess.run(["fc-list", "--format", "%{file}\\n"],
                         capture_output=True, text=True).stdout
    found = sorted(pathlib.Path(x) for x in out.splitlines() if "Plangothic" in x)
    if not found:
        sys.exit("no Plangothic found; install it or pass the .ttf paths as arguments")
    return found


def wanted() -> set:
    """Every character above the BMP on a card, taken from the built package."""
    import sqlite3
    import tempfile
    import zipfile
    apkg = BUILD / "HSK-3.0-2025.apkg"
    if not apkg.exists():
        sys.exit(f"build {apkg.name} first -- the glyphs are read from the cards")
    chars = set()
    with zipfile.ZipFile(apkg) as z:
        name = next(x for x in z.namelist() if x.startswith("collection.anki"))
        with tempfile.TemporaryDirectory() as td:
            z.extract(name, td)
            con = sqlite3.connect(pathlib.Path(td) / name)
            for (flds,) in con.execute("select flds from notes"):
                flds = re.sub(r"<[^>]+>|\[sound:[^]]+\]", " ", flds)
                chars |= {c for c in flds if ord(c) > 0xFFFF}
            con.close()
    return chars


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fonts", nargs="*", help="source .ttf files (default: Plangothic)")
    args = ap.parse_args()
    from fontTools.subset import Options, Subsetter
    from fontTools.ttLib import TTFont

    want = wanted()
    print(f"{len(want)} characters above the BMP on the cards")
    OUT.mkdir(parents=True, exist_ok=True)
    left = set(want)
    made = []
    for src in source_fonts(args.fonts):
        if not left:
            break
        font = TTFont(src, fontNumber=0)
        cmap = set()
        for table in font["cmap"].tables:
            cmap |= set(table.cmap)
        take = {c for c in left if ord(c) in cmap}
        if not take:
            continue
        left -= take
        opts = Options()
        opts.desubroutinize = True
        opts.notdef_outline = True
        sub = Subsetter(options=opts)
        sub.populate(text="".join(sorted(take)))
        sub.subset(font)
        # The leading underscore is what stops Check Media offering to delete it.
        dst = OUT / f"_rare-cjk-{len(made)}.woff2"
        font.flavor = "woff2"
        font.save(dst)
        made.append(dst)
        print(f"  {src.name}: {len(take)} glyphs -> {dst.name} "
              f"({dst.stat().st_size / 1024:.0f} kB)")
    if left:
        print(f"  {len(left)} still without a glyph: {''.join(sorted(left))[:40]}")
    for stale in sorted(OUT.glob("_rare-cjk-*.woff2")):
        if stale not in made:
            stale.unlink()
            print(f"  removed {stale.name}, no longer needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fetch the glyph origins the kaikki dump does not carry, straight from Wiktionary.

wiktextract attaches an etymology to the sense it sits under, so a "Glyph origin"
section that is a sibling of "Etymology" rather than a parent of it is absent from the
dump. That is the usual layout for a Han character, which is why several hundred
writing cards would otherwise say nothing about where the glyph came from.

Writes data/glyph-origins.csv, which is committed: a build needs no network, and the
prose is reviewable in the diff. Re-running only fetches characters not already there
unless given --refresh. Pages are cached under .cache/wiktionary-glyph.

Usage: fetch-glyph-origins.py [--refresh] [--limit N]
"""
import argparse
import csv
import html
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from glyph_origin import any_about_the_glyph   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data/glyph-origins.csv"
CACHE = ROOT / ".cache/wiktionary-glyph"
API = "https://en.wiktionary.org/w/api.php"
AGENT = "anki-hsk3/1.0 (https://github.com/; personal Anki deck build)"

# The prose opens with the classification, the same one the dump records as a liushu
# template argument, so cards built from either source can be styled alike.
TYPE = [
    ("Phono-semantic compound", "psc"),
    ("Ideogrammic compound", "ideo"),
    ("Pictogram", "pict"),
    ("Simplified", "simp"),
    ("Ideogram", "ideo"),
]
TAG = re.compile(r"<[^>]+>")
PARA = re.compile(r"<(p|li)\b[^>]*>(.*?)</\1>", re.S)
# Wiktionary marks a doubtful reading with a superscript reference; it reads as a stray
# digit once the tags are gone.
CITE = re.compile(r"\[\d+\]|\[edit\]|\[note \d+\]")
# The table of ancient forms carries its own caption and source note. A page can have
# the table and no explanation, and that note is not a glyph origin.
BOILERPLATE = re.compile(
    r"Richard Sears|Chinese Etymology site|^Historical forms of the character"
    r"|^References\b|^Note:"
    # A cleanup banner ships its own stylesheet, which survives tag stripping as CSS.
    r"|mw-parser-output|^This (?:article|entry) "
    # A footnote marker, a reference list entry, and a template Wiktionary failed to
    # render -- none of them says anything about the glyph.
    r"|^\^|^(?:Kangxi|Dai Kanwa|Dae Jaweon|Hanyu|Unihan|Digital Shinjigen)"
    r"|The template Template:"
    # The table of ancient forms lists where its images came from, as a bulleted
    # legend of source works. That is a bibliography, not an account of the glyph.
    r"|^(?:Shuowen Jiezi|Jinwen Bian|Liushutong|Yinxu Jiaguwen Bian)\b")


def get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def prose(fragment: str) -> str:
    """The section renders a table of oracle-bone and bronze forms as well as the
    explanation. Only the paragraphs say anything a card can use."""
    out = []
    for kind, para in PARA.findall(fragment):
        text = html.unescape(TAG.sub("", para))
        text = CITE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text and not BOILERPLATE.search(text):
            # 再's account is a line followed by the competing readings as a list, and
            # the card renders a list under its lead. Mark them as the dump does.
            out.append(("* " + text) if kind == "li" else text)
    return "\n".join(out).strip()


def glyph_origin(char: str) -> tuple:
    """(text, type) for a character, or ("", "") when Wiktionary has no such section."""
    cached = CACHE / f"{char}.json"
    if cached.exists():
        doc = json.loads(cached.read_text(encoding="utf-8"))
    else:
        try:
            sections = get({"action": "parse", "page": char, "prop": "sections"})
        except Exception as e:
            print(f"  {char}: {e}")
            return "", ""
        if "error" in sections:
            doc = {"text": ""}
        else:
            secs = sections["parse"]["sections"]
            # A page covers several languages. The Chinese section's glyph origin is
            # the one a Chinese card wants; Translingual carries the same material on
            # pages that have no Chinese section of their own.
            want = ""
            for lang in ("Chinese", "Translingual"):
                top = next((s["number"] for s in secs
                            if s["line"] == lang and str(s["level"]) == "2"), None)
                if top is None:
                    continue
                hit = [s for s in secs if s["line"] == "Glyph origin"
                       and s["number"].startswith(top + ".")]
                if hit:
                    want = hit[0]["index"]
                    break
            if not want:
                doc = {"html": ""}
            else:
                body = get({"action": "parse", "page": char,
                            "section": want, "prop": "text"})
                doc = {"html": body["parse"]["text"]["*"]}
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        time.sleep(0.2)

    # The page is cached as fetched, so changing what counts as usable prose costs
    # nothing: only a --refresh goes back to Wiktionary.
    text = prose(doc["html"]) if doc.get("html") else ""
    kind = next((k for prefix, k in TYPE if text.startswith(prefix)), "")
    return text, kind


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    etym = json.loads((ROOT / "build/etymology.json").read_text(encoding="utf-8"))
    # The same map the writing card uses for its Traditional field. Most of these
    # characters are not words of their own, so a word list cannot supply it, and the
    # glyph origin lives on the traditional page: 沒 has one, 没 has no Chinese section.
    chars = json.loads((ROOT / "build/char-meanings.json").read_text(encoding="utf-8"))
    trad = {c: v.get("traditional") or c for c, v in chars.items()}

    have = {}
    if OUT.exists() and not args.refresh:
        # A row that fails today's reading of the page is dropped rather than kept: the
        # page is cached, so it costs nothing to derive it again from what was fetched.
        have = {r["character"]: r for r in csv.DictReader(OUT.open(encoding="utf-8"))
                if r["text"] and not BOILERPLATE.search(r["text"])}

    # Every character the deck shows, not only the ones written by hand: a glyph
    # origin appears on a vocabulary card too, under each character of the word.
    writing = list(chars)
    # Not only the characters with no etymology at all: where the dump kept the word's
    # history instead of the glyph's, the slot is full but the card still has no answer
    # to the question it asks. 簡 is "borrowed from English Jane" and nothing else.
    missing = []
    for c in writing:
        t = trad.get(c, c)
        if t in have:
            continue
        if any_about_the_glyph(etym.get(t) or etym.get(c)):
            continue
        if t not in missing:
            missing.append(t)
    if args.limit:
        missing = missing[:args.limit]
    print(f"{len(missing)} characters to look up")

    found = 0
    for n, char in enumerate(missing, 1):
        text, kind = glyph_origin(char)
        if text:
            have[char] = {"character": char, "type": kind, "text": text}
            found += 1
        if n % 25 == 0:
            print(f"  {n}/{len(missing)}, {found} found")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ["character", "type", "text"])
        w.writeheader()
        for k in sorted(have):
            w.writerow(have[k])
    print(f"{found} new, {len(have)} in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

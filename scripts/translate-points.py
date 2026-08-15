#!/usr/bin/env python3
"""Draft translations of the grammar points for data/grammar-point-translations.csv.

The card names the point it is teaching. Where that name is a list of the items
themselves -- 小—、第—, or the thirty-five adverbs of 按理、按说、百般 -- there is
nothing to translate and the sentence shows the item in use. Where it is prose
(表示动作持续的时间) or a pattern built from grammatical terms (数词+多+量词), an
English reader is told the category and not the point, so those go to DeepL.

The committed CSV is a draft that has been gone over by hand, and the two differ:
a point is a pattern quoting the words it teaches, and a translator reads those
words as text to translate, turning 借用名量词：杯 into "borrowed measure word: cup"
and 第+数词 into "the + numeral". The characters of the pattern stay as characters,
since the card shows the English under the Chinese it renders.

A row already in the file is left alone, so this adds only what is missing, and
what it adds is raw. The build reads the CSV, never the network.
"""
import argparse
import csv
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/official_grammar.tsv"
OUT = ROOT / "data/grammar-point-translations.csv"
KEY_FILE = pathlib.Path.home() / "deepl-key"
BATCH = 40
CJK = re.compile(r"[㐀-鿿]")


def api_key() -> str:
    key = os.environ.get("DEEPL_API_KEY") or (
        KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    if not key:
        raise SystemExit(f"set DEEPL_API_KEY or write the key to {KEY_FILE}")
    return key


def needs_english(point: str) -> bool:
    """True when the point says something beyond naming the items it teaches.

    An item is written as itself and may carry an optional part or an alternative --
    有（一）点儿, 二/两 -- so those are stripped before its length is judged. What is
    left over is prose: 专用名量词：, 表示动作持续的时间, 数词+多+量词.
    """
    rest = point
    for item in re.split(r"[、，]", point):
        item = item.strip()
        if not item:
            continue
        bare = re.sub(r"[（(][^）)]*[）)]", "", item)
        parts = [x for x in re.split(r"[／/]", bare) if x]
        if parts and all(len(x) <= 5 and not re.search(r"[+＋：:]", x) for x in parts):
            rest = rest.replace(item, "", 1)
    return bool(CJK.search(re.sub(r"[、，\s]", "", rest)))


def points() -> list[str]:
    seen = {}
    with RAW.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            for field in ("content", "grammarDetail"):
                value = (row.get(field) or "").strip()
                if value and needs_english(value):
                    seen.setdefault(value, None)
    return list(seen)


def translate(batch: list[str], key: str) -> dict[str, str]:
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    body = urllib.parse.urlencode(
        [("text", t) for t in batch]
        + [("source_lang", "ZH"), ("target_lang", "EN-GB"),
           ("context", "A grammar point in the HSK Chinese syllabus.")]).encode()
    req = urllib.request.Request(f"https://{host}/v2/translate", data=body,
                                 headers={"Authorization": f"DeepL-Auth-Key {key}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 456, 500, 503):
                raise
            time.sleep(2 ** attempt * 5)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    else:
        return {}
    got = [t["text"].strip().replace("’", "'") for t in data["translations"]]
    if len(got) != len(batch):
        return {}
    return {zh: en for zh, en in zip(batch, got) if en}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--list", action="store_true", help="show what would be sent")
    args = ap.parse_args()

    want_all = points()
    if args.list:
        print(f"{len(want_all)} points would be translated")
        for p in want_all[:30]:
            print("  ", p[:70])
        return 0

    key = api_key()
    done = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as fh:
            done = {r["chinese"]: r["english"] for r in csv.DictReader(fh)}
    want = [p for p in want_all if p not in done]
    print(f"{len(done)} already translated, {len(want)} to go")

    for i in range(0, len(want), BATCH):
        batch = want[i:i + BATCH]
        got = translate(batch, key)
        done.update(got)
        with OUT.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["chinese", "english"])
            for k in want_all:
                if k in done:
                    w.writerow([k, done[k]])
        print(f"  {min(i + BATCH, len(want))}/{len(want)}"
              + (f"  ({len(batch) - len(got)} unmatched)" if len(got) != len(batch)
                 else ""), flush=True)
        time.sleep(args.delay)

    print(f"wrote {OUT}: {len(done)} of {len(want_all)} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

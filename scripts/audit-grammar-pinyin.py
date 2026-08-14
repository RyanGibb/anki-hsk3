#!/usr/bin/env python3
"""Is every Chinese word in the grammar sentences read the same way everywhere?

Reads data/grammar-pinyin.csv, aligns each sentence character-to-syllable, and reports
every 2- and 3-character sequence that got more than one rendering. Some of what it
reports is meant: 我还 is hái or huán, 十分 is "very" or "ten minutes". The rest is not.
"""
import collections
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECKED = ROOT / "data/grammar-pinyin.csv"

from pinyin_align import CJK, FLAT, RULED, align  # noqa: E402

def kind(variants) -> str:
    flat = [v.replace(" ", "") for v in variants]
    if len(set(flat)) == 1:
        return "spacing"
    bare = [v.translate(FLAT) for v in flat]
    return "tone" if len(set(bare)) == 1 else "syllable"


def main() -> int:
    if not CHECKED.exists():
        sys.exit(f"missing {CHECKED}")
    rows = list(csv.DictReader(CHECKED.open(encoding="utf-8")))
    seen = collections.defaultdict(collections.Counter)
    skipped = 0
    for r in rows:
        hanzi, pinyin = r["chinese"], r["pinyin"]
        if re.search(r"[0-9A-Za-z]", hanzi):   # digits and letters get spelled out
            skipped += 1
            continue
        a = align(hanzi, pinyin)
        if a is None:
            skipped += 1
            continue
        for n in (2, 3):
            for k in range(len(a) - n + 1):
                span = a[k:k + n]
                # a slice starting mid-word compares chàngchang gē against chànggē
                if not span[0][2]:
                    continue
                word = "".join(c for c, _, _ in span)
                rendering = span[0][1] + "".join(
                    ("" if starts is False else " ") + s for _, s, starts in span[1:])
                seen[word][rendering.lower()] += 1

    groups = collections.defaultdict(list)
    for w, c in seen.items():
        if len(c) > 1:
            groups["rule-governed" if set(w) & RULED else kind(list(c))].append((w, c))
    print(f"{len(rows) - skipped} sentences aligned, {skipped} skipped")
    for g in ("syllable", "tone", "spacing", "rule-governed"):
        print(f"  {g:14s} {len(groups[g])}")
    print()
    for g in ("syllable", "tone", "spacing"):
        for w, c in sorted(groups[g], key=lambda kv: -sum(kv[1].values()))[:20]:
            print(f"  {g:9s} {w:6s} "
                  + "  |  ".join(f"{k} x{n}" for k, n in c.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

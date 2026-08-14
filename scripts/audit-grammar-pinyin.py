#!/usr/bin/env python3
"""Every Chinese word, everywhere it appears, rendered the same way?

Not a sample: aligns all 2,055 sentences character-to-syllable, then reports every
2- and 3-character sequence that got more than one reading or more than one spacing.
Each one is a defect -- whichever rendering is right, they cannot both be.
"""
import collections
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from consistency import CJK, TONED, syllabify   # noqa: E402

HERE = pathlib.Path(__file__).parent
WORD = re.compile(r"[A-Za-z" + TONED + TONED.upper() + r"ü'()]+")


def align(hanzi: str, pinyin: str):
    """[(char(s), syllable, starts_a_word)] or None if they cannot be matched up."""
    chars = [c for c in hanzi if CJK.match(c)]
    sylls = []
    for word in WORD.findall(pinyin):
        parts = syllabify(word.replace("(", "").replace(")", ""))
        if not parts:
            return None
        for j, p in enumerate(parts):
            sylls.append((p, j == 0))
    out, i, j = [], 0, 0
    while i < len(chars) and j < len(sylls):
        syl, starts = sylls[j]
        # 哪儿 is one syllable nǎr spanning two characters
        if (syl.lower().endswith("r") and not syl.lower().endswith("er")
                and i + 1 < len(chars) and chars[i + 1] == "儿"):
            out.append((chars[i] + "儿", syl, starts))
            i += 2
        else:
            out.append((chars[i], syl, starts))
            i += 1
        j += 1
    if i != len(chars) or j != len(sylls):
        return None
    return out


def main() -> int:
    base = {r["id"]: r for r in csv.DictReader(
        (HERE / "sentences.tsv").open(encoding="utf-8"), delimiter="\t",
        quoting=csv.QUOTE_NONE)}
    norm = {}
    for line in (HERE / "normalised.tsv").open(encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2:
            norm[p[0]] = p[1]

    seen = collections.defaultdict(collections.Counter)
    where = collections.defaultdict(dict)
    skipped = 0
    for i, pinyin in norm.items():
        hanzi = base[i]["hanzi"]
        if re.search(r"[0-9A-Za-z]", hanzi):
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
                # and calls it an inconsistency. Only start where a word starts.
                if not span[0][2]:
                    continue
                word = "".join(c for c, _, _ in span)
                # only inside one word, or the spacing question is a different one
                rendering = span[0][1] + "".join(
                    ("" if starts is False else " ") + s for _, s, starts in span[1:])
                seen[word][rendering.lower()] += 1
                where[word].setdefault(rendering.lower(), []).append(i)

    # 一, 不 and 了 vary by rule, not by carelessness: 一 takes its tone from the
    # syllable after it, 了 attaches or stands alone by clause position. A sequence
    # containing them is expected to have several renderings.
    RULED = set("一不了")

    def kind(variants):
        flat = [v.replace(" ", "") for v in variants]
        if len(set(flat)) == 1:
            return "spacing"
        bare = [re.sub(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]",
                       lambda m: "aeiouü"["āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ".index(m.group(0)) // 4],
                       v) for v in flat]
        return "tone" if len(set(bare)) == 1 else "syllable"

    bad = {w: c for w, c in seen.items() if len(c) > 1}
    groups = collections.defaultdict(list)
    for w, c in bad.items():
        groups["rule-governed" if set(w) & RULED else kind(list(c))].append((w, c))
    print(f"{len(norm) - skipped} sentences aligned, {skipped} skipped")
    for g in ("syllable", "tone", "spacing", "rule-governed"):
        print(f"  {g:14s} {len(groups[g])}")
    print()
    with (HERE / "defects.tsv").open("w", encoding="utf-8") as fh:
        fh.write("word\tkind\trendering\tcount\tids\texample_hanzi\texample_pinyin\n")
        for g in ("syllable", "tone", "spacing"):
            for w, c in sorted(groups[g], key=lambda kv: -sum(kv[1].values())):
                for r, n in c.most_common():
                    ids = where[w][r]
                    e = ids[0]
                    fh.write(f"{w}\t{g}\t{r}\t{n}\t{','.join(ids[:40])}\t"
                             f"{base[e]['hanzi']}\t{norm[e]}\n")
    n = sum(len(groups[g]) for g in ("syllable", "tone", "spacing"))
    print(f"\n{n} words to rule on -> defects.tsv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

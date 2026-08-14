#!/usr/bin/env python3
"""Line a sentence's characters up with the syllables of its pinyin.

The checked pinyin is the only thing that knows where the words are: 里边 is one
word because someone wrote it as one, and nothing in the characters says so.
"""
import re

CJK = re.compile(r"[㐀-鿿]")
TONED = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ"
FLAT = str.maketrans(TONED + TONED.upper(),
                     "aaaaeeeeiiiioooouuuuüüüü" * 1 + "AAAAEEEEIIIIOOOOUUUUÜÜÜÜ")
WORD = re.compile(r"[A-Za-z" + TONED + TONED.upper() + r"ü'()]+")

INITIAL = "zh|ch|sh|[bpmfdtnlgkhjqxrzcsyw]"
FINAL = ("iang|iong|uang|ueng|ian|iao|ing|ong|uai|uan|uei|uen|ang|eng|van|"
         "ia|ie|iu|in|ua|uo|ui|un|ue|ve|ai|ei|ao|ou|an|en|er|vn|"
         "a|o|e|i|u|v|ng|n|m")
SYLL = re.compile(f"(?:{INITIAL})?(?:{FINAL})r?", re.I)

# 一, 不 and 了 vary by rule: 一 takes its tone from the syllable after it, 了 attaches
# to its verb or stands alone by clause position. Several renderings are correct.
RULED = set("一不了")


def syllabify(word: str) -> list:
    """Split one pinyin word into syllables.

    An apostrophe is a syllable boundary and the only reason it is written, so it comes
    first: fǎn'ér is fǎn + ér, and gluing it gives fǎ + nér. A final n, ng or r belongs
    to the next syllable when a vowel follows, or gerén reads as ger + én.
    """
    out = []
    for part in word.split("'"):
        flat = part.translate(FLAT).replace("ü", "v").lower()
        i = 0
        while i < len(flat):
            m = SYLL.match(flat, i)
            if not m or m.end() == i:
                return []
            end = m.end()
            while (end < len(flat) and flat[end] in "aeiouv"
                   and flat[end - 1] in "ngr" and end - 1 > i):
                end -= 1
            out.append(part[i:end])
            i = end
    return out


def align(hanzi: str, pinyin: str):
    """[(character, syllable, starts_a_word)], or None if the two cannot be matched."""
    chars = [c for c in hanzi if CJK.match(c)]
    sylls = []
    for word in WORD.findall(pinyin):
        parts = syllabify(word.replace("(", "").replace(")", ""))
        if not parts:
            return None
        sylls += [(p, j == 0) for j, p in enumerate(parts)]
    out, i, j = [], 0, 0
    while i < len(chars) and j < len(sylls):
        syl, starts = sylls[j]
        # 哪儿 is one syllable, nǎr, spanning two characters
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



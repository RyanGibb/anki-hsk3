#!/usr/bin/env python3
"""Line a sentence's characters up with the syllables of its pinyin.

The checked pinyin is the only thing that knows where the words are: 里边 is one
word because someone wrote it as one, and nothing in the characters says so.
"""
import re

# The marked vowels, four tones to each: index // 4 is the vowel, index % 4 the tone.
TONED = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ"
FLAT = str.maketrans(TONED + TONED.upper(),
                     "aaaaeeeeiiiioooouuuuüüüü" + "AAAAEEEEIIIIOOOOUUUUÜÜÜÜ")
TONE_VALUE = {c: str(i % 4 + 1) for i, c in enumerate(TONED)}
MARK = re.compile(f"[{TONED}]")
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


ALIGNABLE = re.compile(r"[㐀-鿿0-9A-Za-z]")

# Where a syllable may begin without a mark saying so. Everything else is a letter the
# syllable before it could have ended on.
OPENS = "aoe"


def apostrophes(marked: str, numbered: str) -> str:
    """The reading with the apostrophes pinyin needs written back into it.

    An apostrophe is written before a syllable beginning with a, o or e so that the
    letter before it is not read into it. The word list writes 感恩 as gǎnēn, which
    syllabifies as gǎ-nēn, and that is the reading the writing card gave 恩. The
    numbered reading beside it says where the syllables fall, so nothing is decided
    here, only marked: gǎn'ēn.

    The numbered reading is the authority and the marked one is checked against it
    letter by letter; anything that does not line up is left exactly as it came.
    """
    out, i = [], 0
    for syl in numbered.split():
        want = re.sub(r"[0-9]$", "", syl).replace("u:", "v").replace("ü", "v")
        while i < len(marked) and not marked[i].isalpha():
            out.append(marked[i])
            i += 1
        if want[:1] and want[0] in OPENS and out and out[-1].isalpha():
            out.append("’")
        flat = marked[i:i + len(want)].translate(FLAT).replace("ü", "v").lower()
        if flat != want:
            return marked
        out.append(marked[i:i + len(want)])
        i += len(want)
    return "".join(out) if i == len(marked) else marked


def align(hanzi: str, pinyin: str):
    """[(character, syllable, starts_a_word)], or None if the two cannot be matched.

    A digit is read one syllable at a time -- 2022年 is èr líng èr èr nián -- so it
    counts as a character here, and so does a speaker's A： label.
    """
    chars = [c for c in hanzi if ALIGNABLE.match(c)]
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


def numbered(p: str) -> str:   # noqa: D401
    """nǔ -> nu3, the form CC-CEDICT keys its entries by and the syllable recordings
    are named after."""
    out, tone = [], "5"
    for ch in p:
        i = TONED.find(ch)
        if i < 0:
            out.append("v" if ch == "ü" else ch)
        else:
            tone = str(i % 4 + 1)
            out.append("aeiouv"[i // 4])
    return "".join(out) + tone


def norm(p: str) -> str:
    """A reading reduced to what was said.

    The deck's notation is not the recording index's: it divides the halves of a
    four-character idiom with a hyphen (chéngqiān-shàngwàn) and writes ü, where the
    index runs the syllables together and types ü as v. None of that is audible.
    """
    p = p.split("/")[0].lower()
    for mark in (" ", "’", "'", "-"):
        p = p.replace(mark, "")
    return p.replace("u:", "ü").replace("v", "ü")


def toneless(p: str) -> str:
    return norm(p).translate(FLAT)


def tones(word: str, reading: str):
    """[(character, tone)] for a reading, or None if it will not divide into syllables.

    5 for a syllable written without a mark, as the dictionaries number a neutral tone.
    """
    pairs = align(word, norm(reading))
    if not pairs:
        return None
    out = []
    for char, syl, _starts in pairs:
        mark = MARK.search(syl)
        out.append((char, TONE_VALUE[mark.group()] if mark else "5"))
    return out


def same_sound(card: str, recorded: str, word: str, strict: bool = False) -> bool:
    """Whether a recording says what the card says.

    Loosely by default, because 聪明 is recorded both as cōngmíng and cōngming and
    they are the same word. Strictly where the deck teaches two words written alike:
    过 guò and 过 guo are not one word said casually, and a recording of the first
    teaches the wrong sound on the second's card. Ignoring tones wholesale would put
    被子 bèizi on 杯子 bēizi's card, and a quilt is not a cup.

    A word of one syllable is read strictly whatever is asked. An unstressed syllable
    is one that gave its tone to the syllable before it, and a word of one syllable has
    no syllable before it: 子 the suffix is zi and 子 the noun is zǐ, and a card
    teaching the first is not taught by a recording of the second.
    """
    if norm(card) == norm(recorded):
        return True
    if strict or toneless(card) != toneless(recorded):
        return False
    alone = len(toneless(card).split()) == 1 and len(word) == 1
    # The syllables now differ only in their tone marks. Two differences are the
    # notation and not the speaker: a syllable written unstressed by one source and
    # not the other, and the sandhi of 一 and 不, which sit wherever the word puts
    # them -- 进一步, 从容不迫 -- so the tones are read against the characters.
    ours, theirs = tones(word, card), tones(word, recorded)
    if ours and theirs and len(ours) == len(theirs):
        return all(x == y or ("5" in (x, y) and not alone) or char[:1] in "一不"
                   for (char, x), (_, y) in zip(ours, theirs))
    a, b = MARK.findall(norm(card)), MARK.findall(norm(recorded))
    # sheí and shéi are the same syllable with the mark typed on a different vowel
    if [TONE_VALUE[x] for x in a] == [TONE_VALUE[x] for x in b]:
        return True
    return len(a) != len(b) and not alone   # neutral tone

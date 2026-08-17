#!/usr/bin/env python3
"""Attach audio and stroke diagrams; stage the files in build/media.

Audio is matched by READING, not spelling: Yue Tan read 还 as huán, so the card that
teaches it as hái cannot use that recording. Readings come from data/swac-index.csv;
the mp3s carry no tags.

Stages the whole corpus into build/media; the package takes only what is referenced,
so the rest is there to copy in by hand.
"""
import collections
import csv
import json
import os
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pinyin_align import TONE_VOWELS, align, numbered   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
MEDIA = BUILD / "media"
CMN = ROOT / ".cache/audio-cmn/96k/hsk"
# A second speaker: whole recordings, not concatenation, since a one-syllable word is
# a syllable.
SYLLABS = ROOT / ".cache/audio-cmn/64k/syllabs"
# not svgs/, which set no fill and render solid black
MMAH = (pathlib.Path(os.environ.get("MAKEMEAHANZI", "~/projects/makemeahanzi"))
        .expanduser() / "svgs-still")
MMAH_DICT = MMAH.parent / "dictionary.txt"
SWAC = ROOT / "data/swac-index.csv"
# Clips with the silence cut off their ends, by scripts/trim-silence.py. Every clip
# the deck ships passes through stage(), so preferring them here covers all of it.
TRIMMED = ROOT / ".cache/trimmed"

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
CJK = re.compile(r"[㐀-鿿豈-﫿]")




def norm(p: str) -> str:
    """A reading reduced to what was said.

    The deck's notation is not the corpus's: it divides the halves of a four-character
    idiom with a hyphen (ch\u00e9ngqi\u0101n-sh\u00e0ngw\u00e0n) and writes \u00fc, where the index runs the
    syllables together and types \u00fc as v. None of that is audible.
    """
    p = p.split("/")[0].lower()
    for mark in (" ", "\u2019", "'", "-"):
        p = p.replace(mark, "")
    return p.replace("u:", "\u00fc").replace("v", "\u00fc")


# Two notation differences, worth ~130 recordings: sandhi (一半 yíbàn vs yībàn) and
# neutral tones (cōngmíng/cōngming). Those two only: ignoring tones wholesale would put
# 被子 bèizi on 杯子 bēizi's card, and a quilt is not a cup.
TONE_MARKS = str.maketrans("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ", "aaaaeeeeiiiioooouuuuüüüü")
TONED = re.compile(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]")


TONE_VALUE = {c: str(i % 4 + 1) for i, c in enumerate(TONE_VOWELS)}


def toneless(p: str) -> str:
    return norm(p).translate(TONE_MARKS)


def tones(word: str, reading: str):
    """[(character, tone)] for a reading, or None if it will not divide into syllables.

    5 for a syllable written without a mark, as the dictionaries number a neutral tone.
    """
    pairs = align(word, norm(reading))
    if not pairs:
        return None
    out = []
    for char, syl, _starts in pairs:
        mark = TONED.search(syl)
        out.append((char, TONE_VALUE[mark.group()] if mark else "5"))
    return out


def same_sound(card: str, recorded: str, word: str, strict: bool = False) -> bool:
    """Whether a recording says what the card says.

    Loosely by default, because 聪明 is recorded both as cōngmíng and cōngming and
    they are the same word. Strictly where the deck teaches two words written alike:
    过 guò and 过 guo are not one word said casually, and a recording of the first
    teaches the wrong sound on the second's card.

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
    a, b = TONED.findall(norm(card)), TONED.findall(norm(recorded))
    # sheí and shéi are the same syllable with the mark typed on a different vowel
    if [TONE_VALUE[x] for x in a] == [TONE_VALUE[x] for x in b]:
        return True
    return len(a) != len(b) and not alone   # neutral tone


def stage(src: pathlib.Path, name: str) -> None:
    """Replaces a stale file of a different size: plain skip-if-exists kept every
    diagram black after the switch to svgs-still/."""
    cut = TRIMMED / src.name
    if cut.is_file():
        src = cut
    dst = MEDIA / name
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return
    shutil.copy2(src, dst)


def main() -> int:
    words = json.loads((BUILD / "words.json").read_text(encoding="utf-8"))
    if not CMN.is_dir():
        sys.exit(f"missing {CMN} -- sparse-clone hugolpz/audio-cmn first")
    if not MMAH.is_dir():
        sys.exit(f"missing {MMAH} -- set MAKEMEAHANZI, or run build.sh")
    MEDIA.mkdir(parents=True, exist_ok=True)

    cmn = {
        p.name[len("cmn-"):-len(".mp3")]: p
        for p in CMN.glob("cmn-*.mp3")
        if "_" not in p.name
    }

    # Syllable recordings not to use. Upstream reports most of them: fifth-tone files
    # are snippets cut from a discussion rather than recordings (audio-cmn#2, #13),
    # zhu2 and zhu4 are the wrong audio (#10), and san1, bang2, bang4 and jv4 stop
    # before the syllable ends (#12). nu3 is Ryan's ear rather than a report.
    # Membership is by listening either way, because these faults are audible while
    # sitting inside the corpus's normal duration and level range: nu3 runs 1.30s in
    # a single burst, which is what a good third tone looks like from the outside.
    SUSPECT = re.compile(r"^[a-zü:]+5$|^zhu[24]$|^(?:san1|bang[24]|jv4|nu3)$")
    syllabs = {k: v for k, v in (
        (p.name[len("cmn-"):-len(".mp3")].lstrip("_"), p)
        for p in SYLLABS.glob("cmn-*.mp3")) if not SUSPECT.match(k)} \
        if SYLLABS.is_dir() else {}

    swac = {r["word"]: r["pinyin"]
            for r in csv.DictReader(SWAC.open(encoding="utf-8"))
            if "_" not in r["word"]}
    by_reading: dict[str, list[str]] = collections.defaultdict(list)
    for word, pron in swac.items():
        by_reading[norm(pron)].append(word)

    stats = collections.Counter()
    strokes_needed: set[str] = set()
    substitutions = []

    # Where the syllabus lists a word twice with two readings, a recording has to say
    # this entry's reading exactly: 过 guò must not be played on 过 guo's card.
    ambiguous = {x["simplified"] for x in words
                 if any(o["simplified"] == x["simplified"]
                        and o["pinyin_numbered"] != x["pinyin_numbered"]
                        for o in words)}

    deck_readings: dict[str, list[str]] = collections.defaultdict(list)
    for w in words:
        deck_readings[w["simplified"]].append(w["pinyin"])

    for w in words:
        simp = w["simplified"]
        want = norm(w["pinyin"])
        w["audio"] = ""
        w["audio_source"] = ""

        source = kind = None
        if simp in swac and simp in cmn and same_sound(
                w["pinyin"], swac[simp], simp, strict=simp in ambiguous):
            source = simp
            kind = "audio-cmn (Yue Tan)"
        else:
            for alt in by_reading.get(want, []):
                # A substitution rests entirely on the index label, so where the deck
                # also teaches the word lent from, the deck's reading of it has to
                # agree with that label. The index calls cmn-高大.mp3 gāodù; the deck
                # reads 高大 gāodà, and one of the two is wrong, so the file is not
                # evidence of how gāodù sounds.
                theirs = deck_readings.get(alt)
                if theirs and not any(same_sound(t, swac[alt], alt) for t in theirs):
                    continue
                if alt in cmn:
                    source = alt
                    kind = "audio-cmn (homophone)"
                    substitutions.append((w, alt))
                    break
        if not source and len(simp) == 1:
            syl = syllabs.get(w["pinyin_numbered"].replace(" ", "").lower())
            if syl:
                name = syl.name
                stage(syl, name)
                w["audio"] = f"[sound:{name}]"
                w["audio_source"] = "audio-cmn syllabs (Chen Wang)"
                stats["syllable (Chen Wang)"] += 1
        if source:
            name = cmn[source].name
            stage(cmn[source], name)
            w["audio"] = f"[sound:{name}]"
            w["audio_source"] = kind
            stats["exact reading" if source == simp else "homophone"] += 1
        else:
            stats["blank"] += 1

        chars = [c for c in simp if CJK.match(c)]
        imgs = []
        for c in chars:
            svg = MMAH / f"{ord(c)}-still.svg"
            if svg.exists():
                # bare name: the collection already holds these, byte-identical
                name = f"{c}.svg"
                strokes_needed.add(c)
                # these SVGs carry no intrinsic size; style.css sizes them
                imgs.append(f'<img class=stroke src="{name}">')
        w["stroke_order"] = "".join(imgs)
        if imgs:
            stats["with strokes"] += 1

    # Anki plays [sound:a][sound:b] in sequence: two recordings, not a splice, so it is
    # audibly a reading-out. Only where the isolated syllables really are the word.
    TONE3 = re.compile(r"[ǎěǐǒǔǚ]")
    stacked = 0
    for w in words:
        if w["audio"] or len(w["simplified"]) < 2:
            continue
        cs = list(w["simplified"])
        if not all(c in cmn and c in swac for c in cs):
            continue
        syl = [swac[c] for c in cs]
        if "".join(syl) != w["pinyin"]:
            continue
        if any(x in w["simplified"] for x in "一不"):
            continue
        if any(TONE3.search(syl[i]) and TONE3.search(syl[i + 1])
               for i in range(len(syl) - 1)):
            continue
        for c in cs:
            stage(cmn[c], cmn[c].name)
        w["audio"] = "".join(f"[sound:{cmn[c].name}]" for c in cs)
        w["audio_source"] = "audio-cmn (per-character)"
        stacked += 1
    print(f"per-character stacks : {stacked}")

    char_readings = {}
    if MMAH_DICT.exists():
        for line in MMAH_DICT.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            char_readings[d["character"]] = [norm(x) for x in (d.get("pinyin") or [])]
    # makemeahanzi gives one reading per character -- 地 as de, never dì -- so a
    # recording of the other reading looked like a mismatch. The syllabus knows both,
    # because it teaches 地 twice. A recording is only right if it says something this
    # deck teaches: 血 is taught as xuè alone, so a xiě recording stays refused.
    # 熟 is entered as one reading, "shú/shóu", which is two. And ü is written both
    # ways: the syllabus has nü3 where everything else here says nv3.
    def readings_of(field: str) -> list:
        return [x.replace(" ", "").replace("ü", "v").lower()
                for x in field.split("/") if x.strip()]

    taught, taught_marked = {}, {}
    for w in words:
        if len(w["simplified"]) == 1:
            taught.setdefault(w["simplified"], set()).update(
                readings_of(w["pinyin_numbered"]))
            taught_marked.setdefault(w["simplified"], []).extend(
                x for x in w["pinyin"].split("/") if x.strip())
    known = {ch: set(reads) for ch, reads in taught.items()}
    for ch, reads in char_readings.items():
        known.setdefault(ch, set()).update(numbered(r) for r in reads)
    (BUILD / "char-readings.json").write_text(
        json.dumps(taught_marked, ensure_ascii=False), encoding="utf-8")

    char_audio = {}
    skipped_chars = []
    homophone = {}
    for word, pron in swac.items():
        homophone.setdefault(numbered(pron), word)

    # A word where this character is read this way, for readings no isolated
    # recording can cover.
    in_word = {}
    for x in words:
        simp, nums = x["simplified"], x["pinyin_numbered"].split()
        # a one-character "word" is the character, and its recording is the one
        # already refused for saying the wrong reading
        if len(simp) < 2 or len(simp) != len(nums) or simp not in cmn:
            continue
        for ch, num in zip(simp, nums):
            in_word.setdefault((ch, num.lower()), simp)

    def clip_for(c: str, reading: str):
        """A recording of this character said this way, and the word it was said in.

        A neutral tone takes its pitch from the syllable before it, so 了 le and 子 zi
        cannot be recorded alone and the syllable corpus does not try. They are heard
        inside a word instead -- 算了, 包子 -- which is the only place they exist.
        """
        if c in cmn and (c not in swac or numbered(swac[c]) == reading):
            return cmn[c], ""
        # a character read the same way, before an isolated syllable: the syllable set
        # is a second speaker reading in citation form, and 常 for 长's cháng is the
        # voice the rest of the deck uses
        twin = homophone.get(reading)
        if twin and twin in cmn:
            return cmn[twin], ""
        syl = syllabs.get(reading)
        if syl:
            return syl, ""
        word = in_word.get((c, reading))
        return (cmn[word], word) if word else (None, "")

    for r in csv.DictReader((ROOT / "data/raw/chelsea_hanzi_writing.tsv")
                            .open(encoding="utf-8"), delimiter="\t"):
        c = r["word"]
        readings = list(dict.fromkeys(taught.get(c, [])))
        if not readings:
            readings = [numbered(x) for x in (char_readings.get(c) or [])][:1]
        got = {}
        for reading in readings:
            src, heard_in = clip_for(c, reading)
            if not src:
                continue
            stage(src, src.name)
            got[reading] = {"sound": f"[sound:{src.name}]", "in": heard_in}
        if got:
            char_audio[c] = got
        elif c in cmn and c in swac:
            skipped_chars.append((c, "/".join(readings), swac[c]))

    # A syllable said light is said inside a word or not at all, so a word that is one
    # such syllable is heard in another: 子 in 包子, 头 in 石头. The card says which,
    # as the writing card does, since what plays is not the word on the card.
    heard = 0
    for w in words:
        if w["audio"] or len(w["simplified"]) != 1:
            continue
        reading = w["pinyin_numbered"].replace(" ", "").lower()
        word = in_word.get((w["simplified"], reading))
        if not word:
            continue
        src = cmn[word]
        stage(src, src.name)
        w["audio"] = f"[sound:{src.name}]"
        w["audio_source"] = "audio-cmn (in a word)"
        w["heard_in"] = word
        heard += 1
    print(f"heard inside a word  : {heard} words")

    # Anything the corpus never recorded: a clip made by hand where one exists, else
    # a synthesised one. Both are optional -- a checkout with neither still builds.
    hand = ROOT / "data/audio"
    tts_dir = ROOT / ".cache/tts"
    tts_index = json.loads((tts_dir / "index.json").read_text(encoding="utf-8")) \
        if (tts_dir / "index.json").exists() else {}
    made = collections.Counter()
    for w in words:
        if w["audio"]:
            continue
        src = hand / f"{w['simplified']}.mp3"
        if not src.exists():
            got = tts_index.get(w["simplified"])
            src = tts_dir / got if got else None
        # A clip the service returned empty is worse than none: the card looks
        # voiced and plays nothing.
        if not src or not src.exists() or src.stat().st_size < 1000:
            continue
        stage(src, src.name)
        w["audio"] = f"[sound:{src.name}]"
        w["audio_source"] = ("hand-recorded" if src.parent == hand
                             else "azure zh-CN-Xiaoxiao -20%")
        made[w["audio_source"]] += 1
    for k, v in made.items():
        print(f"{k:21s}: {v} words")

    extra = 0
    for src in sorted(MMAH.glob("*-still.svg")):
        char = chr(int(src.name.split("-")[0]))
        name = f"{char}.svg"
        if not (MEDIA / name).exists():
            stage(src, name)
            extra += 1
    for src in sorted(CMN.glob("cmn-*.mp3")) + sorted(SYLLABS.glob("cmn-*.mp3")):
        if not (MEDIA / src.name).exists():
            stage(src, src.name)
            extra += 1
    print(f"corpus staged        : +{extra} files this deck does not reference")

    (BUILD / "char-audio.json").write_text(
        json.dumps(char_audio, ensure_ascii=False), encoding="utf-8")
    reads = sum(len(v) for v in char_audio.values())
    print(f"character audio      : {len(char_audio)} of 1200 "
          f"({100*len(char_audio)/1200:.1f}%), {reads} readings voiced, "
          f"{len(skipped_chars)} skipped for a mismatched reading")
    (BUILD / "char-audio-skipped.csv").write_text(
        "character,card_reading,recorded_reading\n"
        + "\n".join(f"{a},{b},{c}" for a, b, c in skipped_chars), encoding="utf-8")

    for c in strokes_needed:
        stage(MMAH / f"{ord(c)}-still.svg", f"{c}.svg")

    (BUILD / "words.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    missing = [w for w in words if not w["audio"]]
    (BUILD / "missing-audio.csv").write_text(
        "level,entry,simplified,traditional,pinyin,meaning\n"
        + "\n".join(
            '{},{},{},{},{},"{}"'.format(
                w["level"], w["entry"], w["simplified"], w["traditional"],
                w["pinyin"], w["meaning"].replace('"', "'")[:60])
            for w in sorted(missing, key=lambda w: (LEVELS.index(w["level"]),
                                                    int(w["key"])))
        ),
        encoding="utf-8",
    )

    (BUILD / "audio-substitutions.csv").write_text(
        "entry,simplified,pinyin,recorded_word,level\n"
        + "\n".join(
            f"{w['entry']},{w['simplified']},{w['pinyin']},{alt},{w['level']}"
            for w, alt in substitutions
        ),
        encoding="utf-8",
    )

    total = len(words)
    have = sum(1 for w in words if w["audio"])
    print(f"words                : {total}")
    stats["blank"] = sum(1 for w in words if not w["audio"])
    for k in ("exact reading", "homophone", "syllable (Chen Wang)", "blank"):
        if stats[k]:
            print(f"  {k:20s}: {stats[k]}")
    print(f"audio coverage       : {have}/{total} ({100*have/total:.1f}%)")
    print(f"stroke-order svgs    : {len(strokes_needed)} chars, "
          f"{stats['with strokes']} words")

    by_level = collections.defaultdict(lambda: [0, 0])
    for w in words:
        by_level[w["level"]][1] += 1
        if w["audio"]:
            by_level[w["level"]][0] += 1
    for lv in ["1", "2", "3", "4", "5", "6", "7-9"]:
        hit, tot = by_level[lv]
        print(f"  L{lv:4s} {hit:5d}/{tot:5d}  {100*hit/tot:5.1f}%")

    size = sum(p.stat().st_size for p in MEDIA.iterdir())
    print(f"media staged         : {len(list(MEDIA.iterdir()))} files, {size/1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

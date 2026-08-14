#!/usr/bin/env python3
"""Attach audio and stroke diagrams; stage the files in build/media.

Audio is matched by READING, not spelling: Yue Tan recorded 还 as huàn, the card reads
hái. Readings come from data/swac-index.csv; the mp3s carry no tags.

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

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
CJK = re.compile(r"[㐀-鿿豈-﫿]")


TONE_VOWELS = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ"


def numbered(p: str) -> str:
    """nǔ -> nu3, which is how the syllable recordings are named."""
    out, tone = [], "5"
    for ch in p:
        i = TONE_VOWELS.find(ch)
        if i < 0:
            out.append("v" if ch == "ü" else ch)
        else:
            tone = str(i % 4 + 1)
            out.append("aeiouv"[i // 4])
    return "".join(out) + tone


def norm(p: str) -> str:
    return p.split("/")[0].replace(" ", "").replace("\u2019", "").replace("'", "").lower()


# Two notation differences, worth ~130 recordings: sandhi (一半 yíbàn vs yībàn) and
# neutral tones (cōngmíng/cōngming). Those two only: ignoring tones wholesale matches
# 背包 to a bèibāo recording, a different word.
TONE_MARKS = str.maketrans("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ", "aaaaeeeeiiiioooouuuuüüüü")
TONED = re.compile(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]")


def toneless(p: str) -> str:
    return norm(p).translate(TONE_MARKS)


def same_sound(card: str, recorded: str, word: str) -> bool:
    if norm(card) == norm(recorded):
        return True
    if toneless(card) != toneless(recorded):
        return False
    a, b = TONED.findall(norm(card)), TONED.findall(norm(recorded))
    if len(a) != len(b):
        return True                        # neutral tone
    if word[:1] in "一不" and a[1:] == b[1:]:
        return True                        # sandhi
    return False


def stage(src: pathlib.Path, name: str) -> None:
    """Replaces a stale file of a different size: plain skip-if-exists kept every
    diagram black after the switch to svgs-still/."""
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

    syllabs = {p.name[len("cmn-"):-len(".mp3")].lstrip("_"): p
               for p in SYLLABS.glob("cmn-*.mp3")} if SYLLABS.is_dir() else {}

    swac = {r["word"]: r["pinyin"]
            for r in csv.DictReader(SWAC.open(encoding="utf-8"))
            if "_" not in r["word"]}
    by_reading: dict[str, list[str]] = collections.defaultdict(list)
    for word, pron in swac.items():
        by_reading[norm(pron)].append(word)

    stats = collections.Counter()
    strokes_needed: set[str] = set()
    substitutions = []

    for w in words:
        simp = w["simplified"]
        want = norm(w["pinyin"])
        w["audio"] = ""
        w["audio_source"] = ""

        source = kind = None
        if simp in swac and simp in cmn and same_sound(w["pinyin"], swac[simp], simp):
            source = simp
            kind = "audio-cmn (Yue Tan)"
        else:
            for alt in by_reading.get(want, []):
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
    char_audio = {}
    skipped_chars = []
    for r in csv.DictReader((ROOT / "data/raw/chelsea_hanzi_writing.tsv")
                            .open(encoding="utf-8"), delimiter="\t"):
        c = r["word"]
        want = char_readings.get(c) or []
        if c not in cmn:
            # No recording of the character, but the syllable is in the corpus. Only
            # where the character has a single reading: with two, one of them is wrong.
            if len(want) != 1:
                continue
            syl = syllabs.get(numbered(want[0]))
            if not syl:
                continue
            stage(syl, syl.name)
            char_audio[c] = f"[sound:{syl.name}]"
            continue
        if c in swac and want and not any(
                same_sound(x, swac[c], c) for x in char_readings.get(c, [])):
            skipped_chars.append((c, "/".join(want), swac[c]))
            continue
        name = cmn[c].name
        stage(cmn[c], name)
        char_audio[c] = f"[sound:{name}]"
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
    print(f"character audio      : {len(char_audio)} of 1200 "
          f"({100*len(char_audio)/1200:.1f}%), "
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

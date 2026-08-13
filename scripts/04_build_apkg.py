#!/usr/bin/env python3
"""Build the .apkg. IDs are fixed constants, so re-importing updates the existing
notes instead of duplicating them."""
import collections
import csv
import html
import json
import os
import pathlib
import re

import genanki

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
MEDIA = BUILD / "media"
RAW = ROOT / "data/raw"
MMAH_DICT = pathlib.Path(
    os.environ.get("MAKEMEAHANZI", "~/projects/makemeahanzi")
).expanduser() / "dictionary.txt"

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
CJK = re.compile(r"[㐀-鿿豈-﫿]")

MID_VOCAB, MID_GRAMMAR, MID_CHAR = 1758100001, 1758100002, 1758100003
DID_ROOT = 1758100100

TPL = ROOT / "templates"


def tpl(name: str) -> str:
    return (TPL / name).read_text(encoding="utf-8")


VOCAB_FIELDS = ["Key", "Level", "Simplified", "Sense", "Traditional", "Pinyin",
                "PinyinNumbered", "Meaning", "PartOfSpeech", "PartOfSpeechGlossed",
                "Classifier", "Audio",
                "Homophones", "Homographs", "StrokeOrder"]

vocab_model = genanki.Model(
    MID_VOCAB, "HSK 3.0 Vocabulary",
    fields=[{"name": f} for f in VOCAB_FIELDS],
    css=tpl("style.css"),
    templates=[{
        "name": "Recognition",
        "qfmt": tpl("vocab-recognition-front.html"),
        "afmt": tpl("vocab-recognition-back.html"),
    }],
)

grammar_model = genanki.Model(
    MID_GRAMMAR, "HSK 3.0 Grammar",
    fields=[{"name": f} for f in
            ["Key", "Level", "Point", "Type", "Category", "Detail", "Examples",
             "ExamplesPinyin", "TypeEn", "CategoryEn", "DetailEn", "PointEn"]],
    css=tpl("style.css"),
    templates=[{
        "name": "Grammar",
        "qfmt": tpl("grammar-front.html"),
        "afmt": tpl("grammar-back.html"),
    }],
)

char_model = genanki.Model(
    MID_CHAR, "HSK 3.0 Character",
    fields=[{"name": f} for f in
            ["Key", "Character", "Level", "WritingLevel", "Traditional", "Pinyin",
             "Meaning", "Audio", "StrokeOrder"]],
    css=tpl("style.css"),
    # Writing only: all 3,088 recognition characters appear in a vocabulary word.
    templates=[{
        "name": "Writing",
        "qfmt": tpl("char-writing-front.html"),
        "afmt": tpl("char-writing-back.html"),
    }],
)


# Anki sorts subdecks alphabetically with no manual override; the digits are the order.
SECTIONS = {"vocab": "1 Vocabulary", "writing": "2 Writing", "grammar": "3 Grammar"}

# Importing creates every deck the package names, so a root that does not match where
# the cards already live leaves an empty tree behind.
ROOT_DECK = os.environ.get("HSK_DECK_ROOT", "HSK 3.0")


def deck(section: str, level: str) -> genanki.Deck:
    offset = list(SECTIONS).index(section) * 10 + LEVELS.index(level)
    return genanki.Deck(DID_ROOT + offset,
                        f"{ROOT_DECK}::{level}::{SECTIONS[section]}")


def read_tsv(path):
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def make_pinyin(words):
    """Sentence reading: the syllabus's pinyin where the token is an HSK word, pypinyin
    for the rest. pypinyin has no erhua, rendering 哪儿 as "nǎér"."""
    import jieba
    from pypinyin import pinyin as py
    jieba.setLogLevel(60)
    # Unambiguous forms only. 为 is listed as both wèi and wéi, so a dict keyed on the
    # form would keep whichever came last; pypinyin picks by context.
    readings: dict[str, set] = collections.defaultdict(set)
    for w in words:
        readings[w["simplified"]].add(w["pinyin"])
    known = {k: next(iter(v)) for k, v in readings.items() if len(v) == 1}
    override = {}
    path = ROOT / "data/pinyin-overrides.csv"
    if path.exists():
        override = {r["token"]: r["pinyin"]
                    for r in csv.DictReader(path.open(encoding="utf-8"))}
    stats = collections.Counter()

    def read(token: str) -> str:
        if token in override:
            stats["override"] += 1
            return override[token]
        if token in known:
            stats["syllabus"] += 1
            return known[token].split("/")[0]
        stats["pypinyin"] += 1
        out = "".join(x[0] for x in py(token))
        if len(token) > 1 and token.endswith("儿") and out.endswith("ér"):
            out = out[:-2] + "r"          # 玩儿 -> wánr, not wánér
        return out

    def gen(hanzi: str) -> str:
        out = " ".join(read(t) for t in jieba.cut(hanzi))
        for a, b in (("！", "!"), (" !", "!"), ("。", "."), (" .", "."), ("？", "?"),
                     (" ?", "?"), ("，", ","), (" ,", ","), ("：", ":"), (" :", ":")):
            out = out.replace(a, b)
        return out.strip()

    return gen, stats


# "abbr. for 超級市場|超级市场[chao1 ji2 shi4 chang3]"
XREF = re.compile(r"(?:([㐀-鿿]+)\|)?([㐀-鿿]+)\[([A-Za-z0-9:, ]+)\]")
# "also pr. [di4]", "Taiwan pr. [zhi1dao5]" -- not reliably spaced, so split on digits
BARE = re.compile(r"\[((?:[A-Za-z:]+[0-9][ ,]?)+)\]")
SYLL = re.compile(r"[A-Za-z:]+[0-9]")
# "as in 除了他，誰也沒來|除了他，谁也没来"
PIPE = re.compile(r"([㐀-鿿，、。！？：；…]+)\|([㐀-鿿，、。！？：；…]+)")


def clean_xrefs(text: str) -> str:
    from pypinyin.contrib.tone_convert import to_tone

    def one(m):
        word, numbered = m.group(2), m.group(3)
        try:
            reading = "".join(to_tone(x) for x in
                              SYLL.findall(numbered.replace("u:", "v")))
        except Exception:
            return word
        return f"{word} {reading}"

    def bare(m):
        try:
            return "".join(to_tone(x) for x in
                           SYLL.findall(m.group(1).replace("u:", "v")))
        except Exception:
            return m.group(0)

    return PIPE.sub(r"\2", BARE.sub(bare, XREF.sub(one, text)))


def render_senses(meaning: str) -> str:
    parts = [html.escape(clean_xrefs(p.strip()), quote=False)
             for p in meaning.split("/") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return (f'{parts[0]}<div class="more">' + " / ".join(parts[1:]) + "</div>")


def lvl_of(exam_level_id: str) -> str:
    return exam_level_id.replace("HSK", "")


def main() -> int:
    decks, media = [], set()
    words = json.loads((BUILD / "words.json").read_text(encoding="utf-8"))

    vocab_decks = {lv: deck("vocab", lv) for lv in LEVELS}
    pos_en = {row["zh"]: row["en"] for row in
              csv.DictReader((ROOT / "data/pos-labels.csv").open(encoding="utf-8"))}

    def pos_glossed(parts: list[str]) -> str:
        out = []
        for p in parts:
            out.append(re.sub(
                r"[^、,／/（）()]+",
                lambda m: (f"{m.group(0)} <span class=en>{pos_en[m.group(0).strip()]}"
                           "</span>") if m.group(0).strip() in pos_en else m.group(0),
                p))
        return "、".join(out)

    for w in words:
        tags = [f"HSK3.0::L{w['level']}"]
        tags += [f"HSK3.0::also-L{x}" for x in w["also_levels"]]
        tags.append({
            "audio-cmn (Yue Tan)": "HSK3.0::audio::shtooka",
            "audio-cmn (homophone)": "HSK3.0::audio::homophone",
            "audio-cmn (per-character)": "HSK3.0::audio::syllables",
            "audio-cmn syllabs (Chen Wang)": "HSK3.0::audio::chen-wang",
        }.get(w["audio_source"], "HSK3.0::audio::none"))
        if w["traditional_source"].endswith("ambiguous"):
            tags.append("HSK3.0::traditional-ambiguous")
        note = genanki.Note(
            model=vocab_model,
            # new-card position = the syllabus's word index, so cards come in HSK order
            due=int(w["key"]),
            guid=genanki.guid_for("hsk3-vocab", w["entry"]),
            fields=[
                w["key"], w["level"], w["simplified"], w["homograph_index"],
                w["traditional"], w["pinyin"], w["pinyin_numbered"],
                render_senses(w["meaning"]),
                "、".join(w["pos"]), pos_glossed(w["pos"]),
                w.get("classifier", ""), w["audio"],
                " ".join(w["homophone"][:12]), " ".join(w["homograph"]),
                w["stroke_order"],
            ],
            tags=tags,
        )
        vocab_decks[w["level"]].add_note(note)
        for m in re.findall(r"\[sound:([^]]+)\]", w["audio"]):
            media.add(m)
        media.update(re.findall(r'<img [^>]*src="([^"]+)"', w["stroke_order"]))
    decks += list(vocab_decks.values())

    grammar_decks = {lv: deck("grammar", lv) for lv in LEVELS}
    labels = {row["zh"]: row["en"] for row in
              csv.DictReader((ROOT / "data/grammar-labels.csv").open(encoding="utf-8"))}

    def label_en(s: str) -> str:
        s = s.strip()
        if not s:
            return ""
        if s in labels:
            return labels[s]
        m = re.match(r"^(.*?)(\d+)$", s)          # 比较句2 -> comparative sentence 2
        if m and m.group(1) in labels:
            return f"{labels[m.group(1)]} {m.group(2)}"
        return ""

    gen_pinyin, py_stats = make_pinyin(words)
    for n, r in enumerate(read_tsv(RAW / "chelsea_grammar.tsv"), 1):
        lv = lvl_of(r["examLevelId"])
        cases = [c.strip() for c in (r.get("cases") or "").split("|") if c.strip()]
        point = (r["content"].strip() or r.get("grammarDetail", "").strip()
                 or r.get("categoryType", "").strip())
        grammar_decks[lv].add_note(genanki.Note(
            model=grammar_model,
            due=n,
            # 7 rows have empty content: keying on level+content alone collapsed them
            # to 2 guids, silently dropping 5 notes on import
            guid=genanki.guid_for("hsk3-grammar", r["examLevelId"], r["content"],
                                  r.get("grammarDetail", "")),
            fields=[
                str(n), lv, point, r.get("grammarType", ""),
                r.get("categoryType", ""), r.get("grammarDetail", ""),
                "".join(f"<li>{html.escape(c, quote=False)}</li>" for c in cases),
                "".join(
                    f"<li>{html.escape(c, quote=False)}"
                    f'<div class=pinyinSen>{html.escape(gen_pinyin(c), quote=False)}'
                    f"</div></li>"
                    for c in cases
                ),
                label_en(r.get("grammarType", "")),
                label_en(r.get("categoryType", "")),
                label_en(r.get("grammarDetail", "")),
                label_en(point),
            ],
            tags=[f"HSK3.0::grammar::L{lv}"],
        ))
    decks += list(grammar_decks.values())
    print(f"  grammar pinyin tokens: {py_stats['syllabus']} from the syllabus, "
          f"{py_stats['pypinyin']} from pypinyin, {py_stats['override']} overridden")

    mmah = {}
    if MMAH_DICT.exists():
        for line in MMAH_DICT.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            mmah[d["character"]] = d
    char_audio = json.loads((BUILD / "char-audio.json").read_text(encoding="utf-8"))
    char_info = json.loads(
        (BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    writing = {r["word"]: lvl_of(r["examLevelId"])
               for r in read_tsv(RAW / "chelsea_hanzi_writing.tsv")}
    char_decks = {lv: deck("writing", lv) for lv in LEVELS}
    seen = set()
    for n, r in enumerate(read_tsv(RAW / "chelsea_hanzi_writing.tsv"), 1):
        c = r["word"]
        if c in seen:
            continue
        seen.add(c)
        lv = lvl_of(r["examLevelId"])
        info = mmah.get(c, {})
        svg = MEDIA / f"{c}.svg"
        stroke = f'<img width="640" src="{c}.svg">' if svg.exists() else ""
        if stroke:
            media.add(f"{c}.svg")
        for m in re.findall(r"\[sound:([^]]+)\]", char_audio.get(c, "")):
            media.add(m)
        char_decks[lv].add_note(genanki.Note(
            model=char_model,
            due=n,
            guid=genanki.guid_for("hsk3-char", c),
            fields=[
                str(n), c, lv, writing.get(c, ""),
                char_info.get(c, {}).get("traditional") or c,
                " ".join(info.get("pinyin") or []),
                html.escape(clean_xrefs(char_info.get(c, {}).get("meaning")
                                        or info.get("definition") or ""),
                            quote=False).replace("/", " / "),
                char_audio.get(c, ""), stroke,
            ],
            tags=[f"HSK3.0::char::write-L{lv}"],
        ))
    decks += list(char_decks.values())

    pkg = genanki.Package(decks)
    staged = {p.name for p in MEDIA.iterdir() if p.is_file()}
    missing = sorted(media - staged)
    if missing:
        raise SystemExit(f"referenced media not staged: {missing[:5]}")
    pkg.media_files = [str(MEDIA / m) for m in sorted(media)]
    out = BUILD / "HSK-3.0-2025.apkg"
    pkg.write_to_file(str(out))

    counts = {d.name: len(d.notes) for d in decks}
    for k in sorted(counts):
        if counts[k]:
            print(f"  {k:34s} {counts[k]:5d}")
    print(f"total notes : {sum(counts.values())}")
    print(f"media files : {len(pkg.media_files)}")
    print(f"wrote {out} ({out.stat().st_size/1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

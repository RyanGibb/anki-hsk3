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
                "Homophones", "Homographs", "StrokeOrder", "Etymology",
                "Components", "Literal"]

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
             "Meaning", "Audio", "StrokeOrder", "Etymology", "Example",
             "ExampleWord"]],
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


TONE_MARK = {"1": "ˉ", "2": "ˊ", "3": "ˇ", "4": "ˋ", "5": "·"}


def tone_hint(w) -> str:
    """Which of 长 cháng and 长 zhǎng is being asked for, without giving away the
    syllable. Empty for a word that has no homograph to be confused with."""
    if not w["homograph_index"]:
        return ""
    return "".join(TONE_MARK.get(c, "") for c in w["pinyin_numbered"] if c.isdigit())


PROPER = {"ns", "nt", "nz"}   # place, organisation, other proper noun -- 上海 is not 上 + 海
SUFFIX = set("们儿子头过着")    # attaches to its stem: 人们, 点儿, 看过


def make_pinyin(words):
    """Sentence reading: the syllabus's pinyin where the token is an HSK word, pypinyin
    for the rest. pypinyin has no erhua, rendering 哪儿 as "nǎér"."""
    import jieba
    import jieba.posseg as posseg
    from pypinyin import pinyin as py
    jieba.setLogLevel(60)
    # Unambiguous forms only. 为 is listed as both wèi and wéi, so a dict keyed on the
    # form would keep whichever came last; pypinyin picks by context.
    readings: dict[str, set] = collections.defaultdict(set)
    for w in words:
        readings[w["simplified"]].add(w["pinyin"])
    known = {k: next(iter(v)) for k, v in readings.items() if len(v) == 1}
    vocab = {w["simplified"] for w in words}
    for w in vocab:
        if len(w) > 1:
            jieba.add_word(w, freq=500000)   # outranks 文书 in 中文书, 今天天气
    override = {}
    path = ROOT / "data/pinyin-overrides.csv"
    if path.exists():
        override = {r["token"]: r["pinyin"]
                    for r in csv.DictReader(path.open(encoding="utf-8"))}
    whole = vocab | set(override)   # a hand-written reading means keep the token whole
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

    def split(token: str) -> list:
        """Break up what jieba glued. The syllabus is the whitelist: 一起 and 一点儿
        are words; 一个, 本书 and 多少钱 are words standing next to each other."""
        if len(token) < 2 or token in whole or token[0] == token[1]:
            return [token]                       # 看看, and anything hand-listed
        for n in range(len(token) - 1, 0, -1):
            if token[:n] in vocab and token[n] not in SUFFIX:
                return [token[:n]] + split(token[n:])
        return [token]

    def cut(hanzi: str) -> list:
        out: list = []
        for t in posseg.cut(hanzi, HMM=False):
            out += [t.word] if t.flag in PROPER else split(t.word)
        return out

    def gen(hanzi: str) -> str:
        out = " ".join(read(t) for t in cut(hanzi))
        for a, b in (("！", "!"), (" !", "!"), ("。", "."), (" .", "."), ("？", "?"),
                     (" ?", "?"), ("，", ","), ("、", ","), (" ,", ","),
                     ("：", ":"), (" :", ":")):
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


BULLET = re.compile(r"^[*#]+\s*")


def load_etymology():
    """character -> its Wiktionary glyph origin, keyed on the TRADITIONAL form: the
    etymology of 條 says nothing about the shape of 条."""
    etym = json.loads((BUILD / "etymology.json").read_text(encoding="utf-8"))
    info = json.loads((BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    trad = {c: (v.get("traditional") or c) for c, v in info.items()}

    def paragraphs(ch: str) -> list[tuple[bool, str]]:
        e = etym.get(trad.get(ch, ch)) or etym.get(ch)
        if not e:
            return []
        out = []
        for p in e["text"].split("\n"):
            p = p.strip()
            if p:
                out.append((bool(BULLET.match(p)), BULLET.sub("", p).strip()))
        return out

    def one(ch: str, full: bool) -> str:
        ps = paragraphs(ch)
        if not ps:
            return ""
        # "Two theories:" and "a standing man with four head variants:" head the bullets
        # under them; alone they say nothing, so pull the list up into the lead.
        head, i = ps[0][1], 1
        items = []
        while i < len(ps) and ps[i][0]:
            items.append(ps[i][1])
            i += 1
        if items:
            head = head.rstrip(":") + ": " + "; ".join(items)
        head = html.escape(head, quote=False)
        if not full or i >= len(ps):
            return head
        rest = " ".join(html.escape(p, quote=False) for _, p in ps[i:])
        return f'{head}<div class="more">{rest}</div>'

    def word(simplified: str) -> str:
        out = []
        for ch in dict.fromkeys(c for c in simplified if CJK.match(c)):
            body = one(ch, full=False)
            if body:
                t = trad.get(ch, ch)
                label = ch if t == ch else f"{ch} {t}"
                out.append(f'<div class="etymItem"><b>{label}</b> {body}</div>')
        return "".join(out)

    return one, word


def main() -> int:
    decks, media = [], set()
    words = json.loads((BUILD / "words.json").read_text(encoding="utf-8"))
    etym_char, etym_word = load_etymology()

    char_meta = json.loads((BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    literal = json.loads((BUILD / "literal-meanings.json").read_text(encoding="utf-8"))

    def components(simplified: str) -> str:
        """One entry per character: what it means, then where the glyph came from.
        A one-character word gets one too -- that is where the glyph origin is most
        of what there is to say.

        Not which sense the compound uses -- Wiktionary records that for six words in
        the whole dump -- so 机 is listed as machine, opportunity and aircraft alike.
        """
        out = []
        for ch in dict.fromkeys(c for c in simplified if CJK.match(c)):
            senses = (char_meta.get(ch) or {}).get("meaning", "")
            senses = " / ".join(p.strip() for p in senses.split("/")[:3] if p.strip())
            origin = etym_char(ch, full=False)
            if not (senses or origin):
                continue
            trad = (char_meta.get(ch) or {}).get("traditional") or ch
            label = ch if trad == ch else f"{ch} {trad}"
            body = f'<b>{label}</b> {html.escape(senses, quote=False)}'
            if origin:
                body += f'<div class=origin>{origin}</div>'
            out.append(f'<div class="etymItem">{body}</div>')
        return "".join(out)

    def example_of(ch: str) -> str:
        """The earliest HSK word using this character, as a cue for which one is meant.

        Pinyin and English only: the point is to pin down the sense without showing the
        character on the side of the card where you are asked to produce it.
        """
        e = (char_meta.get(ch) or {}).get("example") or {}
        if not e:
            return ""
        return (f'<span class=exPinyin>{html.escape(e["pinyin"], quote=False)}</span>'
                f' &mdash; {html.escape(e["meaning"], quote=False)}')

    def example_word(ch: str) -> str:
        """The same example with its characters, for the side that has already shown
        you the answer."""
        e = (char_meta.get(ch) or {}).get("example") or {}
        return html.escape(e.get("word", ""), quote=False) if e else ""

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
                w["key"], w["level"], w["simplified"], tone_hint(w),
                w["traditional"], w["pinyin"], w["pinyin_numbered"],
                render_senses(w["meaning"]),
                "、".join(w["pos"]), pos_glossed(w["pos"]),
                w.get("classifier", ""), w["audio"],
                " ".join(w["homophone"][:12]), " ".join(w["homograph"]),
                w["stroke_order"], "",
                components(w["simplified"]),
                html.escape(literal.get(w["traditional"], ""), quote=False),
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

    rows = read_tsv(RAW / "chelsea_grammar.tsv")
    # 她正在学习呢1。 -- the digit indexes which 呢 the point is about, and is not part
    # of the sentence. Only strip where a point says so, or 2022年2月4日 loses its date.
    indexed = {m for r in rows
               for m in re.findall(r"[㐀-鿿][0-9]",
                                   (r["content"] or "") + (r.get("grammarDetail") or ""))}

    def unindex(s: str) -> str:
        for tok in indexed:
            s = s.replace(tok, tok[0])
        return s

    generate, py_stats = make_pinyin(words)
    checked = {}
    path = ROOT / "data/grammar-pinyin.csv"
    if path.exists():
        checked = {unindex(r["chinese"]): r["pinyin"]
                   for r in csv.DictReader(path.open(encoding="utf-8"))}

    def gen_pinyin(sentence: str) -> str:
        if sentence in checked:
            py_stats["checked"] += 1
            return checked[sentence]
        return generate(sentence)

    translated = {}
    path = ROOT / "data/grammar-translations.csv"
    if path.exists():
        translated = {r["chinese"]: r["english"]
                      for r in csv.DictReader(path.open(encoding="utf-8"))}
    for n, r in enumerate(rows, 1):
        lv = lvl_of(r["examLevelId"])
        cases = [unindex(c.strip()) for c in (r.get("cases") or "").split("|") if c.strip()]
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
                    "</div>"
                    + (f'<div class=meaningSen>'
                       f'{html.escape(translated[c], quote=False)}</div>'
                       if c in translated else "")
                    + "</li>"
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
    print(f"  grammar pinyin: {py_stats['checked']} sentences hand-checked; "
          f"the rest generated from {py_stats['syllabus']} syllabus tokens, "
          f"{py_stats['pypinyin']} pypinyin, {py_stats['override']} overridden")

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
        stroke = f'<img class=stroke src="{c}.svg">' if svg.exists() else ""
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
                render_senses(char_info.get(c, {}).get("meaning")
                              or info.get("definition") or ""),
                char_audio.get(c, ""), stroke, etym_char(c, full=True),
                example_of(c), example_word(c),
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

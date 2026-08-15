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
import shutil
import sys

import genanki

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from glyph_origin import any_about_the_glyph   # noqa: E402
from pinyin_align import ALIGNABLE, align   # noqa: E402

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
MID_SENTENCE = 1758100004
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

sentence_model = genanki.Model(
    MID_SENTENCE, "HSK 3.0 Sentence",
    fields=[{"name": f} for f in
            ["Key", "Level", "Hanzi", "HanziLinked", "Pinyin", "English",
             "Words", "Point", "PointEn", "Labels", "Audio"]],
    css=tpl("style.css"),
    templates=[{
        "name": "Sentence",
        "qfmt": tpl("sentence-front.html"),
        "afmt": tpl("sentence-back.html"),
    }],
)

char_model = genanki.Model(
    MID_CHAR, "HSK 3.0 Character",
    fields=[{"name": f} for f in
            ["Key", "Simplified", "Level", "WritingLevel", "Traditional", "Pinyin",
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


def also_read(w, by_entry={}) -> str:
    """The other way this word is read, for the card to name. The entry keys it is
    cross-referenced by -- 长1, 长2 -- mean nothing to a reader."""
    others = [by_entry[e]["pinyin"] for e in w.get("homograph", []) if e in by_entry]
    return "also " + ", ".join(others) if others else ""


def tone_hint(w, siblings={}, gloss={}) -> str:
    """Which of the words written this way is being asked for.

    The part of speech first, because it says nothing about the pronunciation: the
    tone would hand over half the answer on a card that asks for the reading. Where
    two entries share a part of speech the tone separates them instead, and where they
    share both -- 乘 rides and multiplies, a verb read chéng either way -- only their
    order in the syllabus is left.
    """
    if not w["homograph_index"]:
        return ""
    others = [o for o in siblings.get(w["simplified"], []) if o["entry"] != w["entry"]]

    def tones(x):
        return "".join(TONE_MARK.get(c, "")
                       for c in x["pinyin_numbered"] if c.isdigit())

    def part(x):
        return (x.get("pos") or [""])[0].split("、")[0].strip("（）()")

    for cue in (part, tones):
        mine = cue(w)
        if mine and all(cue(o) != mine for o in others):
            if cue is part and gloss.get(mine):
                return f'{mine} <span class=en>{gloss[mine]}</span>'
            return mine
    # 乘 rides and multiplies, both as a verb read chéng: nothing but the order in
    # the syllabus separates the two cards
    return w["homograph_index"]


PROPER = {"ns", "nt", "nz"}   # place, organisation, other proper noun -- 上海 is not 上 + 海
SPEAKER = re.compile(r"^[A-Z]：")
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
            # jieba's own dictionary has 文书 and 今天天气; the syllabus outranks it
            jieba.add_word(w, freq=500000)
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


POINTER = re.compile(r"^(variant of|old variant of|see|abbr\. for)\b", re.I)
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


def spoken(pinyin: str) -> str:
    """谁 is shéi, also shuí -- one word with a second pronunciation, not two words.
    A slash reads as though they were alternatives of equal standing."""
    parts = [x.strip() for x in pinyin.split("/") if x.strip()]
    return parts[0] + (f" (also {', '.join(parts[1:])})" if len(parts) > 1 else "")


def short_gloss(meaning: str) -> str:
    """Enough of a word's meaning to identify it, for citing it on another card.

    A first sense can be a paragraph: 除了 opens with two worked examples inside the
    parentheses, and the whole of that on 了's card says nothing about 了.
    """
    first = clean_xrefs(meaning.split("/")[0]).strip()
    first = re.sub(r"\s*\((used|as in|abbr|lit|fig)\b.*$", "", first,
                   flags=re.I).strip(" ;,")
    if len(first) > 64:
        first = first[:64].rsplit(";", 1)[0].rstrip(" ,;") + "…"
    return first


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


# Words that appear in any gloss and so distinguish nothing.
STOP = set("""a an the to of and or in on at for with by from as is are be being been
sth sb one ones s not no also used use using esp especially etc eg ie that this it its
into out up down over under about between form forms variant surname classifier""".split())


# How Wiktionary writes an account of a character's shape, as opposed to the history
# of the word it spells.
GLYPH = re.compile(r"phono-semantic|ideogrammic|pictogram|指事|象形|會意|形聲"
                   r"|simplified from|originally written|oracle bone"
                   r"|bronze (script|inscription)|seal script", re.I)


def gloss_words(text: str) -> set:
    return {w for w in re.split(r"[^a-z]+", text.lower()) if len(w) > 2 and w not in STOP}


def load_etymology():
    """character -> its Wiktionary glyph origin, keyed on the TRADITIONAL form: the
    etymology of 條 says nothing about the shape of 条."""
    etym = json.loads((BUILD / "etymology.json").read_text(encoding="utf-8"))
    info = json.loads((BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    trad = {c: (v.get("traditional") or c) for c, v in info.items()}

    # wiktextract keeps an etymology only where it sits under a sense, so a "Glyph
    # origin" section beside the Etymology sections is missing from the dump, and where
    # the dump kept a borrowing instead the slot is full but says nothing about the
    # shape. fetch-glyph-origins.py reads those sections off the page itself.
    origins = ROOT / "data/glyph-origins.csv"
    if origins.exists():
        for row in csv.DictReader(origins.open(encoding="utf-8")):
            if row["text"] and not any_about_the_glyph(etym.get(row["character"])):
                etym[row["character"]] = [{"text": row["text"], "type": row["type"],
                                           "glosses": [], "senses": 0}]

    def choose(ch: str) -> dict:
        """Which of a character's etymologies explains its shape.

        The card asks where the glyph came from, so a section that accounts for the
        graph beats one that accounts for the word: 吧 is borrowed from English "bar",
        but the character is 口 + 巴. Among sections that do explain the graph, the one
        whose glosses match the definition on the card wins -- 許 has a phono-semantic
        account and a separate one for the surname, and both are about the graph.
        """
        sections = etym.get(trad.get(ch, ch)) or etym.get(ch) or []
        if len(sections) < 2:
            return sections[0] if sections else {}
        want = gloss_words((info.get(ch) or {}).get("meaning") or "")
        return max(sections, key=lambda e: (
            bool(e.get("type")) or bool(GLYPH.search(e["text"])),
            len(want & gloss_words(" ".join(e.get("glosses") or []))),
            e.get("senses", 0), len(e["text"])))

    def paragraphs(ch: str) -> list[tuple[bool, str]]:
        e = choose(ch)
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
                label = ch if t == ch else f"{ch} ({t})"
                out.append(f'<div class="etymItem"><b>{label}</b> {body}</div>')
        return "".join(out)

    return one, word


def main() -> int:
    decks, media = [], set()
    words = json.loads((BUILD / "words.json").read_text(encoding="utf-8"))
    also_read.__defaults__ = ({w["entry"]: w for w in words},)
    groups = collections.defaultdict(list)
    for w in words:
        if w["homograph_index"]:
            groups[w["simplified"]].append(w)

    # Links go to the traditional entry, as they do everywhere else on the cards. The
    # syllabus words have an adjudicated traditional form already; CC-CEDICT covers the
    # rest, and a word in neither is linked as written.
    to_trad = {}
    for line in (RAW / "cedict_ts.u8").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\S+) (\S+) \[", line)
        if m and m.group(2) not in to_trad:
            to_trad[m.group(2)] = m.group(1)
    to_trad.update({w["simplified"]: w["traditional"] for w in words})
    char_by_reading = {}
    char_any = {}
    cedict_defs = {}
    for line in (RAW / "cedict_ts.u8").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\S+) (\S+) \[([^]]*)\] /(.*)/$", line)
        if not m:
            continue
        trad, simp, reading, body = m.groups()
        senses = [d for d in body.split("/") if not d.startswith("CL:")][:3]
        if senses and simp not in cedict_defs:
            cedict_defs[simp] = clean_xrefs(" / ".join(senses))
        if senses and len(simp) == 1:
            # several entries can share a reading, and the surname is often first:
            # 还 huán is "surname Huan" before it is "to give back". Take the fullest.
            key = (simp, reading.replace(" ", "").lower())
            defining = [d for d in senses if not POINTER.match(d)]
            entry = (trad, clean_xrefs(" / ".join(defining or senses)),
                     len(defining), len(senses))
            char_by_reading.setdefault(key, []).append(entry)
            char_any.setdefault(simp, []).append(entry)
    etym_char, etym_word = load_etymology()

    char_meta = json.loads((BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    literal = json.loads((BUILD / "literal-meanings.json").read_text(encoding="utf-8"))

    def pick_char(ch: str, reading: str, want_trad: str):
        """Among the entries sharing a reading, the one the deck already settled on.

        只 zhī is 隻 the classifier, not 秖 "grain beginning to ripen"; and where the
        traditional form does not decide it, an entry that defines the character beats
        one that only points at another -- 着 zhe is not "variant of 着".
        """
        cands = char_by_reading.get((ch, reading.lower()))
        if not cands:
            return None
        best = max(cands, key=lambda c: (c[2], c[3]))
        exact = [c for c in cands if c[0] == want_trad]
        if not exact:
            return best
        chosen = max(exact, key=lambda c: (c[2], c[3]))
        # 佔's own entry says only "variant of 占": keep the form, borrow the meaning
        return chosen if chosen[2] else (chosen[0], best[1], best[2], best[3])

    def components(simplified: str, numbered: str = "", traditional: str = "") -> str:
        """One entry per character: what it means, then where the glyph came from.
        A one-character word gets one too -- that is where the glyph origin is most
        of what there is to say.

        The reading decides the senses: 长 is "long" in 长处 and "chief" in 校长, and a
        card showing one while saying the other is simply wrong. Where the syllables do
        not line up with the characters, fall back to the character's usual senses.

        Not which sense a compound draws on -- Wiktionary records that for six words in
        the whole dump -- so 机 is listed as machine, opportunity and aircraft alike.
        """
        chars = [c for c in simplified if CJK.match(c)]
        sylls = [x for x in numbered.split(" ") if x]
        reading_of = dict(zip(chars, sylls)) if len(chars) == len(sylls) else {}
        trad_of = (dict(zip(chars, traditional))
                   if len(traditional) == len(chars) else {})
        out = []
        for ch in dict.fromkeys(chars):
            by_reading = pick_char(ch, reading_of.get(ch, ""),
                                   trad_of.get(ch, (char_meta.get(ch) or {})
                                               .get("traditional") or ch))
            if by_reading:
                trad, senses = by_reading[0], by_reading[1]
            else:
                senses = (char_meta.get(ch) or {}).get("meaning", "")
                senses = " / ".join(p.strip() for p in senses.split("/")[:3] if p.strip())
                trad = (char_meta.get(ch) or {}).get("traditional") or ch
            origin = etym_char(ch, full=False)
            if not (senses or origin):
                continue
            label = ch if trad == ch else f"{ch} ({trad})"
            body = f'<b>{label}</b> {html.escape(senses, quote=False)}'
            if origin:
                body += f'<div class=origin>{origin}</div>'
            out.append(f'<div class="etymItem">{body}</div>')
        return "".join(out)

    # The earliest word in which a character is read a given way. 地 is 地铁 as dì and
    # 慢慢地 as de, and a card teaching both readings needs an example of each.
    example_by_reading = {}
    for w in sorted(words, key=lambda w: int(w["key"])):
        simp, nums = w["simplified"], w["pinyin_numbered"].split()
        if len(simp) < 2 or len(simp) != len(nums):
            continue
        for ch, num in zip(simp, nums):
            example_by_reading.setdefault(
                (ch, num.replace("ü", "v").lower()),
                (simp, w["pinyin"], short_gloss(w["meaning"])))

    def examples_of(ch: str) -> list:
        """[(word, pinyin, meaning)], one per reading the card teaches."""
        out = []
        for _, num, _ in taught_readings.get(ch, []) or []:
            got = example_by_reading.get((ch, num))
            if got and got not in out:
                out.append(got)
        if not out:
            e = (char_meta.get(ch) or {}).get("example") or {}
            if e:
                out.append((e["word"], e["pinyin"], short_gloss(e["meaning"])))
        return out

    def example_of(ch: str) -> str:
        """The examples with no characters, for the side that asks you to write it."""
        return "".join(
            f'<div class=example>as in <span class=exPinyin>'
            f'{html.escape(p, quote=False)}</span> &mdash; '
            f'{html.escape(m, quote=False)}</div>'
            for _, p, m in examples_of(ch))

    def etym_block(ch: str) -> str:
        """The character and its origin, in the same shape the vocabulary cards use:
        the label, then the text running on from it."""
        origin = etym_char(ch, full=True)
        if not origin:
            return ""
        trad = (char_meta.get(ch) or {}).get("traditional") or ch
        label = ch if trad == ch else f"{ch} ({trad})"
        return f'<div class="etymItem"><b>{label}</b> {origin}</div>'

    def example_word(ch: str) -> str:
        """The same examples with their characters, for the side that has answered."""
        return "".join(
            f'<div class=example>as in <b>{html.escape(w, quote=False)}</b> '
            f'<span class=exPinyin>{html.escape(p, quote=False)}</span> &mdash; '
            f'{html.escape(m, quote=False)}</div>'
            for w, p, m in examples_of(ch))

    vocab_decks = {lv: deck("vocab", lv) for lv in LEVELS}
    pos_en = {row["zh"]: row["en"] for row in
              csv.DictReader((ROOT / "data/pos-labels.csv").open(encoding="utf-8"))}
    tone_hint.__defaults__ = (groups, pos_en)

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
                w["traditional"], spoken(w["pinyin"]), w["pinyin_numbered"],
                render_senses(w["meaning"]),
                "、".join(w["pos"]), pos_glossed(w["pos"]),
                w.get("classifier", ""), w["audio"],
                " ".join(w["homophone"][:12]), also_read(w),
                w["stroke_order"], "",
                components(w["simplified"], w["pinyin_numbered"], w["traditional"]),
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
    # 她正在学习呢1。 -- the digit indexes which 呢 the point is about and is not part of
    # the sentence. Two things stop it eating real numbers: the token must be one this
    # row's own point uses, since 于1 and 了2 index other points entirely, and a digit
    # followed by another digit is a number -- 成立于1950年, 引用了20则.
    indexed = {}
    for r in rows:
        key = (r["examLevelId"], r["content"], r.get("grammarDetail", ""))
        indexed[key] = set(re.findall(
            r"[㐀-鿿][0-9]", (r["content"] or "") + (r.get("grammarDetail") or "")))

    def unindex(s: str, row=None) -> str:
        toks = indexed.get(
            (row["examLevelId"], row["content"], row.get("grammarDetail", "")), ())if row \
            else set().union(*indexed.values())
        for tok in toks:
            s = re.sub(re.escape(tok) + r"(?![0-9])", tok[0], s)
        return s

    generate, py_stats = make_pinyin(words)
    checked = {}
    path = ROOT / "data/grammar-pinyin.csv"
    if path.exists():
        # answers to the source text and to the cleaned one, so a caller holding
        # either finds it
        for r in csv.DictReader(path.open(encoding="utf-8")):
            checked[r["chinese"]] = r["pinyin"]
            checked.setdefault(unindex(r["chinese"]), r["pinyin"])

    def linked(sentence: str) -> str:
        """The sentence with each word linked to its Wiktionary entry.

        Where the words are is only knowable from the checked pinyin: 里边 is one word
        because it was written as one group of syllables, and nothing in the characters
        says so. A sentence whose reading was generated rather than checked is left
        alone.
        """
        pinyin = checked.get(sentence)
        pairs = align(sentence, pinyin) if pinyin else None
        if not pairs:
            return html.escape(sentence, quote=False)
        out, word, i, n = [], "", 0, 0
        while i < len(sentence):
            if ALIGNABLE.match(sentence[i]) and n < len(pairs):
                text, _, starts = pairs[n]
                if starts and word:
                    out.append(word)
                    word = ""
                # 一下（儿） is one syllable over two characters that are not adjacent,
                # so follow the characters rather than counting them
                for want in text:
                    while i < len(sentence) and sentence[i] != want:
                        if word:
                            out.append(word)
                            word = ""
                        out.append(html.escape(sentence[i], quote=False))
                        i += 1
                    if i < len(sentence):
                        word += sentence[i]
                        i += 1
                n += 1
            else:
                if word:
                    out.append(word)
                    word = ""
                out.append(html.escape(sentence[i], quote=False))
                i += 1
        if word:
            out.append(word)
        def link(w: str) -> str:
            """A pinyin word is not always a dictionary word: 吃了 is written chīle but
            Wiktionary has no page for it, so link 吃 and leave 了 as text."""
            if not CJK.match(w[0]):
                return w
            for n in range(len(w), 0, -1):
                if w[:n] in to_trad:
                    head = to_trad[w[:n]]
                    return (f'<a href="https://en.wiktionary.org/wiki/{head}#Chinese">'
                            f'{w[:n]}</a>' + w[n:])
            return w

        return "".join(link(w) for w in out)

    def sentence_words(sentence: str) -> str:
        """Each word of the sentence with what it means, as a compound's card does for
        its characters. Words are as the checked pinyin divides them."""
        pinyin = checked.get(sentence)
        pairs = align(sentence, pinyin) if pinyin else None
        if not pairs:
            return ""
        words, word = [], ""
        for text, _, starts in pairs:
            if starts and word:
                words.append(word)
                word = ""
            word += text
        if word:
            words.append(word)
        out = []
        for w in dict.fromkeys(words):
            for n in range(len(w), 0, -1):
                gloss = cedict_defs.get(w[:n])
                if gloss:
                    trad = to_trad.get(w[:n], w[:n])
                    label = w[:n] if trad == w[:n] else f"{w[:n]} ({trad})"
                    out.append(f'<div class="etymItem"><b>{label}</b> '
                               f'{html.escape(gloss, quote=False)}</div>')
                    break
        return "".join(out)

    def gen_pinyin(sentence: str) -> str:
        if sentence in checked:
            py_stats["checked"] += 1
            return checked[sentence]
        return generate(sentence)

    translated = {}
    path = ROOT / "data/grammar-translations.csv"
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            translated[r["chinese"]] = r["english"]
            translated.setdefault(unindex(r["chinese"]), r["english"])
    tts_dir = ROOT / ".cache/tts"
    tts_index = json.loads((tts_dir / "index.json").read_text(encoding="utf-8")) \
        if (tts_dir / "index.json").exists() else {}
    for k in list(tts_index):
        tts_index.setdefault(unindex(k), tts_index[k])

    def sentence_audio(text: str) -> str:
        """No corpus records these sentences, so they are synthesised or silent."""
        got = tts_index.get(text)
        if not got or not (tts_dir / got).exists():
            return ""
        if not (MEDIA / got).exists():
            shutil.copy2(tts_dir / got, MEDIA / got)
        media.add(got)
        return f"[sound:{got}]"

    seen_sentence = set()
    n = 0
    for r in rows:
        lv = lvl_of(r["examLevelId"])
        # the source text is the key for everything looked up by sentence; the
        # cleaned one is what the card shows
        cases = [(c.strip(), unindex(c.strip(), r))
                 for c in (r.get("cases") or "").split("|") if c.strip()]
        # A：你的手机呢？ and B：我的手机在房间里。 are one exchange, and the answer
        # on its own is a stray B with nothing to answer. Keep the turns together.
        grouped, i = [], 0
        while i < len(cases):
            turn = [cases[i]]
            while (SPEAKER.match(cases[i][1]) and i + 1 < len(cases)
                   and SPEAKER.match(cases[i + 1][1])):
                turn.append(cases[i + 1])
                i += 1
            grouped.append(turn)
            i += 1
        point = (r["content"].strip() or r.get("grammarDetail", "").strip()
                 or r.get("categoryType", "").strip())
        for turn in grouped:
            raws = [x[0] for x in turn]
            lines = [x[1] for x in turn]
            key = "\n".join(lines)
            if key in seen_sentence:
                continue
            seen_sentence.add(key)
            n += 1
            join = "<br>".join
            grammar_decks[lv].add_note(genanki.Note(
                model=sentence_model,
                due=n,
                guid=genanki.guid_for("hsk3-sentence", key),
                fields=[
                    str(n), lv,
                    join(html.escape(x, quote=False) for x in lines),
                    join(linked(x) for x in lines),
                    join(html.escape(gen_pinyin(x), quote=False) for x in lines),
                    join(html.escape(translated.get(x, ""), quote=False)
                         for x in lines),
                    "".join(sentence_words(x) for x in lines),
                    point, label_en(point),
                    " &middot; ".join(
                        v + (f' <span class=en>{en}</span>' if en else "")
                        for v, en in ((r.get("grammarType", "").strip(),
                                       label_en(r.get("grammarType", ""))),
                                      (r.get("categoryType", "").strip(),
                                       label_en(r.get("categoryType", ""))),
                                      (r.get("grammarDetail", "").strip(),
                                       label_en(r.get("grammarDetail", ""))))
                        if v),
                    "".join(sentence_audio(x) for x in raws),
                ],
                tags=[f"HSK3.0::sentence::L{lv}"],
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
    # The syllabus teaches 地 twice, as de and as dì, and they do not mean the same
    # thing. A card that prints one reading and every reading's senses together says
    # 地 is "earth ... and also a particle", which is two words in one answer.
    taught_readings = {}
    variant_readings = set()
    for w in words:
        if len(w["simplified"]) != 1:
            continue
        # 熟 is entered as "shú/shóu", which is two readings; and the syllabus writes
        # nü3 where the recordings are filed under nv3
        # one entry with two readings is one word said two ways -- 熟 shú, also shóu --
        # where two entries are two words that happen to be written alike
        marks = [x for x in w["pinyin"].split("/") if x.strip()]
        if len(marks) > 1:
            variant_readings.add(w["simplified"])
        nums = [x.replace(" ", "").replace("ü", "v").lower()
                for x in w["pinyin_numbered"].split("/") if x.strip()]
        for mark, num in zip(marks, nums):
            entry = (mark, num, w["traditional"])
            if entry not in taught_readings.setdefault(w["simplified"], []):
                taught_readings[w["simplified"]].append(entry)

    def char_reading_senses(ch: str):
        """[(reading, senses)] for a character, one entry per way it is read.

        A reading heard inside a word says so: 子 zi cannot be recorded alone, so the
        card plays 包子 and tells you that is what it is playing.
        """
        out = []
        for marked, numbered, trad in taught_readings.get(ch, []):
            entry = pick_char(ch, numbered, trad)
            if entry and not entry[2]:
                # 血 xiě is entered only as "see 血 xuè"; the other reading defines it
                elsewhere = [c for c in char_any.get(ch, []) if c[2]]
                if elsewhere:
                    entry = max(elsewhere, key=lambda c: (c[2], c[3]))
            if entry:
                heard = (char_audio.get(ch) or {}).get(numbered, {}).get("in", "")
                out.append((marked + (f" (in {heard})" if heard else ""), entry[1]))
        return out
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
        voiced = char_audio.get(c) or {}
        order = [n for _, n, _ in taught_readings.get(c, [])] or list(voiced)
        clips = "".join(voiced.get(n, {}).get("sound", "") for n in order)
        for m in re.findall(r"\[sound:([^]]+)\]", clips):
            media.add(m)
        char_decks[lv].add_note(genanki.Note(
            model=char_model,
            due=n,
            guid=genanki.guid_for("hsk3-char", c),
            fields=[
                str(n), c, lv, writing.get(c, ""),
                char_info.get(c, {}).get("traditional") or c,
                (" (also ".join(r for r, _, _ in taught_readings.get(c, [])) + ")"
                 if c in variant_readings else
                 " / ".join(
                     r + (f' (in {(char_audio.get(c) or {}).get(n, {}).get("in", "")})'
                          if (char_audio.get(c) or {}).get(n, {}).get("in") else "")
                     for r, n, _ in taught_readings.get(c, [])))
                or (" ".join(info.get("pinyin") or [])
                    + next((f' (in {v["in"]})'
                            for v in (char_audio.get(c) or {}).values()
                            if v.get("in")), "")),
                ("".join(f'<div class=charSense><b>{r}</b> '
                         f'{html.escape(m, quote=False)}</div>'
                         for r, m in char_reading_senses(c))
                 if len(char_reading_senses(c)) > 1
                 else (render_senses(char_reading_senses(c)[0][1])
                       if char_reading_senses(c)
                       else render_senses(char_info.get(c, {}).get("meaning")
                                          or info.get("definition") or ""))),
                clips, stroke, etym_block(c),
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

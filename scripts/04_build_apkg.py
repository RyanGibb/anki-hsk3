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
from glyph_origin import about_the_glyph, any_about_the_glyph   # noqa: E402
from pinyin_align import ALIGNABLE, align, numbered   # noqa: E402

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
                "Homophones", "Homographs", "StrokeOrder",
                "Components", "Literal", "ExampleSentence", "PartOrigins"]

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
             "Meaning", "Audio", "StrokeOrder", "GlyphOrigin", "Example",
             "ExampleWord", "PartOrigins"]],
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


def also_read(w, by_entry={}, gloss={}) -> str:
    """The other word written this way, named by whatever tells it apart.

    Usually that is the reading: 还 is also huán. Where the syllabus splits a word
    that is read one way, as it does 本 and 打, saying "also běn" says nothing, and
    what separates them is the part of speech the front of the card already shows.
    The entry keys they are cross-referenced by -- 长1, 长2 -- mean nothing to a reader.
    """
    out = []
    for e in w.get("homograph", []):
        other = by_entry.get(e)
        if not other:
            continue
        if other["pinyin"] != w["pinyin"]:
            out.append(other["pinyin"])
            continue
        part = (other.get("pos") or [""])[0].split("、")[0].strip("（）()")
        out.append(f'{part} <span class=en>{gloss[part]}</span>' if gloss.get(part)
                   else part or other["pinyin"])
    return "also " + ", ".join(x for x in out if x) if out else ""


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

    def level(x):
        return f'HSK {x["level"]}'

    for cue in (part, tones, level):
        mine = cue(w)
        if mine and all(cue(o) != mine for o in others):
            if cue is part and gloss.get(mine):
                return f'{mine} <span class=en>{gloss[mine]}</span>'
            return mine
    # 称 weighs and names, both as a verb read chēng at the same level: nothing but
    # the order in the syllabus separates the two cards, so say that much plainly
    # rather than printing a bare digit.
    return (f'{w["homograph_index"]} <span class=en>of '
            f'{len(others) + 1}</span>')


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


# The syllabus writes a word's parts of speech as one string, and marks the ones
# taught at a later level in brackets: 对 is 形、介、（动、量）.
POS_SPLIT = re.compile(r"[、,（）()]")
POINTER = re.compile(r"^(variant of|old variant of|see|abbr\. for)\b", re.I)
# "abbr. for 超級市場|超级市场[chao1 ji2 shi4 chang3]"
XREF = re.compile(r"(?:([㐀-鿿]+)\|)?([㐀-鿿]+)\[([A-Za-z0-9:, ]+)\]")
# "also pr. [di4]", "Taiwan pr. [zhi1dao5]" -- not reliably spaced, so split on digits
BARE = re.compile(r"\[((?:[A-Za-z:]+[0-9][ ,-]?)+)\]")
SYLL = re.compile(r"[A-Za-z:]+[0-9]")
# "as in 除了他，誰也沒來|除了他，谁也没来"
PIPE = re.compile(r"([㐀-鿿，、。！？：；…]+)\|([㐀-鿿，、。！？：；…]+)")


def clean_xrefs(text: str) -> str:
    from pypinyin.contrib.tone_convert import to_tone

    def reading(numbered: str) -> str:
        """The syllables as one word, broken where a capital starts another.

        The dictionary capitalises the syllables of a proper noun, and running them
        all together gives LǐWángshì for 李王氏 and YàxìyàZhōu for 亚细亚洲, where a
        capital inside a word is exactly where a word ends. The tone goes on the
        lowercase form and the capital is put back afterwards, because a capitalised
        bare vowel defeats the converter, which hands A1 back as it found it.
        """
        out = []
        for i, syl in enumerate(SYLL.findall(numbered.replace("u:", "v"))):
            toned = to_tone(syl.lower())
            if syl[:1].isupper():
                toned = toned[:1].upper() + toned[1:]
                if i:
                    out.append(" ")
            out.append(toned)
        return "".join(out)

    def one(m):
        word, numbered = m.group(2), m.group(3)
        # A character named in a gloss is a label, and the deck labels a character
        # with both its forms: 閒 is a variant of 间 (間), which is how the row above
        # it in the same list is headed, and naming only one of the two left the two
        # rows looking like they were about different characters. A word quoted in
        # the middle of a sentence is prose, where 超级市场 (超級市場) is an interruption.
        if m.group(1) and m.group(1) != word and len(word) == 1:
            word = f"{word} ({m.group(1)})"
        try:
            return f"{word} {reading(numbered)}"
        except Exception:
            return word

    def bare(m):
        try:
            return reading(m.group(1))
        except Exception:
            return m.group(0)

    out = PIPE.sub(r"\2", BARE.sub(bare, XREF.sub(one, text)))
    # A classifier is dictionary notation rather than part of the meaning. The word
    # path lifts it into its own field; a character standing inside a word has no
    # such field, and "greens (CL:棵 kē)" is not what 菜 means.
    out = re.sub(r"\s*\(CL:[^)]*\)", "", out)
    out = re.sub(r"\s*/?\s*CL:[^/]*", "", out)
    # The deck teaches one standard: the syllabus's readings, spoken by mainland
    # voices, tested by a mainland exam. A reading from another standard is not a
    # meaning, and 结 as "(of a plant) to produce (fruit or seeds) / Taiwan pr. jié"
    # offers a card its own recording contradicts. An "also pr." is kept: that is an
    # alternative within the standard, and the reading field carries it too.
    out = re.sub(r"\s*\(Taiwan pr\.[^)]*\)", "", out)
    out = re.sub(r"\s*/?\s*Taiwan pr\.[^/]*", "", out)
    return out.strip(" /")


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


# 老李 and 小高 are how a familiar name is formed, and a surname before a title is the
# other place one appears. Nothing else in a sentence is a name.
TITLE = re.compile(r"^(老师|先生|女士|小姐|医生|经理|教授|同学|阿姨|叔叔|大夫|师傅)")


def mask_answer(text: str, ch: str) -> str:
    """Hide the character inside prose that the writing card asks you to produce.

    A gloss illustrates itself: 大 is "eldest (as in 大姐 dàjiě)" and 报 is "to register
    for (abbr. for 报名 bàomíng)". Read on the question side, that is the answer. The
    card still needs the phrase, so the character is wrapped rather than removed, and
    only the question side hides what is wrapped.
    """
    if not ch or ch not in text:
        return text
    out, i = [], 0
    for m in re.finditer(r"<[^>]+>", text):
        out.append(text[i:m.start()].replace(ch, f'<span class=mask>{ch}</span>'))
        out.append(m.group(0))
        i = m.end()
    out.append(text[i:].replace(ch, f'<span class=mask>{ch}</span>'))
    return "".join(out)


def cedict_lines():
    """The dictionary, then the patch of words it does not carry."""
    for name in ("cedict_ts.u8", "cedict_patch.u8"):
        path = RAW / name
        if path.exists():
            yield from path.read_text(encoding="utf-8").splitlines()


def char_rank(entry):
    """How much an entry says about a character standing inside a word.

    CC-CEDICT files 年 under the surname Nian before the year, as it files 都 under
    Du before dōu, and marks the difference by capitalising the reading. A character
    inside 今年 is not a name, so the capital settles it before anything else does.
    """
    _trad, _gloss, defining, senses, reading = entry
    return (not reading[:1].isupper(), defining > 0, defining, senses)


def best_entry(cands, want_trad, key, proper=False):
    """Which CC-CEDICT entry a word in a sentence means.

    Every test here is something the dictionary states about the entry rather than
    something read out of its wording: the reading it is filed under, the capital that
    marks a proper noun, the traditional form, and how much it has to say. So 那 is
    "that" and not "surname Na", 家 is 家 "home" and not 傢 "used in 家伙", and 个 read
    lightly still finds 個 the classifier rather than 個 [ge3].

    The capital cannot be read on its own, because the first word of a sentence is
    capitalised whether or not it is a name: 別 opens 别忘了 "don't forget" and 張 opens
    张老师. Whether a name is meant comes from what surrounds the word, so the caller
    decides it and this only has to agree.
    """
    def rank(e):
        trad, gloss, reading, n_senses = e
        bare = re.sub(r"[0-9]", "", reading).lower()
        want = re.sub(r"[0-9]", "", key).lower()
        return (reading.lower() == key.lower(),
                bool(key) and bare == want,
                reading[:1].isupper() == proper,
                # 只 [zhi1] is "variant of 隻" while 隻 [zhi1] is the classifier
                # itself, the same test the character glosses use.
                not POINTER.match(gloss),
                n_senses,
                # The form decides what is left, as it does for 裡 against 里.
                trad == want_trad)
    return max(cands, key=rank)[1]


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

    # A page that only says "see X" has no account of its own, and the deck shows such
    # characters as the parts of others: 餐 is phonetic 𣦼, whose shape is explained
    # under 𣦻, and 故 is semantic 攵, explained under 攴. The variant's account is used
    # and said to be the variant's. Two things have to hold. The target must give the
    # character as a form of itself, which is Wiktionary saying the two shapes are one
    # character: 攵 points at both 攴 and 文, and only 攴 claims it. And the target's
    # account must not name the character, since 繼 as "semantic 糸 + phonetic 㡭"
    # explains 繼 out of 㡭 rather than explaining 㡭.
    redirect = json.loads((BUILD / "redirects.json").read_text(encoding="utf-8")) \
        if (BUILD / "redirects.json").exists() else {}
    variant = json.loads((BUILD / "variants.json").read_text(encoding="utf-8")) \
        if (BUILD / "variants.json").exists() else {}
    # Where a part is written one way and explained under another, Wiktionary links the
    # two inside the glyph origin itself: 搬 shows 扌 and links 手. fetch-glyph-origins.py
    # reads those links off the pages, which is the only place they exist -- the dump is
    # plain text and drops them.
    # What a character says it is in its own entry, which outranks anything inferred:
    # 礻 is "Left radical form of 示", while the dump also carries a redirect from 礻 to
    # 衤, the clothing radical it merely resembles.
    radical_of = json.loads((BUILD / "radical-of.json").read_text(encoding="utf-8")) \
        if (BUILD / "radical-of.json").exists() else {}
    explained_by = {}
    links = ROOT / "data/glyph-links.csv"
    if links.exists():
        explained_by = {r["character"]: r["explained_by"]
                        for r in csv.DictReader(links.open(encoding="utf-8"))}

    def choose(ch: str) -> dict:
        """Which of a character's etymologies explains its shape.

        The card asks where the glyph came from, so a section that accounts for the
        graph beats one that accounts for the word: 吧 is borrowed from English "bar",
        but the character is 口 + 巴. Among sections that do explain the graph, the one
        whose glosses match the definition on the card wins -- 許 has a phono-semantic
        account and a separate one for the surname, and both are about the graph.
        """
        def borrow(other: str, lead: str) -> dict:
            """Another character's account, where it is an account of this one too."""
            for x in etym.get(other) or []:
                if ch not in x.get("text", "") and about_the_glyph(
                        x.get("text", ""), x.get("type", "")):
                    return dict(x, text=lead + x["text"])
            return {}

        sections = etym.get(trad.get(ch, ch)) or etym.get(ch) or []
        if not any(about_the_glyph(x.get("text", ""), x.get("type", ""))
                   for x in sections):
            taken = {}
            parent = radical_of.get(ch)
            if parent:
                taken = borrow(parent, f"Radical form of {parent}. ")
            for other in ([] if taken else
                          redirect.get(trad.get(ch, ch)) or redirect.get(ch) or []):
                if ch in (variant.get(other) or []):
                    taken = borrow(other, f"Also written {other}. ")
                if taken:
                    break
            linked = explained_by.get(ch)
            if not taken and linked:
                taken = borrow(linked, f"Explained under {linked}. ")
            if taken:
                sections = [taken]
        # A card asking where a glyph came from has no use for the history of the
        # word: 答 is "cognate with 對 … compare Tibetan", true and about the word,
        # while the graph's own account sits under 荅. Drop those outright rather
        # than ranking them last, so the fetched Glyph origin can take their place.
        sections = [x for x in sections
                    if about_the_glyph(x.get("text", ""), x.get("type", ""))]
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

    def simplification(ch: str) -> str:
        """How the character came to be written the way the card writes it.

        An account keyed on the traditional form explains a shape the card does not
        show. 禮 is 礻 over phonetic 豊, and 礼 is not that: it is an ancient variant of
        禮 that the 1956 scheme brought back. Wiktionary files that under the simplified
        character, where the deck was passing over it -- 习 is 習 with 白 and 羽 gone,
        丝 is 絲 through the variant 𢇁, 专 is 專 in cursive.
        """
        if trad.get(ch, ch) == ch:
            return ""
        for x in etym.get(ch) or []:
            if about_the_glyph(x.get("text", ""), x.get("type", "")):
                return x["text"].split("\n")[0].strip()
        return ""

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
        # wiktextract drops a glyph it cannot reproduce, leaving the sentence pointing
        # at nothing: "recorded in Shuowen as ." Close it up rather than show the hole.
        def tidy(text: str) -> str:
            return html.escape(re.sub(r"(?:,| as| like| to)?\s+\.(?=\s|$)", ".", text),
                               quote=False)

        head = tidy(head)
        # Two accounts of two shapes, so each is left whole and the simplified one comes
        # last: putting it between the lead and the rest cut 禮's account in two and
        # left "Originally written 豊, see there for more" hanging after 礼's.
        later = simplification(ch)
        block = (f'<div class="later"><b><a href="https://en.wiktionary.org/wiki/'
                 f'{ch}#Chinese">{ch}</a></b> {tidy(later)}</div>'
                 if later and later not in head else "")
        # The paragraphs after the lead wander off the shape and into the word: 礼
        # continues "Uncertain. Schuessler (2007) proposes that this is an old areal
        # etymon. Compare Tibetan ཞེ་ས", and elsewhere into Peng'im romanisations and
        # notes on where traditional characters are used. A card asking where a glyph
        # came from wants none of it, so each paragraph faces the same test the section
        # did. Of 3,376, some 800 are about the shape.
        tail = [p for _, p in ps[i:] if about_the_glyph(p, "")]
        if not full or not tail:
            return head + block
        rest = " ".join(html.escape(p, quote=False) for p in tail)
        return f'{head}<div class="more">{rest}</div>{block}'

    return one


def main() -> int:
    decks, media = [], set()
    words = json.loads((BUILD / "words.json").read_text(encoding="utf-8"))
    by_entry_all = {w["entry"]: w for w in words}
    groups = collections.defaultdict(list)
    for w in words:
        if w["homograph_index"]:
            groups[w["simplified"]].append(w)

    # Links go to the traditional entry, as they do everywhere else on the cards. The
    # syllabus words have an adjudicated traditional form already; CC-CEDICT covers the
    # rest, and a word in neither is linked as written.
    to_trad = {}
    for line in cedict_lines():
        m = re.match(r"^(\S+) (\S+) \[", line)
        if m and m.group(2) not in to_trad:
            to_trad[m.group(2)] = m.group(1)
    to_trad.update({w["simplified"]: w["traditional"] for w in words})
    # A traditional character stands in the text of a gloss as well as beside a
    # simplified one -- "variant of 间 (間)" -- and 間 unlinked next to a linked 间 read
    # as an aside rather than as the other half of the same label. Its page is its own.
    # Single characters only: a run of them is a word, and which words there are is
    # decided by the entries above, not by this.
    for trad in list(to_trad.values()):
        if len(trad) == 1:
            to_trad.setdefault(trad, trad)

    def link(w: str) -> str:
        """A pinyin word is not always a dictionary word: 吃了 is written chīle but
        Wiktionary has no page for it, so 吃 and 了 are linked in turn. Leaving the
        remainder as plain text would leave the aspect particles unlinked, and they
        are usually what the sentence is teaching."""
        if not w or not CJK.match(w[0]):
            return w
        for n in range(len(w), 0, -1):
            if w[:n] in to_trad:
                head = to_trad[w[:n]]
                return (f'<a href="https://en.wiktionary.org/wiki/{head}#Chinese">'
                        f'{w[:n]}</a>' + link(w[n:]))
        return w[0] + link(w[1:])

    def link_run(run: str) -> str:
        """Words found in the dictionary rather than in the reading, for a
        sentence whose reading cannot be aligned: 24小时 and 1GB spell their
        numbers out, so nothing lines up character to syllable. Every character
        is kept, linked or not."""
        out, i = [], 0
        while i < len(run):
            if not CJK.match(run[i]):
                out.append(html.escape(run[i], quote=False))
                i += 1
                continue
            for n in range(min(6, len(run) - i), 0, -1):
                if run[i:i + n] in to_trad:
                    out.append(link(run[i:i + n]))
                    i += n
                    break
            else:
                out.append(html.escape(run[i], quote=False))
                i += 1
        return "".join(out)

    CJK_RUN = re.compile(r"[㐀-鿿豈-﫿]+")

    def label_link(shown: str, target: str) -> str:
        """A label as a single link. 礼 (禮) is one thing to click and one page to
        arrive at, the traditional form's, which is where its account is written;
        linking only the 礼 of it left the (禮) beside the link looking like an aside."""
        return (f'<a href="https://en.wiktionary.org/wiki/{target}#Chinese">'
                f'{html.escape(shown, quote=False)}</a>')

    def link_words(fragment: str) -> str:
        """The Chinese in a rendered field, linked, leaving the field's own markup be.

        A classifier, a homophone, the 大姐 a gloss illustrates itself with -- each is a
        word the deck elsewhere teaches, and each was flat text. The fields hold HTML by
        this point, and a link's href is Chinese as well, so only what lies between the
        tags is linked.
        """
        out, at = [], 0
        for m in re.finditer(r"<[^>]+>", fragment):
            out.append(CJK_RUN.sub(lambda x: link(x.group()), fragment[at:m.start()]))
            out.append(m.group(0))
            at = m.end()
        out.append(CJK_RUN.sub(lambda x: link(x.group()), fragment[at:]))
        return "".join(out)
    char_by_reading = {}
    char_any = {}
    cedict_defs = {}
    for line in cedict_lines():
        m = re.match(r"^(\S+) (\S+) \[([^]]*)\] /(.*)/$", line)
        if not m:
            continue
        trad, simp, reading, body = m.groups()
        # A word glossed inside a sentence has to be read at a glance, so three senses
        # is enough there. A character's own card is where the character is the
        # subject, and cutting at three cut 會 exactly where the verb ends: it said
        # "can, to be likely to, to meet" and never that 会 is a meeting. 661 of the
        # 1200 characters written have more than three.
        all_senses = [d for d in body.split("/") if not d.startswith("CL:")]
        senses = all_senses[:3]
        if senses:
            # Candidates keyed by reading, the way the vocabulary path chooses, with
            # the case left alone: CC-CEDICT capitalises a proper noun's reading, so
            # 那 [Na4] "surname Na" cannot match a sentence reading nà written [na4].
            entry = (trad, clean_xrefs(" / ".join(senses)),
                     reading.replace(" ", "").replace("u:", "v"), len(senses))
            cedict_defs.setdefault((simp, entry[2].lower()), []).append(entry)
            cedict_defs.setdefault(simp, []).append(entry)
        if senses and len(simp) == 1:
            # several entries can share a reading, and the surname is often first:
            # 还 huán is "surname Huan" before it is "to give back". Take the fullest.
            key = (simp, reading.replace(" ", "").lower())
            defining = [d for d in all_senses if not POINTER.match(d)]
            entry = (trad, clean_xrefs(" / ".join(defining or all_senses)),
                     len(defining), len(all_senses), reading)
            char_by_reading.setdefault(key, []).append(entry)
            char_any.setdefault(simp, []).append(entry)
    # "see 苏州市" is a direction to look elsewhere, not a meaning, and on a sentence
    # card there is nowhere to look. Where every sense of an entry points at another
    # word, say what that word says instead.
    target_of = re.compile(r"^(?:see(?: also)?|variant of|old variant of|abbr\. for"
                           r"|used in)\s+([㐀-鿿豈-﫿]+)")
    for k, entries in cedict_defs.items():
        for i, (trad, gloss, reading, n) in enumerate(entries):
            if not POINTER.match(gloss):
                continue
            m = target_of.match(gloss)
            if not m:
                continue
            for other in cedict_defs.get(m.group(1), []):
                if not POINTER.match(other[1]):
                    entries[i] = (trad, other[1], reading, other[3])
                    break
    etym_char = load_etymology()

    char_meta = json.loads((BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    # Wiktionary names a character's parts in their traditional forms while the deck's
    # tables are keyed on the simplified: 簡 is phonetic 間, and what the deck knows and
    # can gloss is 间. Only where the deck holds that character, so 閒 is left alone --
    # the 闲 the deck teaches is 閑, a different character that merely looks like it.
    deck_form = {v["traditional"]: c for c, v in char_meta.items()
                 if v.get("traditional") and v["traditional"] != c}
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
        best = max(cands, key=char_rank)
        exact = [c for c in cands if c[0] == want_trad]
        if not exact:
            return best
        chosen = max(exact, key=char_rank)
        # 佔's own entry says only "variant of 占": keep the form, borrow the meaning
        return chosen if chosen[2] else (chosen[0], best[1], best[2], best[3], chosen[4])

    # The simplified form's account stands beside the traditional one rather than
    # inside it. Opacity composites a whole subtree, so a block nested in the origin
    # is dimmed by the origin as well as by the glosses around it, and 脑's link would
    # read a shade darker than every other link on the card.
    LATER = '<div class="later">'

    def origin_block(origin: str) -> str:
        first, sep, later = origin.partition(LATER)
        return (f'<div class=origin>{first}</div>'
                + (LATER + later if sep else ""))

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
                # A row here says what a character of the word means, in a list of
                # them. Three senses is what that is worth; the character's own card
                # is where the rest belongs.
                trad = by_reading[0]
                senses = " / ".join(by_reading[1].split(" / ")[:3])
            else:
                senses = (char_meta.get(ch) or {}).get("meaning", "")
                senses = clean_xrefs(" / ".join(
                    p.strip() for p in senses.split("/")[:3] if p.strip()))
                trad = (char_meta.get(ch) or {}).get("traditional") or ch
            origin = etym_char(ch, full=False)
            if not (senses or origin):
                continue
            label = ch if trad == ch else f"{ch} ({trad})"
            body = (f'<b>{label_link(label, trad)}</b> '
                    f'{link_words(html.escape(senses, quote=False))}')
            if origin:
                body += origin_block(origin)
            out.append(f'<div class="gloss">{body}</div>')
        return "".join(out)

    # A compound's origin names what it is built from -- 纸 is semantic 糸 plus phonetic
    # 氏 -- and those parts have origins of their own, which is where the account of the
    # character actually bottoms out. Only the first clause is read: the prose after it
    # compares the character to others, so 氏 mentions 氐, 低, 昏, 柢 and 匕, none of
    # which it is made of. The walk stops of its own accord, at a pictogram or at a part
    # Wiktionary has nothing to say about.
    shown_chars: set = set()
    # A part can be a character no ordinary font has, which is the whole reason the
    # deck carries glyphs for them: 餐 is phonetic 𣦼, up in Extension B.
    PART = "[㐀-鿿豈-﫿\U00020000-\U0003134F]"
    ROLE = re.compile(rf"\b(?:semantic|phonetic)\s+({PART})")
    # Each part is usually glossed where it is named -- 門 (“door”) + 月 (“moon”) -- so
    # the character and the plus are rarely neighbours, and a compound of three parts
    # has two pluses to read. Both sides of every one are taken.
    BEFORE = re.compile(rf"({PART})\s*(?:\([^)]*\))?\s*$")
    AFTER = re.compile(rf"\s*({PART})")

    def either_side(head: str) -> list:
        out = []
        for plus in re.finditer(r"\+", head):
            for m in (BEFORE.search(head[:plus.start()]),
                      AFTER.match(head[plus.end():])):
                if m:
                    out.append(m.group(1))
        return out

    # An account can answer by pointing at another character instead of taking this
    # one apart: 间 is 閒 with 月 replaced by 日, and what 閒 is stands one step on.
    # Followed only where the sentence says the shape changed, because a bare "variant
    # of" covers two words as readily as two shapes -- 耶 is a variant of 邪 and is not
    # built like it, 惹 is called a corruption of 了 and looks nothing like it.
    GRAPHIC = re.compile(r"replaced by|styliz|stylis|radical form|cursive"
                         r"|simplified form|abbreviat|written as|clerical", re.I)
    FROM = re.compile(rf"\bform of ({PART})|\bstyliz(?:ation|ed) of ({PART})"
                      rf"|\bof ({PART})")

    def lead(ch: str) -> str:
        text = etym_char(ch, full=True) or ""
        return re.split(r'<div class="more">', text)[0].split(". ")[0]

    def named_parts(head: str) -> list:
        """The parts an account takes the character apart into, before any pointer
        is followed. The guard below needs this much of the answer and no more, so
        following one pointer cannot set off another."""
        return ROLE.findall(head) or either_side(head)

    def made_of(ch: str) -> list:
        head = lead(ch)
        found = named_parts(head)
        if not found and GRAPHIC.search(head):
            named = FROM.search(head)
            if named:
                other = next(g for g in named.groups() if g)
                # not where the other is built out of this one, which would be a
                # circle: 把 is semantic 扌 plus phonetic 巴, so 把 is no account of
                # 巴. Being mentioned is not being built from: 閒 is 門 + 月 and adds
                # that it is the original character of 間, which is why 間 points here.
                if ch not in named_parts(lead(other)):
                    found = [other]
        return [c for c in dict.fromkeys(found) if c != ch]

    def part_origins(simplified: str) -> str:
        """The origins of the parts, and of their parts, under the word's own.

        A step at a time rather than a branch at a time, so what the word is made of
        comes before what those are made of, and a rule divides the two: 答 gives 竹
        and 合, then the 亼 and 口 that 合 is, then what those are. Read depth first it
        would open with 竹 and descend, and the parts of the word would be scattered
        down the card among the parts of its parts.
        """
        seen = {c for c in simplified if CJK.match(c)}
        shown_chars.update(seen)
        queue = [(c, 1) for ch in simplified if CJK.match(ch) for c in made_of(ch)]
        out, drawn = [], 1
        while queue:
            ch, step = queue.pop(0)
            ch = deck_form.get(ch, ch)
            if ch in seen:
                continue
            seen.add(ch)
            shown_chars.add(ch)
            queue += [(c, step + 1) for c in made_of(ch)]
            origin = etym_char(ch, full=False)
            if not origin:
                continue
            if step > drawn and out:
                out.append('<hr class=partStep>')
                drawn = step
            senses = clean_xrefs(" / ".join(
                p.strip() for p in
                (char_meta.get(ch) or {}).get("meaning", "").split("/")[:2] if p.strip()))
            trad = (char_meta.get(ch) or {}).get("traditional") or ch
            if not senses:
                # char-meanings.json covers the characters the syllabus words are made
                # of, and a part is not one: 攵 is absent from it while the dictionary
                # calls it a variant of 攴, and 扌 the hand radical.
                best = max((char_any.get(ch) or []),
                           key=lambda e: (e[2], e[3]), default=None)
                if best:
                    senses = " / ".join(best[1].split(" / ")[:2])
                    trad = best[0]
            label = ch if trad == ch else f"{ch} ({trad})"
            body = f'<b>{label_link(label, trad)}</b> '
            if senses:
                body += link_words(html.escape(senses, quote=False))
            out.append(f'<div class="gloss">{body}{origin_block(origin)}</div>')
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

    # A character met on its own before it is met in a compound needs no compound to
    # show it in use: 八 is eight from HSK 1, and "as in bāchéng -- eighty percent"
    # only points a beginner at a word six levels above. Where the compound comes
    # first the example still earns its place: 上班 is HSK 1 and 班 alone is HSK 2.
    # Kept per reading, since 地 is a word read dì and another read de.
    alone_level = {}
    for w in words:
        if len(w["simplified"]) != 1:
            continue
        key = (w["simplified"], w["pinyin_numbered"].replace("ü", "v").lower())
        if key not in alone_level or LEVELS.index(w["level"]) < alone_level[key]:
            alone_level[key] = LEVELS.index(w["level"])

    example_level = {}
    for w in words:
        if len(w["simplified"]) > 1:
            example_level.setdefault(w["simplified"], w["level"])

    def examples_of(ch: str) -> list:
        """[(word, pinyin, meaning)], one per reading the card teaches that needs one."""
        readings = taught_readings.get(ch, []) or []
        out = []
        needed = False
        for _, num, _ in readings:
            got = example_by_reading.get((ch, num))
            if not got:
                continue
            alone = alone_level.get((ch, num))
            if alone is not None and alone <= LEVELS.index(example_level.get(got[0], "7-9")):
                continue                       # met on its own first
            needed = True
            if got not in out:
                out.append(got)
        # The fallback is for a character the syllabus never lists on its own, so it
        # must not undo the rule above by supplying an example for one that it does.
        if not out and not needed and not any((ch, num) in alone_level
                                              for _, num, _ in readings):
            e = (char_meta.get(ch) or {}).get("example") or {}
            if e:
                out.append((e["word"], e["pinyin"], short_gloss(e["meaning"])))
        return out

    # Every word the deck teaches that uses the character. The card named one of them,
    # and one is not what a character is met in: 物 is 动物 and 动物园 and 礼物, and which
    # of those a reader knows it from is not the syllabus's to decide. Kept to the level
    # being written and below, because a character written at HSK 3 is not helped by a
    # word from 7-9 and the tail is long unbounded -- 不 is in 172 words and 子 in 127,
    # against 5 and 11 at or below where they are written.
    words_using: dict[str, list] = collections.defaultdict(list)
    for w in words:
        if len(w["simplified"]) > 1:
            for c in dict.fromkeys(w["simplified"]):
                words_using[c].append((LEVELS.index(w["level"]), int(w["key"]),
                                       w["simplified"], w["pinyin"],
                                       short_gloss(w["meaning"])))
    for seen_in in words_using.values():
        seen_in.sort()

    def also_seen(ch: str, level: str) -> list:
        """The rest of the words at or below this level that use the character."""
        cap = LEVELS.index(level) if level in LEVELS else len(LEVELS) - 1
        already = {w for w, _p, _m in examples_of(ch)}
        return [(w, p, m) for lvl, _key, w, p, m in words_using.get(ch, [])
                if lvl <= cap and w not in already]

    def example_of(ch: str, level: str = "") -> str:
        """The examples with no characters, for the side that asks you to write it.

        The same words the answer gives, so the two sides say the same thing about
        where the character is met; only the characters are held back, since writing
        one of them is what is being asked.
        """
        return "".join(
            f'<div class=example>as in <span class=exPinyin>'
            f'{html.escape(p, quote=False)}</span> &mdash; '
            f'{html.escape(m, quote=False)}</div>'
            for _, p, m in examples_of(ch) + (also_seen(ch, level) if level else []))

    def etym_block(ch: str) -> str:
        """The character and its origin, in the same shape the vocabulary cards use:
        the label, then the text running on from it."""
        origin = etym_char(ch, full=True)
        if not origin:
            return ""
        trad = (char_meta.get(ch) or {}).get("traditional") or ch
        label = ch if trad == ch else f"{ch} ({trad})"
        return f'<div class="gloss"><b>{label_link(label, trad)}</b> {origin}</div>'

    def example_word(ch: str, level: str = "") -> str:
        """The same examples with their characters, for the side that has answered.

        Every word is written out the same way, one to a line. A list of bare words
        after them -- also in 动物园 · 礼物 -- reads as an afterthought and asks the
        reader to hold three things at once; the same three lines read as three.
        """
        return "".join(
            f'<div class=example>as in <b>{link_words(html.escape(w, quote=False))}</b> '
            f'<span class=exPinyin>{html.escape(p, quote=False)}</span> &mdash; '
            f'{html.escape(m, quote=False)}</div>'
            for w, p, m in examples_of(ch) + (also_seen(ch, level) if level else []))

    vocab_decks = {lv: deck("vocab", lv) for lv in LEVELS}
    pos_en = {row["zh"]: row["en"] for row in
              csv.DictReader((ROOT / "data/pos-labels.csv").open(encoding="utf-8"))}
    tone_hint.__defaults__ = (groups, pos_en)
    also_read.__defaults__ = (by_entry_all, pos_en)

    def pos_label(p: str) -> str:
        en = pos_en.get(p, "")
        return f'{p}{f" <span class=en>{en}</span>" if en else ""}'

    def sense_blocks(w: dict) -> str:
        """The meaning under the part of speech it belongs to.

        可以 is 动、形 and means "can, may, possible, able to, not bad, pretty good";
        which two of those are the adjective is the thing the card was not saying.
        Every card is headed this way, divided or not, so a word that is only a verb
        reads the same as one that is a verb and a noun.

        A part of speech the syllabus does not give the word is still worth knowing
        and is not what is being taught: 比 is a preposition and a verb to the
        syllabus, and the dictionary also calls it a noun, "ratio". Those are set
        quietly under the rest.
        """
        def senses(m: str) -> str:
            return link_words(" / ".join(
                html.escape(clean_xrefs(x.strip()), quote=False)
                for x in m.split("/") if x.strip()))

        split = w.get("meaning_by_pos") or []
        if not split:
            head = pos_glossed(w["pos"])
            body = link_words(render_senses(w["meaning"]))
            return f'<div class=charSense>{head} {body}</div>' if head else body
        declared = {p for group in w["pos"] for p in POS_SPLIT.split(group) if p}
        # 动荡 is a verb and an adjective to the syllabus, and the dictionary glosses
        # it only as "unrest, turmoil, upheaval" -- nouns, every one. Setting the whole
        # meaning aside as an afterthought would leave the card with nothing to say at
        # full size, so where nothing is declared nothing is set aside.
        if not any(p in declared for p, _ in split):
            declared = {p for p, _ in split}
        # A part of speech the syllabus gives the word and the dictionary glosses no
        # sense under still says something: 动荡 is a verb and an adjective, and that
        # its four glosses are all nouns does not make it less so. The heading stands
        # on its own and the meaning above it is the meaning.
        bare = [p for group in w["pos"] for p in POS_SPLIT.split(group)
                if p and p not in {q for q, _ in split}]
        return "".join(
            f'<div class="charSense{"" if p in declared else " beyond"}">'
            f'{"" if p in declared else "also "}{pos_label(p)} {senses(m)}</div>'
            for p, m in split) + "".join(
            f'<div class=charSense>{pos_label(p)}</div>' for p in bare)

    def pos_glossed(parts: list[str]) -> str:
        out = []
        for p in parts:
            out.append(re.sub(
                r"[^、,／/（）()]+",
                lambda m: (f"{m.group(0)} <span class=en>{pos_en[m.group(0).strip()]}"
                           "</span>") if m.group(0).strip() in pos_en else m.group(0),
                p))
        return "、".join(out)

    # The Key is what the browser sorts on, and one that starts again at 1 for each
    # kind of note interleaves three sequences into no order at all: three notes claim
    # 1, three claim 2. It is numbered once across the deck instead -- every
    # vocabulary note, then every writing note, then every sentence, each in level
    # order. Where a note sits within its own section is unchanged; only the number is.
    #
    # Not the position a card is introduced at, which stays the syllabus's own index
    # for a word and the source order for the rest. What the browser lists and what
    # the scheduler deals are different questions.
    SECTION = {"vocab": 0, "writing": 1, "grammar": 2}
    keyed = []

    def number(section: str, level: str, note) -> None:
        keyed.append((SECTION[section], LEVELS.index(level), len(keyed), note))

    vocab_notes = []
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
                sense_blocks(w),
                # Every meaning is headed by its part of speech now, so the line that
                # used to carry it below said it a second time.
                "、".join(w["pos"]), "",
                link_words(w.get("classifier", "")), w["audio"],
                link_words(" ".join(w["homophone"][:12])), also_read(w),
                w["stroke_order"],
                components(w["simplified"], w["pinyin_numbered"], w["traditional"]),
                html.escape(literal.get(w["traditional"], ""), quote=False),
                # filled in once the sentences have been built, below
                "",
                part_origins(w["simplified"]),
            ],
            tags=tags,
        )
        vocab_notes.append((w, note))
        number("vocab", w["level"], note)
        vocab_decks[w["level"]].add_note(note)
        for m in re.findall(r"\[sound:([^]]+)\]", w["audio"]):
            media.add(m)
        media.update(re.findall(r'<img [^>]*src="([^"]+)"', w["stroke_order"]))
    decks += list(vocab_decks.values())

    grammar_decks = {lv: deck("grammar", lv) for lv in LEVELS}
    labels = {row["zh"]: row["en"] for row in
              csv.DictReader((ROOT / "data/grammar-labels.csv").open(encoding="utf-8"))}

    # The point itself, in English, from data/grammar-point-translations.csv. A point
    # that only names the items it teaches -- 小—、第—, 按理、按说、百般 -- has no entry
    # and needs none: the sentence shows the item.
    point_en_of = {}
    pt = ROOT / "data/grammar-point-translations.csv"
    if pt.exists():
        point_en_of = {r["chinese"]: r["english"]
                       for r in csv.DictReader(pt.open(encoding="utf-8"))}

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

    rows = read_tsv(RAW / "official_grammar.tsv")
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

    def pieces(sentence: str) -> list:
        """The sentence in the words its reading was written in, each with the
        syllables it was read as, punctuation between them.

        Where the words are is only knowable from the checked pinyin: 里边 is one word
        because it was written as one group of syllables, and nothing in the characters
        says so. A sentence whose reading was generated rather than checked has no
        words to give.
        """
        pinyin = checked.get(sentence)
        pairs = align(sentence, pinyin) if pinyin else None
        if not pairs:
            return []
        out, word, read, i, n = [], "", [], 0, 0

        def flush():
            nonlocal word, read
            if word:
                out.append((word, read))
            word, read = "", []

        while i < len(sentence):
            if ALIGNABLE.match(sentence[i]) and n < len(pairs):
                text, syl, starts = pairs[n]
                if starts:
                    flush()
                # 一下（儿） is one syllable over two characters that are not adjacent,
                # so follow the characters rather than counting them
                for want in text:
                    while i < len(sentence) and sentence[i] != want:
                        flush()
                        out.append((html.escape(sentence[i], quote=False), []))
                        i += 1
                    if i < len(sentence):
                        word += sentence[i]
                        i += 1
                read.append(syl)
                n += 1
            else:
                flush()
                out.append((html.escape(sentence[i], quote=False), []))
                i += 1
        flush()
        return out

    def linked(sentence: str) -> str:
        """The sentence with each word linked to its Wiktionary entry. One whose
        reading was generated rather than checked is left alone."""
        got = pieces(sentence)
        if not got:
            return link_run(sentence)
        return "".join(link(text) for text, _ in got)

    # Words whose entry no rule picks correctly: 京 is Beijing and not the surname
    # Jing, 春节 is a festival and not 春 the surname, 经医生 is "after the doctor" and
    # not a name before a title. 05_verify fails if one stops matching a sentence.
    word_gloss = {}
    fixes = ROOT / "data/sentence-word-glosses.csv"
    if fixes.exists():
        for row in csv.DictReader(fixes.open(encoding="utf-8")):
            word_gloss[(row["chinese"], row["word"])] = row["meaning"]

    def longest_match(run: str) -> list:
        """Split a run of characters on the longest words the dictionary knows."""
        out, i = [], 0
        while i < len(run):
            for n in range(min(6, len(run) - i), 0, -1):
                if cedict_defs.get(run[i:i + n]):
                    out.append(run[i:i + n])
                    i += n
                    break
            else:
                i += 1
        return out

    def gloss_word(sentence: str, w: str, read=(), proper=False) -> str:
        """One entry per word, and per leftover piece of it: 读了 and 人们 are one word
        to the reading and no word to the dictionary, and 了 and 们 are usually the
        point of the sentence."""
        out, i = [], 0
        while i < len(w):
            for n in range(len(w) - i, 0, -1):
                piece = w[i:i + n]
                # A syllable per character means each piece has a reading of its own;
                # otherwise only the whole word does.
                if len(read) == len(w):
                    key = "".join(numbered(x) for x in read[i:i + n])
                elif read and piece == w:
                    key = "".join(numbered(x) for x in read)
                else:
                    key = ""
                cands = (cedict_defs.get((piece, key.lower())) if key else None) \
                    or cedict_defs.get(piece)
                if not cands:
                    continue
                gloss = word_gloss.get((sentence, piece)) \
                    or best_entry(cands, to_trad.get(piece), key, proper and i == 0)
                trad = to_trad.get(piece, piece)
                label = piece if trad == piece else f"{piece} ({trad})"
                out.append(f'<div class="gloss"><b>{label_link(label, trad)}</b> '
                           f'{link_words(html.escape(gloss, quote=False))}</div>')
                i += n
                break
            else:
                i += 1
        return "".join(out)

    def teaches(point: str, sentence: str) -> str:
        """Which item of the point this sentence is an example of.

        The items are listed in the point itself. 打开 turns up as 打不开 and 看见 as
        看得见, so a two-character item is looked for with an infix as well. A sentence
        matching none of them is treated as its own item, so nothing is set aside on a
        guess.
        """
        items = []
        for part in re.split(r"[、，/／]", point):
            w = re.sub(r"[0-9]+$", "", part.strip("—-（）()… ")).strip()
            if w and CJK.search(w):
                items.append(w)
        if len(items) < 2:
            return ""
        hit = [i for i in items if i in sentence
               or (len(i) == 2
                   and re.search(re.escape(i[0]) + r"[得不了一两个]{1,2}"
                                 + re.escape(i[1]), sentence))]
        return max(hit, key=len) if hit else sentence

    def sentence_words(sentence: str) -> str:
        """Each word of the sentence with what it means, as a compound's card does for
        its characters. Words are as the checked pinyin divides them."""
        pinyin = checked.get(sentence)
        pairs = align(sentence, pinyin) if pinyin else None
        if not pairs:
            # 24小时, 1GB, 10% -- the reading spells the number out, so nothing lines
            # up character to syllable. The words are still worth glossing, so they
            # are found in the dictionary instead of in the reading, and chosen
            # without one.
            words = [(w, ()) for run in re.findall(r"[㐀-鿿]+", sentence)
                     for w in longest_match(run)]
            return "".join(gloss_word(sentence, w, read) for w, read in
                           dict.fromkeys(words))
        words, word, reading = [], "", []
        for text, syllable, starts in pairs:
            if starts and word:
                words.append((word, tuple(reading)))
                word, reading = "", []
            word += text
            if syllable:
                reading.append(syllable)
        if word:
            words.append((word, tuple(reading)))
        out = []
        # Found in the sentence rather than counted from the words, which leaves out
        # the punctuation: one comma is enough to make 老师和同学 look like 老 + 和.
        at, cursor = {}, 0
        for w, _reading in words:
            i = sentence.find(w, cursor)
            if i < 0:
                i = cursor
            at.setdefault(w, i)
            cursor = i + len(w)
        for w, read in dict.fromkeys(words):
            here = at.get(w, 0)
            key0 = "".join(numbered(x) for x in read)
            # A card can hold more than one sentence, and the word after a full stop
            # or an opening quote is capitalised for the same reason the first one is.
            prev = sentence[:here].rstrip()
            here = 0 if not prev or prev[-1] in "。！？!?：:；;“”\"'‘’（）()《》【】" else here
            # The checked reading capitalises a name wherever it stands -- Zhāng lǎoshī,
            # Lǎo Zhāng -- so the capital settles it, except at the start of a sentence
            # where every word is capitalised anyway. There, a following title is what
            # distinguishes 王老师 from 别忘了.
            proper = (key0[:1].isupper() if here else
                      bool(TITLE.match(sentence[here + len(w):])))
            # 读了 and 人们 are one word to the reading and no word to the dictionary.
            # Glossing the longest piece it knows and stopping would leave 了 and 们
            # unexplained, and those are usually the point of the sentence, so what is
            # left over is glossed in turn.
            out.append(gloss_word(sentence, w, read, proper))
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
    # No mapping from the source text's clip to the cleaned sentence: the syllabus
    # writes 呢1 to tell two entries apart, and a clip synthesised from that reads the
    # digit out loud. A sentence is voiced from what the card shows or not at all.

    # A syllabus sentence sometimes displays language rather than using it: 在/正在
    # offers two words for one slot, （钱） marks a word that may be left out, and
    # （转折） names the point rather than belonging to the sentence. A voice reads all
    # of it -- 同学们在/正在上课 was spoken 同学们在正在上课 -- so speech is asked for what
    # a speaker would say. Dropping the brackets is enough for most; where a word has
    # to be chosen or a label dropped, data/sentence-speech.csv says what to say.
    said = {r["chinese"]: r["spoken"] for r in csv.DictReader(
        (ROOT / "data/sentence-speech.csv").open(encoding="utf-8"))}

    def as_said(text: str) -> str:
        return said.get(text) or text.replace("（", "").replace("）", "")

    def sentence_audio(text: str) -> str:
        """No corpus records these sentences, so they are synthesised or silent."""
        got = tts_index.get(as_said(text))
        if not got or not (tts_dir / got).exists():
            return ""
        if not (MEDIA / got).exists():
            shutil.copy2(tts_dir / got, MEDIA / got)
        media.add(got)
        return f"[sound:{got}]"

    seen_sentence = set()
    wanted_audio = []
    # The sentences a vocabulary card may borrow, in the order the deck teaches them.
    # An exchange is two turns that answer each other, and half of one on a vocabulary
    # card is a reply to nothing, so only a sentence that stands alone is taken.
    usable = []
    # A point that lists several items -- 按理、按说、百般 -- is taught one item at a
    # time, so two sentences under it are only saying the same thing when they use the
    # same item. The first sentence for an item carries it; the rest are extra
    # practice, tagged so they can be set aside without being thrown away.
    taught = set()
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
            lines = [x[1] for x in turn]
            key = "\n".join(lines)
            if key in seen_sentence:
                continue
            seen_sentence.add(key)
            if len(lines) == 1:
                usable.append(lines[0])
            wanted_audio.extend(as_said(x) for x in lines)
            n += 1
            unit = (point, teaches(point, "".join(lines)))
            extra = unit in taught
            taught.add(unit)
            join = "<br>".join
            sentence_note = genanki.Note(
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
                    point, point_en_of.get(point) or label_en(point),
                    " &middot; ".join(
                        v + (f' <span class=en>{en}</span>' if en else "")
                        for v, en in ((r.get("grammarType", "").strip(),
                                       label_en(r.get("grammarType", ""))),
                                      (r.get("categoryType", "").strip(),
                                       label_en(r.get("categoryType", ""))),
                                      (r.get("grammarDetail", "").strip(),
                                       label_en(r.get("grammarDetail", ""))))
                        if v),
                    # Keyed on what the card shows, like every other field here. The
                    # source text carries the syllabus's disambiguation digit, and a
                    # clip made from 呢1 reads the digit out loud.
                    "".join(sentence_audio(x) for x in lines),
                ],
                tags=[f"HSK3.0::sentence::L{lv}"]
                + (["HSK3.0::sentence::extra"] if extra else []),
            )
            number("grammar", lv, sentence_note)
            grammar_decks[lv].add_note(sentence_note)
    decks += list(grammar_decks.values())

    # A word that names a thing is answered by its meaning; one that does a job is not.
    # 得 as "structural particle" is a category, and 我尝了尝，觉得很好吃 is the thing
    # itself. So a vocabulary card carries a sentence that uses the word, taken from
    # the sentences the deck already teaches -- the earliest one, which is the one it
    # will have met first.
    #
    # The word has to be a word of the sentence and not a run of characters inside one:
    # 得 occurs in 觉得, where it is no more an example of 得 than 的 is of 目. Which is
    # why the reading decides it, being the only thing that says where the words are.
    def spoken_as(read) -> str:
        return "".join(numbered(x) for x in read).replace("ü", "v").lower()

    # Some of what the syllabus files as a case is a pair of phrases rather than a
    # sentence -- 次 opens with 去一次、看一次 -- and a phrase shows the word without
    # showing it doing anything. A whole sentence is preferred wherever there is one,
    # and the order among those is untouched.
    ENDS = re.compile(r"[。？！]\s*$")
    example_sentence = {}
    for text in sorted(usable, key=lambda s: not ENDS.search(s)):
        english = translated.get(text)
        reading = checked.get(text)
        if not (english and reading):
            continue
        shown = (f'<div class=sentence>{linked(text)}</div>'
                 f'<div class="pinyin ofSentence">'
                 f'{html.escape(reading, quote=False)}</div>'
                 f'<div class="english ofSentence">'
                 f'{html.escape(english, quote=False)}</div>')
        for word, read in pieces(text):
            if not (read and CJK.match(word[0])):
                continue
            keys = [(word, spoken_as(read)), (word, "")]
            for k in keys:
                example_sentence.setdefault(k, shown)

    at = VOCAB_FIELDS.index("ExampleSentence")
    for w, note in vocab_notes:
        # 地 is taught twice, as de and as dì, and a sentence using one is no example
        # of the other. Only where no sentence uses the reading the card teaches does
        # the word alone decide it.
        said_as = w["pinyin_numbered"].replace(" ", "").replace("ü", "v").lower()
        note.fields[at] = (example_sentence.get((w["simplified"], said_as))
                           or example_sentence.get((w["simplified"], "")) or "")
    print(f"  example sentences: {sum(1 for _, n in vocab_notes if n.fields[at])}"
          f"/{len(vocab_notes)} words")

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
    taught_entries = {}
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
        taught_entries.setdefault(w["simplified"], []).append(w)

    def by_part_of_speech(ch: str, numbered: str) -> list:
        """[(part of speech, senses)] where a reading is taught as more than one.

        The dictionary gives 會 one entry of six senses. The syllabus gives it two,
        會1 a verb at level 1 and 會2 a noun at level 3, and data/homograph-glosses.csv
        divides the six between them -- so which three are the noun is already written
        down, and the writing card can say it. Where a reading is taught once there is
        nothing to divide and the dictionary's own entry stands.
        """
        blocks = []
        for w in taught_entries.get(ch, []):
            if w["pinyin_numbered"].replace(" ", "").replace("ü", "v").lower() != numbered:
                continue
            if not w["pos"]:
                continue
            declared = {p for group in w["pos"] for p in POS_SPLIT.split(group) if p}
            split = w.get("meaning_by_pos") or [("、".join(w["pos"]), w["meaning"])]
            # where nothing the dictionary gives is a part of speech the syllabus
            # names, nothing is set aside -- see sense_blocks
            if not any(p in declared for p, _ in split):
                declared = {p for p, _ in split}
            blocks += [(p, m, p in declared) for p, m in split]
        # The dictionary's own glosses arrive cleaned and spaced about their slashes;
        # these come from the word list, where 之 still reads "literary equivalent of
        # 的[de5]" and 会 reads "to know how to/to be likely to".
        return [(p, " / ".join(x.strip() for x in clean_xrefs(m).split("/") if x.strip()), d)
                for p, m, d in blocks] if len(blocks) > 1 else []

    def char_reading_senses(ch: str):
        """[(label, senses, bold, declared)] for a character, one block per way it is
        taught. Not declared means the dictionary gives the character a part of speech
        the syllabus does not: 比 is a verb and a preposition to the syllabus, and a
        noun, "ratio", to the dictionary.

        A reading heard inside a word says so: 子 zi cannot be recorded alone, so the
        card plays 包子 and tells you that is what it is playing.
        """
        out = []
        readings = taught_readings.get(ch, [])
        for marked, numbered, trad in readings:
            heard = (char_audio.get(ch) or {}).get(numbered, {}).get("in", "")
            said = marked + (f" (in {heard})" if heard else "")
            split = by_part_of_speech(ch, numbered)
            if split:
                out += [(f"{said} {pos_glossed([p])}" if len(readings) > 1
                         else pos_glossed([p]), m, False, d) for p, m, d in split]
                continue
            entry = pick_char(ch, numbered, trad)
            if entry and not entry[2]:
                # 血 xiě is entered only as "see 血 xuè"; the other reading defines it
                elsewhere = [c for c in char_any.get(ch, []) if c[2]]
                if elsewhere:
                    entry = max(elsewhere, key=char_rank)
            if entry:
                out.append((said, entry[1], True, True))
        return out

    def char_meaning(ch: str, info: dict) -> str:
        """A reading is a label to be picked out; a part of speech is a glyph, and
        bold would thicken strokes the card is teaching."""
        blocks = char_reading_senses(ch)
        # 名 is a noun and is also a character the card asks you to write, so a
        # heading naming its part of speech would answer the question. Such a card
        # gives its senses unheaded. A reading is never the character, so a card split
        # by reading is unaffected.
        if any(ch in lab for lab, *_ in blocks):
            blocks = [("", " / ".join(m for _, m, *_ in blocks), False, True)]
        if len(blocks) > 1:
            # These are the dictionary's full lists, and 掉 has seventeen. A block
            # leads with its first sense and carries the rest quietly, as a card with
            # one block always has. A part of speech the syllabus does not give the
            # character is set quieter still, as it is on a vocabulary card.
            return "".join(
                f'<div class="charSense{"" if declared else " beyond"}">'
                f'{"" if declared else "also "}{f"<b>{lab}</b>" if bold else lab} '
                f'{render_senses(m)}</div>' for lab, m, bold, declared in blocks)
        # One block is still headed by its part of speech, as a vocabulary card is:
        # 年 is a noun and a classifier whether or not the dictionary divides its one
        # sense between them. Only where the syllabus lists the character on its own,
        # and only once -- where it lists it twice the blocks above say it instead.
        entries = taught_entries.get(ch, [])
        head = pos_glossed(entries[0]["pos"]) if len(entries) == 1 else ""
        if ch in head:
            head = ""
        body = (render_senses(blocks[0][1]) if blocks else
                render_senses(char_info.get(ch, {}).get("meaning")
                              or info.get("definition") or ""))
        return f'<div class=charSense>{head} {body}</div>' if head and body else body

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
        char_note = genanki.Note(
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
                mask_answer(char_meaning(c, info), c),
                clips, stroke, etym_block(c),
                mask_answer(example_of(c, lv), c),
                example_word(c, lv),
                part_origins(c),
            ],
            tags=[f"HSK3.0::char::write-L{lv}"],
        )
        number("writing", lv, char_note)
        char_decks[lv].add_note(char_note)
    decks += list(char_decks.values())

    for i, (*_, note) in enumerate(sorted(keyed, key=lambda x: x[:3]), 1):
        note.fields[0] = str(i)
    print(f"keys: 1 to {len(keyed)} across the deck")

    pkg = genanki.Package(decks)
    # The cards name glyphs no ordinary font carries -- 亼 and the rest of what a
    # character is built from -- so the deck brings them itself, cut down to the ones
    # it uses by scripts/make-font-subset.py. The leading underscore is how a media
    # file says a template refers to it rather than a note.
    for font in sorted((ROOT / "data/fonts").glob("_*.woff2")):
        shutil.copy2(font, MEDIA / font.name)
        media.add(font.name)

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

    # What tts.py should voice, in the words the cards use. Taking the list from the
    # build is what keeps the two in step: a sentence voiced from the syllabus's
    # source text says the disambiguation digit in 呢1 out loud.
    silent = [x for x in dict.fromkeys(wanted_audio) if not sentence_audio(x)]
    (BUILD / "tts-wanted.json").write_text(
        json.dumps({"sentences": list(dict.fromkeys(wanted_audio)),
                    "silent": silent}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"speech wanted: {len(set(wanted_audio))} sentences, {len(silent)} unvoiced")
    # Every character a card shows, the parts among them. fetch-glyph-origins.py looks
    # up what has no origin, and a part reached only by the walk is not in any word
    # list, so nothing else can tell it they are wanted.
    (BUILD / "shown-chars.json").write_text(
        json.dumps(sorted(shown_chars), ensure_ascii=False), encoding="utf-8")
    print(f"characters shown: {len(shown_chars)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

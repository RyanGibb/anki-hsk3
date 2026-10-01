"""The recognition cards, and the parts of speech that head their
meanings."""
import collections
import csv
import html
import json
import re

import genanki

from syllabus import LEVELS, POS_SPLIT
from deck.paths import BUILD, ROOT
from deck.notation import TONE_MARK, clean_xrefs, render_senses, spoken, ways_read
from deck.models import deck, vocab_model
from word import Word


def also_read(w: Word, by_entry: dict[str, Word], pos: "PartsOfSpeech") -> str:
    """The other word written this way, named by whatever tells it apart, and what it
    means.

    Usually the reading tells them apart: 还 is also huán. Where the syllabus splits a
    word that is read one way, as it does 本 and 打, saying "also běn" says nothing, and
    what separates them is the part of speech the front of the card already shows. The
    entry keys they are cross-referenced by -- 长1, 长2 -- mean nothing to a reader.

    Naming the other card without saying what is on it leaves the reader to take it on
    trust that 花 is a noun somewhere else. The meaning comes whole: this is the only
    place the deck says anything about that card, and half a gloss is worse than none.
    """
    rows = []
    for e in w.get("homograph", []):
        other = by_entry.get(e)
        if not other:
            continue
        told = other["pinyin"] if other["pinyin"] != w["pinyin"] else ""
        split = other.get("meaning_by_pos") or []
        taught = pos.taught(other.get("pos") or [], split) if split else set()
        # Every block of the other card, the taught ones first, since the card being
        # read is where they are being told about it: 本2 files root and origin under
        # a noun the syllabus never names, and keeping only the taught blocks left
        # "root" nowhere on the classifier's card at all.
        parts = ([(pos.label(p), m) for p, m in split if p in taught]
                 + [(pos.label(p), m) for p, m in split if p not in taught]) \
            or [(pos.glossed(other.get("pos") or []), other["meaning"])]
        for i, (head, m) in enumerate(parts):
            rows.append(f'<div class=alsoWritten>'
                        f'<span>{f"also {told}".strip() if i == 0 else ""}</span>'
                        f'<span>&mdash; {f"{head} " if head else ""}'
                        f'{pos.senses(m)}</span></div>')
    return "".join(rows)


def tone_hint(w: Word, siblings: dict[str, list[Word]], gloss: dict) -> str:
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


class PartsOfSpeech:
    """The syllabus's own labels, and the meaning set out under them.

    可以 is 动、形 and means "can, may, possible, able to, not bad, pretty good"; which
    two of those are the adjective is what the card was not saying. Every meaning is
    headed this way, divided or not, so a word that is only a verb reads like one that
    is a verb and a noun.
    """

    def __init__(self, wiki):
        self.wiki = wiki
        self.en = {row["zh"]: row["en"] for row in
                   csv.DictReader((ROOT / "data/pos-labels.csv").open(encoding="utf-8"))}

    def label(self, p: str) -> str:
        en = self.en.get(p, "")
        return f'{p}{f" <span class=en>{en}</span>" if en else ""}'

    def glossed(self, parts: list[str], w: Word | None = None) -> str:
        """The labels with their English, and given the word they belong to, the level
        each arrives at."""
        def one(m):
            p = m.group(0).strip()
            if p not in self.en:
                return m.group(0)
            return (f"{m.group(0)} <span class=en>{self.en[p]}</span>"
                    + (self.at_level(self.level_of(w, p), True) if w else ""))
        return "、".join(re.sub(r"[^、,／/（）()]+", one, p) for p in parts)

    @staticmethod
    def level_of(w: Word, p: str) -> str:
        """The level the syllabus teaches the word as this part of speech: 半 is one
        entry, a numeral at HSK 1 and an adverb at HSK 4. A part of speech the word list
        does not give it takes the entry's own level."""
        return (w.get("pos_levels") or {}).get(p) or w["level"]

    @staticmethod
    def named(pos: list[str]) -> list:
        """The parts of speech the syllabus gives a word, its brackets undone and its
        order kept: 对 is written 形、介、（动、量） and is all four, in that order."""
        return [p for group in pos for p in POS_SPLIT.split(group) if p]

    @classmethod
    def taught(cls, pos: list[str], split) -> set:
        """Which of the labels in a division are ones the syllabus teaches the word as.

        动荡 is a verb and an adjective to the syllabus, and the dictionary glosses it
        only as "unrest, turmoil, upheaval" -- nouns, every one. Setting the whole
        meaning aside as an afterthought would leave the card with nothing to say at
        full size, so where nothing is taught nothing is set aside.
        """
        named = set(cls.named(pos))
        return named if any(p in named for p, *_ in split) else {p for p, *_ in split}

    def divided(self, entries: list[Word], numbered: str) -> list:
        """[(part of speech, senses, taught, level)] for the entries reading a character
        the way the card reads it.

        會 is one entry of six senses to the dictionary and two words to the syllabus,
        會1 a verb and 會2 a noun, so the division is already written down and a card
        showing the character can say it. Every entry at that reading, since two of
        them are two words written alike and both are the character in front of you.

        The level is when each part of speech is asked of you: 会 is a verb at HSK 1
        and a noun at HSK 3, two entries, and 半 a numeral at HSK 1 and an adverb at
        HSK 4, one. Nothing for a part of speech the syllabus does not give the word,
        since it never introduces one.
        """
        blocks = []
        for w in entries:
            ways = ways_read(w)
            if numbered not in ways or not w["pos"]:
                continue
            split = w.get("meaning_by_pos") or [("、".join(w["pos"]), w["meaning"])]
            taught = self.taught(w["pos"], split)
            blocks += [(p, m, p in taught, self.level_of(w, p)) for p, m in split]
        return blocks

    @staticmethod
    def at_level(level: str, taught: bool) -> str:
        """The level tag that follows a part of speech on a card showing several."""
        return f' <span class=atLevel>HSK {level}</span>' if taught and level else ""

    def senses(self, m: str) -> str:
        """One part of speech's worth of meaning, as CC-CEDICT divides it."""
        return self.wiki.markup(" / ".join(
            x for x in (html.escape(clean_xrefs(p.strip()), quote=False)
                        for p in m.split("/")) if x.strip()))

    def blocks(self, w: Word) -> str:
        """The meaning under the part of speech it belongs to.

        A part of speech the syllabus does not give the word is still worth knowing and
        is not what is being taught: 比 is a preposition and a verb to the syllabus, and
        the dictionary also calls it a noun, "ratio". Those are set quietly under the
        rest. One the syllabus does give and the dictionary glosses nothing under is
        still said, on one quiet line at the end: 小 is taught as a prefix, as in 小王,
        and 在 as a preposition, and neither has a sense filed under that heading. Set
        as a heading of its own it read as a block whose senses had gone missing.
        """
        split = w.get("meaning_by_pos") or []
        if not split:
            head = self.glossed(w["pos"], w)
            body = self.wiki.markup(render_senses(w["meaning"]))
            return f'<div class=charSense>{head} {body}</div>' if head else body
        taught = self.taught(w["pos"], split)
        bare = [p for p in self.named(w["pos"]) if p not in {q for q, _ in split}]
        # Each block leads with its first sense and carries the rest quietly, as an
        # unsplit meaning does and as every block on a writing card does: 就 has
        # seven senses under 副 alone, and a card is not a dictionary page.
        return "".join(
            f'<div class="charSense{"" if p in taught else " beyond"}">'
            f'{"" if p in taught else "also "}{self.label(p)}'
            f'{self.at_level(self.level_of(w, p), p in taught)} '
            f'{self.wiki.markup(render_senses(m))}</div>'
            for p, m in split) + (
            '<div class="charSense beyond">also taught as '
            + ", ".join(f'{self.label(p)}{self.at_level(self.level_of(w, p), True)}'
                        for p in bare)
            + '</div>' if bare else "")


Vocabulary = collections.namedtuple("Vocabulary", "decks notes")


def build_vocabulary(words: list[Word], wiki, media, number, gloss, pos,
                     groups, by_entry_all) -> Vocabulary:
    """The recognition cards: a word, how it is read, what it means, how it is
    written and what its characters are.

    The notes come back as well as the decks: the sentence each one cites is only
    known once the sentence cards have been built, and is filled in then.
    """
    literal = json.loads((BUILD / "literal-meanings.json").read_text(encoding="utf-8"))
    vocab_decks = {lv: deck("vocab", lv) for lv in LEVELS}

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
                w["key"], w["level"], w["simplified"], tone_hint(w, groups, pos.en),
                w["traditional"],
                # A syllable said light is said inside a word, and the card says which
                # word, since what plays is not the word written above it.
                spoken(w["pinyin"])
                + (f' (in {heard})' if (heard := w.get("heard_in")) else ""),
                w["pinyin_numbered"],
                pos.blocks(w),
                # Every meaning is headed by its part of speech, so this field stays
                # empty; it is kept so the note type keeps its shape on import.
                "、".join(w["pos"]), "",
                wiki.markup(w.get("classifier", "")), w["audio"],
                wiki.markup(" ".join(w["homophone"][:12])), also_read(w, by_entry_all, pos),
                w["stroke_order"],
                gloss.components(w["simplified"], w["pinyin_numbered"], w["traditional"]),
                html.escape(literal.get(w["traditional"], ""), quote=False),
                # filled in once the sentences have been built, below
                "",
                gloss.part_origins(w["simplified"]),
            ],
            tags=tags,
        )
        vocab_notes.append((w, note))
        number("vocab", w["level"], note)
        vocab_decks[w["level"]].add_note(note)
        for m in re.findall(r"\[sound:([^]]+)\]", w["audio"]):
            media.add(m)
        media.update(re.findall(r'<img [^>]*src="([^"]+)"', w["stroke_order"]))

    return Vocabulary(list(vocab_decks.values()), vocab_notes)


class Numbering:
    """The Key each note sorts under, counted once across the whole deck.

    One that starts again at 1 for each kind of note interleaves three sequences into
    no order at all: three notes claim 1, three claim 2. Numbered once instead -- every
    vocabulary note, then every writing note, then every sentence, each in level order.
    Where a note sits within its own section is unchanged; only the number is.

    Not the position a card is introduced at, which stays the syllabus's own index for
    a word and the source order for the rest. What the browser lists and what the
    scheduler deals are different questions.
    """

    SECTION = {"vocab": 0, "writing": 1, "grammar": 2}

    def __init__(self):
        self.keyed = []

    def __call__(self, section: str, level: str, note) -> None:
        self.keyed.append(
            (self.SECTION[section], LEVELS.index(level), len(self.keyed), note))

    def apply(self) -> int:
        """Written last, once every note exists and the order is known."""
        for i, (*_, note) in enumerate(sorted(self.keyed, key=lambda x: x[:3]), 1):
            note.fields[0] = str(i)
        return len(self.keyed)

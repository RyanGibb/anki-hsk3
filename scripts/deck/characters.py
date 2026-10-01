"""The writing cards, and the readings the syllabus teaches each
character."""
import collections
import json
import re

import genanki

from pinyin_align import align, numbered
from syllabus import LEVELS
from deck.paths import BUILD, MEDIA, MMAH_DICT, RAW
from deck.notation import CJK, char_rank, clean_xrefs, lvl_of, mask_answer, read_tsv, render_senses, syllable, toned, ways_read
from deck.models import char_model, deck
from word import Word


def build_characters(words: list[Word], wiki, media, number, gloss, pos,
                     readings) -> list:
    """The writing cards: a character, how it is read, what it means, how it is
    written, the words it is met in and what it is made of.

    The glossing a vocabulary card does of the characters inside a word is the same
    glossing a writing card does of the character itself, so it is passed in rather
    than written twice.
    """
    mmah = {}
    if MMAH_DICT.exists():
        for line in MMAH_DICT.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            mmah[d["character"]] = d
    char_audio = json.loads((BUILD / "char-audio.json").read_text(encoding="utf-8"))
    char_info = json.loads(
        (BUILD / "char-meanings.json").read_text(encoding="utf-8"))

    def by_part_of_speech(ch: str, numbered: str) -> list:
        """[(part of speech, senses)] where a reading is taught as more than one.

        The dictionary gives 會 one entry of six senses. The syllabus gives it two,
        會1 a verb at level 1 and 會2 a noun at level 3, and data/homograph-glosses.csv
        divides the six between them -- so which three are the noun is already written
        down, and the writing card can say it. Where a reading is taught once there is
        nothing to divide and the dictionary's own entry stands.
        """
        blocks = pos.divided(readings.entries.get(ch, []), numbered)
        # The dictionary's own glosses arrive cleaned and spaced about their slashes;
        # these come from the word list, where 之 still reads "literary equivalent of
        # 的[de5]" and 会 reads "to know how to/to be likely to".
        return [(p, " / ".join(x.strip() for x in clean_xrefs(m).split("/") if x.strip()),
                 d, lv) for p, m, d, lv in blocks] if len(blocks) > 1 else []

    def char_reading_senses(ch: str):
        """[(label, senses, bold, declared)] for a character, one block per way it is
        taught. Not declared means the dictionary gives the character a part of speech
        the syllabus does not: 比 is a verb and a preposition to the syllabus, and a
        noun, "ratio", to the dictionary.

        A reading heard inside a word says so: 子 zi cannot be recorded alone, so the
        card plays 包子 and tells you that is what it is playing.
        """
        def taught_at(numbered: str) -> str:
            """The level the syllabus first lists the character at, read this way.

            A card split by reading asks the same question a card split by part of
            speech does: 长 is cháng at HSK 2 and zhǎng at HSK 3, and saying so on one
            block and not the other would leave the two looking like one level's work.
            """
            lv = [w["level"] for w in readings.entries.get(ch, [])
                  if numbered in ways_read(w)]
            return min(lv, key=LEVELS.index) if lv else ""

        out = []
        ways = readings.by_char.get(ch, [])
        for marked, numbered, trad in ways:
            heard = (char_audio.get(ch) or {}).get(numbered, {}).get("in", "")
            said = marked + (f" (in {heard})" if heard else "")
            split = by_part_of_speech(ch, numbered)
            if split:
                # The level follows the part of speech it belongs to, not the reading:
                # 会 is one reading, a verb at HSK 1 and a noun at HSK 3.
                out += [((f"{said} {pos.glossed([p])}" if len(ways) > 1
                          else pos.glossed([p])) + pos.at_level(lv, d), m, False, d)
                        for p, m, d, lv in split]
                continue
            entry = gloss.pick_char(ch, numbered, trad)
            if entry and not entry[2]:
                # 血 xiě is entered only as "see 血 xuè"; the other reading defines it
                elsewhere = [c for c in gloss.char_any.get(ch, []) if c[2]]
                if elsewhere:
                    entry = max(elsewhere, key=char_rank)
            if entry:
                out.append((said + (pos.at_level(taught_at(numbered), True)
                                    if len(ways) > 1 else ""),
                            entry[1], True, True))
        return out

    def reading_meaning(ch: str, info: dict) -> str:
        """What the character means at the reading the card gives it.

        A character on the writing list the syllabus never teaches as a word has no
        taught reading to go by, and char-meanings gathers senses without regard to
        reading: 罢 is bà on the card and was glossed "to stop ... (final particle,
        same as 吧)", where the particle is 罢 at ba. Only where the dictionary reads
        the character more than one way, since otherwise there is nothing to narrow and
        char-meanings is the fuller account.
        """
        if len({syllable(e[4]) for e in (gloss.char_any.get(ch) or [])}) < 2:
            return ""
        trad = char_info.get(ch, {}).get("traditional") or ch
        for mark in info.get("pinyin") or []:
            try:
                entry = gloss.pick_char(ch, syllable(numbered(mark)), trad)
            except Exception:
                continue
            if entry and entry[1]:
                return entry[1]
        return ""

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
        entries = readings.entries.get(ch, [])
        head = pos.glossed(entries[0]["pos"], entries[0]) if len(entries) == 1 else ""
        if ch in head:
            head = ""
        body = (render_senses(blocks[0][1]) if blocks else
                render_senses(reading_meaning(ch, info)
                              or char_info.get(ch, {}).get("meaning")
                              or info.get("definition") or ""))
        return f'<div class=charSense>{head} {body}</div>' if head and body else body

    def unsaid_readings(ch: str, level: str, marks: list) -> list:
        """Every reading the cited words give a character that its header never does.

        应 is on the writing list at level 3 because of 应该 yīnggāi, and the syllabus
        enters it as a word only at 7-9, as yìng, to answer. Read from the entries
        alone the header, the meaning and the recording are all built at a reading no
        word at that level uses, and "should" appears nowhere on the card. 奔 is the
        plainer case: taught alone as bèn, written at 6, shown only in 奔跑 bēnpǎo. A
        character never taught alone heads with the dictionary's reading and meets the
        same fate: 卓 is zhuō to the dictionary and zhuó in 卓越, the only word citing it.

        Each reading is taken up on its own. Asking whether the header said any of them
        at all let one example that agrees silence every one that does not -- 适应
        shìyìng vetoed 应该, and 应 lost the reading it is written for.

        一, 不 and 儿 are left alone: yí in 一半 and the r of 一点儿 are the sandhi and
        erhua the convention writes, not other readings. So is a header reading said
        neutral inside a word, as the zi of 电子 is zǐ.

        Where the syllabus teaches the character as no word at all the dictionary's
        reading is a guess at the header rather than the header itself, and holds only
        while the words citing the character agree with it. 相 is xiāng to the
        dictionary, xiàng in 相机 and 照相 and xiāng in 相信 -- and taking the guess for
        a header left the card headed xiàng alone, with the reading of nine of the
        deck's words nowhere on it. So once a word gives a reading the guess did not,
        the guess is one reading among several and is named with them.
        """
        if ch in "一不儿":
            return []
        said = {syllable(num) for _, num, _ in readings.by_char.get(ch, [])}
        guessed = set() if said else {syllable(numbered(m)) for m in marks}
        ways = said or guessed
        if not ways:
            return []
        bases = {w[:-1] for w in ways}

        def read_in(word, mark):
            return [syllable(numbered(sy))
                    for c2, sy, _ in align(word, mark) or [] if c2 == ch]

        def header_says(num):
            return num in said or (num.endswith("5") and num[:-1] in bases)

        cited = gloss.examples(ch, level)
        out = []
        for num in dict.fromkeys(n for word, mark, _ in cited
                                 for n in read_in(word, mark)):
            if header_says(num):
                continue
            # A reading the dictionary already gives is not met in one word rather than
            # another, so it is not named after one.
            where = "" if num in guessed else next(
                word for word, mark, _ in cited if num in read_in(word, mark))
            out.append((toned(num), num, where))
        return out if any(w for _, _, w in out) else []

    writing = {r["word"]: lvl_of(r["examLevelId"])
               for r in read_tsv(RAW / "chelsea_hanzi_writing.tsv")}
    # Taken up before any card is built, so that everything a reading decides follows
    # from it: the meaning under each reading, the etymology block, the example each
    # one is heard in, and which recordings play. Only the writing cards are touched --
    # a vocabulary card is one entry and knows its own reading.
    heard_in: dict = {}
    for c, lv in writing.items():
        trad = char_info.get(c, {}).get("traditional") or c
        for mark, num, where in unsaid_readings(
                c, lv, (mmah.get(c) or {}).get("pinyin") or []):
            entry = (mark, num, trad)
            if entry not in readings.by_char.setdefault(c, []):
                readings.by_char[c].append(entry)
                heard_in[(c, num)] = where

    # Where a character is read more than one way the card leads on one of them, and
    # that one should be the way a learner has already met it. Taking the entries first
    # and the examples after led 应 -- written at level 3 for 应该 yīnggāi -- with the
    # yìng of the word it is entered as, at 7-9. So the readings are ordered by where
    # each is first taught, which the header, the meaning, the etymology and the
    # recordings all follow. Sorted rather than rebuilt: readings met at the same level
    # keep the order they were found in.
    first_taught = {}
    for w in words:
        chars = [c for c in w["simplified"] if CJK.match(c)]
        sylls = [x for x in w["pinyin_numbered"].split(" ") if x]
        if len(chars) != len(sylls):
            continue
        at = LEVELS.index(w["level"])
        for c, s in zip(chars, sylls):
            if at < first_taught.get((c, syllable(s)), len(LEVELS)):
                first_taught[(c, syllable(s))] = at
    for c in writing:
        readings.by_char.get(c, []).sort(
            key=lambda e: first_taught.get((c, syllable(e[1])), len(LEVELS)))

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
        order = [n for _, n, _ in readings.by_char.get(c, [])] or list(voiced)
        clips = "".join(voiced.get(n, {}).get("sound", "") for n in order)
        for m in re.findall(r"\[sound:([^]]+)\]", clips):
            media.add(m)
        # A reading is named after a word wherever the character alone will not say it:
        # a syllable that cannot be recorded on its own plays inside a word, and a
        # reading taken from the examples is only ever met in one.
        def named_after(n: str) -> str:
            where = ((char_audio.get(c) or {}).get(n, {}).get("in")
                     or heard_in.get((c, n), ""))
            return f" (in {where})" if where else ""

        read = ((" (also ".join(r for r, _, _ in readings.by_char.get(c, [])) + ")"
                 if c in readings.variant else
                 " / ".join(r + named_after(n)
                            for r, n, _ in readings.by_char.get(c, [])))
                or (" ".join(info.get("pinyin") or [])
                    + next((f' (in {v["in"]})'
                            for v in (char_audio.get(c) or {}).values()
                            if v.get("in")), "")))
        char_note = genanki.Note(
            model=char_model,
            due=n,
            guid=genanki.guid_for("hsk3-char", c),
            fields=[
                str(n), c, lv, writing.get(c, ""),
                char_info.get(c, {}).get("traditional") or c,
                # A reading heard inside a word names that word, and a word holding
                # this character is the answer to the card asking for it, so the
                # character is masked here as it is in a gloss that quotes itself.
                mask_answer(read, c),
                mask_answer(char_meaning(c, info), c),
                clips, stroke,
                gloss.etym_block(c, "/".join(
                    n for _, n, _ in readings.by_char.get(c, []))),
                mask_answer(gloss.example_of(c, lv), c),
                gloss.example_word(c, lv),
                gloss.part_origins(c),
            ],
            tags=[f"HSK3.0::char::write-L{lv}"],
        )
        number("writing", lv, char_note)
        char_decks[lv].add_note(char_note)

    return list(char_decks.values())


Readings = collections.namedtuple("Readings", "by_char entries variant")


def readings_taught(words: list[Word]) -> Readings:
    """How the syllabus teaches each single character: the ways it is read, the
    entries that teach it, and whether it is one word said two ways.

    The writing cards need this and so does the example a vocabulary card cites,
    so it is worked out once and handed to both.
    """
    by_char, entries, variant = {}, {}, set()
    for w in words:
        if len(w["simplified"]) != 1:
            continue
        # 熟 is entered as "shú/shóu", which is two readings; and the syllabus writes
        # nü3 where the recordings are filed under nv3
        # one entry with two readings is one word said two ways -- 熟 shú, also shóu --
        # where two entries are two words that happen to be written alike
        marks = [x for x in w["pinyin"].split("/") if x.strip()]
        if len(marks) > 1:
            variant.add(w["simplified"])
        nums = ways_read(w)
        for mark, num in zip(marks, nums):
            entry = (mark, num, w["traditional"])
            if entry not in by_char.setdefault(w["simplified"], []):
                by_char[w["simplified"]].append(entry)
        entries.setdefault(w["simplified"], []).append(w)
    return Readings(by_char, entries, variant)

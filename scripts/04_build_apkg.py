#!/usr/bin/env python3
"""Build the .apkg. IDs are fixed constants, so re-importing updates the existing
notes instead of duplicating them."""
import collections
import json
import pathlib
import re
import shutil
import sys

import genanki

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from word import load_words   # noqa: E402
from deck.paths import BUILD, MEDIA, ROOT   # noqa: E402
from deck.notation import AFFIX, syllable   # noqa: E402
from deck.models import VOCAB_FIELDS   # noqa: E402
from deck.wiktionary import Wiktionary   # noqa: E402
from deck.grammar import build_grammar   # noqa: E402
from deck.characters import build_characters, readings_taught   # noqa: E402
from deck.vocabulary import Numbering, PartsOfSpeech, build_vocabulary   # noqa: E402
from deck.glossary import Glossary   # noqa: E402


def main() -> int:
    decks, media = [], set()
    words = load_words()
    by_entry_all = {w["entry"]: w for w in words}
    # Every word by its spelling: 为 is listed as 为, 为1 and 为2, and the one with no
    # digit needs telling from the other two as much as they need telling from it.
    groups = collections.defaultdict(list)
    for w in words:
        groups[w["simplified"]].append(w)

    wiki = Wiktionary(words)
    number = Numbering()
    pos = PartsOfSpeech(wiki)
    readings = readings_taught(words)
    gloss = Glossary(words, wiki, readings, pos)

    vocabulary = build_vocabulary(words, wiki, media, number, gloss, pos,
                                  groups, by_entry_all)
    # A row of data/compound-senses.csv names a sense in the character's row as the
    # card shows it; one that matches nothing has gone stale and says nothing.
    if gloss.undrawn():
        sys.exit(f"data/compound-senses.csv names senses no card shows: "
                 f"{gloss.undrawn()[:5]}")
    decks += vocabulary.decks
    vocab_notes = vocabulary.notes

    sentences = build_grammar(words, wiki, media, gloss.cedict_defs, number)
    decks += sentences.decks

    at = VOCAB_FIELDS.index("ExampleSentence")

    def worn_light(reading: str):
        """The readings a sentence gives the word when it speaks a later syllable
        neutral: 关系 is guānxì to the word list and guānxi in every sentence that
        uses it, the citation tone worn down rather than another word. One
        direction only, and never the first syllable, so 地 taught as dì still
        refuses a sentence reading it de, and 东西 taught light does not take
        east-and-west."""
        sylls = reading.split()
        spots = [i for i in range(1, len(sylls)) if not sylls[i].endswith("5")]
        for mask in range(1, 1 << len(spots)):
            worn = {s for b, s in enumerate(spots) if mask >> b & 1}
            yield syllable(" ".join(
                re.sub(r"\d$", "5", s) if i in worn else s
                for i, s in enumerate(sylls)))

    for w, note in vocab_notes:
        # 地 is taught twice, as de and as dì, and a sentence using one is no example
        # of the other. Only where no sentence uses the reading the card teaches does
        # the word alone decide it.
        said_as = syllable(w["pinyin_numbered"])
        # The sentence has to read the word the way the card teaches it. A sentence
        # that merely contains the characters is about another word: 子 the light
        # suffix is not shown by 子系统, where it is zǐ, and 头 the suffix is not
        # shown by 十几头牛, where it counts cattle.
        cited = sentences.example_sentence.get((w["simplified"], said_as), "")
        for worn in worn_light(w["pinyin_numbered"]) if not cited else ():
            cited = sentences.example_sentence.get((w["simplified"], worn), "")
            if cited:
                break
        # A word the syllabus marks an affix appears only inside another word, so a
        # sentence using it is a sentence with it on the end of something.
        if not cited and len(w["simplified"]) == 1 and AFFIX.search("".join(w["pos"])):
            cited = sentences.inside.get((w["simplified"], said_as), "")
        note.fields[at] = cited
    print(f"  example sentences: {sum(1 for _, n in vocab_notes if n.fields[at])}"
          f"/{len(vocab_notes)} words")

    print(f"  grammar pinyin: {sentences.py_stats['checked']} sentences hand-checked; "
          f"the rest generated from {sentences.py_stats['syllabus']} syllabus tokens, "
          f"{sentences.py_stats['pypinyin']} pypinyin, {sentences.py_stats['override']} overridden")

    decks += build_characters(words, wiki, media, number, gloss, pos, readings)

    print(f"keys: 1 to {number.apply()} across the deck")

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
    silent = [x for x in dict.fromkeys(sentences.wanted_audio) if not sentences.audio_for(x)]
    (BUILD / "tts-wanted.json").write_text(
        json.dumps({"sentences": list(dict.fromkeys(sentences.wanted_audio)),
                    "silent": silent}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"speech wanted: {len(set(sentences.wanted_audio))} sentences, {len(silent)} unvoiced")
    # Every character a card shows, the parts among them. fetch-glyph-origins.py looks
    # up what has no origin, and a part reached only by the walk is not in any word
    # list, so nothing else can tell it they are wanted.
    (BUILD / "shown-chars.json").write_text(
        json.dumps(sorted(gloss.shown_chars), ensure_ascii=False), encoding="utf-8")
    print(f"characters shown: {len(gloss.shown_chars)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

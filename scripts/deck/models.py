"""The note types and the decks they are filed in."""
import os

import genanki

from syllabus import LEVELS
from deck.paths import TPL


# 1758100002 is reserved: collections built before the sentence cards hold a
# grammar-point note type under it, and a new type there would collide with it.
MID_VOCAB, MID_CHAR, MID_SENTENCE = 1758100001, 1758100003, 1758100004
DID_ROOT = 1758100100


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

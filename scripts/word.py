"""One word of the syllabus as build/words.json holds it, and the one way to read it."""
import json
import pathlib
from typing import NotRequired, TypedDict

WORDS = pathlib.Path(__file__).resolve().parent.parent / "build/words.json"


class Word(TypedDict):
    """Written by 02_build_words.py, then given its recordings and strokes by
    03_media.py. JSON holds the pairs in meaning_by_pos as two-item arrays."""

    # From the syllabus's word list (02)
    key: str                    # the list's own index: the order cards are introduced in
    entry: str                  # the word with any homograph digit: 会1, 会2
    simplified: str             # the word as written
    homograph_index: str        # that digit, or ""
    level: str                  # the first level the word is listed at
    also_levels: list[str]      # the later ones
    pos: list[str]              # parts of speech as the list writes them: 形、介、（动、量）
    pos_levels: dict[str, str]  # the first level each part of speech is listed at
    pinyin: str                 # the reading, marked: zhòngyào
    pinyin_numbered: str        # the same, numbered: zhong4 yao4; readings split by "/"

    # From CC-CEDICT, as adjudicated (02)
    traditional: str
    traditional_auto: str       # the dictionary's choice before any override, for checking
    traditional_source: str     # cedict, cedict:primary, adjudicated, ...
    cedict_candidates: str      # every traditional form the dictionary offers, "/"-joined
    meaning: str                # the senses the card shows, "/"-separated
    meaning_full: str           # the dictionary's senses before any hand editing
    meaning_source: str         # cc-cedict, or curated from data/homograph-glosses.csv
    meaning_by_pos: list[tuple[str, str]]   # (part of speech, senses), from sense-pos.csv
    classifier: str

    # Its neighbours in the list (02)
    homograph: list[str]        # entries written the same way
    homophone: list[str]        # words read the same way

    # Media (03)
    audio: str                  # [sound:...], or "" where there is none
    audio_source: str
    stroke_order: str
    heard_in: NotRequired[str]  # the word a syllable is recorded inside, where it is


def load_words() -> list[Word]:
    """The words, every one checked against the record, so a field added or dropped
    upstream stops the build here rather than a thousand lines on as a KeyError."""
    words = json.loads(WORDS.read_text(encoding="utf-8"))
    # 02_build_words.py writes the words and 03_media.py adds the recordings and the
    # stroke diagrams to them. Run out of order the media fields are simply absent.
    if words and "audio" not in words[0]:
        raise SystemExit("build/words.json carries no media: run scripts/03_media.py "
                         "after scripts/02_build_words.py and before this")
    need, may = Word.__required_keys__, Word.__optional_keys__
    for w in words:
        if not need <= w.keys() <= need | may:
            raise SystemExit(f"{w.get('entry')} does not match scripts/word.py: missing "
                             f"{sorted(need - w.keys())}, unknown "
                             f"{sorted(w.keys() - need - may)}")
    return words

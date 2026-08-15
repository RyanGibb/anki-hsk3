#!/usr/bin/env python3
"""What counts as an account of a glyph, as opposed to an account of a word.

Wiktionary explains 簡 twice over: the character is 竹 over phonetic 間, and the word is
a borrowing of the English name Jane. A writing card asks where the shape came from, so
only the first is an answer. The dump carries whichever section wiktextract kept, which
is often the borrowing alone, so both the fetcher and the build need the same test.
"""
import re

# Openings that introduce the history of a word rather than the making of a character.
LOAN = re.compile(
    r"^\s*(?:Borrowed from|From English|From Japanese|From Proto-|Transliteration"
    r"|Orthographic borrowing|Phonetic (?:adaptation|transcription)|Calque|Clipping"
    r"|Abbreviation of|Contraction of)\b|transliteration of", re.I)
# Vocabulary that only appears when the shape itself is being described.
GRAPH = re.compile(
    r"compound|pictogram|ideogram|phonetic|semantic|component|oracle|bronze"
    r"|seal script|simplif|cursive|変|变体|variant form|radical|stroke", re.I)


def about_the_glyph(text: str, liushu: str = "") -> bool:
    """True when this etymology says something about the shape of the character.

    Evidence has to be positive. Absence of a loanword marker is not enough: 答 is
    given as "Cognate with 對 … Compare Tibetan འདེབས", which is the history of the
    word and says nothing about the graph, while the graph's own account sits under
    荅. What does say something names how the character was made -- the 六書 class the
    dump records, or the vocabulary of one.
    """
    if liushu:
        return True
    if not text or LOAN.search(text):
        return False
    return bool(GRAPH.search(text))


def any_about_the_glyph(sections) -> bool:
    return any(about_the_glyph(s.get("text", ""), s.get("type", ""))
               for s in sections or [])

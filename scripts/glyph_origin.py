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
# Vocabulary that only appears when the shape itself is being described. Not every
# account names a 六書 class: 司 is "a mouth 口 giving orders and a scepter 刁", 亻 is
# "a stylization of 人", and 丐 is "a corruption of 匄". Each says where the shape came
# from without using any of the words a classification would.
GRAPH = re.compile(
    r"compound|pictogram|ideogram|phonetic|semantic|component|oracle|bronze"
    r"|seal script|simplif|cursive|変|变体|variant form|radical|stroke"
    r"|styliz|stylis|corrupt|same character|original form|proto-form|glyph|graph\b"
    r"|Shuowen|說文|说文|interpret|inverted|depict|clerical script|this character",
    re.I)


# wiktextract renders a glyph it cannot reproduce as nothing at all, so an account
# that consists of pointing at one comes through as "Derived from its seal script
# form, ." -- a sentence whose subject was dropped. Only where that is the whole of it:
# 騎 loses a reference midway through 2,349 characters that say plenty besides.
LOST_REFERENCE = re.compile(r"[,:]\s*\.\s*$")


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
    if len(text) < 120 and LOST_REFERENCE.search(text):
        return False
    return bool(GRAPH.search(text))


def any_about_the_glyph(sections) -> bool:
    return any(about_the_glyph(s.get("text", ""), s.get("type", ""))
               for s in sections or [])

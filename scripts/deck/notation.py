"""The dictionaries' notation, and the deck's: readings, cross-references,
senses, and choosing among entries."""
import collections
import csv
import html
import re

from deck.paths import RAW
from word import Word


CJK = re.compile(r"[㐀-鿿豈-﫿]")


def read_tsv(path):
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


TONE_MARK = {"1": "ˉ", "2": "ˊ", "3": "ˇ", "4": "ˋ", "5": "·"}


# a word that is only ever the end or the start of another
AFFIX = re.compile(r"前缀|后缀")
WORDS = re.compile(r"[A-Za-z\u3400-\u9fff]")
# "erhua variant of 好玩" is a direction elsewhere like any other: the deck follows
# it rather than printing it, so 一点儿 says "a bit; a little bit" and not where to look.
# "See you later!" is a sense, so "see" is a pointer only with Chinese after it.
POINTER = re.compile(r"^(?:(?:old |erhua )?variant of|abbr\. for"
                     r"|see(?: also)?(?=\s+[㐀-鿿豈-﫿]))\b", re.I)
# ...and what it points at.
TARGET = re.compile(r"^(?:(?:old |erhua )?variant of|see(?: also)?|abbr\. for)\s+"
                    r"([㐀-鿿豈-﫿]+)")
# "abbr. for 超級市場|超级市场[chao1 ji2 shi4 chang3]"
XREF = re.compile(r"(?:([㐀-鿿]+)\|)?([㐀-鿿]+)\[([A-Za-z0-9:, ]+)\]")
# "also pr. [di4]", "Taiwan pr. [zhi1dao5]" -- not reliably spaced, so split on digits
BARE = re.compile(r"\[((?:[A-Za-z:]+[0-9][ ,-]?)+)\]")
SYLL = re.compile(r"[A-Za-z:]+[0-9]")
# "as in 除了他，誰也沒來|除了他，谁也没来"
PIPE = re.compile(r"([㐀-鿿，、。！？：；…]+)\|([㐀-鿿，、。！？：；…]+)")


def syllable(s: str) -> str:
    """A numbered syllable spelled one way. The syllabus writes nü3, the dictionary
    writes nu:3, and comparing them as they come makes two readings of one."""
    return s.replace(" ", "").replace("u:", "v").replace("ü", "v").lower()


def ways_read(w: Word) -> list:
    """Every way the syllabus reads a word, each spelled as syllable() spells it: 谁 is
    one word read shei2/shui2."""
    return [syllable(x) for x in w["pinyin_numbered"].split("/") if x.strip()]


def toned(numbered: str) -> str:
    """you3 as yǒu. A syllable the converter does not know comes back as it went in."""
    from pypinyin.contrib.tone_convert import to_tone
    try:
        return to_tone(syllable(numbered))
    except Exception:
        return numbered


# What the deck's own convention writes into a word's reading, and what the character
# is read on its own. 一 and 不 shift tone before certain tones -- 一起 is yìqǐ -- and
# erhua wears 儿 down to an r. A row citing the character undoes exactly this and no
# more: a general "the tone differs, so cite the dictionary" rule would lose 相, where
# xiāng and xiàng are two readings rather than one worn into the other.
SANDHI = {("一", "yi2"): "yi1", ("一", "yi4"): "yi1",
          ("不", "bu2"): "bu4", ("儿", "r5"): "er2"}


def citation_readings() -> dict:
    """character -> the reading a word's spelling is standing in for.

    朋友 is written peng2 you5 and 友 on its own is yǒu; the card says the word and the
    row beneath it should say the character. Only where the dictionary leaves no doubt:
    友 has one reading, you3, so a neutral 友 is a light yǒu. 吗 has ma2 and ma3 beside
    ma5, and the question particle is not either of them, so it is left neutral. Nor is
    a light syllable the dictionary enters in its own right worn down from anything:
    子 is zi3 "son, child" and separately zi5, the noun suffix of 包子.

    A tone the convention wrote is undone here too, by SANDHI above.
    """
    by_base = collections.defaultdict(set)
    for line in cedict_lines():
        m = re.match(r"^\S+ (\S) \[([^]]*)\] /", line)
        if m:
            r = syllable(m.group(2))
            by_base[(m.group(1), re.sub(r"[0-9]", "", r))].add(r)
    # The neutral tone is the word's, not the character's: 友 is entered only as you3
    # and it is 朋友 that writes you5. So the dictionary is asked what a light syllable
    # could be standing on, not whether it lists a light one.
    out = {}
    for (ch, base), rs in by_base.items():
        full = [r for r in rs if not r.endswith("5")]
        if len(full) == 1 and f"{base}5" not in rs:
            out[(ch, f"{base}5")] = full[0]
    out.update(SANDHI)
    return out


def clean_xrefs(text: str) -> str:
    from pypinyin.contrib.tone_convert import to_tone

    # CC-CEDICT spells the umlaut u: and writes it apart in 27 entries -- 女孩兒 is
    # "erhua form of 女孩[nu : 3 hai2]". The syllable will not parse spelled that way
    # and is dropped without a word, leaving 女孩儿 glossed "erhua form of 女孩 hái".
    text = re.sub(r"(?<=[nl]u)\s*:\s*(?=[1-5])", ":", text)

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

    # A classifier is dictionary notation rather than part of the meaning. The word
    # path lifts it into its own field; a character standing inside a word has no
    # such field, and "greens (CL:棵 kē)" is not what 菜 means.
    #
    # Taken out while it is still the dictionary's own notation. Rewriting first puts
    # brackets inside it -- 頓|顿[dun4] is labelled 顿 (頓) dùn -- and then the bracket
    # closing the classifier is no longer the first one to come along: 念 was left
    # reading "to give (sb) a tongue-lashing dùn)".
    text = re.sub(r"\s*\(CL:[^)]*\)", "", text)
    text = drop_slot(text, "CL:")
    out = PIPE.sub(r"\2", BARE.sub(bare, XREF.sub(one, text)))
    # The deck teaches one standard: the syllabus's readings, spoken by mainland
    # voices, tested by a mainland exam. A reading from another standard is not a
    # meaning, and 结 as "(of a plant) to produce (fruit or seeds) / Taiwan pr. jié"
    # offers a card its own recording contradicts. An "also pr." is kept: that is an
    # alternative within the standard, and the reading field carries it too.
    out = re.sub(r"\s*\(Taiwan pr\.[^)]*\)", "", out)
    out = drop_slot(out, "Taiwan pr.")
    return out.strip(" /")


def drop_slot(text: str, opening: str) -> str:
    """The text without any sense that opens with these words, and without the one
    separator that set it off. The separator after it stays, spaced as it was: 载 is
    "...etc) / Taiwan pr. zài / year", and taking the note with the spaces around both
    slashes left "...etc)/ year" reading as one sense."""
    o = re.escape(opening)
    text = re.sub(rf"\s*/\s*{o}[^/]*?(?=\s*/|\s*$)", "", text)
    return re.sub(rf"^\s*{o}[^/]*(?:/\s*|$)", "", text)


def sense_key(text: str) -> str:
    """A sense reduced to what it says, so the same sense written two ways is one.

    The syllabus's division of a meaning is written in the dictionary's own notation --
    "(bound form) branch of (an organization); sub- (as in 分局[fen1 ju2])" -- and a card
    carries the same sense rendered, as "分局 fēnjú". Punctuation and spacing go too: a
    row that reached the card through one cleaning and a division that reached it
    through another differ by a bracket as readily as by anything else.
    """
    return re.sub(r"[^a-z0-9一-鿿]", "", clean_xrefs(text).lower())


def spoken(pinyin: str) -> str:
    """谁 is shéi, also shuí -- one word with a second pronunciation, not two words.
    A slash reads as though they were alternatives of equal standing."""
    parts = [x.strip() for x in pinyin.split("/") if x.strip()]
    return parts[0] + (f" (also {', '.join(parts[1:])})" if len(parts) > 1 else "")


def mend(text: str) -> str:
    """An account with what the dump could not carry over taken back out of it.

    Three kinds of damage, none of them anything Wiktionary shows a reader. A glyph
    wiktextract cannot reproduce is dropped where it stood, leaving the sentence
    pointing at nothing -- "recorded in Shuowen as ." -- or a reconstruction with a
    hole in it, *bo()k. A script it has no font for is announced instead of written,
    so 牙 compares "Mru [script needed] (hngou, “tooth”)". And a citation's link comes
    through as the address itself, so 鬼 cites "(Shuowen Jiezi
    https://ctext.org/shuo-wen-jie-zi/gui-bu?searchu=%E6%AD%B8&searchmode=showall#result;
    Liezi https://ctext.org/liezi/tian-rui...)" where the names alone are the citation.

    Only the damage: what is left is every word the dump did carry over.
    """
    # An address ends where its sentence resumes, so the punctuation after it is the
    # sentence's and stays: "(Shuowen Jiezi; Liezi)." keeps both marks.
    text = re.sub(r"\[script needed\]|\(\s*\)"
                  r"|https?://[^\s]+?(?=[.,;:)\]]*(?:\s|$))", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    # Then what the hole leaves behind: a sentence closing on the reference that is
    # no longer there, and a space held open before the punctuation that followed it.
    text = re.sub(r"(?:,| as| like| to)?\s+\.(?=\s|$)", ".", text)
    text = re.sub(r"\s+([,;.)])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    return re.sub(r"\s{2,}", " ", text).strip()


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
    # A sense can empty out in the cleaning: 究 is entered "after all/to investigate/
    # to study carefully/Taiwan pr. [jiu4]", and the reading note is not a sense of
    # the word. What is left is nothing, so the slot goes too, rather than standing
    # as a slash with no sense after it.
    parts = [x for x in (html.escape(clean_xrefs(p.strip()), quote=False)
                         for p in meaning.split("/")) if x.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return (f'{parts[0]}<div class="more">' + " / ".join(parts[1:]) + "</div>")


def lvl_of(exam_level_id: str) -> str:
    return exam_level_id.replace("HSK", "")


# Words that appear in any gloss and so distinguish nothing.
STOP = set("""a an the to of and or in on at for with by from as is are be being been
sth sb one ones s not no also used use using esp especially etc eg ie that this it its
into out up down over under about between form forms variant surname classifier""".split())


def gloss_words(text: str) -> set:
    return {w for w in re.split(r"[^a-z]+", text.lower()) if len(w) > 2 and w not in STOP}


# 老李 and 小高 are how a familiar name is formed, and a surname before a title is the
# other place one appears. Nothing else in a sentence is a name.
TITLE = re.compile(r"^(老师|先生|女士|小姐|医生|经理|教授|同学|阿姨|叔叔|大夫|师傅"
                   r"|校长|老板|某)")


# The simplified form's own account, set after the account of the shape it came
# from; and the paragraphs that follow a lead, or the senses after the first. Named
# here because glossary.py takes a block apart at them and grammar.py builds one.
LATER = '<div class="later">'
MORE = '<div class="more">'


def senses_of(meaning: str) -> list:
    """The senses of a "/"-joined gloss, each trimmed, cross-references read."""
    return [x.strip() for x in clean_xrefs(meaning).split("/") if x.strip()]


def headed(wiki, ch: str, trad: str) -> str:
    """The bold head of a gloss row: the character as written, with the traditional
    form beside it where that differs, linked to the entry it came from."""
    label = ch if trad == ch else f"{ch} ({trad})"
    return f"<b>{wiki.label(label, trad)}</b>"


def lead_and_rest(wiki, said: list) -> str:
    """The first sense at full size and the rest quietly under it, as a word's own
    card carries a long meaning: 跟 turns on "compared with", its sixth, and a
    reader should not have to take the whole list at once to reach it."""
    body = wiki.markup(html.escape(said[0], quote=False)) if said else ""
    if len(said) > 1:
        body += MORE + wiki.markup(html.escape(" / ".join(said[1:]), quote=False)) + "</div>"
    return body


def outside_tags(text: str, f) -> str:
    """f applied to the text between the tags, leaving the markup itself alone: a
    link's href is Chinese as well, and must not be linked or masked again."""
    out, i = [], 0
    for m in re.finditer(r"<[^>]+>", text):
        out.append(f(text[i:m.start()]))
        out.append(m.group(0))
        i = m.end()
    out.append(f(text[i:]))
    return "".join(out)


def mask_answer(text: str, ch: str) -> str:
    """Hide the character inside prose that the writing card asks you to produce.

    A gloss illustrates itself: 大 is "eldest (as in 大姐 dàjiě)" and 报 is "to register
    for (abbr. for 报名 bàomíng)". Read on the question side, that is the answer. The
    card still needs the phrase, so the character is wrapped rather than removed, and
    only the question side hides what is wrapped.
    """
    if not ch or ch not in text:
        return text
    return outside_tags(text, lambda t: t.replace(ch, f'<span class=mask>{ch}</span>'))


def cedict_lines():
    """The dictionary, with the patch read into it.

    A patched sense of a word the dictionary carries joins that word's own lines: 在
    is patched with "in; at", and as a line of its own it was a second entry that
    nothing choosing one entry ever chose, so a sentence's 在 could not be glossed
    "at". It joins every line with that heading, so that which of them is chosen --
    by how much each says -- is what it was. A word the dictionary does not carry is
    a line of its own after the rest.
    """
    main = (RAW / "cedict_ts.u8").read_text(encoding="utf-8").splitlines() \
        if (RAW / "cedict_ts.u8").exists() else []
    patch = (RAW / "cedict_patch.u8").read_text(encoding="utf-8").splitlines() \
        if (RAW / "cedict_patch.u8").exists() else []
    head = re.compile(r"^(\S+ \S+ \[[^\]]*\]) /(.*)/$")
    at: dict[str, list] = {}
    for i, line in enumerate(main):
        m = head.match(line)
        if m:
            at.setdefault(m.group(1), []).append(i)
    alone = []
    for line in patch:
        m = head.match(line)
        if m and m.group(1) in at:
            for i in at[m.group(1)]:
                main[i] = main[i] + m.group(2) + "/"
        else:
            alone.append(line)
    yield from main
    yield from alone


def char_rank(entry):
    """How much an entry says about a character standing inside a word.

    CC-CEDICT files 年 under the surname Nian before the year, as it files 都 under
    Du before dōu, and marks the difference by capitalising the reading. A character
    inside 今年 is not a name, so the capital settles it before anything else does.
    """
    _trad, _gloss, defining, senses, reading = entry
    return (not reading[:1].isupper(), defining > 0, defining, senses)


def best_entry(cands, want_trad, key, proper=False, simp=""):
    """The CC-CEDICT entry a word in a sentence means.

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
        trad, gloss, reading, n_senses, borrowed = e
        bare = re.sub(r"[0-9]", "", reading).lower()
        want = re.sub(r"[0-9]", "", key).lower()
        return (reading.lower() == key.lower(),
                bool(key) and bare == want,
                reading[:1].isupper() == proper,
                # 只 [zhi1] is "variant of 隻" while 隻 [zhi1] is the classifier
                # itself, the same test the character glosses use. An entry whose
                # senses were borrowed from the word it points at is ranked with the
                # pointers it came from, not with the entries that have senses of
                # their own.
                not POINTER.match(gloss) and not borrowed,
                # The form the deck settled on, before length: 秊 is filed under 年 as
                # "grain; harvest (old); variant of 年" and says more than 年 itself,
                # which is "year" and a classifier, so 一年有十二个月 was glossed grain.
                # It decides 裡 against 里 as well.
                trad == want_trad,
                # How much it has to say. The count alone ties 隻, whose classifier
                # runs "for birds and certain animals, one of a pair, some utensils,
                # vessels etc" as a single sense, with 秖 "grain that has begun to
                # ripen", and the tie went to whichever the file listed first.
                n_senses, len(gloss),
                # Last, so it only settles a tie nothing else can. 卹 and 恤 are entered
                # with the same senses at the same reading, and the tie fell to the file,
                # leaving a T恤 labelled 恤 (卹) as though that were how it is written.
                trad == simp)
    return max(cands, key=rank)

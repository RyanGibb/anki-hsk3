"""The grammar cards and the sentence cards built from them."""
import collections
import csv
import html
import json
import re
import shutil

import genanki

from pinyin_align import ALIGNABLE, align, numbered
from syllabus import LEVELS
from deck.paths import MEDIA, RAW, ROOT
from deck.notation import CJK, TITLE, best_entry, clean_xrefs, lvl_of, read_tsv, syllable
from deck.models import deck, sentence_model
from deck.vocabulary import PartsOfSpeech
from word import Word


PROPER = {"ns", "nt", "nz"}   # place, organisation, other proper noun -- 上海 is not 上 + 海
SPEAKER = re.compile(r"^[A-Z]：")
SUFFIX = set("们儿子头过着")    # attaches to its stem: 人们, 点儿, 看过


def make_pinyin(words: list[Word]):
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


Sentences = collections.namedtuple(
    "Sentences",
    "decks example_sentence inside wanted_audio audio_for py_stats")


def build_grammar(words: list[Word], wiki, media, cedict_defs, number) -> Sentences:
    """The sentence cards, and the sentence each vocabulary card borrows.

    Everything the syllabus's grammar file has to say: the points, the sentences
    that teach them, their readings, their translations, and a gloss for every
    word in them. The vocabulary cards draw on the same sentences, so the map from
    a word to the sentence that uses it is built here and handed back.
    """
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
            return wiki.run(sentence)
        return "".join(wiki.word(text) for text, _ in got)

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

    # What the syllabus teaches a word as, which is a better opening than the order
    # CC-CEDICT happens to file its senses in: 件 opens on "item" where the syllabus
    # teaches the classifier, and 位 on "position" where it teaches the one for people.
    taught_word: dict[str, list] = collections.defaultdict(list)
    forms: dict[str, set] = collections.defaultdict(set)
    for w in words:
        taught_word[w["simplified"]].append(w)
        forms[w["simplified"]].add(w["traditional"])
    # A word the syllabus teaches twice can be two traditional characters -- 面 is 面
    # "face" and 麵 "flour" -- and to_trad keeps whichever was written down last, so
    # asking for that form would settle the sentence on the order of a file.
    two_formed = {s for s, ts in forms.items() if len(ts) > 1}

    def taught_senses(piece: str, key: str) -> list:
        """The senses the syllabus teaches, where it settles which they are.

        A word it teaches once is unarguable. One it teaches twice is settled by the
        reading where the two differ -- 挂着 is zhe and 着凉 is zhuó -- and by nothing
        the deck has where they do not: 别 is bié as "don't" and bié as "to part", and
        which of them a sentence means is not written down anywhere. Those keep the
        dictionary's own order.
        """
        ws = taught_word.get(piece) or []
        if len(ws) > 1 and key:
            ws = [x for x in ws
                  if syllable(x["pinyin_numbered"]) == syllable(key)]
        if len(ws) != 1:
            return []
        w = ws[0]

        def senses(m):
            return [x.strip() for x in clean_xrefs(m).split("/") if x.strip()]

        # Where the meaning is divided by part of speech, the syllabus's own order of
        # them decides: 跟 is 介、连、（名、动） and the preposition is what 跟我说说 and
        # 我的爱好跟他一样 turn on, while the dictionary opens on "heel".
        split = dict(w.get("meaning_by_pos") or [])
        out: list = []
        for p in PartsOfSpeech.named(w["pos"]):
            if p in split:
                out += senses(split[p])
        seen = {x.casefold() for x in out}
        return out + [x for x in senses(w["meaning"]) if x.casefold() not in seen]

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
                written = word_gloss.get((sentence, piece))
                # A sense written down for this sentence says which entry is meant, not
                # only which of its senses leads. 游 in 游游泳 is the 游 that swims and
                # not the 遊 that tours, and taking the sense without the entry left the
                # card glossing "to swim" under a 遊 it is not written with.
                if written:
                    said = clean_xrefs(written).split(" / ")[0].strip().casefold()
                    same = [c for c in cands if said and said in c[1].casefold()]
                    cands = same or cands
                chose = best_entry(
                    cands, None if piece in two_formed else wiki.to_trad.get(piece),
                    key, proper and i == 0, piece)
                gloss = chose[1]
                # The form to print is the one the senses were read from. A character
                # map arrives at a form on its own and the two then disagree: 干 glossed
                # "to do" was labelled 乾 "dry", 面 in 没见过面 was labelled 麵 "noodles",
                # and 春, whose traditional form is itself, was labelled with the
                # variant 旾.
                trad = chose[0]
                label = piece if trad == piece else f"{piece} ({trad})"
                # Every sense is given, the first at full size and the rest quietly
                # under it, as a word's own card carries a long meaning. 跟 turns on
                # "compared with", its sixth, and a reader should not have to take the
                # whole list at once to reach it.
                said = [p.strip() for p in gloss.split(" / ") if p.strip()]
                # What the sentence means by the word leads, and the dictionary's other
                # senses follow rather than being thrown away: a word written down for
                # this sentence first, since that is the only place the deck knows which
                # of two senses a sentence draws on -- 别 is bié either way -- then what
                # the syllabus teaches, then the dictionary's own order.
                lead = ([p.strip() for p in clean_xrefs(written).split(" / ")
                         if p.strip()] if written else taught_senses(piece, key))
                if lead:
                    already = {s.casefold() for s in lead}
                    said = lead + [s for s in said if s.casefold() not in already]
                body = wiki.markup(html.escape(said[0], quote=False)) if said else ""
                if len(said) > 1:
                    body += ('<div class="more">'
                             + wiki.markup(html.escape(" / ".join(said[1:]),
                                                       quote=False))
                             + "</div>")
                out.append(f'<div class="gloss"><b>{wiki.label(label, trad)}</b> '
                           f'{body}</div>')
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

    # 离合词, the words the syllabus teaches as coming apart: 帮忙 is said 帮我一个忙 and
    # 洗澡 洗个澡, so the two halves stand where the dictionary has one word. Taken from
    # the syllabus rather than listed here, which is where the deck learns what it is
    # teaching.
    apart = {w for r in rows if "离合词" in (r.get("grammarDetail") or "")
             for w in re.split(r"[、，/／]", r["content"] or "")
             if len(w.strip()) == 2 and CJK.search(w)}

    def split_verbs(sentence: str, pieces: set, point: str) -> list:
        """The separable verbs this sentence says in halves, each with its own entry.

        Glossing 帮 and 忙 where the sentence means 帮忙 leaves the reader the two
        literal halves -- to help, and busy -- and never the word they make.

        Only where the sentence is teaching that word. What goes between the halves is
        anything at all -- 帮我一个忙 -- so reading the halves alone would take 坐下一班
        地铁, the next train, for 下班 finishing work. The syllabus says which word each
        sentence is an example of, and that settles it.
        """
        out = []
        for w in sorted(apart):
            if w not in point or w in sentence:
                continue
            if w[0] not in pieces or w[1] not in pieces:
                continue
            if not re.search(re.escape(w[0]) + r".{1,4}?" + re.escape(w[1]), sentence):
                continue
            cands = cedict_defs.get(w)
            if cands:
                out.append((w, best_entry(cands, wiki.to_trad.get(w), "", False, w)))
        return out

    def sentence_words(sentence: str, point: str = "") -> str:
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
        # The halves are glossed where they stand, and the word they make is said after
        # them: the sentence has 帮 and it has 忙, and neither is 帮忙.
        glossed = {p for w, _ in words for p in w}
        for whole, chose in split_verbs(sentence, glossed, point):
            trad = chose[0]
            label = whole if trad == whole else f"{whole} ({trad})"
            said = [p.strip() for p in chose[1].split(" / ") if p.strip()]
            body = wiki.markup(html.escape(said[0], quote=False)) if said else ""
            if len(said) > 1:
                body += ('<div class="more">'
                         + wiki.markup(html.escape(" / ".join(said[1:]), quote=False))
                         + "</div>")
            out.append(f'<div class="gloss"><b>{wiki.label(label, trad)}</b> '
                       f'{body}</div>')
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
        # The source wraps a long sentence and the wrap lands on the separator, so
        # 毅然选|择回乡工作 arrives as two pieces and the card showed the first half
        # alone. A piece this long that closes nothing is the front of the next one.
        # The item lists that end without punctuation on purpose -- 哥哥姐姐、今天和明天
        # -- are all shorter than the wrap, so the two do not meet.
        WRAP = 32
        whole: list = []
        for c in (r.get("cases") or "").split("|"):
            for c in re.split(r"(?<=[。！？])\s+", c.strip()):
                # 择回乡工作。年轻人的私事… — one piece holding two examples with a
                # space where the separator should be. The only one in the file.
                c = c.strip()
                if not c:
                    continue
                if whole and len(whole[-1]) >= WRAP \
                        and whole[-1][-1] not in "。？！”』）)…":
                    # only as far as the sentence it was cut out of: what follows the
                    # first full stop is the next example, run on without a separator
                    stop = re.search(r"[。！？]", c)
                    cut = stop.end() if stop else len(c)
                    whole[-1] += c[:cut]
                    c = c[cut:].strip()
                    if not c:
                        continue
                whole.append(c)
        cases = [(c, unindex(c, r)) for c in whole]
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
                    "".join(sentence_words(x, point) for x in lines),
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
        return syllable("".join(numbered(x) for x in read))

    # Some of what the syllabus files as a case is a pair of phrases rather than a
    # sentence -- 次 opens with 去一次、看一次 -- and a phrase shows the word without
    # showing it doing anything. A whole sentence is preferred wherever there is one,
    # and the order among those is untouched.
    ENDS = re.compile(r"[。？！]\s*$")
    example_sentence = {}
    inside = {}
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
            example_sentence.setdefault((word, spoken_as(read)), shown)
            # An affix is never a word of a sentence: 子 is a suffix in 孩子 and 桌子
            # and stands alone nowhere. The character is keyed on the syllable that
            # word gives it, so the reading still has to be the one the card teaches
            # -- 子系统 reads 子 as zǐ and does not answer for the light one.
            if len(word) == len(read) > 1:
                for i in (0, len(word) - 1):
                    inside.setdefault((word[i], spoken_as([read[i]])), shown)

    return Sentences(decks=list(grammar_decks.values()),
                     example_sentence=example_sentence,
                     inside=inside,
                     wanted_audio=wanted_audio,
                     audio_for=sentence_audio,
                     py_stats=py_stats)

"""What a card says about the characters a word is made of."""
import collections
import csv
import html
import json
import re

from syllabus import LEVELS
from deck.paths import BUILD, RAW, ROOT
from deck.notation import CJK, POINTER, SANDHI, cedict_lines, char_rank, citation_readings, clean_xrefs, sense_key, short_gloss, syllable, toned
from deck.etymology import load_etymology


Glossary = collections.namedtuple(
    "Glossary",
    "cedict_defs char_any shown_chars pick_char components part_origins"
    " etym_block examples example_of example_word undrawn")


def read_glossary(words, wiki, readings, pos) -> Glossary:
    """What a character means, what it is made of, and the words it is met in.

    A vocabulary card glosses the characters inside its word and a writing card
    glosses the character itself; both ask the same questions of the same tables,
    so the tables are read once and the answers shared. These are closures because
    they are one apparatus over one body of state, not eight separate ideas.
    """
    neutralised = citation_readings()
    char_by_reading = {}
    char_any = {}
    cedict_defs = {}
    points_at: dict = {}
    for line in cedict_lines():
        m = re.match(r"^(\S+) (\S+) \[([^]]*)\] /(.*)/$", line)
        if not m:
            continue
        trad, simp, reading, body = m.groups()
        # Every sense, since the deck does not work out which one a sentence draws on
        # and cutting the list decides it by accident: 别浪费时间了 is "don't waste time"
        # and the first three senses of 别 are to leave, to differentiate and to turn
        # aside, so the card said everything except what the sentence meant. Likewise
        # 若 without "if" and 跟 without "compared with".
        all_senses = [d for d in body.split("/") if not d.startswith("CL:")]
        senses = all_senses
        if senses:
            # Candidates keyed by reading, the way the vocabulary path chooses, with
            # the case left alone: CC-CEDICT capitalises a proper noun's reading, so
            # 那 [Na4] "surname Na" cannot match a sentence reading nà written [na4].
            entry = (trad, clean_xrefs(" / ".join(senses)),
                     reading.replace(" ", "").replace("u:", "v"), len(senses), False)
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
            # An entry can define the character a little and hand the rest over: 台 at
            # tai2 gives "(classical) you (in letters)" and points at 臺 for everything
            # else, which is where "broadcasting station" lives and so where the 台 of
            # 电视台 is answered. Noted while the pointer is still readable, since only
            # the defining senses are kept above.
            for d in all_senses:
                if (p := re.match(r"^(?:old )?variant of ([㐀-鿿豈-﫿]+)", d)):
                    points_at[key + (trad,)] = p.group(1)
    # "see 苏州市" is a direction to look elsewhere, not a meaning, and on a sentence
    # card there is nowhere to look. Where every sense of an entry points at another
    # word, say what that word says instead.
    target_of = re.compile(r"^(?:see(?: also)?|(?:old |erhua )?variant of|abbr\. for"
                           r"|erhua form of|used in)\s+([㐀-鿿豈-﫿]+)")
    for k, entries in cedict_defs.items():
        for i, (trad, gloss, reading, n, _borrowed) in enumerate(entries):
            if not POINTER.match(gloss):
                continue
            m = target_of.match(gloss)
            if not m:
                continue
            # At the reading that was pointed from, before anything else. 着 is entered
            # four times over as a variant of 著 at four readings, and the target has an
            # entry for each: 挂着 is zhe, the aspect particle, and taking whichever
            # entry came first made it 着 zhāo, a move in chess.
            aimed = cedict_defs.get(m.group(1), [])
            same = [o for o in aimed if o[2] == reading]
            for other in same + aimed:
                if not POINTER.match(other[1]):
                    # Marked as borrowed: the senses are another entry's, and which
                    # entry is settled by the order they were read in, so this cannot
                    # speak for the word the way one with senses of its own can. 只
                    # zhī points at 隻 the classifier and lands on 秖 "grain that has
                    # begun to ripen", the entry that happens to come first.
                    entries[i] = (trad, other[1], reading, other[3], True)
                    break
    etym_char = load_etymology()

    char_meta = json.loads((BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    # Wiktionary names a character's parts in their traditional forms while the deck's
    # tables are keyed on the simplified: 簡 is phonetic 間, and what the deck knows and
    # can gloss is 间. Only where the deck holds that character, so 閒 is left alone --
    # the 闲 the deck teaches is 閑, a different character that merely looks like it.
    deck_form = {v["traditional"]: c for c, v in char_meta.items()
                 if v.get("traditional") and v["traditional"] != c}

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
        # 佔's own entry says only "variant of 占": keep the form, borrow the meaning.
        # So does an entry that defines the character a little and points at another
        # form for the rest -- 台 is "(classical) you (in letters)", which is no account
        # of the 台 in 电视台, and 臺 is where the broadcasting station is.
        aimed = [c for c in cands
                 if c[0] == points_at.get((ch, reading.lower(), chosen[0]))]
        borrow = max(aimed, key=char_rank) if aimed else best
        if chosen[2] and not aimed:
            return chosen
        return (chosen[0], borrow[1], borrow[2], borrow[3], chosen[4])

    # The simplified form's account stands beside the traditional one rather than
    # inside it. Opacity composites a whole subtree, so a block nested in the origin
    # is dimmed by the origin as well as by the glosses around it, and 脑's link would
    # read a shade darker than every other link on the card.
    LATER = '<div class="later">'

    def origin_block(origin: str) -> str:
        first, sep, later = origin.partition(LATER)
        return (f'<div class=origin>{first}</div>'
                + (LATER + later if sep else ""))

    # A character is written one way on its own and another inside another character.
    # The dump says so from the form's end -- 氵 is "radical form of 水" -- so the map
    # arrives the other way round and is turned over here. data/radical-forms.csv
    # carries the pairs it words differently, or does not word at all.
    radical_forms: dict[str, list] = collections.defaultdict(list)
    for form, parent in (
            json.loads((BUILD / "radical-of.json").read_text(encoding="utf-8"))
            if (BUILD / "radical-of.json").exists() else {}).items():
        radical_forms[parent].append((form, ""))
    named_forms = ROOT / "data/radical-forms.csv"
    if named_forms.exists():
        for r in csv.DictReader(named_forms.open(encoding="utf-8")):
            here = radical_forms[r["character"]]
            if r["form"] not in [f for f, _ in here]:
                here.append((r["form"], r["where"]))

    def as_a_part(ch: str) -> str:
        """The shape the character takes when it stands inside another one.

        水 is written 氵 in 洗 and 言 is 讠 in 说, and the card said so from one end
        only: 氵's own row calls itself the radical form of 水, while a reader who
        looked up 水 was told nothing. Both where there are two -- 金 is 釒 inside a
        traditional character and 钅 inside a simplified one -- and where two characters
        share a shape it says which is which: 阝 is 阜 on the left of 阳 and 邑 on the
        right of 都.
        """
        forms = radical_forms.get(ch) or []
        if not forms:
            return ""
        return ('<div class=asPart>written '
                + " or ".join(f"<b>{wiki.label(f, f)}</b>{f' {side}' if side else ''}"
                              for f, side in forms)
                + " inside another character</div>")

    # Which of a character's senses a word draws on. The row lists the character's
    # senses in the dictionary's order, and 要's opens on "to want": under 重要 it is
    # "(bound form) important" that the word is made of, and the row leads with it.
    draws_on: dict = {}
    path = ROOT / "data/compound-senses.csv"
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            draws_on[(r["word"], r["character"])] = r["sense"]
    drawn: set = set()

    def leading(senses: list, lead: str) -> list:
        """The senses with the one named first, or as they were if none is it."""
        hit = [i for i, s in enumerate(senses) if lead and sense_key(s) == sense_key(lead)]
        return ([senses[hit[0]]] + senses[:hit[0]] + senses[hit[0] + 1:]) if hit else senses

    def undrawn() -> list:
        """Rows of data/compound-senses.csv naming a sense no card showed."""
        return sorted(set(draws_on) - drawn)

    def under_pos(ch: str, reading: str, senses: str, lead: str = "") -> str:
        """The row's senses set out under the parts of speech the syllabus divides them
        into, or nothing where it divides them into one.

        比 is a verb, a preposition and a noun, and which of "to compare / more {adj.}
        than {noun} / ratio / to gesture" is which is already written down -- the same
        division the word's own card is headed by. The row ran all four together, so
        the character read on its own card and the character read inside a word were
        two different-looking things.

        The senses are the row's own, relabelled and no more: a division naming a sense
        the row does not carry names nothing, and a sense the division does not reach
        keeps a block at the end. The dictionary reads 点 in more ways than the
        syllabus teaches it, and none of them is dropped for going unlabelled.
        """
        blocks = pos.divided(readings.entries.get(ch, []), reading)
        if len(blocks) < 2:
            return ""
        here = [x.strip() for x in senses.split("/") if x.strip()]
        at = collections.defaultdict(list)
        for i, s in enumerate(here):
            at[sense_key(s)].append(i)
        out, used = [], set()
        for p, m, taught, lv in blocks:
            mine = []
            for s in m.split("/"):
                if at.get(sense_key(s)):
                    i = at[sense_key(s)].pop(0)
                    used.add(i)
                    mine.append(here[i])
            if mine:
                out.append((p, mine, taught, lv))
        if not out:
            return ""
        rest = [s for i, s in enumerate(here) if i not in used]
        # The block holding the sense the word draws on comes first, that sense at its
        # head: 重要's 要 is an adjective before it is a verb.
        rows = [(p, leading(mine, lead), taught, lv) for p, mine, taught, lv in out]
        if rest:
            rows.append((None, leading(rest, lead), True, ""))
        rows.sort(key=lambda r: not (lead and sense_key(r[1][0]) == sense_key(lead)))
        # A part of speech the syllabus does not teach is set aside as "also" -- unless
        # it is the one this word is made of, which leads the row and is set as such,
        # though with no level to give it.
        drawn_on = lead and rows and sense_key(rows[0][1][0]) == sense_key(lead)
        return "".join(
            (f'<div class="charSense{"" if taught or (drawn_on and i == 0) else " beyond"}">'
             f'{"" if taught or (drawn_on and i == 0) else "also "}'
             f'{pos.label(p)}{pos.at_level(lv, taught)} '
             if p else '<div class=charSense>')
            + f'{wiki.markup(html.escape(" / ".join(mine), quote=False))}</div>'
            for i, (p, mine, taught, lv) in enumerate(rows))

    def components(simplified: str, numbered: str = "",
                   traditional: str = "") -> str:
        """One entry per character: what it means, then where the glyph came from.
        The whole account, wherever the row stands -- 较 under 比较 is the same
        character as 较 on its own card, and cutting its account to the lead there
        dropped the paragraph saying the phonetic was 爻 before it was 交.

        The reading decides the senses: 长 is "long" in 长处 and "chief" in 校长, and a
        card showing one while saying the other is simply wrong. Where the syllables do
        not line up with the characters, fall back to the character's usual senses.

        Not which sense a compound draws on -- Wiktionary records that for six words in
        the whole dump -- so 机 is listed as machine, opportunity and aircraft alike.
        """
        chars = [c for c in simplified if CJK.match(c)]
        sylls = [x for x in numbered.split(" ") if x]
        # Every way the word reads the character, in the order it reads them: 一模一样
        # is yì mú yí yàng and one row answers for both 一. A reduplication reads its
        # second syllable light -- 爸爸 is bàba -- and the tone is put back below, so
        # 爸 is said once.
        heard = collections.defaultdict(list)
        if len(chars) == len(sylls):
            for c, s in zip(chars, sylls):
                if s not in heard[c]:
                    heard[c].append(s)
        reading_of = {c: entry_reading(c, syllable(ss[0].split("/")[0]))
                      for c, ss in heard.items()}
        trad_of = (dict(zip(chars, traditional))
                   if len(traditional) == len(chars) else {})
        out = []
        for ch in dict.fromkeys(chars):
            by_reading = pick_char(ch, reading_of.get(ch, ""),
                                   trad_of.get(ch, (char_meta.get(ch) or {})
                                               .get("traditional") or ch))
            if by_reading:
                trad = by_reading[0]
                senses = by_reading[1]
            else:
                senses = (char_meta.get(ch) or {}).get("meaning", "")
                senses = clean_xrefs(" / ".join(
                    p.strip() for p in senses.split("/") if p.strip()))
                trad = (char_meta.get(ch) or {}).get("traditional") or ch
            origin = etym_char(ch, full=True)
            if not (senses or origin):
                continue
            label = ch if trad == ch else f"{ch} ({trad})"
            # The character's own reading, not the word's: 朋友 is péngyou and 友 is
            # yǒu. A compound flattens a tone and the row beneath it restores one.
            #
            # The senses are one reading's, so the heading is one reading's too. A
            # writing card is handed every reading the syllabus teaches, and heading
            # 还 with "hái / huán" above hái's senses left huán's -- to pay back, to
            # return -- nowhere on the card. The rest drop to the rows beneath, which
            # gloss each reading they name. Two spellings of one reading stay together:
            # 谁 is entered as one word said two ways, shei2/shui2, and both are the
            # reading of the character in front of you.
            spoken_here, shown, worn = [], set(), []
            for syll in heard.get(ch, []):
                for part in syll.split("/"):
                    if not part:
                        continue
                    part = syllable(part)
                    said_as = neutralised.get((ch, part), part)
                    entry = entry_reading(ch, said_as)
                    if shown and entry not in shown and ch not in readings.variant:
                        continue
                    shown.add(entry)
                    t = toned(said_as)
                    if t not in spoken_here:
                        spoken_here.append(t)
                    # The convention wrote a change into the word above this row -- 一
                    # before a fourth tone is yì -- and the row cites yī, so it says
                    # which. A neutral tone is not worth saying: the word spells it
                    # light and the row spells it out, and that is the whole of it.
                    if (ch, part) in SANDHI and toned(part) not in worn:
                        worn.append(toned(part))
            said = " / ".join(spoken_here)
            if said and worn:
                said += (' <span class=sandhi>(' + " / ".join(worn) + " here)</span>")
            lead = draws_on.get((simplified, ch), "")
            split = [x.strip() for x in senses.split("/") if x.strip()]
            if lead and any(sense_key(s) == sense_key(lead) for s in split):
                drawn.add((simplified, ch))
                senses = " / ".join(leading(split, lead))
            body = (f'<b>{wiki.label(label, trad)}</b>'
                    f'{f" <span class=charRead>{said}</span>" if said else ""} '
                    f'{under_pos(ch, reading_of.get(ch, ""), senses, lead)
                       or wiki.markup(html.escape(senses, quote=False))}'
                    f'{also_read(ch, shown or spoken_numbers(ch, heard))}'
                    f'{as_a_part(ch)}')
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
    # An account that spells the sum out in words rather than writing it with a plus:
    # 意 is "Modern form is a compound of 音 and 心".
    COMPOUND = re.compile(rf"compound of ({PART})\s*(?:\([^)]*\))?\s*and\s+({PART})")

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

    # A part can be named twice over: once as the shape the character was built from,
    # and again as the shape that became. 般 is "the proto-form of 盤 + 攴", and the
    # sentence after says 盤 was corrupted into 舟 and 攴 evolved into 殳 -- the two
    # halves actually on the page. Both earn a row: one says where the character came
    # from, the other says what the reader is looking at. Read past the lead for this
    # and nothing else, since a shape the account says the character now carries is not
    # the loose comparison the rest of the prose is full of.
    # Whether the character carries that shape is a question about the glyph and not
    # about the prose, and the prose alone gets it wrong: the same sentence pattern says
    # 子 corrupted into 于 under 智, which is 知 over 日 and has no 于 in it. So the shape
    # is looked up, in the Ideographic Description Sequences: 般 is ⿰舟殳. A part can sit
    # further down -- 邑 is inside the 邕 of 雝 -- so the breakdown is followed all the
    # way. Where the regions disagree about a character both answers are read, since a
    # part named by any of them is a part the reader may be looking at: 寒 is ⿱𡨄⺀ to
    # four of them and ⿱𡨄冫 to Korea, and 冫 is the 仌 the account names.
    BECAME = re.compile(rf"(?:corrupt(?:ed)?|evolved|develop(?:ed)?|chang(?:ed)?"
                        rf"|merged|turn(?:ed)?|deform(?:ed)?)\s+(?:in)?to\s+({PART})",
                        re.I)
    IS_PART = re.compile(PART)
    REGION = re.compile(r"\[[A-Z]*\]")
    # Kept in the order the breakdown writes them, not as a set: these become rows on a
    # card, and a set of characters is ordered by a hash Python seeds afresh each run,
    # so the same source built twice put 环节's parts in two different orders.
    breaks_into: dict[str, dict] = collections.defaultdict(dict)
    for line in (RAW / "ids.txt").read_text(encoding="utf-8").splitlines():
        row = line.split("\t")
        if line.startswith("#") or len(row) < 3:
            continue
        breaks_into[row[1]].update(dict.fromkeys(
            c for alt in row[2:] for c in REGION.sub("", alt)
            if IS_PART.match(c) and c != row[1]))

    # A radical is written one way and named another: makemeahanzi breaks 焦 into 隹 and
    # 灬, and the sentence saying 小 corrupted into 火 is talking about that 灬. So a
    # shape answers for the character it is the radical form of as well as for itself.
    same_shape: dict[str, set] = collections.defaultdict(set)
    for name in ("redirects.json", "radical-of.json"):
        if (BUILD / name).exists():
            for shape, target in json.loads(
                    (BUILD / name).read_text(encoding="utf-8")).items():
                same_shape[shape].update(
                    target if isinstance(target, list) else [target])

    def shapes_in(ch: str) -> set:
        seen, queue = set(), list(breaks_into.get(ch, ()))
        while queue:
            c = queue.pop()
            if c not in seen:
                seen.add(c)
                queue += breaks_into.get(c, ())
        return seen | {t for s in seen for t in same_shape.get(s, ())}

    def account(ch: str) -> str:
        """The character's own account of its shape, without the prose that wanders off
        it and without the separate account of the simplified form."""
        text = etym_char(ch, full=True) or ""
        return re.split(r'<div class="(?:more|later)">', text)[0]

    # Wiktionary takes the traditional character apart -- 輕 is semantic 車 plus phonetic
    # 巠 -- and says in the same breath what the simplified one writes instead: 車 → 车
    # and 巠 → 𢀖. Both are worth a row and neither answers for the other: 巠 is why 轻
    # sounds as it does, 𢀖 is the mark on the page. deck_form reaches only a shape the
    # deck teaches in its own right, which 车 is and 𢀖 is not. Wiktionary has an account
    # of 𢀖, and of 讠 and 饣, as cursive and as the 1956 scheme's own components.
    ARROW = re.compile(rf"({PART})\s*(?:→|->|⇒)\s*({PART})")

    def simplification(ch: str) -> str:
        """How the simplified character came to be written that way.

        Usually an account of its own, set apart from the account of the shape it was
        simplified from. Where there is nothing else to say it is the whole account:
        訝's shape is explained and 讶's entry reads only "Simplified from 訝 (訁 → 讠)",
        so both places are read.
        """
        parts = re.split(r'<div class="later">', etym_char(ch, full=True) or "")
        # The opening paragraph is where the shape is named -- "Simplified from 訝
        # (訁 → 讠)" -- and the paragraphs under it carry the history in prose, where
        # a shape is mentioned rather than put in place.
        return (parts[1].split('<div class="more">')[0] if len(parts) > 1
                else parts[0])

    def lead(ch: str) -> str:
        return account(ch).split(". ")[0]

    def named_parts(head: str) -> list:
        """The parts an account takes the character apart into, before any pointer
        is followed. The guard below needs this much of the answer and no more, so
        following one pointer cannot set off another."""
        # Most accounts name the parts around a plus sign or by their role. A few say
        # it in words instead -- 意 is "a compound of 音 and 心" -- and read only by
        # the two patterns above, those characters end up with no parts at all.
        return (ROLE.findall(head) or either_side(head)
                or [c for pair in COMPOUND.findall(head) for c in pair])

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
        # Then the shapes the account says this character came to carry: one a part
        # corrupted or evolved into, and one simplification put in a part's place. The
        # part it replaced keeps its row, since neither answers for the other -- 巠 is
        # why 轻 sounds as it does and 𢀖 is the mark on the page. Which part an arrow
        # replaced is not worth working out: Wiktionary analyses 說 as 言 and writes the
        # simplification as 訁 → 讠, so the two ends do not even match. The breakdown
        # settles whether the shape is there, which is the whole question.
        # 朴 is a case of its own: 樸 is 木 plus phonetic 菐, and the simplified
        # character is not that at all but 木 plus phonetic 卜, which its own account
        # says in full rather than as an arrow. So that account is taken apart too.
        carries = shapes_in(ch)
        later = simplification(ch)
        named = (BECAME.findall(account(ch))
                 + [b for _, b in ARROW.findall(later)]
                 + named_parts(later))
        found = found + [c for c in named if c in carries]
        # An account can be about a shape the card does not show, and then none of the
        # parts it names is in the character at all. 響 is 鄉 + 音, and 响 on the page is
        # 口 + 向: the origin is fetched from the traditional page because 响 has no
        # Chinese section of its own, and it says nothing about the simplified form. 退
        # is the same from the other direction, taken apart as its oracle bone form,
        # 皀 + 夊, where what is written is 辶 and 艮. The account keeps its rows, since
        # it is why the character sounds and means what it does; the breakdown answers
        # for what is on the page.
        if found and not any(c in carries or c in ch for c in found):
            found += [c for c in breaks_into.get(ch, ()) if c != ch]
        return [c for c in dict.fromkeys(found) if c != ch]

    # How often each character is read each way across the words the syllabus teaches.
    in_words = collections.Counter()
    for w in words:
        chars = [c for c in w["simplified"] if CJK.match(c)]
        sylls = [x for x in w["pinyin_numbered"].split(" ") if x]
        if len(chars) == len(sylls):
            for c, s in zip(chars, sylls):
                in_words[(c, syllable(s))] += 1

    def also_read(ch: str, already: set) -> str:
        """Every other way the dictionary reads the character, and what it means then.

        A row heads with the reading in front of the learner and gives the rest beneath
        it, so a character is never met as less than it is: 长 is cháng in 长处 and the
        reader who meets 校长 next has been told it is also zhǎng; 子 is the suffix of
        包子 and also zǐ, son and child. Readings the dictionary lists without defining
        are left out -- there is nothing to say under them.
        """
        out = ""
        for r in dictionary_readings(ch, every=True):
            if r in already:
                continue
            if (m := gloss_at(ch, r)):
                out += (f'<div class=alsoRead><span class=charRead>{toned(r)}</span> '
                        f'{wiki.markup(html.escape(m, quote=False))}</div>')
        return out

    def part_numbers(ch: str) -> list:
        """The readings part_readings puts on the row, in that order, as the dictionary
        numbers them."""
        taught = list(dict.fromkeys(n for _, n, _ in readings.by_char.get(ch, [])))
        return taught or dictionary_readings(ch)

    def part_readings(ch: str) -> str:
        """How a part is read, where the card names one it is built from.

        A part is not a word of the sentence, so there is no syllable to take from the
        reading above it -- 竹 and 亼 are just characters, and the card should say what
        they sound like. Where the deck teaches the character on its own, those are the
        readings that matter and they come in the order it teaches them: 长 is cháng
        before zhǎng. Where it never does, the dictionary's own, the fullest first --
        单 is dān and not the surname Shàn, and 行 is xíng and not héng -- and two at
        most, because a part read four ways is telling you about 夹 and not about the
        character in front of you.
        """
        taught = list(dict.fromkeys(m for m, _, _ in readings.by_char.get(ch, [])))
        if taught:
            return " / ".join(taught)
        return " / ".join(toned(r) for r in dictionary_readings(ch))

    def entry_reading(ch: str, spoken: str) -> str:
        """The reading whose entry answers for a syllable the dictionary does not list.

        A word bends a character's tone and wears it down: 一定 says yí where the
        dictionary has only yī, and 晚上 says shang where it has shǎng and shàng. The
        entry that stands in is the one for the same syllable the deck reads oftenest, so
        a row glosses the reading it prints rather than gathering every sense the
        character has under every reading -- and the reading it borrowed from is not
        then repeated beneath it as though it were something else.
        """
        if gloss_at(ch, spoken):
            return spoken
        base = re.sub(r"[0-9]", "", spoken)
        for r in dictionary_readings(ch, every=True):
            if re.sub(r"[0-9]", "", r) == base:
                return r
        return spoken

    def spoken_numbers(ch: str, heard) -> set:
        """The readings a word gives a character, as the dictionary numbers them."""
        out = set()
        for syll in heard.get(ch, []):
            for part in syll.split("/"):
                if part:
                    part = syllable(part)
                    out.add(entry_reading(ch, neutralised.get((ch, part), part)))
        return out

    # Which traditional character the deck means by a simplified one at a given
    # reading. 只 is two characters: 隻 read zhī and 只 read zhǐ.
    taught_trad = {(c, num): trad
                   for c, ways in readings.by_char.items()
                   for _, num, trad in ways}

    def gloss_at(ch: str, reading: str, depth: int = 0) -> str:
        """What the character means when it is read that way.

        Among entries sharing a reading the traditional form the deck teaches decides,
        as it does when the reading is the one being taught: 只 read zhī is 隻 the
        classifier and not 秖, "grain that has begun to ripen", a different character
        that happens to share the simplified form. An entry that only points elsewhere
        is followed rather than shown -- 甚 read shén is "variant of 什", and what a
        reader wants there is what 什 means.
        """
        want = taught_trad.get((ch, reading))
        best = None
        for e in char_any.get(ch, []):
            if syllable(e[4]) != reading:
                continue
            rank = (e[0] == want,) + tuple(char_rank(e))
            if best is None or rank > best[0]:
                best = (rank, e)
        if not best:
            return ""
        gloss = best[1][1]
        if depth < 2 and POINTER.match(gloss):
            aimed = re.search(r"(?:variant of|see|abbr\. for)\s+([㐀-鿿豈-﫿]+)", gloss)
            if aimed and aimed.group(1) != ch:
                return gloss_at(aimed.group(1), reading, depth + 1) or gloss
        return gloss

    def dictionary_readings(ch: str, every: bool = False) -> list:
        """The readings the dictionary gives a character, the fullest first.

        Two at most unless every one is asked for -- a character read four ways is
        telling you about 夹 and not about the character in front of you.
        """
        best = {}
        for e in char_any.get(ch, []):
            r = syllable(e[4])
            # How often the syllabus reads the character that way, first: 衣 is not
            # taught on its own and the dictionary defines yì at more length than yī,
            # while every word the deck has -- 衣服, 毛衣 -- says yī. A surname reading
            # is not the word, and length of definition decides what is left.
            key = (-in_words[(ch, r)], e[4][:1].isupper(), -e[2])
            if r not in best or key < best[r]:
                best[r] = key
        keep = sorted(best, key=lambda r: best[r])
        if every:
            return keep
        # Choosing which two to headline, a light syllable beside a toned one is that
        # tone worn down and not a reading to spend a line on. Every reading is another
        # matter: the dictionary enters 子 as zi5 as well as zi3, and the noun suffix
        # is a meaning the other reading does not carry.
        toneful = {re.sub(r"[0-9]", "", r) for r in best if not r.endswith("5")}
        return [r for r in keep
                if not (r.endswith("5") and re.sub(r"[0-9]", "", r) in toneful)][:2]

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
        out, drawn, printed = [], 1, set()
        while queue:
            ch, step = queue.pop(0)
            ch = deck_form.get(ch, ch)
            if ch in seen:
                continue
            seen.add(ch)
            shown_chars.add(ch)
            queue += [(c, step + 1) for c in made_of(ch)]
            # The whole account, as the card teaching that character gives it. Cut to
            # its lead, 退 under 腿 read only as its oracle bone form and stopped before
            # the two paragraphs saying the vessel 皀 became 艮 and what Shuowen made of
            # it -- which is the part of it about the shape on the page.
            origin = etym_char(ch, full=True)
            if not origin:
                continue
            # Once. A radical form borrows its parent's whole account and names it as
            # the parent's -- "Radical form of 手. Pictogram ..." -- and the parent's
            # own row then said it all again. The first telling stands, whichever
            # shape brought it; the later row keeps its gloss line, which is the one
            # thing the borrowing row does not carry.
            key = re.sub(r"^(?:Radical form of|Also written|Explained under)"
                         r" .{1,4}\.\s*", "", re.sub("<[^>]+>", "", origin))[:100]
            if key in printed:
                origin = ""
            else:
                printed.add(key)
            if step > drawn and out:
                out.append('<hr class=partStep>')
                drawn = step
            # What the part means when it is read the way the row says it is, so the
            # readings beneath add to the heading instead of repeating it. char-meanings
            # gathers a character's senses without regard to reading -- 子 is the suffix
            # and son and child and the first earthly branch all at once -- and stands in
            # only where the dictionary has nothing under any reading.
            here = part_numbers(ch)
            senses = " / ".join(g for g in (gloss_at(ch, r) for r in here) if g)
            trad = (char_meta.get(ch) or {}).get("traditional") or ch
            if not senses:
                senses = clean_xrefs(" / ".join(
                    p.strip() for p in
                    (char_meta.get(ch) or {}).get("meaning", "").split("/") if p.strip()))
            if not senses:
                # char-meanings.json covers the characters the syllabus words are made
                # of, and a part is not one: 攵 is absent from it while the dictionary
                # calls it a variant of 攴, and 扌 the hand radical.
                best = max((char_any.get(ch) or []),
                           key=lambda e: (e[2], e[3]), default=None)
                if best:
                    senses = best[1]
                    trad = best[0]
            # A part the dictionary only points elsewhere for explains nothing: 夊 is
            # entered as "see 夂", and 退 answered what it is built from with a
            # cross-reference. The character it points at is the same shape rather than
            # a part of it, so it joins this step instead of opening another, and
            # arrives with its own gloss and its own account.
            if senses and POINTER.match(senses):
                aimed = re.search(PART, senses)
                if aimed and aimed.group() not in seen:
                    queue.insert(0, (aimed.group(), step))
            label = ch if trad == ch else f"{ch} ({trad})"
            said = part_readings(ch)
            body = (f'<b>{wiki.label(label, trad)}</b>'
                    f'{f" <span class=charRead>{said}</span>" if said else ""} ')
            if not senses and not origin:
                continue
            if senses:
                body += wiki.markup(html.escape(senses, quote=False))
            body += also_read(ch, set(here)) + as_a_part(ch)
            out.append(f'<div class="gloss">{body}'
                       f'{origin_block(origin) if origin else ""}</div>')
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
        ways = readings.by_char.get(ch, []) or []
        out = []
        needed = False
        for _, num, _ in ways:
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
                                              for _, num, _ in ways):
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

    def examples(ch: str, level: str = "") -> list:
        """The words a writing card cites, as (word, pinyin, meaning)."""
        return examples_of(ch) + (also_seen(ch, level) if level else [])

    def example_of(ch: str, level: str = "") -> str:
        """The examples with no characters, for the side that asks you to write it.

        The same words the answer gives, so the two sides say the same thing about
        where the character is met; only the characters are held back, since writing
        one of them is what is being asked.
        """
        rows = "".join(
            f'<div class=example><span>as in</span>'
            f'<span class=exPinyin>{html.escape(p, quote=False)}</span>'
            f'<span>&mdash; {html.escape(m, quote=False)}</span></div>'
            for _, p, m in examples(ch, level))
        return f'<div class=examples>{rows}</div>' if rows else ""

    def etym_block(ch: str, numbered: str = "") -> str:
        """What a writing card says about the character it asks for: the same row a
        vocabulary card gives each character of its word, and the fuller account of
        the glyph. A card about one character can afford to say everything about it,
        so it does, headline and all.
        """
        # A character the syllabus never lists on its own has no reading from the
        # syllabus either, and 物 should still say wù.
        return components(ch, numbered or " ".join(dictionary_readings(ch)[:1]),
                          (char_meta.get(ch) or {}).get("traditional") or ch)

    def example_word(ch: str, level: str = "") -> str:
        """The same examples with their characters, for the side that has answered.

        Every word is written out the same way, one to a line. A list of bare words
        after them -- also in 动物园 · 礼物 -- reads as an afterthought and asks the
        reader to hold three things at once; the same three lines read as three.
        """
        rows = "".join(
            f'<div class=example><span>as in</span>'
            f'<span><b>{wiki.markup(html.escape(w, quote=False))}</b> '
            f'<span class=exPinyin>{html.escape(p, quote=False)}</span></span>'
            f'<span>&mdash; {html.escape(m, quote=False)}</span></div>'
            for w, p, m in examples(ch, level))
        return f'<div class=examples>{rows}</div>' if rows else ""

    return Glossary(cedict_defs=cedict_defs, char_any=char_any,
                    shown_chars=shown_chars,
                    pick_char=pick_char, components=components,
                    part_origins=part_origins, etym_block=etym_block,
                    examples=examples,
                    example_of=example_of, example_word=example_word,
                    undrawn=undrawn)

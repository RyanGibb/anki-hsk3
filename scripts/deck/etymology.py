"""Where a character comes from, as Wiktionary tells it."""
import csv
import html
import json
import re

from glyph_origin import about_the_glyph, any_about_the_glyph
from deck.paths import BUILD, ROOT
from deck.notation import WORDS, gloss_words, mend


# Wiktionary writes a list two ways: bulleted, and as a definition list whose term is
# marked and whose description is the plain paragraph after it.
BULLET = re.compile(r"^([*#;]+)\s*")
# How long an item of a list can be and still be read as part of the sentence that
# promises it. "Square or round block" is one of 天's four head variants and belongs
# in the line naming them; each of 水's eight proposals for where the word comes from
# runs to several sentences of its own, and semicolons between those read as breaks
# in the middle of a sentence.
AS_A_PHRASE = 120


# How Wiktionary writes an account of a character's shape, as opposed to the history
# of the word it spells.
GLYPH = re.compile(r"phono-semantic|ideogrammic|pictogram|指事|象形|會意|形聲"
                   r"|simplified from|originally written|oracle bone"
                   r"|bronze (script|inscription)|seal script", re.I)


def load_etymology():
    """character -> its Wiktionary glyph origin, keyed on the TRADITIONAL form: the
    etymology of 條 says nothing about the shape of 条."""
    etym = json.loads((BUILD / "etymology.json").read_text(encoding="utf-8"))
    info = json.loads((BUILD / "char-meanings.json").read_text(encoding="utf-8"))
    trad = {c: (v.get("traditional") or c) for c, v in info.items()}

    # wiktextract keeps an etymology only where it sits under a sense, so a "Glyph
    # origin" section beside the Etymology sections is missing from the dump, and where
    # the dump kept a borrowing instead the slot is full but says nothing about the
    # shape. fetch-glyph-origins.py reads those sections off the page itself.
    origins = ROOT / "data/glyph-origins.csv"
    if origins.exists():
        for row in csv.DictReader(origins.open(encoding="utf-8")):
            if row["text"] and not any_about_the_glyph(etym.get(row["character"])):
                etym[row["character"]] = [{"text": row["text"], "type": row["type"],
                                           "glosses": [], "senses": 0}]

    # A page that only says "see X" has no account of its own, and the deck shows such
    # characters as the parts of others: 餐 is phonetic 𣦼, whose shape is explained
    # under 𣦻, and 故 is semantic 攵, explained under 攴. The variant's account is used
    # and said to be the variant's. Two things have to hold. The target must give the
    # character as a form of itself, which is Wiktionary saying the two shapes are one
    # character: 攵 points at both 攴 and 文, and only 攴 claims it. And the target's
    # account must not name the character, since 繼 as "semantic 糸 + phonetic 㡭"
    # explains 繼 out of 㡭 rather than explaining 㡭.
    redirect = json.loads((BUILD / "redirects.json").read_text(encoding="utf-8")) \
        if (BUILD / "redirects.json").exists() else {}
    variant = json.loads((BUILD / "variants.json").read_text(encoding="utf-8")) \
        if (BUILD / "variants.json").exists() else {}
    # Where a part is written one way and explained under another, Wiktionary links the
    # two inside the glyph origin itself: 搬 shows 扌 and links 手. fetch-glyph-origins.py
    # reads those links off the pages, which is the only place they exist -- the dump is
    # plain text and drops them.
    # What a character says it is in its own entry, which outranks anything inferred:
    # 礻 is "Left radical form of 示", while the dump also carries a redirect from 礻 to
    # 衤, the clothing radical it merely resembles.
    radical_of = json.loads((BUILD / "radical-of.json").read_text(encoding="utf-8")) \
        if (BUILD / "radical-of.json").exists() else {}
    explained_by = {}
    links = ROOT / "data/glyph-links.csv"
    if links.exists():
        explained_by = {r["character"]: r["explained_by"]
                        for r in csv.DictReader(links.open(encoding="utf-8"))}

    def choose(ch: str) -> dict:
        """Which of a character's etymologies explains its shape.

        The card asks where the glyph came from, so a section that accounts for the
        graph beats one that accounts for the word: 吧 is borrowed from English "bar",
        but the character is 口 + 巴. Among sections that do explain the graph, the one
        whose glosses match the definition on the card wins -- 許 has a phono-semantic
        account and a separate one for the surname, and both are about the graph.
        """
        def borrow(other: str, lead: str) -> dict:
            """Another character's account, where it is an account of this one too."""
            for x in etym.get(other) or []:
                if ch not in x.get("text", "") and about_the_glyph(
                        x.get("text", ""), x.get("type", "")):
                    return dict(x, text=lead + x["text"])
            return {}

        sections = etym.get(trad.get(ch, ch)) or etym.get(ch) or []
        if not any(about_the_glyph(x.get("text", ""), x.get("type", ""))
                   for x in sections):
            taken = {}
            parent = radical_of.get(ch)
            if parent:
                taken = borrow(parent, f"Radical form of {parent}. ")
            for other in ([] if taken else
                          redirect.get(trad.get(ch, ch)) or redirect.get(ch) or []):
                if ch in (variant.get(other) or []):
                    taken = borrow(other, f"Also written {other}. ")
                if taken:
                    break
            linked = explained_by.get(ch)
            if not taken and linked:
                taken = borrow(linked, f"Explained under {linked}. ")
            if taken:
                sections = [taken]
        # A card asking where a glyph came from has no use for the history of the
        # word: 答 is "cognate with 對 … compare Tibetan", true and about the word,
        # while the graph's own account sits under 荅. Drop those outright rather
        # than ranking them last, so the fetched Glyph origin can take their place.
        sections = [x for x in sections
                    if about_the_glyph(x.get("text", ""), x.get("type", ""))]
        if len(sections) < 2:
            return sections[0] if sections else {}
        want = gloss_words((info.get(ch) or {}).get("meaning") or "")
        return max(sections, key=lambda e: (
            bool(e.get("type")) or bool(GLYPH.search(e["text"])),
            len(want & gloss_words(" ".join(e.get("glosses") or []))),
            e.get("senses", 0), len(e["text"])))

    def split_up(text: str) -> list[tuple[str, str]]:
        """The paragraphs, each with the list marker it carries.

        The dump can break one sentence across two paragraphs: 聿 opens "Pictogram
        (象形) or" and carries on "ideogrammic compound (會意 /会意): hand (又) holding a
        brush" below it. A paragraph that neither closes the sentence above it nor
        opens one of its own is the rest of that sentence, and the halves are put
        back together here so that wherever they land they land together -- 於 gave
        its second half alone and the card opened mid-sentence, on "from 于,
        essentially treating this phenomenon as xundu".
        """
        out = []
        for p in text.split("\n"):
            p = p.strip()
            # A paragraph carrying no word at all is what is left of something the
            # dump could not reproduce: 車 opens on a bare "]". The account is the
            # first paragraph, so an empty one would be the whole of it.
            if not (p and WORDS.search(p)):
                continue
            mark = BULLET.match(p)
            mark, p = (mark.group(1)[:1] if mark else ""), BULLET.sub("", p).strip()
            if out and not mark and p[:1].islower() \
                    and not re.search(r"[.!?:]$", out[-1][1]):
                out[-1] = (out[-1][0], f"{out[-1][1]} {p}")
            else:
                out.append((mark, p))
        # A term in a definition list names what the paragraph under it describes. With
        # nothing under it -- the account ends, or the next line is another term -- it
        # names nothing: 商 ended on "dynasty's name" and "“to trade” → “trader,
        # merchant”", the description of each lost from the dump.
        return [(m, p) for k, (m, p) in enumerate(out)
                if m != ";" or (k + 1 < len(out) and out[k + 1][0] != ";")]

    def joined(ps: list, k: int) -> tuple[str, int]:
        """The paragraph starting at k with the list under it pulled up, and where
        that list ends.

        "Two theories:" and "a standing man with four head variants:" head the items
        below them and say nothing alone. A term in a definition list is marked and its
        description is the plain paragraph after it, so that paragraph comes too: 幸
        read "Two kinds of glyph are found in Warring States era:" and stopped, with
        the Sanjin glyph and the Chu glyph each described a line below its own term.
        """
        head, i, items = ps[k][1], k + 1, []
        # Only where the head asks for them. A colon promises a list and says nothing
        # without it -- "Two kinds of glyph are found in Warring States era:" -- while
        # a head that closes itself is complete, and the bullets under it belong to
        # something else: 洛 is a phono-semantic compound, and what follows is a note
        # on clipping 洛必達法則 for l'Hôpital's rule.
        j = i
        while re.search(r"[:：]$", head) and j < len(ps) \
                and (ps[j][0] or ps[j - 1][0] == ";"):
            items.append(ps[j][1].rstrip("."))
            j += 1
        # Short ones are phrases and belong in the sentence promising them. Ones that
        # are paragraphs stay paragraphs: 水 lists eight proposals for where the word
        # comes from, several sentences each, and strung together on semicolons they
        # ran into one another. The colon is left standing and they follow it.
        if items and max(len(x) for x in items) > AS_A_PHRASE:
            return head, i
        if items:
            head = head.rstrip(":") + ": " + "; ".join(items) + "."
            i = j
        # A head still ending on a colon promises something that is neither a list nor
        # the rest of its own sentence, and a card showing only the lead never keeps
        # that promise: 竟 read "Uncertain. At least three theories exist:" and stopped
        # where the three theories are the paragraphs below. Taking them here keeps
        # them out of the tail, so nothing is said twice.
        while i < len(ps) and re.search(r"[:：]$", head):
            head = f"{head} {ps[i][1]}"
            i += 1
        return head, i

    def lead_of(ps: list) -> tuple[str, int]:
        return joined(ps, 0)

    def rest_of(ps: list, i: int) -> list[str]:
        """The paragraphs after the lead, each still a paragraph.

        Run together into one block they read as a single argument that keeps
        changing its mind: 人 goes from what 亼 is, to what 亻 is, to Sagart's
        cognate, to the two etymologies Schuessler proposes, without a break
        anywhere. Each one is read the way the lead is, so a list arrives as a list
        rather than as prose with its markers taken off.
        """
        out = []
        while i < len(ps):
            text, i = joined(ps, i)
            out.append(text)
        return out

    def paragraphs(ch: str) -> list[tuple[str, str]]:
        e = choose(ch)
        if not e:
            return []
        out = split_up(e["text"])
        # 夂 opens on "; Etymologies 1 and 3", the tail of a heading the dump kept and
        # no account of anything. The account is the first paragraph, so a first one
        # that says nothing about the glyph is dropped -- but only while a later one
        # does, since a character whose every paragraph fails the test still has to be
        # answered for by the one it has.
        while len(out) > 1 and not about_the_glyph(out[0][1], "") \
                and any(about_the_glyph(p, "") for _, p in out[1:]):
            out.pop(0)
        return out

    def simplification(ch: str) -> tuple[str, list]:
        """How the character came to be written the way the card writes it, as the
        opening paragraph and what follows it.

        An account keyed on the traditional form explains a shape the card does not
        show. 禮 is 礻 over phonetic 豊, and 礼 is not that: it is an ancient variant of
        禮 that the 1956 scheme brought back. Wiktionary files that under the simplified
        character, where the deck was passing over it -- 习 is 習 with 白 and 羽 gone,
        丝 is 絲 through the variant 𢇁, 专 is 專 in cursive.

        This account comes whole as any other does: opening on both forms 采 is found
        in and stopping before "The current glyph is of composition 2" said nothing
        about the one being written.
        """
        if trad.get(ch, ch) == ch:
            return "", []
        for x in etym.get(ch) or []:
            if about_the_glyph(x.get("text", ""), x.get("type", "")):
                ps = split_up(x["text"])
                if not ps:
                    break
                head, i = lead_of(ps)
                return head, rest_of(ps, i)
        return "", []

    def one(ch: str, full: bool) -> str:
        ps = paragraphs(ch)
        if not ps:
            return ""
        head, i = lead_of(ps)

        def tidy(text: str) -> str:
            return html.escape(mend(text), quote=False)

        head = tidy(head)
        # Two accounts of two shapes, so each is left whole and the simplified one comes
        # last: putting it between the lead and the rest cut 禮's account in two and
        # left "Originally written 豊, see there for more" hanging after 礼's.
        def quietly(paras: list) -> str:
            return "".join(f'<div class="more">{tidy(p)}</div>' for p in paras)

        later, after = simplification(ch)
        block = (f'<div class="later"><b><a href="https://en.wiktionary.org/wiki/'
                 f'{ch}#Chinese">{ch}</a></b> {tidy(later)}'
                 + (quietly(after) if full else "")
                 + '</div>'
                 if later and later not in head else "")
        # The section is chosen for being an account of the glyph, and then it comes
        # whole. Judging its paragraphs one by one cannot be done well from here --
        # 於 kept "Schuessler (2007) sees this pronunciation" and dropped the two
        # paragraphs saying whose pronunciation and why, and 礼 keeps its Tibetan
        # cognate while losing what the account was building towards. Completeness
        # is the better policy: a paragraph the reader skims costs less than an
        # account that stops without finishing.
        tail = rest_of(ps, i)
        if not full or not tail:
            return head + block
        return f'{head}{quietly(tail)}{block}'

    return one

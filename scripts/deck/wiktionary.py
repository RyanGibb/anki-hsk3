"""Links into Wiktionary, for whatever it has an entry for."""
import html
import re

from deck.notation import CJK, cedict_lines, outside_tags
from word import Word


class Wiktionary:
    """Chinese linked to the page that explains it, wherever it stands on a card.

    Links go to the traditional entry, as they do everywhere else on the cards. The
    syllabus words have an adjudicated traditional form already; CC-CEDICT covers the
    rest, and a word in neither is linked as written.
    """

    RUN = re.compile(r"[㐀-鿿豈-﫿]+")

    def __init__(self, words: list[Word]):
        self.to_trad = {}
        for line in cedict_lines():
            m = re.match(r"^(\S+) (\S+) \[", line)
            if m and m.group(2) not in self.to_trad:
                self.to_trad[m.group(2)] = m.group(1)
        self.to_trad.update({w["simplified"]: w["traditional"] for w in words})
        # A traditional character stands in the text of a gloss as well as beside a
        # simplified one -- "variant of 间 (間)" -- and 間 unlinked next to a linked 间
        # read as an aside rather than as the other half of the same label. Its page is
        # its own. Single characters only: a run of them is a word, and which words
        # there are is decided by the entries above, not by this.
        for trad in list(self.to_trad.values()):
            if len(trad) == 1:
                self.to_trad.setdefault(trad, trad)

    def word(self, w: str) -> str:
        """A pinyin word is not always a dictionary word: 吃了 is written chīle but
        Wiktionary has no page for it, so 吃 and 了 are linked in turn. Leaving the
        remainder as plain text would leave the aspect particles unlinked, and they
        are usually what the sentence is teaching."""
        if not w or not CJK.match(w[0]):
            return w
        for n in range(len(w), 0, -1):
            if w[:n] in self.to_trad:
                head = self.to_trad[w[:n]]
                return (f'<a href="https://en.wiktionary.org/wiki/{head}#Chinese">'
                        f'{w[:n]}</a>' + self.word(w[n:]))
        return w[0] + self.word(w[1:])

    def run(self, run: str) -> str:
        """Words found in the dictionary rather than in the reading, for a
        sentence whose reading cannot be aligned: 24小时 and 1GB spell their
        numbers out, so nothing lines up character to syllable. Every character
        is kept, linked or not."""
        out, i = [], 0
        while i < len(run):
            if not CJK.match(run[i]):
                out.append(html.escape(run[i], quote=False))
                i += 1
                continue
            for n in range(min(6, len(run) - i), 0, -1):
                if run[i:i + n] in self.to_trad:
                    out.append(self.word(run[i:i + n]))
                    i += n
                    break
            else:
                out.append(html.escape(run[i], quote=False))
                i += 1
        return "".join(out)

    def label(self, shown: str, target: str) -> str:
        """A label as a single link. 礼 (禮) is one thing to click and one page to
        arrive at, the traditional form's, which is where its account is written;
        linking only the 礼 of it left the (禮) beside the link looking like an aside."""
        return (f'<a href="https://en.wiktionary.org/wiki/{target}#Chinese">'
                f'{html.escape(shown, quote=False)}</a>')

    def markup(self, fragment: str) -> str:
        """The Chinese in a rendered field, linked, leaving the field's own markup be.

        A classifier, a homophone, the 大姐 a gloss illustrates itself with -- each is a
        word the deck elsewhere teaches, and each was flat text. The fields hold HTML by
        this point, and a link's href is Chinese as well, so only what lies between the
        tags is linked.
        """
        return outside_tags(fragment, lambda t: self.RUN.sub(lambda x: self.word(x.group()), t))

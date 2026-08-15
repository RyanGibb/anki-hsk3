#!/usr/bin/env python3
"""Index the kaikki Wiktionary dump: per word, whether it has a non-archaic sense, and
per character, its glyph origin.

The sense counts only break ties between CC-CEDICT variants. NOT a simplified->traditional
table: 听/万/远/干/极/厂 each have an entry of their own because each is also a rare
traditional character.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DUMP = ROOT / "data/raw/kaikki-zh.jsonl"
OUT = ROOT / "build/wiktionary.json"
ETYM = ROOT / "build/etymology.json"
LITERAL = ROOT / "build/literal-meanings.json"
REDIRECT = ROOT / "build/redirects.json"
VARIANT = ROOT / "build/variants.json"
RADICAL = ROOT / "build/radical-of.json"

DATED = {"archaic", "obsolete", "historical"}
# The supplementary planes count: the parts a character is built from reach them,
# and 餐 is phonetic 𣦼, whose own account sits under 𣦻 in Extension B.
CJK = re.compile(r"^[㐀-鿿豈-﫿\U00020000-\U0003134F]$")
# Some entries carry dialect readings in the etymology field instead of a glyph origin.
DIALECT = re.compile(r"^\*\s*(Wu|Min|Yue|Hakka|Gan|Xiang|Jin)\b")
# The dump ends an entry with the gloss of the sense the next etymology covers, on its
# own line: 許 finishes "... phonetic 午 (OC *ŋaːʔ). ; “place”". It belongs to the
# etymology that was not chosen.
TRAILING_GLOSS = re.compile(r"(?:\s*;\s*[“‘\"'][^”’\"']{0,60}[”’\"'])+\s*$")
RADICAL_FORM = re.compile(r"\bradical form of ([㐀-鿿豈-﫿\U00020000-\U0003134F])", re.I)


def main() -> int:
    if not DUMP.exists():
        sys.exit(f"missing {DUMP} -- see README.md")

    entries: dict[str, dict] = {}
    etym: dict[str, list] = {}
    literal: dict[str, str] = {}
    # A page that only says "see X" carries no etymology, and 𣦼 is such a page: the
    # account of the shape sits under 𣦻, the same character written another way. Every
    # target is kept, because a page can name several -- 攵 points at 攴 and at 文 --
    # and which is the variant is settled by the target itself.
    redirect: dict[str, list] = {}
    # The characters an entry gives as forms of itself: 攴 lists 攵, 𣦻 lists 𣦼. This
    # is Wiktionary saying two shapes are one character, which is the evidence a
    # redirect needs before its account is shown under the other.
    variant: dict[str, list] = {}
    # A character can say what it is a form of in its definition: 礻 is "Left radical
    # form of 示". Only that wording, which is a statement about the shape; "alternative
    # form of" covers a variant word as readily as a variant graph, and 吊 is an
    # alternative form of 屌 while looking nothing like it.
    radical: dict[str, str] = {}
    with DUMP.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("lang_code") != "zh":
                continue
            word = d.get("word")
            if not word:
                continue
            if d.get("pos") == "soft-redirect":
                targets = [t for t in (d.get("redirects") or []) if CJK.match(t)]
                if targets and CJK.match(word):
                    redirect.setdefault(word, [])
                    redirect[word] += [t for t in targets if t not in redirect[word]]
                continue
            if CJK.match(word) and word not in radical:
                for sense in d.get("senses") or []:
                    for gloss in sense.get("glosses") or []:
                        hit = RADICAL_FORM.search(gloss)
                        if hit and hit.group(1) != word:
                            radical[word] = hit.group(1)
                            break
                    if word in radical:
                        break
            if CJK.match(word):
                forms = [f.get("form") for f in (d.get("forms") or [])]
                forms = [f for f in forms if f and CJK.match(f) and f != word]
                if forms:
                    have = variant.setdefault(word, [])
                    have += [f for f in forms if f not in have]
            text = d.get("etymology_text")
            if text:
                text = TRAILING_GLOSS.sub("", text).strip()
            if text and CJK.match(word) and not DIALECT.match(text.lstrip()):
                # A character can have several etymologies -- 許 has one for the glyph
                # and one for the surname -- and which of them a card wants depends on
                # the sense the card teaches. Keep them all with their glosses; the
                # deck knows its own definitions and picks there.
                glosses = [g for sense in (d.get("senses") or [])
                           for g in (sense.get("glosses") or [])][:12]
                liushu = [t for t in (d.get("etymology_templates") or [])
                          if t.get("name") == "liushu"]
                sections = etym.setdefault(word, [])
                if not any(x["text"] == text for x in sections):
                    sections.append({
                        "text": text,
                        "type": liushu[0].get("args", {}).get("1") if liushu else "",
                        "glosses": [g[:90] for g in glosses],
                        "senses": len(d.get("senses") or []),
                    })
            lit = (d.get("literal_meaning") or "").strip()
            if lit and len(lit) > len(literal.get(word, "")):
                literal[word] = lit
            e = entries.setdefault(word, {"live": 0, "dated": 0, "pos": []})
            pos = d.get("pos")
            if pos and pos not in e["pos"]:
                e["pos"].append(pos)
            for s in d.get("senses") or []:
                if "no-gloss" in (s.get("tags") or []):
                    continue
                if DATED & set(s.get("tags") or []):
                    e["dated"] += 1
                else:
                    e["live"] += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    ETYM.write_text(json.dumps(etym, ensure_ascii=False), encoding="utf-8")
    LITERAL.write_text(json.dumps(literal, ensure_ascii=False), encoding="utf-8")
    REDIRECT.write_text(json.dumps(redirect, ensure_ascii=False), encoding="utf-8")
    VARIANT.write_text(json.dumps(variant, ensure_ascii=False), encoding="utf-8")
    RADICAL.write_text(json.dumps(radical, ensure_ascii=False), encoding="utf-8")
    live = sum(1 for e in entries.values() if e["live"])
    print(f"zh words indexed : {len(entries)}")
    print(f"  with a current (non-archaic) sense: {live}")
    print(f"characters with a glyph origin: {len(etym)}")
    print(f"  with more than one etymology  : {sum(1 for v in etym.values() if len(v) > 1)}")
    print(f"words with a literal meaning   : {len(literal)}")
    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.0f} MB) and {ETYM} "
          f"({ETYM.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

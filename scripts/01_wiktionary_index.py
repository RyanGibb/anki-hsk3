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

DATED = {"archaic", "obsolete", "historical"}
CJK = re.compile(r"^[㐀-鿿豈-﫿]$")
# Some entries carry dialect readings in the etymology field instead of a glyph origin.
DIALECT = re.compile(r"^\*\s*(Wu|Min|Yue|Hakka|Gan|Xiang|Jin)\b")


def main() -> int:
    if not DUMP.exists():
        sys.exit(f"missing {DUMP} -- see README.md")

    entries: dict[str, dict] = {}
    etym: dict[str, dict] = {}
    literal: dict[str, str] = {}
    with DUMP.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("lang_code") != "zh":
                continue
            word = d.get("word")
            if not word or d.get("pos") == "soft-redirect":
                continue
            text = d.get("etymology_text")
            if text and CJK.match(word) and not DIALECT.match(text.lstrip()):
                # A character can have several etymologies: 許 has one for the glyph and
                # one for the surname. The glyph is the entry carrying the ordinary
                # senses, so count them -- the surname section has exactly one.
                n = len(d.get("senses") or [])
                have = etym.get(word)
                if not have or (n, len(text)) > (have["senses"], len(have["text"])):
                    liushu = [t for t in (d.get("etymology_templates") or [])
                              if t.get("name") == "liushu"]
                    etym[word] = {
                        "text": text,
                        "type": liushu[0].get("args", {}).get("1") if liushu else "",
                        "senses": n,
                    }
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
    live = sum(1 for e in entries.values() if e["live"])
    print(f"zh words indexed : {len(entries)}")
    print(f"  with a current (non-archaic) sense: {live}")
    print(f"characters with a glyph origin: {len(etym)}")
    print(f"words with a literal meaning   : {len(literal)}")
    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.0f} MB) and {ETYM} "
          f"({ETYM.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

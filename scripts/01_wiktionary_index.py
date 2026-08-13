#!/usr/bin/env python3
"""Index the kaikki Wiktionary dump: per word, whether it has a non-archaic sense.

Only for breaking ties between CC-CEDICT variants. NOT a simplified->traditional table:
听/万/远/干/极/厂 each have an entry of their own because each is also a rare traditional
character.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DUMP = ROOT / "data/raw/kaikki-zh.jsonl"
OUT = ROOT / "build/wiktionary.json"

DATED = {"archaic", "obsolete", "historical"}


def main() -> int:
    if not DUMP.exists():
        sys.exit(f"missing {DUMP} -- see README.md")

    entries: dict[str, dict] = {}
    with DUMP.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("lang_code") != "zh":
                continue
            word = d.get("word")
            if not word or d.get("pos") == "soft-redirect":
                continue
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
    live = sum(1 for e in entries.values() if e["live"])
    print(f"zh words indexed : {len(entries)}")
    print(f"  with a current (non-archaic) sense: {live}")
    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

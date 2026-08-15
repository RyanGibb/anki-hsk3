#!/usr/bin/env python3
"""Fetch the grammar syllabus from chinesetest.cn, the source it belongs to.

The published PDF prints the grammar items and no examples. The site serves the same
syllabus with worked examples from its own API, which is where the third-party dataset
this deck used to read came from -- one conversion later, having lost a record whose
点 spans two lines.

Writes data/raw/official_grammar.tsv in the shape the build already reads, with the
corrections in data/grammar-fixes.csv applied and named, so a re-fetch does not quietly
reintroduce a mistake we have already found.

Usage: fetch-grammar.py [--check]     --check reports differences and writes nothing
"""
import argparse
import csv
import json
import pathlib
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data/raw/official_grammar.tsv"
FIXES = ROOT / "data/grammar-fixes.csv"
# The page size is honoured; the parameters are MyBatis-Plus style, and pageNum/pageSize
# are accepted and ignored, which returns page one however many times you ask.
URL = "https://www.chinesetest.cn/api/hsk/outline/languagePage?current=1&size=1000"
FIELDS = ["examLevelId", "content", "grammarType", "categoryType", "grammarDetail",
          "cases"]


def fetch() -> list:
    req = urllib.request.Request(
        URL, data=b"", headers={"User-Agent": "Mozilla/5.0",
                                "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode("utf-8"))
    data = body["data"]
    records = data["records"]
    if len(records) != data["total"]:
        sys.exit(f"got {len(records)} of {data['total']} records")
    return records


def tidy(value: str, joiner: str = "；") -> str:
    """One field, one line. The API separates examples with newlines and the build
    reads them separated by bars, as the dataset it replaces did. Every other field
    is prose, and a bar in the middle of a point's name means nothing to a reader, so
    those are joined with a semicolon: 副词、形容词作状语；表示时间、处所的词语作状语."""
    parts = [p.strip() for p in (value or "").replace("\r", "").split("\n")]
    return joiner.join(p for p in parts if p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    records = fetch()
    fixes = list(csv.DictReader(FIXES.open(encoding="utf-8"))) if FIXES.exists() else []
    applied = []
    rows = []
    for rec in records:
        row = {f: tidy(rec.get(f), "|" if f == "cases" else "；")
               for f in FIELDS}
        row["examLevelId"] = (rec.get("examLevelId") or "").strip()
        for fix in fixes:
            for field in FIELDS:
                if fix["wrong"] and fix["wrong"] in row[field]:
                    row[field] = row[field].replace(fix["wrong"], fix["right"])
                    applied.append(fix)
        rows.append(row)
    print(f"{len(rows)} grammar points from chinesetest.cn")
    for fix in applied:
        print(f"  corrected {fix['wrong']} -> {fix['right']}  ({fix['why']})")
    unused = [f for f in fixes if f not in applied]
    for fix in unused:
        print(f"  correction no longer matches anything: {fix['wrong']}")

    if args.check:
        if OUT.exists():
            old = OUT.read_text(encoding="utf-8")
            new = "\n".join(["\t".join(FIELDS)]
                            + ["\t".join(r[f] for f in FIELDS) for r in rows]) + "\n"
            print("unchanged" if old == new else "DIFFERS from the committed file")
        return 1 if unused else 0

    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}")
    return 1 if unused else 0


if __name__ == "__main__":
    sys.exit(main())

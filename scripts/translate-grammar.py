#!/usr/bin/env python3
"""Translate the grammar examples into data/grammar-translations.csv.

Run once and commit the result: the build reads the CSV, never the network. Resumable,
so a dropped connection costs only the batch it was on.

DeepL returns translations in the order sent, so a short batch is refused rather than
paired up wrongly.
"""
import argparse
import csv
import json
import pathlib
import time
import os
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/official_grammar.tsv"
OUT = ROOT / "data/grammar-translations.csv"
KEY_FILE = pathlib.Path.home() / "deepl-key"
BATCH = 40


def api_key() -> str:
    key = os.environ.get("DEEPL_API_KEY") or (
        KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    if not key:
        raise SystemExit(f"set DEEPL_API_KEY or write the key to {KEY_FILE}")
    return key


def sentences() -> list[str]:
    seen = {}
    with RAW.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            for case in (row.get("cases") or "").split("|"):
                case = case.strip()
                if case:
                    seen.setdefault(case, None)
    return list(seen)


def translate(batch: list[str], key: str) -> dict[str, str]:
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    body = urllib.parse.urlencode(
        [("text", t) for t in batch]
        + [("source_lang", "ZH"), ("target_lang", "EN-GB")]).encode()
    req = urllib.request.Request(f"https://{host}/v2/translate", data=body,
                                 headers={"Authorization": f"DeepL-Auth-Key {key}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 456, 500, 503):
                raise
            time.sleep(2 ** attempt * 5)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    else:
        return {}
    got = [t["text"].strip().replace("\u2019", "'") for t in data["translations"]]
    if len(got) != len(batch):
        return {}
    return {zh: en for zh, en in zip(batch, got) if en}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    key = api_key()
    done = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as fh:
            done = {r["chinese"]: r["english"] for r in csv.DictReader(fh)}

    want = [s for s in sentences() if s not in done]
    print(f"{len(done)} already translated, {len(want)} to go")

    for i in range(0, len(want), BATCH):
        batch = want[i:i + BATCH]
        got = translate(batch, key)
        missed = [s for s in batch if s not in got]
        done.update(got)
        with OUT.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["chinese", "english"])
            for k in sentences():
                if k in done:
                    w.writerow([k, done[k]])
        print(f"  {min(i + BATCH, len(want))}/{len(want)}"
              + (f"  ({len(missed)} unmatched)" if missed else ""), flush=True)
        time.sleep(args.delay)

    print(f"wrote {OUT}: {len(done)} of {len(sentences())} sentences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

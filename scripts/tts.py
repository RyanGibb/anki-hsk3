#!/usr/bin/env python3
"""Synthesise the audio the recorded corpus does not cover, saying the checked reading.

Words with no recording, and the grammar sentences, which no corpus has. Every syllable
is given to the engine as pinyin, so 长 is zhǎng or cháng because the deck decided which
and not because the synthesiser guessed. That is the whole reason for using a service
that accepts phonemes.

Writes into .cache/tts and leaves an index the build reads. Nothing here runs during a
build: a checkout without a key still produces a deck, just a quieter one.

Needs an Azure Speech resource: set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION, or write
them to ~/azure-key1 and ~/azure-region.
"""
import csv
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache/tts"
INDEX = CACHE / "index.json"
KEY_FILE = pathlib.Path.home() / "azure-key1"
REGION_FILE = pathlib.Path.home() / "azure-region"
VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "-20%"
FORMAT = "audio-24khz-48kbitrate-mono-mp3"

def credentials() -> tuple:
    key = os.environ.get("AZURE_SPEECH_KEY") or (
        KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    region = os.environ.get("AZURE_SPEECH_REGION") or (
        REGION_FILE.read_text().strip() if REGION_FILE.exists() else "")
    if not key or not region:
        raise SystemExit("set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION, or write them "
                         f"to {KEY_FILE} and {REGION_FILE}")
    return key, region


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def speak(ssml: str, key: str, region: str) -> bytes:
    req = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"),
        headers={"Ocp-Apim-Subscription-Key": key,
                 "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": FORMAT,
                 "User-Agent": "anki-hsk3"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503):
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("gave up after five attempts")


def name(text: str, word: bool) -> str:
    """A word is its own filename, the way cmn-爱.mp3 and 爱.svg already are. A sentence
    is too long to be one, so it gets a digest."""
    if word:
        return f"tts-{text}.mp3"
    return "tts-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] + ".mp3"


def main() -> int:
    key, region = credentials()

    words = json.loads((ROOT / "build/words.json").read_text(encoding="utf-8"))
    # A word written the same as another but read differently cannot be voiced from
    # the characters alone: 结果 asked for on its own comes back jiéguǒ "result", which
    # is the wrong word for the card teaching jiēguǒ "to bear fruit".
    ambiguous = {w["simplified"] for w in words
                 if any(o["simplified"] == w["simplified"]
                        and o["pinyin_numbered"] != w["pinyin_numbered"]
                        for o in words)}
    want = {w["simplified"] for w in words
            if not w["audio"] and w["simplified"] not in ambiguous}
    checked = {}
    path = ROOT / "data/grammar-pinyin.csv"
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            checked[r["chinese"]] = r["pinyin"]

    CACHE.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}

    # Plain text: Azure will not accept <phoneme> for zh-CN, so the reading is the
    # engine's to choose. In a sentence it reads from context and gets 长得 zhǎng,
    # 睡不着 zháo and 拿不了 liǎo right; a word on its own has no context, which is why
    # one written like another but read differently is left out above.
    jobs = [(text, esc(text), True) for text in want]
    jobs += [(text, esc(text), False) for text in checked]

    todo = [j for j in jobs if not (CACHE / name(j[0], j[2])).exists()]
    print(f"{len(jobs)} to voice, {len(jobs) - len(todo)} already done, {len(todo)} to go")

    done = 0
    for text, body, word in todo:
        ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xml:lang="zh-CN"><voice name="{VOICE}">'
                f'<prosody rate="{RATE}">{body}</prosody></voice></speak>')
        try:
            (CACHE / name(text, word)).write_bytes(speak(ssml, key, region))
        except Exception as e:
            print(f"  {text[:24]}: {e}")
            continue
        index[text] = name(text, word)
        done += 1
        if done % 200 == 0:
            INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
            print(f"  {done}/{len(todo)}")

    for text, _, word in jobs:
        if (CACHE / name(text, word)).exists():
            index[text] = name(text, word)
    INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"{len(index)} clips in {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

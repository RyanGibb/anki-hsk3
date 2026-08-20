#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

fetch() { [ -s "$1" ] || curl -fL --progress-bar -o "$1" "$2"; }

mkdir -p data/raw
fetch data/raw/kaikki-zh.jsonl \
  https://kaikki.org/dictionary/Chinese/kaikki.org-dictionary-Chinese.jsonl
fetch data/raw/cedict_ts.u8 \
  https://raw.githubusercontent.com/Punpuf/hsk-syllabus-vocabulary-parser/main/cedict_ts.u8
# Words CC-CEDICT does not carry, written in its format by the syllabus parser. Without
# them 压轴 and 致力于 have no entry at all, so nothing gives their traditional form.
fetch data/raw/cedict_patch.u8 \
  https://raw.githubusercontent.com/Punpuf/hsk-syllabus-vocabulary-parser/main/data/cedict_patch.u8
# What each character breaks down into, in Ideographic Description Sequences. Wiktionary
# names the parts; this says whether the character carries the shape it names.
fetch data/raw/ids.txt \
  https://raw.githubusercontent.com/cjkvi/cjkvi-ids/master/ids.txt

if [ ! -d .cache/audio-cmn/64k/syllabs ]; then
  [ -d .cache/audio-cmn ] || git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/hugolpz/audio-cmn.git .cache/audio-cmn
  git -C .cache/audio-cmn sparse-checkout set 96k/hsk 64k/syllabs
fi

: "${MAKEMEAHANZI:=$HOME/projects/makemeahanzi}"
if [ ! -d "$MAKEMEAHANZI/svgs-still" ]; then
  MAKEMEAHANZI=$PWD/.cache/makemeahanzi
  [ -d "$MAKEMEAHANZI" ] || git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/skishore/makemeahanzi.git "$MAKEMEAHANZI"
  git -C "$MAKEMEAHANZI" sparse-checkout set svgs-still
fi
export MAKEMEAHANZI

python3 scripts/01_wiktionary_index.py
python3 scripts/02_build_words.py
python3 scripts/03_media.py
nix shell --impure \
  --expr 'with import <nixpkgs> {}; python3.withPackages (ps: [ ps.genanki ps.jieba ps.pypinyin ])' \
  --command python3 scripts/04_build_apkg.py
python3 scripts/05_verify.py

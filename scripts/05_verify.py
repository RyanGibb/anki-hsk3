#!/usr/bin/env python3
"""Verify the built package: counts, traditional characters, media, field sanity."""
import collections
import csv
import json
import pathlib
import re
import sqlite3
import tempfile
import zipfile
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pinyin_align import align, syllabify   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
APKG = BUILD / "HSK-3.0-2025.apkg"

OFFICIAL_CUMULATIVE = {"1": 300, "2": 500, "3": 1000, "4": 2000,
                       "5": 3600, "6": 5400, "7-9": 11000}
LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]

fails: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    words = json.loads((BUILD / "words.json").read_text(encoding="utf-8"))

    print("counts vs the official syllabus")
    running = 0
    for lv in LEVELS:
        running += sum(1 for w in words if w["level"] == lv)
        want = OFFICIAL_CUMULATIVE[lv]
        check(f"L{lv} cumulative {running} (official {want})",
              abs(running - want) <= 110, f"delta {running - want}")

    print("\ntraditional characters vs the known-correct set")
    print("  (scoring `traditional_auto`, before the adjudicated overrides are")
    print("   applied -- scoring the final value would be circular)")
    gold = list(csv.DictReader(
        (ROOT / "data/traditional-fixes-goldset.csv").open(encoding="utf-8")))
    by_simp = {}
    for w in words:
        by_simp.setdefault(w["simplified"], w)
    hit = tested = 0
    misses = []
    for g in gold:
        w = by_simp.get(g["simplified"])
        if not w:
            continue
        tested += 1
        if w["traditional_auto"] == g["new_traditional"]:
            hit += 1
        else:
            misses.append((g["simplified"], g["new_traditional"], w["traditional_auto"]))
    check(f"automatic method: {hit}/{tested} correct", hit / max(tested, 1) >= 0.95)
    for m in misses:
        print(f"        {m[0]}: want {m[1]}, auto gave {m[2]}  (override applied)")
    final_ok = sum(1 for g in gold
                   if (w := by_simp.get(g["simplified"]))
                   and w["traditional"] == g["new_traditional"])
    check(f"after overrides: {final_ok}/{tested}", final_ok == tested)

    # The gold set holds only words the old deck got wrong, so it misses the commonest
    # failure: a simplified character that is also a rare traditional one.
    print("\ncommon-word regression (the class the gold set does not cover)")
    KNOWN = {
        "听": "聽", "万": "萬", "远": "遠", "干": "幹", "极": "極", "厂": "廠",
        "还": "還", "几": "幾", "气": "氣", "旧": "舊", "离": "離", "园": "園",
        "仅": "僅", "爱": "愛", "手机": "手機", "周末": "週末", "重复": "重複",
        "月": "月", "份": "份", "水": "水", "点": "點", "汉语": "漢語",
    }
    wrong = [(s, want, by_simp[s]["traditional"])
             for s, want in KNOWN.items()
             if s in by_simp and by_simp[s]["traditional"] != want]
    check(f"{len(KNOWN) - len(wrong)}/{len(KNOWN)} correct", not wrong)
    for s, want, got in wrong:
        print(f"        {s}: want {want}, got {got}")

    print("\ngloss follows the chosen traditional form")
    PAIRED = {
        "台风": ("颱風", "typhoon", "stage presence"),
        "重复": ("重複", "to repeat", "variant of"),
    }
    for simp, (trad, must, must_not) in PAIRED.items():
        w = by_simp.get(simp)
        if not w:
            check(f"{simp} present", False)
            continue
        ok = (w["traditional"] == trad
              and must in w["meaning"]
              and must_not not in w["meaning"])
        check(f"{simp} -> {w['traditional']} :: {w['meaning'][:44]}", ok)

    print("\nhomographs have distinct glosses")
    groups: dict[str, list] = {}
    for w in words:
        if w["homograph_index"]:
            groups.setdefault(w["simplified"], []).append(w)
    shared = [s for s, g in groups.items()
              if len(g) > 1 and len({x["meaning"] for x in g}) == 1]
    check(f"{len(groups) - len(shared)}/{len(groups)} groups distinct", not shared,
          ", ".join(shared) if shared else "")
    # A hand-split gloss divides its dictionary entry between the cards rather than
    # choosing from it: every sense the dictionary gives 本 is taught by 本1 or by 本2,
    # and by only one of them. Senses are matched verbatim, so data/homograph-glosses.csv
    # has to hold CC-CEDICT's exact wording and not a tidied version of it.
    invented, lost = [], []
    for simp, g in groups.items():
        curated = [w for w in g if w["meaning_source"] == "curated"]
        for w in curated:
            full = [s for s in w["meaning_full"].split("/") if s]
            invented += [f"{w['entry']}: {s[:32]}"
                         for s in w["meaning"].split("/") if s and s not in full]
        # Entries the adjudicator gave separate dictionary entries (面 against 麵) have
        # no single sense list to divide, so only words sharing one can be checked.
        shared_entry = len({w["meaning_full"] for w in g}) == 1
        if not curated or not shared_entry:
            continue
        claimed = [s for w in curated for s in w["meaning"].split("/") if s]
        for s in (x for x in curated[0]["meaning_full"].split("/") if x):
            if claimed.count(s) != 1:
                lost.append(f"{simp}: {'unclaimed' if not claimed.count(s) else 'twice'}"
                            f" {s[:32]}")
    # data/sense-pos.csv divides one entry's senses between parts of speech. Divides,
    # so every sense is claimed once and nothing new is written, matched verbatim as
    # the homograph file is. A part of speech the syllabus does not give the word is
    # allowed -- 比 is a noun to the dictionary and not to the syllabus, and the card
    # sets that quietly under the rest -- but it has to be one the deck has a name for.
    known = {row["zh"] for row in csv.DictReader(
        (ROOT / "data/pos-labels.csv").open(encoding="utf-8"))}
    pos_bad = []
    for w in words:
        split = w.get("meaning_by_pos") or []
        if not split:
            continue
        own = [s for s in w["meaning"].split("/") if s]
        claimed = [s for _, m in split for s in m.split("/") if s]
        for p, _ in split:
            if p not in known:
                pos_bad.append(f"{w['entry']}: {p} is not a part of speech")
        for s in own:
            if claimed.count(s) != 1:
                pos_bad.append(f"{w['entry']}: {'unclaimed' if not claimed.count(s) else 'twice'}"
                               f" {s[:32]}")
        for s in claimed:
            if s not in own:
                pos_bad.append(f"{w['entry']}: invented {s[:32]}")
    check("every sense of a split entry belongs to exactly one part of speech",
          not pos_bad, f"{len(pos_bad)}: {pos_bad[:3]}" if pos_bad else "")

    # A word with no dictionary entry keeps its simplified form as its traditional
    # one, which is right for 新能源 and wrong for 压轴 (壓軸). Any word left that way
    # whose characters do have traditional forms is a word the patch should cover.
    s2t = {}
    for line in (ROOT / "data/raw/cedict_ts.u8").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\S+) (\S+) \[", line)
        if m and len(m.group(1)) == len(m.group(2)):
            for a, b in zip(m.group(1), m.group(2)):
                if a != b:
                    s2t.setdefault(b, a)
    guessed = [f'{w["simplified"]} ({"".join(s2t.get(c, c) for c in w["simplified"])}?)'
               for w in words if w["traditional_source"].startswith("fallback")
               and any(c in s2t for c in w["simplified"])]
    check("no word shows its simplified form as its traditional one", not guessed,
          f"{len(guessed)}: {guessed[:4]}" if guessed else "")

    # 一 and 不 change tone before certain tones, and the convention writes that
    # change. It is mechanical, so every hand-checked reading can be tested: 不 is bú
    # before a fourth tone and bù otherwise, 一 is yí before a fourth and yì before the
    # first three. A pause interrupts it -- 这不，院子 keeps bù -- so a sandhi across
    # punctuation is not one.
    checked_pinyin = ROOT / "data/grammar-pinyin.csv"
    if checked_pinyin.exists():
        from pinyin_align import numbered
        wrong = []
        for row in csv.DictReader(checked_pinyin.open(encoding="utf-8")):
            zh, py = row["chinese"], row["pinyin"]
            if re.search(r"[0-9A-Za-z]", zh):
                continue
            pairs = align(zh, py)
            if pairs is None:
                continue
            # align merges erhua into one pair -- 哪儿 is a single nǎr -- so a pair can
            # cover more than one character and there is no counting from characters
            # to pairs. Walk the sentence alongside the pairs instead.
            spots, at = [], 0
            for text, _syl, _start in pairs:
                while at < len(zh) and zh[at] != text[0]:
                    at += 1
                spots.append(at)
                at += len(text)
            for n, (ch, syl, _start) in enumerate(pairs):
                if ch not in "一不" or not syl or n + 1 >= len(pairs):
                    continue
                if spots[n] + len(ch) != spots[n + 1]:   # a pause stands between them
                    continue
                tone = numbered(pairs[n + 1][1])[-1:]
                got = numbered(syl).lower()
                if ch == "不":
                    want = "bu2" if tone == "4" else "bu4"
                    ok = got in (want, "bu5")
                else:
                    want = "yi2" if tone == "4" else "yi4"
                    ok = got in (want, "yi1", "yi5") or tone not in "1234"
                if not ok:
                    wrong.append(f"{zh[:20]}: {ch} as {syl} before {pairs[n+1][1]}")
        check(f"一 and 不 sandhi written as the convention says", not wrong,
              f"{len(wrong)}: {wrong[:3]}" if wrong else "")

    # A clip the speech service returned empty, or a diagram that failed to render,
    # ships as a file of no bytes: the card looks voiced and plays nothing.
    if APKG.exists():
        with zipfile.ZipFile(APKG) as z:
            media = json.loads(z.read("media").decode("utf-8"))
            sizes = {media[i.filename]: i.file_size for i in z.infolist()
                     if i.filename.isdigit()}
        thin = [f"{k} ({n} bytes)" for k, n in sizes.items()
                if n < (1000 if k.endswith(".mp3") else 200)]
        check(f"all {len(sizes)} media files carry data", not thin,
              f"{len(thin)}: {thin[:4]}" if thin else "")

    # The writing card asks for a character, so nothing it shows before the answer
    # may contain that character: 大's gloss illustrates itself with 大姐.
    if APKG.exists():
        showing = []
        with zipfile.ZipFile(APKG) as z:
            name = next(x for x in z.namelist() if x.startswith("collection.anki"))
            with tempfile.TemporaryDirectory() as td:
                z.extract(name, td)
                con = sqlite3.connect(pathlib.Path(td) / name)
                mods = json.loads(con.execute("select models from col").fetchone()[0])
                mid = [k for k, m in mods.items() if m["name"] == "HSK 3.0 Character"]
                if mid:
                    flds = [f["name"] for f in mods[mid[0]]["flds"]]
                    for (f,) in con.execute("select flds from notes where mid=?",
                                            (int(mid[0]),)):
                        note = dict(zip(flds, f.split("\x1f")))
                        ch = note["Simplified"]
                        shown = re.sub(r"<span class=mask>.*?</span>", "",
                                       note["Meaning"] + note["Example"])
                        if ch and ch in shown:
                            showing.append(ch)
                con.close()
        check("no writing card shows the character it asks for", not showing,
              f"{len(showing)}: {showing[:6]}" if showing else "")

    # A sentence is voiced from what the card shows, once the notation is resolved to
    # what a speaker would say. The syllabus writes 呢1 to tell two entries apart, and
    # a clip synthesised from that says the digit out loud, so a card holding a clip
    # filed under any other text is holding the wrong sound.
    tts_index = ROOT / ".cache/tts/index.json"
    if tts_index.exists() and APKG.exists():
        index = json.loads(tts_index.read_text(encoding="utf-8"))
        said = {r["chinese"]: r["spoken"] for r in csv.DictReader(
            (ROOT / "data/sentence-speech.csv").open(encoding="utf-8"))}

        def as_said(text):
            return said.get(text) or text.replace("（", "").replace("）", "")

        wrong = []
        with zipfile.ZipFile(APKG) as z:
            name = next(x for x in z.namelist() if x.startswith("collection.anki"))
            with tempfile.TemporaryDirectory() as td:
                z.extract(name, td)
                con = sqlite3.connect(pathlib.Path(td) / name)
                mods = json.loads(con.execute("select models from col").fetchone()[0])
                mid = [k for k, m in mods.items() if m["name"] == "HSK 3.0 Sentence"]
                if mid:
                    flds = [f["name"] for f in mods[mid[0]]["flds"]]
                    for (f,) in con.execute("select flds from notes where mid=?",
                                            (int(mid[0]),)):
                        v = dict(zip(flds, f.split("\x1f")))
                        want = [index.get(as_said(x))
                                for x in v["Hanzi"].split("<br>")]
                        got = re.findall(r"\[sound:([^\]]+)\]", v["Audio"])
                        if got != [x for x in want if x]:
                            wrong.append(re.sub("<[^>]+>", "", v["Hanzi"])[:22])
                con.close()
        check("every sentence plays its own recording", not wrong,
              f"{len(wrong)}: {wrong[:3]}" if wrong else "")

    # Each corrected reading has to be the reading the deck ends up teaching, and has
    # to still be a correction: if the syllabus is fixed upstream the row is dead
    # weight, and if a word is dropped the row points at nothing.
    reading_fixes = ROOT / "data/reading-fixes.csv"
    if reading_fixes.exists():
        rows = list(csv.DictReader(reading_fixes.open(encoding="utf-8")))
        source = {r["word"]: r["pinyin_numbered"] for r in csv.DictReader(
            (ROOT / "data/raw/punpuf_hsk_word_list.tsv").open(encoding="utf-8"),
            delimiter="\t")}
        built = {w["simplified"]: w["pinyin_numbered"] for w in words}
        wrong = [f'{r["word"]}: {built.get(r["word"])}' for r in rows
                 if built.get(r["word"]) != r["pinyin_numbered"]]
        spent = [r["word"] for r in rows if source.get(r["word"]) != r["was"]]
        check(f"{len(rows)} corrected readings all applied", not wrong,
              ", ".join(wrong) if wrong else "")
        check("no corrected reading is redundant", not spent,
              f"the syllabus now agrees for {', '.join(spent)}" if spent else "")

    # A gloss chosen by hand for one word of one sentence is only right for that
    # sentence, so a row that no longer matches one is a row nobody is reading.
    fixes = ROOT / "data/sentence-word-glosses.csv"
    if fixes.exists():
        rows = list(csv.DictReader(fixes.open(encoding="utf-8")))

        def bare(s: str) -> str:
            """The sentence as the card carries it. The source writes 才2明白 to index
            which 才 its point is about and the deck takes the digit out, so the two
            are stripped alike and compared on the same footing."""
            return re.sub(r"(?<=[㐀-鿿])[0-9](?![0-9])", "", s)

        sentences = {bare(r["chinese"]) for r in
                     csv.DictReader((ROOT / "data/grammar-pinyin.csv")
                                    .open(encoding="utf-8"))}
        stale = [f'{r["word"]} in {r["chinese"][:18]}' for r in rows
                 if bare(r["chinese"]) not in sentences
                 or r["word"] not in r["chinese"]]
        check(f"{len(rows)} hand-picked sentence glosses all still match", not stale,
              ", ".join(stale) if stale else "")

    check("no curated gloss invents a sense", not invented,
          f"{len(invented)}: {invented[:3]}" if invented else "")
    check("every sense of a split word is taught by exactly one of its cards", not lost,
          f"{len(lost)}: {lost[:3]}" if lost else "")

    leaked = [w["entry"] for w in words if "CL:" in w["meaning"]]
    check("no CL: notation left in definitions", not leaked,
          f"{len(leaked)} leaked" if leaked else "")

    pointer_only = [w["entry"] for w in words
                    if re.match(r"^(see|variant of|old variant of)\b",
                                w["meaning"], re.I)]
    check("no definition is only a cross-reference", not pointer_only,
          f"{len(pointer_only)}: {pointer_only[:5]}" if pointer_only else "")

    empty = [w["entry"] for w in words if not w["meaning"].strip()]
    check("every word has a meaning", not empty, f"{len(empty)} empty" if empty else "")

    print("\nrecordings match the reading on the card")
    swac = {r["word"]: r["pinyin"] for r in csv.DictReader(
        (ROOT / "data/swac-index.csv").open(encoding="utf-8"))}
    V = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ"
    TONED = re.compile(f"[{V}]")
    T = str.maketrans(V, "aaaaeeeeiiiioooouuuuüüüü")
    def nm(x):
        """A reading with the deck's own notation taken back out: it hyphenates the
        halves of a four-character idiom and writes ü, the index does neither."""
        x = x.split("/")[0].lower()
        for mark in (" ", "\u2019", "'", "-"):
            x = x.replace(mark, "")
        return x.replace("u:", "ü").replace("v", "ü")
    wrong = []
    for w in words:
        m = re.findall(r"cmn-(.+?)\.mp3", w["audio"] or "")
        if len(m) != 1 or m[0] != w["simplified"] or m[0] not in swac:
            continue
        c, r = nm(w["pinyin"]), nm(swac[m[0]])
        if c == r:
            continue
        if c.translate(T) != r.translate(T):
            wrong.append((w["simplified"], w["pinyin"], swac[m[0]]))
            continue
        # 谁 is indexed sheí against the card's shéi: one syllable, one tone, the mark
        # typed on the other vowel
        if [V.index(x) % 4 for x in TONED.findall(c)] == \
                [V.index(x) % 4 for x in TONED.findall(r)]:
            continue
        # What is left is a tone written two ways. That is the same sound where one
        # source writes a syllable unstressed and the other does not, and where 一 or
        # 不 takes its sandhi, which the word may put anywhere -- 进一步, 从容不迫 --
        # so the tones are read against the characters that carry them.
        def toneof(syl):
            mark = TONED.search(syl)
            return str(V.index(mark.group()) % 4 + 1) if mark else "5"
        ours, theirs = align(w["simplified"], c), align(w["simplified"], r)
        if ours and theirs and len(ours) == len(theirs) and all(
                toneof(x) == toneof(y) or "5" in (toneof(x), toneof(y))
                or ch[:1] in "一不"
                for (ch, x, _s), (_c, y, _t) in zip(ours, theirs)):
            continue
        wrong.append((w["simplified"], w["pinyin"], swac[m[0]]))
    check(f"{len(wrong)} recordings with a mismatched reading", not wrong,
          str(wrong[:4]) if wrong else "")
    shared = [(a["entry"], b["entry"], a["audio"]) for a in words for b in words
              if a["simplified"] == b["simplified"] and a["entry"] < b["entry"]
              and a["audio"] and a["audio"] == b["audio"]
              and a["pinyin_numbered"] != b["pinyin_numbered"]]
    check("no two readings share one recording", not shared,
          str(shared[:3]) if shared else "")
    # A borrowed recording is only as good as the index label that offered it. Where the
    # deck also teaches the word lent from, it has its own reading of it, and the two
    # naming different syllables means one of them is wrong -- 高大 is indexed gāodù.
    readings = collections.defaultdict(set)
    for w in words:
        readings[w["simplified"]].add(nm(w["pinyin"]).translate(T))
    borrowed = []
    for w in words:
        m = re.findall(r"cmn-(.+?)\.mp3", w["audio"] or "")
        if len(m) != 1 or m[0] == w["simplified"] or m[0] not in readings:
            continue
        if nm(swac[m[0]]).translate(T) not in readings[m[0]]:
            borrowed.append((w["simplified"], w["pinyin"], m[0], swac[m[0]]))
    check(f"{len(borrowed)} recordings borrowed on a label the deck contradicts",
          not borrowed, str(borrowed[:4]) if borrowed else "")
    # The index is hand-written and a slip in it is silent: 高大 was indexed gāodù, which
    # cost it its own recording and lent it to 高度. A label has to be sayable as the word
    # it names -- every syllable a reading CC-CEDICT gives that character, allowing erhua,
    # neutral tones and 一/不 sandhi -- unless it is one of the few where Yue Tan said
    # something other than the word.
    SPEAKER = {"嗯": "ǹg",            # the interjection, which CC-CEDICT gives as ēn
               "成绩": "chéngjī"}      # 绩 as jī, the reading Taiwan standardised
    sound = collections.defaultdict(set)
    for line in (ROOT / "data/raw/cedict_ts.u8").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\S+ (\S+) \[([^]]+)\]", line)
        if m and len(m.group(1)) == len(m.group(2).split()):
            for c, s in zip(m.group(1), m.group(2).lower().split()):
                sound[c].add(s.replace("u:", "v"))

    def one(syl: str) -> str:
        """A syllable as CC-CEDICT writes it: letters, then its tone, 5 for none."""
        syl = nm(syl)
        tone = [str(V.index(c) % 4 + 1) for c in syl if c in V]
        return (re.sub(r"[^a-zü]", "", syl.translate(T)).replace("ü", "v")
                + (tone[0] if tone else "5"))

    def sayable(char: str, syl: str) -> bool:
        said = {one(syl)}
        if char.endswith("儿") and len(char) > 1:      # 个儿 gèr, 女儿 nǚér
            said |= {re.sub(end, "", s) for s in said for end in (r"r(?=\d$)",
                                                                 r"er(?=\d$)")}
        return any(s == x                                        # as written
                   or (s[-1] == "5" and s[:-1] == x[:-1])        # said unstressed
                   or (char[0] in "一不" and s[:-1] == x[:-1])    # sandhi
                   for s in said for x in sound[char[0]])

    unsayable = []
    for word, pron in swac.items():
        if "_" in word or SPEAKER.get(word) == pron:
            continue
        pairs = align(word, pron)
        if pairs is None:
            unsayable.append((word, pron, "does not divide into syllables"))
            continue
        for char, syl, _start in pairs:
            if sound[char[0]] and not sayable(char, syl):
                unsayable.append((word, pron, f"{char[0]} does not say {syl}"))
                break
    check(f"{len(unsayable)} recordings indexed as saying something the word cannot",
          not unsayable, str(unsayable[:4]) if unsayable else "")

    # A voice says a slash and a bracket as though they were words: 同学们在/正在上课
    # came back spoken 同学们在正在上课. Nothing queued for speech may carry the
    # syllabus's notation, and data/sentence-speech.csv resolves what dropping the
    # brackets cannot -- a word to choose between, or a label naming the point.
    wanted = json.loads((BUILD / "tts-wanted.json").read_text(encoding="utf-8"))
    notated = [x for x in wanted["sentences"] if set("/（）") & set(x)]
    check(f"{len(notated)} sentences go to the voice carrying notation", not notated,
          str(notated[:3]) if notated else "")
    check(f"{len(wanted['silent'])} sentences the voice has not said",
          not wanted["silent"], str(wanted["silent"][:3]) if wanted["silent"] else "")

    print("\npackage integrity")
    check("apkg exists", APKG.exists())
    if not APKG.exists():
        return 1
    with zipfile.ZipFile(APKG) as z:
        names = z.namelist()
        check("media manifest present", "media" in names)
        db = next((n for n in names if n.startswith("collection.anki")), None)
        check("collection db present", db is not None, db or "")
        if db is None:
            return 1
        manifest = json.loads(z.read("media"))
        check(f"{len(manifest)} media entries", len(manifest) > 10000)
        bundled = set(manifest.values())
        with tempfile.TemporaryDirectory() as td:
            z.extract(db, td)
            con = sqlite3.connect(pathlib.Path(td) / db)
            n_notes = con.execute("select count(*) from notes").fetchone()[0]
            n_cards = con.execute("select count(*) from cards").fetchone()[0]
            # 10999 vocabulary + 1200 writing + one per sentence. Seven sentences the
            # source wrapped onto its separator were two cards each and are now one,
            # and the piece one of them was joined to held two more examples run
            # together, so 2043 became 2038.
            check(f"{n_notes} notes in db", n_notes == 10999 + 1200 + 2038)
            # forgetting HSK_DECK_ROOT silently leaves an empty deck tree on import
            decks = json.loads(con.execute("select decks from col").fetchone()[0])
            roots = {d["name"].split("::")[0] for d in decks.values()
                     if d["name"] != "Default"}
            check(f"deck root: {', '.join(sorted(roots))}", len(roots) == 1)
            # a duplicate guid drops notes on import, silently
            dupes = [g for g, k in collections.Counter(
                x for (x,) in con.execute("select guid from notes")).items() if k > 1]
            check("all guids unique", not dupes, f"{len(dupes)} duplicated")
            check(f"{n_cards} cards in db", n_cards == n_notes)
            models = json.loads(con.execute("select models from col").fetchone()[0])
            writing = 0
            for mid, m in models.items():
                for i, t in enumerate(m["tmpls"]):
                    if t["name"] == "Writing":
                        writing += con.execute(
                            "select count(*) from cards c join notes n on n.id=c.nid "
                            "where n.mid=? and c.ord=?", (int(mid), i)).fetchone()[0]
            check(f"{writing} writing cards (syllabus list is 1200)", writing == 1200)
            recog = sum(
                con.execute("select count(*) from cards c join notes n on n.id=c.nid "
                            "where n.mid=? and c.ord=?", (int(mid), i)).fetchone()[0]
                for mid, m in models.items()
                for i, t in enumerate(m["tmpls"])
                if m["name"] == "HSK 3.0 Character" and t["name"] == "Recognition")
            check("no character recognition cards", recog == 0)
            present = bundled
            missing = set()
            refs = set()
            # Meaning only: etymology prose carries [b], [Song] and other bracketed
            # notation of its own. The rewrite happens at render time, so check the
            # package rather than words.json.
            gloss = {int(m): [f["name"] for f in x["flds"]].index("Meaning")
                     for m, x in models.items()
                     if any(f["name"] == "Meaning" for f in x["flds"])}
            leaked = 0
            for mid, flds in con.execute("select mid,flds from notes"):
                v = flds.split("\x1f")
                if mid in gloss:
                    leaked += bool(re.search(r"\[[A-Za-z0-9:, ]+\]", v[gloss[mid]]))
                for ref in (re.findall(r"\[sound:([^]]+)\]", flds)
                            + re.findall(r'<img [^>]*src="([^"]+)"', flds)):
                    refs.add(ref)
                    if ref not in present:
                        missing.add(ref)
            check("no [numbered pinyin] left in Meaning", leaked == 0,
                  f"{leaked} notes" if leaked else "")
            # A vocabulary card is introduced at the syllabus's own index for the word.
            # The Key numbers the whole deck rather than the syllabus, so the two are
            # no longer the same number; what has to hold is that they agree on the
            # order, since the Key counts the same words in the same sequence.
            rows = con.execute(
                "select cast(substr(n.flds,1,instr(n.flds,char(31))-1) as integer), c.due "
                "from cards c join notes n on n.id=c.nid "
                "where n.mid=(select cast(? as integer)) order by 1",
                (int([m for m, x in models.items()
                      if x["name"] == "HSK 3.0 Vocabulary"][0]),)).fetchall()
            ooo = sum(1 for a, b in zip(rows, rows[1:]) if b[1] <= a[1])
            check("vocabulary due order = syllabus order", ooo == 0,
                  f"{ooo} out of order" if ooo else "")

            check("all media references resolve", not missing,
                  f"{len(missing)} dangling" if missing else "")
            # A name beginning with an underscore is Anki's way of saying a template
            # refers to the file rather than a note: the card CSS names the fonts, and
            # no note ever will.
            extra = {x for x in bundled - refs if not x.startswith("_")}
            styled = sorted(bundled - refs - extra)
            check("no unreferenced media bundled", not extra,
                  f"{len(extra)} extra" if extra else "")
            check(f"{len(styled)} files the templates name", True,
                  ", ".join(styled) if styled else "")
            if missing:
                print("        e.g.", sorted(missing)[:5])
            con.close()

    # Fields are linked in the rendering and again where a word is named, and a link
    # inside a link renders as broken markup rather than as a link.
    with zipfile.ZipFile(APKG) as z:
        name = next(x for x in z.namelist() if x.startswith("collection.anki"))
        with tempfile.TemporaryDirectory() as td:
            z.extract(name, td)
            con = sqlite3.connect(pathlib.Path(td) / name)
            nested = unbalanced = 0
            for (f,) in con.execute("select flds from notes"):
                nested += bool(re.search(r"<a\b[^>]*>(?:(?!</a>).)*<a\b", f))
                unbalanced += f.count("<a ") != f.count("</a>")
            con.close()
    check(f"{nested} notes with a link inside a link", not nested)
    check(f"{unbalanced} notes with an unclosed link", not unbalanced)

    print("\ntone marks sit where the rules put them")
    # a or e takes it; failing that the o of ou; failing that the last vowel
    TONE = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ"
    flat = str.maketrans(TONE, "aaaaeeeeiiiioooouuuuüüüü")

    def misplaced(syllable: str):
        marked = [i for i, ch in enumerate(syllable.lower()) if ch in TONE]
        if len(marked) != 1:
            return None
        plain = syllable.lower().translate(flat)
        vowels = [i for i, ch in enumerate(plain) if ch in "aeiouü"]
        if not vowels:
            return None
        want = (plain.index("a") if "a" in plain else
                plain.index("e") if "e" in plain else
                plain.index("ou") if "ou" in plain else vowels[-1])
        return None if marked[0] == want else syllable

    def scan(pairs):
        out = []
        for label, text in pairs:
            for word in re.split(r"[^a-zü" + TONE + TONE.upper() + r"]+", text or ""):
                for syllable in (syllabify(word) if word else []):
                    if misplaced(syllable):
                        out.append((label, syllable))
        return out

    for name, pairs in [
            ("syllabus", [(w["simplified"], w["pinyin"]) for w in words]),
            ("sentences", [(r["chinese"][:8], r["pinyin"]) for r in csv.DictReader(
                (ROOT / "data/grammar-pinyin.csv").open(encoding="utf-8"))]
             if (ROOT / "data/grammar-pinyin.csv").exists() else [])]:
        off = scan(pairs)
        check(f"{name}: {len(off)} misplaced", not off, str(off[:4]) if off else "")

    print("\nfield sanity")
    check("every word has pinyin", all(w["pinyin"] for w in words))
    check("every word has a level", all(w["level"] in LEVELS for w in words))
    check("every word has stroke order", all(w["stroke_order"] for w in words))
    check("no digits leaked into Simplified",
          not [w for w in words if any(c.isdigit() for c in w["simplified"])])
    audio = sum(1 for w in words if w["audio"])
    cmn = sum(1 for w in words if w["audio_source"].startswith("audio-cmn")
              and "Chen Wang" not in w["audio_source"])
    other_voice = sum(1 for w in words if "Chen Wang" in w["audio_source"])
    stacked = sum(1 for w in words if "per-character" in w["audio_source"])
    said = sum(1 for w in words if "azure" in w["audio_source"])
    # Not everything: a word listed twice with two readings can only use a recording
    # of its own, and nothing says 过 guo where 过 guò is what was recorded.
    check(f"audio {audio}/{len(words)} ({100*audio/len(words):.1f}%)",
          len(words) - audio <= 8)
    check(f"  of which per-character stacks: {stacked}", stacked > 1700)
    check(f"  of which synthesised: {said} ({100*said/max(audio,1):.1f}%)",
          1900 < said < 2400)
    # a recorded voice still says four words in five; the rest had no recording
    check(f"Yue Tan {100*cmn/max(audio - said, 1):.1f}% of what was recorded",
          cmn / max(audio - said, 1) > 0.99)
    # zero means the syllabs checkout is missing
    check(f"second speaker on {other_voice} single characters", 0 < other_voice < 60)
    char_audio = json.loads((BUILD / "char-audio.json").read_text(encoding="utf-8"))
    have = len(char_audio)
    check(f"writing-character audio {have}/1200 ({100*have/1200:.1f}%)", have > 800)

    print()
    if fails:
        print(f"{len(fails)} check(s) FAILED: {fails}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

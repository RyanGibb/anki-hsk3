#!/usr/bin/env python3
"""Merge two independent extractions of the 2025 syllabus into one word table.

They agree on 10,940 words; this asserts that rather than trusting it.
"""
import collections
import csv
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw"
BUILD = ROOT / "build"

LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
LEVEL_ORDER = {lv: i for i, lv in enumerate(LEVELS)}
CJK = re.compile(r"[㐀-鿿豈-﫿]")

HOMOGRAPH = re.compile(r"^(.+?)(\d+)$")


def read_tsv(path):
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def split_homograph(entry: str) -> tuple[str, str]:
    m = HOMOGRAPH.match(entry)
    if m and CJK.search(m.group(1)):
        return m.group(1), m.group(2)
    return entry, ""


CEDICT_LINE = re.compile(r"^(\S+) (\S+) \[([^]]*)\] /(.*)/$")

CL_GLOSS = re.compile(r"^CL:(.+)$")
CL_INLINE = re.compile(r"\(CL:([^)]*)\)")
CL_ITEM = re.compile(r"^(?:[^|\[]+\|)?([^\[]+)(?:\[[^]]*\])?$")
# A classifier is written as characters. "(CL: used before a noun that has no
# specific classifier)" is prose about 个, not a list of classifiers.
CJK_ONLY = re.compile(r"[㐀-鿿豈-﫿]+(?:、[㐀-鿿豈-﫿]+)*")


def split_classifiers(defs: list[str]) -> tuple[list[str], str]:
    keep, cls = [], []

    def collect(spec: str) -> None:
        for item in spec.split(","):
            n = CL_ITEM.match(item.strip())
            if n and n.group(1).strip() not in cls:
                cls.append(n.group(1).strip())

    def spec_of(d: str) -> str:
        m = CL_INLINE.search(d)
        return "、".join(n.group(1).strip()
                        for item in m.group(1).split(",")
                        if (n := CL_ITEM.match(item.strip()))) if m else ""

    # CC-CEDICT states a classifier either as a sense of its own or inside one. Inside
    # one it can belong to that sense alone -- 菜 takes 棵 as a vegetable and 盘 as a
    # dish -- and then it has to stay where it is, next to the sense it governs. Where
    # every sense agrees, as 歌 does on 首, it belongs in the classifier field with the
    # ones stated separately, which is where the card looks for it.
    inline = {s for s in (spec_of(d) for d in defs) if s}
    lift = len(inline) == 1 and CJK_ONLY.fullmatch(next(iter(inline)))

    for d in defs:
        m = CL_GLOSS.match(d)
        if m:
            collect(m.group(1))
            continue
        if lift:
            d = CL_INLINE.sub("", d).replace("  ", " ").strip()
            collect(next(iter(inline)).replace("、", ","))
        else:
            d = CL_INLINE.sub(lambda m: "(classifier " + spec_of(m.group(0)) + ")",
                              d).strip()
        if d:
            keep.append(d)
    return keep, "、".join(cls)

# Glosses describing a spelling, not a meaning: "variant of 藥|药" against "medicine".
META = re.compile(
    r"^(?:old |erroneous |archaic |erhua )?variant of "
    r"|^see (?:also )?[㐀-鿿豈-﫿]"
    r"|^used in \S"
    r"|^surname \S+$"
    r"|^\S+ \(surname\)$"
    r"|^also written "
    r"|^abbr\. for "
)

VARIANT = re.compile(r"^(?:old |erroneous |archaic |erhua )?variant of ")
POINTER = re.compile(r"(?:variant of|also written|see) ([㐀-鿿豈-﫿]+)(?:\||\[|$)")
POINTER_SIMP = re.compile(
    r"(?:variant of|also written|see(?: also)?|abbr\. for) "
    r"(?:[㐀-鿿豈-﫿]+\|)?([㐀-鿿豈-﫿]+)")


def pointer_targets(entry) -> set[str]:
    out = set()
    for d in entry["defs"]:
        if META.match(d):
            m = POINTER.search(d)
            if m:
                out.add(m.group(1))
    return out


def load_cedict(*paths) -> dict[str, list[dict]]:
    """simplified -> [{trad, pinyin, defs}], each gloss kept with its own traditional
    form. Reads the dictionary and then the patch of words it lacks."""
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for path in paths:
        if not pathlib.Path(path).exists():
            continue
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                continue
            m = CEDICT_LINE.match(line.rstrip("\n"))
            if not m:
                continue
            trad, simp, pinyin, defs = m.groups()
            out[simp].append(
                {"trad": trad, "pinyin": pinyin.lower(),
                 "proper": pinyin[:1].isupper(),
                 "defs": [d for d in defs.split("/") if d]}
            )
    return out


def norm_pinyin(p: str) -> str:
    return p.lower().replace(" ", "").replace("u:", "v").replace("ü", "v")


def pick_entry(pinyin_numbered, entries, wikt):
    """Choose ONE entry, so traditional and meaning stay consistent: 台风 is either
    臺風 "poise" or 颱風 "typhoon"."""
    if not entries:
        return None, "none"
    cands = entries
    want = norm_pinyin(pinyin_numbered)
    def substantive_defs(e):
        return [d for d in e["defs"] if not META.match(d)]

    same_pinyin = [e for e in cands if norm_pinyin(e["pinyin"]) == want]
    if same_pinyin and any(substantive_defs(e) for e in same_pinyin):
        cands = same_pinyin

    votes: collections.Counter = collections.Counter()
    for e in cands:
        votes.update(pointer_targets(e))

    common = [e for e in cands if not e["proper"]]
    if common and any(substantive_defs(e) for e in common):
        cands = common

    real = [e for e in cands if substantive_defs(e)]
    if real:
        cands = real

    def merge(group, source):
        defs, seen = [], set()
        for e in group:
            for d in e["defs"]:
                if d not in seen:
                    seen.add(d)
                    defs.append(d)
        return {"trad": group[0]["trad"], "pinyin": group[0]["pinyin"],
                "defs": defs}, source

    by_trad: dict[str, list[dict]] = collections.defaultdict(list)
    for e in cands:
        by_trad[e["trad"]].append(e)
    if len(by_trad) == 1:
        return merge(cands, "cedict")

    weight = {t: sum(len(substantive_defs(e)) for e in g) for t, g in by_trad.items()}
    best = max(weight.values())
    top = [t for t, n in weight.items() if n == best]
    if len(top) == 1:
        return merge(by_trad[top[0]], "cedict:primary")

    pointed = [t for t in top if votes[t]]
    if len(pointed) == 1:
        return merge(by_trad[pointed[0]], "cedict:pointer")

    live = [t for t in top if wikt.get(t, {}).get("live")]
    if len(live) == 1:
        return merge(by_trad[live[0]], "cedict+wiktionary")
    return merge(by_trad[top[0]], "cedict-ambiguous")


def main() -> int:
    wikt_path = BUILD / "wiktionary.json"
    if not wikt_path.exists():
        sys.exit("run scripts/01_wiktionary_index.py first")
    wikt = json.loads(wikt_path.read_text(encoding="utf-8"))
    cedict = load_cedict(RAW / "cedict_ts.u8", RAW / "cedict_patch.u8")
    print(f"cc-cedict simplified headwords: {len(cedict)}")

    punpuf = read_tsv(RAW / "punpuf_hsk_word_list.tsv")
    # Readings the syllabus gives wrongly, where CC-CEDICT and pypinyin agree against
    # it and the deck's own other words settle the sense: 温差 is the 差 of 时差 and
    # 差距. Correcting the reading here fixes the card, the audio chosen for it and
    # the sense picked for each of its characters, which all follow from it.
    fixes = ROOT / "data/reading-fixes.csv"
    if fixes.exists():
        by_word = {r["word"]: r for r in csv.DictReader(fixes.open(encoding="utf-8"))}
        for r in punpuf:
            fix = by_word.get(r["word"])
            if fix and r["pinyin_numbered"] == fix["was"]:
                r["pinyin_numbered"] = fix["pinyin_numbered"]
                r["pinyin"] = fix["pinyin"]
    chelsea = read_tsv(RAW / "chelsea_vocabulary.tsv")

    p_words = {r["word"] for r in punpuf}
    c_words = {r["word"] for r in chelsea}
    if p_words != c_words:
        sys.exit(
            f"sources disagree: {len(p_words - c_words)} only in punpuf, "
            f"{len(c_words - p_words)} only in chelsea"
        )
    print(f"cross-validated: {len(p_words)} unique words, zero set difference")

    # 长 is in the syllabus twice, as cháng and as zhǎng, and so are 56 other words.
    # Each reading is its own entry, numbered 长1 and 长2 the way split_homograph reads
    # them, so each gets its own note and guid.
    readings: dict[str, list] = collections.defaultdict(list)
    for r in sorted(punpuf, key=lambda r: int(r["word_index"])):
        if r["pinyin_numbered"] not in [x["pinyin_numbered"]
                                        for x in readings[r["word"]]]:
            readings[r["word"]].append(r)

    def entry_of(row) -> str:
        rs = readings[row["word"]]
        if len(rs) == 1:
            return row["word"]
        n = [x["pinyin_numbered"] for x in rs].index(row["pinyin_numbered"]) + 1
        return f"{row['word']}{n}"

    first: dict[str, dict] = {}
    levels: dict[str, set[str]] = collections.defaultdict(set)
    for r in sorted(punpuf, key=lambda r: int(r["word_index"])):
        first.setdefault(entry_of(r), r)
        levels[entry_of(r)].add(r["level"])
    entries_all = set(first)

    POS_SPLIT = re.compile(r"[、,／/（）()]+")

    def pos_tokens(s: str) -> frozenset:
        return frozenset(t for t in POS_SPLIT.split(s) if t.strip())

    # Keyed on the entry, not the word: 本 is a classifier in one entry and a pronoun
    # in the other, and merging them loses the only thing telling the two cards apart.
    raw_pos: dict[str, list[str]] = collections.defaultdict(list)
    by_reading = {(r["word"], r["pinyin_numbered"]): entry_of(r) for r in punpuf}
    for r in chelsea:
        v = (r.get("cixing") or "").strip()
        key = by_reading.get((r["word"], r.get("pinyin_numbered") or ""), r["word"])
        if v and v not in raw_pos[key]:
            raw_pos[key].append(v)
    for r in punpuf:
        v = (r.get("part_of_speech") or "").strip()
        if v and v not in raw_pos[entry_of(r)]:
            raw_pos[entry_of(r)].append(v)

    pos: dict[str, list[str]] = {}
    for word, variants in raw_pos.items():
        keep = []
        for i, v in enumerate(variants):
            tv = pos_tokens(v)
            covered = any(
                tv < pos_tokens(o) or (tv == pos_tokens(o) and j < i)
                for j, o in enumerate(variants) if j != i
            )
            if not covered:
                keep.append(v)
        pos[word] = keep

    # Not the gold set: that is the test, and feeding it back would make 05_verify
    # circular.
    adjudicated = {
        row["entry"]: row["traditional"]
        for row in csv.DictReader(
            (ROOT / "data/traditional-overrides.csv").open(encoding="utf-8")
        )
    }

    def follow_pointer(defs, depth=0):
        """Resolve "variant of 標誌|标志" to the target's glosses."""
        if depth > 2 or not defs:
            return defs
        if not all(META.match(d) for d in defs):
            return defs
        for d in defs:
            m = POINTER_SIMP.search(d)
            if not m:
                continue
            for e in cedict.get(m.group(1), []):
                got = [x for x in e["defs"] if not META.match(x)]
                if got:
                    return got
                nxt = follow_pointer(e["defs"], depth + 1)
                if nxt and nxt != e["defs"]:
                    return nxt
        return defs

    words = []
    overridden = 0
    for entry in sorted(entries_all, key=lambda w: int(first[w]["word_index"])):
        r = first[entry]
        simplified, homograph_idx = split_homograph(entry)
        lv = sorted(levels[entry], key=lambda x: LEVEL_ORDER[x])
        entries = cedict.get(simplified, [])
        chosen, trad_src = pick_entry(r["pinyin_numbered"], entries, wikt)
        if chosen:
            traditional = chosen["trad"]
            defs, classifier = split_classifiers(follow_pointer(chosen["defs"]))
            # A note that one spelling is a variant of another is not a meaning, and
            # where the entry says something of its own it is only clutter: 週 is
            # "week; weekly; variant of 周" and 搜 "to search; variant of 蒐". Only
            # variants: "abbr. for 环境保护" is what 环保 means, and "see 正版" points
            # somewhere a reader may want to go. Where every sense is a direction
            # follow_pointer has already replaced them, so this never takes them all.
            if any(not VARIANT.match(d) for d in defs):
                defs = [d for d in defs if not VARIANT.match(d)]
            meaning = "/".join(defs)
        else:
            traditional = simplified
            trad_src = "fallback:unchanged"
            classifier = ""
            meaning = (r.get("definition_cc-cedict") or "").strip()
        traditional_auto = traditional  # kept so verification isn't circular

        decided = adjudicated.get(entry, adjudicated.get(simplified))
        if decided:
            if decided != traditional:
                overridden += 1
                match = [e for e in entries if e["trad"] == decided]
                if match:
                    defs, classifier = split_classifiers(
                        list(dict.fromkeys(d for e in match for d in e["defs"])))
                    # the same rule the chosen entry gets
                    if any(not VARIANT.match(d) for d in defs):
                        defs = [d for d in defs if not VARIANT.match(d)]
                    meaning = "/".join(defs)
            traditional = decided
            trad_src = "adjudicated"
        words.append(
            {
                "key": r["word_index"],
                "entry": entry,
                "simplified": simplified,
                "homograph_index": homograph_idx,
                "level": lv[0],
                "also_levels": lv[1:],
                "pinyin": r["pinyin"],
                "pinyin_numbered": r["pinyin_numbered"],
                "traditional": traditional,
                "traditional_auto": traditional_auto,
                "traditional_source": trad_src,
                "cedict_candidates": "/".join(e["trad"] for e in entries),
                "meaning": meaning,
                # The dictionary's own glosses, kept before any hand editing below. A
                # word split across two cards divides these between them, and 05_verify
                # needs the undivided list to check that every sense reaches a card.
                "meaning_full": meaning,
                "classifier": classifier,
                "pos": pos.get(entry) or pos.get(simplified, []),
            }
        )

    # The dictionary keeps a reading in the same slot as a meaning, separated by the
    # same slash: 差 ends "not up to standard; inferior/Taiwan pr. [cha1]". The deck
    # teaches one standard and drops those, and dropping them here rather than when
    # the card is drawn means everything downstream sees the list the card will show.
    # Without it 差 has a sense that is neither adjective nor verb and cannot be
    # divided by part of speech, over a string no card ever displays.
    READING_ONLY = re.compile(r"^\(?(?:Taiwan|also|old|dial\.?|coll\.?)\s+pr\.", re.I)
    for w in words:
        for field in ("meaning", "meaning_full"):
            kept = [s for s in w[field].split("/") if s and not READING_ONLY.match(s.strip())]
            if kept:
                w[field] = "/".join(kept)

    curated = {
        row["entry"]: row["meaning"]
        for row in csv.DictReader(
            (ROOT / "data/homograph-glosses.csv").open(encoding="utf-8")
        )
    }
    curated_used = 0
    for w in words:
        if w["entry"] in curated:
            w["meaning"] = curated[w["entry"]]
            w["meaning_source"] = "curated"
            curated_used += 1
        else:
            w["meaning_source"] = "cc-cedict"

    # The syllabus marks 可以 动、形 and then leaves you to work out which of "can, may,
    # possible, able to, not bad, pretty good" is the adjective. Where a word is split
    # across two entries the division is written in homograph-glosses.csv; where one
    # entry carries two parts of speech there is nothing to hang it on, so it is
    # written here instead. The dictionary says which senses are verbs, in that it
    # writes them "to ...", and says nothing about the rest.
    by_pos = collections.defaultdict(list)
    path = ROOT / "data/sense-pos.csv"
    if path.exists():
        for row in csv.DictReader(path.open(encoding="utf-8")):
            by_pos[row["entry"]].append((row["pos"], row["meaning"]))
    for w in words:
        w["meaning_by_pos"] = by_pos.get(w["entry"], [])
    print(f"  senses split by part of speech: {len(by_pos)} entries")

    # A card leads with the first sense and hides the rest, so the first has to be the
    # sense the syllabus is teaching. 种 at level 3 is marked 量, a classifier, and the
    # dictionary opens it on "seed" with "classifier for types, kinds, sorts" fifth --
    # the card taught seed. Where the syllabus gives an entry no part of speech but 量,
    # the classifier sense leads. Where it gives others too, 口 is a mouth before it
    # counts people and the dictionary's order stands.
    CLASSIFIER_SENSE = re.compile(r"^(?:\(.*?\)\s*)?(?:classifier for|measure word)",
                                  re.I)
    promoted = 0
    for w in words:
        if {p for group in (w["pos"] or []) for p in group} != {"量"}:
            continue
        senses = [x for x in w["meaning"].split("/") if x.strip()]
        first = next((i for i, x in enumerate(senses) if CLASSIFIER_SENSE.match(x)), 0)
        if first:
            w["meaning"] = "/".join([senses[first]] + senses[:first] + senses[first + 1:])
            promoted += 1
    print(f"  classifier sense first  : {promoted} entries")

    by_pinyin: dict[str, list[str]] = collections.defaultdict(list)
    by_simplified: dict[str, list[str]] = collections.defaultdict(list)
    for w in words:
        by_pinyin[w["pinyin_numbered"].replace(" ", "")].append(w["entry"])
        by_simplified[w["simplified"]].append(w["entry"])
    # An entry is the syllabus's own key for telling two words of one spelling apart,
    # 只1 from 只2, and it belongs in a lookup and not on a card. A homophone is shown,
    # so it is shown as the word is written -- and two entries of one spelling are one
    # homophone, not 支1 and 支2 side by side.
    written = {w["entry"]: w["simplified"] for w in words}
    for w in words:
        key = w["pinyin_numbered"].replace(" ", "")
        w["homograph"] = [e for e in by_simplified[w["simplified"]] if e != w["entry"]]
        same_word = set(by_simplified[w["simplified"]])
        w["homophone"] = list(dict.fromkeys(
            written[e] for e in by_pinyin[key] if e not in same_word))

    # every character in the vocabulary, not just the 1200 that get a writing card:
    # the etymology on a word's answer side is keyed on each character's traditional form
    chars = {r["word"] for r in read_tsv(RAW / "chelsea_hanzi_writing.tsv")}
    chars |= {c for w in words for c in w["simplified"] if CJK.match(c)}
    # Without a reading, every entry for the form merges and 打 opens on 打 (dá)
    # "a dozen". A character is met inside a word long before it is taught alone -- 调
    # is 空调 at level 3, diào only at 7-9 -- so the earliest word to use it decides
    # both which reading leads and which example the card shows.
    order = sorted(words, key=lambda w: (LEVEL_ORDER[w["level"]], int(w["key"])))
    char_example: dict[str, dict] = {}
    solo_reading: dict[str, str] = {}
    for w in order:
        if len(w["simplified"]) == 1:
            solo_reading.setdefault(w["simplified"], w["pinyin_numbered"])
            continue
        syllables = w["pinyin_numbered"].split()
        if len(syllables) != len(w["simplified"]):
            continue
        for ch, syllable in zip(w["simplified"], syllables):
            char_example.setdefault(ch, {
                "word": w["simplified"], "pinyin": w["pinyin"],
                "meaning": w["meaning"].split("/")[0], "reading": syllable.lower()})

    def settle(ch: str, entries: list[dict]) -> str:
        """The reading to narrow on, as CC-CEDICT spells it.

        A compound may neutralise the tone -- 多少 gives shao5, which is no entry at
        all -- so fall back to the toneless match when it is unambiguous, then to the
        character's own entry in the syllabus.
        """
        have = {norm_pinyin(e["pinyin"]) for e in entries}
        want = char_example.get(ch, {}).get("reading", "")
        if want and norm_pinyin(want) in have:
            return want
        if want.endswith("5"):
            bare = norm_pinyin(want)[:-1]
            same = [p for p in have if p[:-1] == bare]
            if len(same) == 1:
                return same[0]
        return solo_reading.get(ch, "")

    # The example word's own traditional form has already been through adjudication, so
    # it beats re-deriving the character's: 仿佛 is 彷彿, which settles 佛 as 彿 and not
    # 髴 "female head ornament".
    by_form = {}
    for w in words:
        by_form.setdefault(w["simplified"], w)
    from_word: dict[str, str] = {}
    for c, e in char_example.items():
        w = by_form.get(e["word"])
        if w and len(w["simplified"]) == len(w["traditional"]):
            from_word[c] = w["traditional"][w["simplified"].index(c)]

    char_info = {}
    for c in sorted(chars):
        entries = cedict.get(c, [])
        want = from_word.get(c)
        # The word decides which entry LEADS; every other sense still follows it.
        pool = [e for e in entries if e["trad"] == want] or entries if want else entries
        chosen, _ = pick_entry(settle(c, pool), pool, wikt)
        if not chosen:
            continue
        defs = [d for d in follow_pointer(chosen["defs"])
                if not META.match(d) and not d.startswith("CL:")]
        rest = [d for e in entries if e["trad"] != chosen["trad"]
                or e["pinyin"] != chosen["pinyin"]
                for d in e["defs"]
                if not META.match(d) and not d.startswith("CL:") and d not in defs]
        # The word decides the senses, not the character's identity. 面包 is 麵包, but
        # the glyph being written is 面, whose origin is a face and not wheat, so the
        # traditional form stays with the unnarrowed ranking that gets 万 -> 萬.
        main, _ = pick_entry(solo_reading.get(c, ""), entries, wikt)
        char_info[c] = {"meaning": "/".join(defs + rest),
                        "traditional": (main or chosen)["trad"],
                        "example": char_example.get(c, {})}
    (BUILD / "char-meanings.json").write_text(
        json.dumps(char_info, ensure_ascii=False), encoding="utf-8")
    got = sum(1 for v in char_info.values() if v["meaning"])
    print(f"  character glosses      : {got}/{len(chars)}")

    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "words.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    multi = [w for w in words if w["also_levels"]]
    homographs = [w for w in words if w["homograph_index"]]
    ambiguous = [w for w in words if w["traditional_source"] == "cedict-ambiguous"]
    variant_pairs = [w for w in words if "/" in w["cedict_candidates"]]
    unchanged = [w for w in words if w["traditional"] == w["simplified"]]
    tie_broken = [w for w in words if w["traditional_source"] == "cedict+wiktionary"]
    print(f"words written            : {len(words)}")
    print(f"  multi-level            : {len(multi)}")
    print(f"  curated homograph gloss: {curated_used}")
    print(f"  wiktionary broke a tie : {len(tie_broken)}")
    print(f"  adjudicated override   : {overridden}")
    print(f"  homograph entries      : {len(homographs)}  e.g. "
          f"{[w['entry'] for w in homographs[:6]]}")
    print(f"  traditional == simp    : {len(unchanged)}")
    print(f"  still ambiguous        : {len(ambiguous)}")
    print(f"  cedict variant pairs   : {len(variant_pairs)}")
    by_level = collections.Counter(w["level"] for w in words)
    print("  per level              : "
          + ", ".join(f"L{lv}={by_level[lv]}" for lv in LEVELS))

    (BUILD / "traditional-review.csv").write_text(
        "entry,simplified,wiktionary,cedict,source\n"
        + "\n".join(
            f"{w['entry']},{w['simplified']},{w['traditional']},"
            f"{w['cedict_candidates']},{w['traditional_source']}"
            for w in ambiguous + variant_pairs
        ),
        encoding="utf-8",
    )
    print(f"wrote {BUILD/'words.json'} and {BUILD/'traditional-review.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

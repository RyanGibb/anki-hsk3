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
    TONED = re.compile(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]")
    T = str.maketrans("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ", "aaaaeeeeiiiioooouuuuüüüü")
    def nm(x):
        return (x.split("/")[0].replace(" ", "")
                .replace("\u2019", "").replace("'", "").lower())
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
        elif (len(TONED.findall(c)) == len(TONED.findall(r))
              and w["simplified"][:1] not in "一不"):
            wrong.append((w["simplified"], w["pinyin"], swac[m[0]]))
    check(f"{len(wrong)} recordings with a mismatched reading", not wrong,
          str(wrong[:4]) if wrong else "")

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
            check(f"{n_notes} notes in db", n_notes == 12733)
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
            # the cross-reference rewrite happens at render time, so check the package
            leaked = 0
            for (flds,) in con.execute("select flds from notes"):
                leaked += bool(re.search(r"\[[A-Za-z0-9:, ]+\]", flds))
                for ref in (re.findall(r"\[sound:([^]]+)\]", flds)
                            + re.findall(r'<img [^>]*src="([^"]+)"', flds)):
                    refs.add(ref)
                    if ref not in present:
                        missing.add(ref)
            check("no [numbered pinyin] left in fields", leaked == 0,
                  f"{leaked} notes" if leaked else "")
            ooo = con.execute(
                "select count(*) from cards c join notes n on n.id=c.nid "
                "where n.mid=(select cast(? as integer)) "
                "and c.due <> cast(substr(n.flds,1,instr(n.flds,char(31))-1) as integer)",
                (int([m for m, x in models.items()
                      if x["name"] == "HSK 3.0 Vocabulary"][0]),)).fetchone()[0]
            check("vocabulary due order = syllabus index", ooo == 0,
                  f"{ooo} out of order" if ooo else "")

            check("all media references resolve", not missing,
                  f"{len(missing)} dangling" if missing else "")
            check("no unreferenced media bundled", bundled == refs,
                  f"{len(bundled - refs)} extra" if bundled - refs else "")
            if missing:
                print("        e.g.", sorted(missing)[:5])
            con.close()

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
    check(f"audio {audio}/{len(words)} ({100*audio/len(words):.1f}%)", audio > 8600)
    check(f"  of which per-character stacks: {stacked}", stacked > 1700)
    check(f"Yue Tan {100*cmn/max(audio,1):.1f}% of audio", cmn / max(audio, 1) > 0.99)
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

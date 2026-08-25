# -*- coding: utf-8 -*-
"""THE FINAL DUEL, Majd's design (2026-08-25): rebuild LAST YEAR's school
from its own aSc export, let the solver play the exact same match, and
compare with tools/score_table.py - same pupils, same teachers, same hours.

Reads data/reference/*.xml, writes data/school_lastyear.xlsx (PRIVATE - the
data/ firewall applies). The current school.xlsx is NOT touched.

Extraction = last year's file is the source of truth:
  - hours per (class, subject, group, week) = the cards actually given
  - groups from the division groups aSc recorded (224 subdivisions)
  - week A/B from the card week masks (145 fortnight cards)
  - blocks = the session run-lengths the school actually used
  - multi-class lessons (23) -> the Options sheet
  - teacher contract = ceil(average weekly card-hours), day off left
    flexible (their real fixed days are unknown - noted caveat)
Rooms are typed 'normal' (type fidelity is unknown; the duel measures
comfort, not room labels - caveat printed).

    python tools/import_lastyear.py
"""
import collections
import glob
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "school_lastyear.xlsx")


def weeks_of(mask):
    m = (mask or "").strip()
    if m == "10":
        return ("A",)
    if m == "01":
        return ("B",)
    return ("A", "B")


def main():
    from openpyxl import Workbook

    hits = glob.glob(os.path.join(HERE, "data", "reference", "**", "*.xml"),
                     recursive=True)
    if not hits:
        sys.exit("No reference export in data/reference/")
    # T3: aSc 2013 exports are cp1256 mislabelled windows-1252 - decode by
    # hand or every Arabic name turns to mojibake.
    raw = open(hits[0], "rb").read().decode("cp1256", errors="replace")
    raw = raw.replace("windows-1252", "utf-8").replace("Windows-1252", "utf-8")
    root = ET.fromstring(raw)

    teachers = {}
    for el in root.iter("teacher"):
        teachers[el.get("id")] = dict(name=el.get("name") or el.get("short") or "",
                                      short=el.get("short") or "")
    classes = {}
    for el in root.iter("class"):
        classes[el.get("id")] = dict(name=el.get("name") or el.get("short") or "",
                                     short=el.get("short") or "")
    rooms = {}
    for el in root.iter("classroom"):
        rooms[el.get("id")] = dict(name=el.get("name") or el.get("short") or "")
    subjects = {}
    for el in root.iter("subject"):
        subjects[el.get("id")] = dict(name=el.get("name") or el.get("short") or "",
                                      short=el.get("short") or "")
    # groups: entireclass flag + per-class numbering of division groups
    entire = set()
    gnum = {}
    per_class_count = collections.Counter()
    for el in root.iter("group"):
        gid = el.get("id")
        if (el.get("entireclass") or "0") in ("1", "true", "True"):
            entire.add(gid)
        else:
            cid = el.get("classid")
            per_class_count[cid] += 1
            gnum[gid] = per_class_count[cid]

    lessons = {}
    for el in root.iter("lesson"):
        lessons[el.get("id")] = dict(
            subject=el.get("subjectid"),
            classes=[c for c in (el.get("classids") or "").split(",") if c],
            groups=[g for g in (el.get("groupids") or "").split(",") if g],
            teachers=[t for t in (el.get("teacherids") or "").split(",") if t],
        )

    # cards -> per (class, subject, teacher, group#, week): list of (day, p)
    placed = collections.defaultdict(list)
    opt_cards = collections.defaultdict(list)   # multi-class lessons
    skipped = 0
    for el in root.iter("card"):
        L = lessons.get(el.get("lessonid"))
        mask = el.get("days") or ""
        if not L or mask.count("1") != 1:
            skipped += 1
            continue
        d = mask.index("1")
        p = int(float(el.get("period")))
        wks = weeks_of(el.get("weeks"))
        tid = L["teachers"][0] if L["teachers"] else ""
        if len(L["classes"]) > 1:
            opt_cards[el.get("lessonid")].append((d, p, wks))
            continue
        cid = L["classes"][0] if L["classes"] else ""
        if not cid:
            skipped += 1
            continue
        g = 0
        for gid in L["groups"]:
            if gid in gnum:
                g = gnum[gid]
                break
        wk = wks[0] if len(wks) == 1 else ""
        placed[cid, L["subject"], tid, g, wk].append((d, p))

    # ---- curriculum rows --------------------------------------------------
    # merge the group copies: hours per group must match; groups = how many
    rows = []
    flags = []
    by_rowkey = collections.defaultdict(dict)   # (cid,subj,tid,wk) -> {g: slots}
    for (cid, subj, tid, g, wk), slots in placed.items():
        by_rowkey[cid, subj, tid, wk][g] = slots

    def blocks_of(slots):
        byday = collections.defaultdict(list)
        for d, p in slots:
            byday[d].append(p)
        runs = []
        for d, ps in byday.items():
            ps.sort()
            run = 1
            for a, b in zip(ps, ps[1:]):
                if b == a + 1:
                    run += 1
                else:
                    runs.append(run)
                    run = 1
            runs.append(run)
        return "+".join(str(r) for r in sorted(runs, reverse=True))

    for (cid, subj, tid, wk), by_g in sorted(by_rowkey.items()):
        gs = sorted(by_g)
        if gs == [0]:
            slots = by_g[0]
            rows.append((cid, subj, len(slots), tid, blocks_of(slots), 1, "", "", wk))
        else:
            whole = by_g.pop(0, None)
            if whole:
                rows.append((cid, subj, len(whole), tid, blocks_of(whole),
                             1, "", "", wk))
            counts = {g: len(sl) for g, sl in by_g.items()}
            h = max(counts.values())
            if len(set(counts.values())) > 1:
                flags.append("%s/%s: groups with unequal hours %r - took max"
                             % (cid, subj, counts))
            n = max(2, len(by_g))
            rows.append((cid, subj, h, tid, blocks_of(by_g[max(by_g)]),
                         n, "", "", wk))

    # ---- options (multi-class lessons) ------------------------------------
    # CHOICE options (Spanish/German/Italian/Music/Art) sharing classes are
    # simultaneous bands (H14). Other multi-class lessons - pooled SPORT in
    # the stadium etc. - are joint lessons, each its OWN band (blank cell).
    CHOICE_KEYS = ("إسبان", "ألمان", "المان", "إيطال", "ايطال", "موسيق", "تشكيل")

    def is_choice(subj_id):
        name = subjects.get(subj_id, {}).get("name", "")
        return any(k in name for k in CHOICE_KEYS)

    parent = {}

    def find(a):
        while parent.get(a, a) != a:
            parent[a] = parent.get(parent[a], parent[a])
            a = parent[a]
        return a

    # honest banding: two choice lessons are one band only if last year
    # actually ran them AT THE SAME SLOTS while sharing a class - the data
    # showed pooled options were NOT all simultaneous (different hours,
    # same teacher across pools), so class-sharing alone proves nothing.
    def sig(lid):
        return tuple(sorted((d, p, w) for d, p, wks in opt_cards[lid]
                            for w in wks))

    by_class_sig = {}
    for lid in opt_cards:
        if not is_choice(lessons[lid]["subject"]):
            continue
        parent.setdefault(lid, lid)
        for c in lessons[lid]["classes"]:
            key = (c, sig(lid))
            if key in by_class_sig:
                ra, rb = find(lid), find(by_class_sig[key])
                if ra != rb:
                    parent[ra] = rb
            by_class_sig[key] = lid
    band_of = {}
    n_bands = 0
    for lid in sorted(opt_cards):
        if is_choice(lessons[lid]["subject"]):
            root_ = find(lid)
            if root_ not in band_of:
                n_bands += 1
                band_of[root_] = "OPTB%d" % n_bands
            band_of[lid] = band_of[root_]

    opts = []
    for lid, cards in sorted(opt_cards.items()):
        L = lessons[lid]
        tid = L["teachers"][0] if L["teachers"] else ""
        opts.append(("LY_%s" % lid, L["subject"], tid, len(cards), "",
                     ";".join(L["classes"]), "", band_of.get(lid, "")))

    # ---- option hours = the busier week's card count ----------------------
    opts_fixed = []
    for oid, subj, tid, _h, bl, cls, rt, band in opts:
        lid = oid[3:]
        per_w = {"A": 0, "B": 0}
        for d, p, wks in opt_cards[lid]:
            for w in wks:
                per_w[w] += 1
        opts_fixed.append((oid, subj, tid, max(per_w.values()) or 1, bl, cls,
                           rt, band))
    opts = opts_fixed

    # ---- repair pass: a class booked past the 44-period week --------------
    # Last year sometimes NESTED a short option inside a longer one (pupil
    # subsets we cannot model). Whole-class band booking then overflows the
    # week. Repair: release such a class from its smallest extra band,
    # flagged - the duel loses one binding, not a lesson.
    week_slots = 44
    def class_loads():
        load = collections.defaultdict(lambda: [0, 0])
        for (cid, subj, h, tid, bl, g, rt, core, wk) in rows:
            for i, w in enumerate("AB"):
                if wk in ("", w, "ALT", "ALT2"):
                    load[cid][i] += h
        for oid, subj, tid, h, bl, cls, rt, band in opts:
            for c in cls.split(";"):
                for i in (0, 1):
                    load[c][i] += h
        return load
    for _ in range(10):
        load = class_loads()
        over = [(c, max(e)) for c, e in load.items() if max(e) > week_slots]
        if not over:
            break
        c, _n = over[0]
        mine = [(i, o) for i, o in enumerate(opts) if c in o[5].split(";")]
        if not mine:
            break
        mine.sort(key=lambda io: io[1][3])       # smallest hours first
        i, o = mine[0]
        rest = [x for x in o[5].split(";") if x != c]
        flags.append("class %s over %d slots: released from option %s (%dh)"
                     % (c, week_slots, o[0], o[3]))
        if rest:
            opts[i] = o[:5] + (";".join(rest),) + o[6:]
        else:
            opts.pop(i)

    # ---- teacher contracts: EXACTLY the checker's arithmetic --------------
    # (hours x groups per week from the WRITTEN rows + options both weeks),
    # so H10 is clean by construction.
    tload = collections.defaultdict(lambda: [0.0, 0.0])
    for (cid, subj, h, tid, bl, g, rt, core, wk) in rows:
        if not tid:
            continue
        e = tload[tid]
        th = h * max(1, g)
        if wk in ("", "A"):
            e[0] += th
        if wk in ("", "B"):
            e[1] += th
    for oid, subj, tid, h, bl, cls, rt, band in opts:
        if tid:
            tload[tid][0] += h
            tload[tid][1] += h

    wb = Workbook()

    def sheet(name, header, data):
        ws = wb.create_sheet(name) if wb.sheetnames != ["Sheet"] else wb.active
        ws.title = name
        ws.append(header)
        ws.append(["" for _ in header])
        for r in data:
            ws.append(list(r))

    sheet("Teachers",
          ["id", "name", "short", "subjects", "hours", "day_off",
           "training_day", "compact", "travels_with", "notes"],
          [[tid, t["name"], t["short"], "",
            int(math.ceil(sum(tload.get(tid, [0, 0])) / 2.0)) or "",
            "", "", "", "", "contract = last year's average card-hours"]
           for tid, t in sorted(teachers.items())])
    sheet("Classes",
          ["id", "name", "grade", "stream", "is_bac", "cohort", "home_room", "size"],
          [[cid, c["name"],
            next((ch for ch in c["name"] if ch.isdigit()), ""),
            "", "yes" if c["name"].strip().startswith("4") else "",
            "ALL", "", ""]
           for cid, c in sorted(classes.items())])
    sheet("Rooms",
          ["id", "name", "type", "capacity", "zone", "notes"],
          [[rid, r["name"], "normal", 99, "",
            "type unknown - duel measures comfort, not room labels"]
           for rid, r in sorted(rooms.items())])
    sheet("Subjects",
          ["id", "name", "short", "difficulty", "room_type", "latest_period",
           "avoid_after", "minmax_exempt", "gap24", "not_after", "nature"],
          [[sid, s["name"], s["short"], "medium", "normal",
            "", "", "", "", "", ""]
           for sid, s in sorted(subjects.items())])
    sheet("Curriculum",
          ["class_id", "subject_id", "hours", "teacher_id", "blocks", "groups",
           "room_type", "core", "week"],
          rows)
    sheet("Options",
          ["id", "subject_id", "teacher_id", "hours", "blocks", "classes",
           "room_type", "band"],
          opts)
    wb.save(OUT)
    print("wrote %s" % OUT)
    print("  %d teachers, %d classes, %d rooms, %d subjects"
          % (len(teachers), len(classes), len(rooms), len(subjects)))
    print("  %d curriculum rows (%d with groups>1, %d fortnight A/B), "
          "%d option groups, %d cards skipped"
          % (len(rows), sum(1 for r in rows if r[5] > 1),
             sum(1 for r in rows if r[8]), len(opts), skipped))
    for f in flags[:10]:
        print("  FLAG:", f)


if __name__ == "__main__":
    main()

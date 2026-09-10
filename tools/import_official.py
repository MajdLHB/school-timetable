# -*- coding: utf-8 -*-
"""Build data/school_official.xlsx from the school's OFFICIAL this-year aSc
export (data/reference/official this year work/official this year.xml).

Majd, 2026-09-07: that file is the source of truth for this year - which
cards exist, what each class studies, who teaches it, and where classes can
sit (ordinary lessons seen in labs and in the Group room are facts). The
logic is the proven last-year importer (tools/import_lastyear.py) with:

  * rooms typed from their names; the Group room is an ordinary room of
    capacity 19 (six small classes used it), labs are ordinary-capable;
  * multi-class option lessons of one subject+teacher+pool merged into one
    option group (their 2h + 1h lessons -> hours 3, blocks 2+1), bands =
    connected pools of equal hours (simultaneity is a PREFERENCE now, Majd
    2026-09-07: "if it doesn't fit let one option study and others go home");
  * training day / fixed day off / short name copied from data/school.xlsx
    by matching teacher names (spellings differ; unmatched names are listed).

    python tools/import_official.py [xml] [out.xlsx]
"""
import collections
import io
import json
import math
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XML = os.path.join(HERE, "data", "reference", "official this year work",
                   "newest table - source of truth data- take all cards from here dont add or make them less.xml")
OUT = os.path.join(HERE, "data", "school_official.xlsx")
THIS_YEAR_WB = os.path.join(HERE, "data", "school.xlsx")
WEEK_SLOTS = 46          # Mon-Sat with period 5 open on Fri and Sat


def weeks_of(mask):
    m = (mask or "").strip()
    if m == "10":
        return ("A",)
    if m == "01":
        return ("B",)
    return ("A", "B")


def norm_name(n):
    """Arabic name normalisation for matching two spellings of one person."""
    n = unicodedata.normalize("NFKD", n or "")
    n = "".join(ch for ch in n if not unicodedata.combining(ch))   # diacritics
    n = n.replace("ـ", "")                                      # tatweel
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        n = n.replace(a, b)
    n = re.sub(r"[^\w]+", " ", n)
    n = re.sub(r"\bال", "", n)              # definite article on family names
    n = re.sub(r"\bم\s+", "", n)            # "م. المنور" abbreviations
    return " ".join(n.split()).strip()


def main():
    from openpyxl import Workbook, load_workbook
    xml_path = sys.argv[1] if len(sys.argv) > 1 else XML
    out_path = sys.argv[2] if len(sys.argv) > 2 else OUT
    raw = open(xml_path, "rb").read().decode("cp1256", errors="replace")
    if raw.lstrip().startswith("<?xml"):
        raw = raw[raw.index("?>") + 2:]
    root = ET.fromstring(raw)

    teachers, classes, rooms, subjects = {}, {}, {}, {}
    for el in root.iter("teacher"):
        teachers[el.get("id")] = dict(name=(el.get("name") or el.get("short") or "").strip(),
                                      short=(el.get("short") or "").strip())
    for el in root.iter("class"):
        classes[el.get("id")] = dict(name=(el.get("name") or el.get("short") or "").strip())
    for el in root.iter("classroom"):
        rooms[el.get("id")] = dict(name=(el.get("name") or el.get("short") or "").strip())
    for el in root.iter("subject"):
        subjects[el.get("id")] = dict(name=(el.get("name") or el.get("short") or "").strip(),
                                      short=(el.get("short") or "").strip())
    gnum, per_class_count = {}, collections.Counter()
    for el in root.iter("group"):
        if (el.get("entireclass") or "0") not in ("1", "true", "True") \
                and (el.get("name") or "").startswith("المجموعة"):
            per_class_count[el.get("classid")] += 1
            gnum[el.get("id")] = per_class_count[el.get("classid")]
    lessons = {}
    for el in root.iter("lesson"):
        lessons[el.get("id")] = dict(
            subject=el.get("subjectid"),
            classes=[c for c in (el.get("classids") or "").split(",") if c],
            groups=[g for g in (el.get("groupids") or "").split(",") if g],
            teachers=[t for t in (el.get("teacherids") or "").split(",") if t])

    DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    busy_days = set()
    placed = collections.defaultdict(list)
    opt_cards = collections.defaultdict(list)
    room_use = collections.defaultdict(collections.Counter)     # class -> room name -> cards
    t_half = collections.defaultdict(set)      # (teacher, day) -> {"am", "pm"} in the official table
    duty = []                                  # teacher duties without pupils: fixed busy time
    skipped = 0
    for el in root.iter("card"):
        L = lessons.get(el.get("lessonid"))
        mask = el.get("days") or ""
        if not L or mask.count("1") != 1:
            skipped += 1
            continue
        d, p = mask.index("1"), int(float(el.get("period")))
        wks = weeks_of(el.get("weeks"))
        if not L["classes"]:
            # e.g. "الجمعية المدرسية" Friday 14-17: a duty, not a lesson to place -
            # the teacher is simply busy then (Unavailable sheet, hard)
            for tt in L["teachers"]:
                duty.append((tt, DAYS[d], p, subjects.get(L["subject"], {}).get("name", "")))
            skipped += 1
            continue
        for tt in L["teachers"]:
            busy_days.add((tt, DAYS[d]))
            t_half[tt, DAYS[d]].add("am" if p <= 5 else "pm")
        for rid in (el.get("classroomids") or "").split(","):
            if rid in rooms:
                for cid in L["classes"]:
                    room_use[cid][rooms[rid]["name"]] += 1
        if len(L["classes"]) > 1:
            opt_cards[el.get("lessonid")].append((d, p, wks))
            continue
        cid = L["classes"][0] if L["classes"] else ""
        if not cid:
            skipped += 1
            continue
        g = next((gnum[gid] for gid in L["groups"] if gid in gnum), 0)
        tid = L["teachers"][0] if L["teachers"] else ""
        placed[cid, L["subject"], tid, g, wks[0] if len(wks) == 1 else ""].append((d, p))

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

    # ---- curriculum rows (same merging logic as the last-year importer) ---
    rows, flags = [], []
    by_rowkey = collections.defaultdict(dict)
    for (cid, subj, tid, g, wk), slots in placed.items():
        by_rowkey[cid, subj, tid, wk][g] = slots
    per_cst = collections.defaultdict(dict)
    for (cid, subj, tid, wk), by_g in by_rowkey.items():
        per_cst[cid, subj, tid][wk] = by_g
    for (cid, subj, tid), by_wk in sorted(per_cst.items()):
        for wk, by_g in sorted(by_wk.items()):
            if 0 in by_g:
                rows.append([cid, subj, len(by_g[0]), tid, blocks_of(by_g[0]), 1, "", "", wk])
        gpart = {wk: {g: sl for g, sl in by_g.items() if g} for wk, by_g in by_wk.items()}
        gpart = {wk: d for wk, d in gpart.items() if d}
        a, b = gpart.get("A", {}), gpart.get("B", {})
        if set(a) == {1} and set(b) == {2} and len(a[1]) == len(b[2]):
            rows.append([cid, subj, len(a[1]), tid, blocks_of(a[1]), 2, "", "", "ALT"])
            gpart.pop("A"), gpart.pop("B")
        elif set(a) == {2} and set(b) == {1} and len(a[2]) == len(b[1]):
            rows.append([cid, subj, len(b[1]), tid, blocks_of(b[1]), 2, "", "", "ALT2"])
            gpart.pop("A"), gpart.pop("B")
        for wk, by_g in sorted(gpart.items()):
            counts = {g: len(sl) for g, sl in by_g.items()}
            h = max(counts.values())
            if len(set(counts.values())) > 1:
                flags.append("%s/%s: groups with unequal hours %r - took max"
                             % (classes[cid]["name"], subjects[subj]["name"], counts))
            if len(by_g) == 1 and wk == "":
                # One half only, every week: the school's carousel. Half 1
                # does this subject while half 2 does the partner subject,
                # and the halves swap every week (aSc cannot record that).
                # = week ALT (group 1 on duty in week A) / ALT2 (group 2).
                g = list(by_g)[0]
                rows.append([cid, subj, h, tid, blocks_of(by_g[g]), 2, "", "",
                             "ALT" if g == 1 else "ALT2"])
                flags.append("%s/%s: only group %d every week -> alternating halves (%s)"
                             % (classes[cid]["name"], subjects[subj]["name"], g,
                                "ALT" if g == 1 else "ALT2"))
            elif len(by_g) == 1:
                flags.append("%s/%s wk%s: only group %s - modelled whole-class"
                             % (classes[cid]["name"], subjects[subj]["name"], wk or "-", list(by_g)))
                rows.append([cid, subj, h, tid, blocks_of(list(by_g.values())[0]), 1, "", "", wk])
            else:
                rows.append([cid, subj, h, tid, blocks_of(by_g[max(by_g)]), len(by_g), "", "", wk])

    # ---- options: merge the 2h and 1h lessons of one (subject, teacher, pool)
    merged = collections.defaultdict(list)          # (subject, teacher, classes) -> [(lid, cards)]
    for lid, cards in opt_cards.items():
        L = lessons[lid]
        merged[L["subject"], (L["teachers"] or [""])[0], tuple(sorted(L["classes"]))].append((lid, cards))
    opts = []
    for (subj, tid, cls), items in sorted(merged.items()):
        slots = [(d, p) for lid, cards in items for d, p, w in cards]
        per_w = {"A": 0, "B": 0}
        for lid, cards in items:
            for d, p, wks in cards:
                for w in wks:
                    per_w[w] += 1
        opts.append(dict(id="OPT_" + items[0][0], subject=subj, teacher=tid,
                         hours=max(per_w.values()) or 1, blocks=blocks_of(slots),
                         classes=list(cls)))
    # bands: connected pools (sharing a class) of EQUAL hours
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    by_class = {}
    for o in opts:
        parent.setdefault(o["id"], o["id"])
        for c in o["classes"]:
            key = (c, o["hours"])
            if key in by_class:
                ra, rb = find(o["id"]), find(by_class[key])
                if ra != rb:
                    parent[ra] = rb
            by_class[key] = o["id"]
    comp_ids = {}
    for o in opts:
        r = find(o["id"])
        comp_ids.setdefault(r, "B%d" % (len(comp_ids) + 1))
        o["band"] = comp_ids[r]

    # ---- teachers: contract + training day / fixed day off from school.xlsx
    tload = collections.defaultdict(lambda: [0.0, 0.0])
    for cid, subj, h, tid, bl, g, rt, core, wk in rows:
        if tid:
            # ALT: one half per week -> the teacher works h hours a week
            th = h if wk in ("ALT", "ALT2") else h * max(1, g)
            if wk in ("", "A", "ALT", "ALT2"):
                tload[tid][0] += th
            if wk in ("", "B", "ALT", "ALT2"):
                tload[tid][1] += th
    for o in opts:
        if o["teacher"]:
            tload[o["teacher"]][0] += o["hours"]
            tload[o["teacher"]][1] += o["hours"]
    known = {}
    if os.path.exists(THIS_YEAR_WB):
        wb0 = load_workbook(THIS_YEAR_WB, read_only=True, data_only=True)
        ws = wb0["Teachers"]
        hdr = None
        for r in ws.iter_rows(values_only=True):
            if hdr is None:
                hdr = [str(h or "").strip() for h in r]
                continue
            rec = dict(zip(hdr, ["" if v is None else str(v).strip() for v in r]))
            if rec.get("name") and rec["name"] != "name":
                known[norm_name(rec["name"])] = rec
        wb0.close()
    matched, unmatched = 0, []
    t_extra = {}
    for tid, t in teachers.items():
        rec = known.get(norm_name(t["name"]))
        if rec is None:
            # tolerant: first+last token match
            toks = norm_name(t["name"]).split()
            cands = [v for k, v in known.items() if toks and k.split()[:1] == toks[:1]
                     and k.split()[-1:] == toks[-1:]]
            rec = cands[0] if len(cands) == 1 else None
        if rec:
            matched += 1
            t_extra[tid] = dict(training_day=rec.get("training_day", ""),
                                day_off=rec.get("day_off", ""), short=rec.get("short", ""),
                                subjects=rec.get("subjects", ""))
        else:
            unmatched.append(t["name"])
            # Majd 2026-09-07: what we do not know we take from the official
            # table - the teacher's free weekday there becomes the day off
            # (first free day Mon-Fri; Saturday only if nothing else is free)
            busy = {d for (tt, d) in busy_days if tt == tid}
            free = [d for d in DAYS if d not in busy]
            pick = next((d for d in free if d != "Sat"), free[0] if free else "")
            if pick and tid in tload:
                t_extra[tid] = dict(training_day="", day_off=pick, short="", subjects="",
                                    from_table=True)

    # ---- rooms: types + capacities from names and observed use -----------
    def room_type_of(name):
        n = name.strip()
        for kw, ty in (("ملعب", "gym"), ("فيز", "lab_phys"), ("علوم", "lab_sci"), ("Inf", "it"),
                       ("inf", "it"), ("م ه آلية", "eng_mech"), ("م ه كه", "eng_elec"),
                       ("تقنية", "tech")):
            if kw in n:
                return ty
        return "normal"

    def room_cap(name, ty):
        n = name.strip()
        if ty == "gym":
            return 99
        if n.lower() == "group":
            return 19
        if ty in ("it", "tech", "eng_mech", "eng_elec"):
            return 20
        return 40          # numbered rooms and labs hosted full classes this year
    small = sorted({cid for cid, use in room_use.items()
                    if use.get("Group") and not classes[cid]["name"].startswith("1")})
    for cid, use in sorted(room_use.items()):
        if use.get("Group") and classes[cid]["name"].startswith("1"):
            flags.append("%s sits in the Group room %d time(s) in the official table, but first-year "
                         "classes are too crowded for small rooms (Majd 2026-09-09) - NOT allowed "
                         "there (UNSURE)" % (classes[cid]["name"], use["Group"]))

    # ---- subjects -----------------------------------------------------------
    def attrs_of(name):
        n = name.strip()

        def has(*kw):
            return any(k in n for k in kw)
        if has("بدنية", "رياضة") and not has("رياضيات"):
            return ("easy", "gym", 9, "", "yes", "yes", "", "")
        if has("فيزيائية"):
            return ("hard", "normal", "", 9, "", "", "", "scientific")
        if has("الحياة", "حياة"):
            return ("medium", "normal", "", "", "", "", "", "scientific")
        if has("اعلامية", "إعلامية", "خوارزميات", "المعلومات", "قواعد", "الشبكات"):
            return ("medium", "it", "", "", "", "", "", "scientific")
        if has("هنسة آلية", "هندسة آلية"):
            return ("medium", "eng_mech", "", "", "", "", "", "scientific")
        if has("هنسة كهربائية", "هندسة كهربائية"):
            return ("medium", "eng_elec", "", "", "", "", "", "scientific")
        if has("تقنية", "تكنولوجية"):
            return ("medium", "tech", "", "", "", "", "", "scientific")
        if has("رياضيات"):
            return ("hard", "normal", "", 8, "", "", "", "scientific")
        if has("فلسفة"):
            return ("hard", "normal", "", 9, "", "", "", "literary")
        if has("عربية", "فرنسية", "نقليزية", "نجليزية", "إسبان", "اسبان", "ألمان", "الماني", "يطال"):
            return ("medium", "normal", "", "", "", "", "", "literary")
        if has("تاريخ", "جغراف", "مدنية", "تفكير", "إسلام", "اسلام", "اقتصاد", "تصرف"):
            return ("medium", "normal", "", "", "", "", "", "social")
        if has("موسيق", "تشكيل"):
            return ("easy", "normal", "", "", "yes", "", "", "")
        return ("medium", "normal", "", "", "", "", "", "")
    lab_row = {}
    for sid, sb in subjects.items():
        if "فيزيائية" in sb["name"]:
            lab_row[sid] = "lab_phys"
        elif "الحياة" in sb["name"] or "حياة" in sb["name"]:
            lab_row[sid] = "lab_sci"
    # Split physics / SVT rows are the lab PRACTICAL: they get their own
    # subject "<id>_TP" (the repo's convention, as in data/school.xlsx), so
    # the checker's per-class-subject room reading keeps theory hours in
    # ordinary rooms and only the practical in the lab.
    tp_ids = {}
    for r in rows:
        if r[5] and int(r[5]) > 1 and r[1] in lab_row:
            base = r[1]
            tp = base + "_TP"
            if tp not in tp_ids:
                sb = subjects[base]
                tp_ids[tp] = dict(name="أشغال تطبيقية - " + sb["name"], short="أ.ت " + (sb["short"] or sb["name"]),
                                  room_type=lab_row[base], base=base)
            r[1] = tp
            r[6] = ""

    # ---- write ------------------------------------------------------------
    wb = Workbook()

    def sheet(name, header, data):
        ws = wb.create_sheet(name) if wb.sheetnames != ["Sheet"] else wb.active
        ws.title = name
        ws.append(header)
        ws.append(["" for _ in header])
        for r in data:
            ws.append(list(r))
    sheet("Teachers",
          ["id", "name", "short", "subjects", "hours", "day_off", "training_day", "compact",
           "travels_with", "notes"],
          [[tid, t["name"], (t_extra.get(tid, {}).get("short") or t["short"] or t["name"]),
            t_extra.get(tid, {}).get("subjects", ""),
            int(math.ceil(sum(tload.get(tid, [0, 0])) / 2.0)) or "",
            t_extra.get(tid, {}).get("day_off", ""), t_extra.get(tid, {}).get("training_day", ""),
            "", "",
            "contract = this year's official card-hours; %s" % (
                "NOT matched in school.xlsx - day off taken from the official table"
                if t_extra.get(tid, {}).get("from_table") else
                "training/day-off from school.xlsx" if tid in t_extra else "NOT matched in school.xlsx")]
           for tid, t in sorted(teachers.items(), key=lambda kv: kv[1]["name"])])
    sheet("Classes",
          ["id", "name", "grade", "stream", "is_bac", "cohort", "home_room", "size"],
          [[cid, c["name"], next((ch for ch in c["name"] if ch.isdigit()), ""), "",
            "yes" if c["name"].startswith("4") else "", "ALL", "",
            19 if cid in small else ""]
           for cid, c in sorted(classes.items(), key=lambda kv: kv[1]["name"])])
    sheet("Rooms",
          ["id", "name", "type", "capacity", "zone", "notes"],
          [[rid, r["name"], room_type_of(r["name"]), room_cap(r["name"], room_type_of(r["name"])),
            "", "type from the name; Group = ordinary room for small classes (official file)"]
           for rid, r in sorted(rooms.items(), key=lambda kv: kv[1]["name"])])
    subj_rows = []
    for sid, sb in sorted(subjects.items(), key=lambda kv: kv[1]["name"]):
        diff, rt, latest, avoid, exempt, g24, notaft, nature = attrs_of(sb["name"])
        subj_rows.append([sid, sb["name"], sb["short"], diff, rt, latest, avoid, exempt, g24,
                          notaft, nature])
    for tp, info in sorted(tp_ids.items()):
        diff, rt, latest, avoid, exempt, g24, notaft, nature = attrs_of(subjects[info["base"]]["name"])
        subj_rows.append([tp, info["name"], info["short"], diff, info["room_type"], latest, avoid,
                          exempt, g24, notaft, nature])
    sheet("Subjects",
          ["id", "name", "short", "difficulty", "room_type", "latest_period", "avoid_after",
           "minmax_exempt", "gap24", "not_after", "nature"], subj_rows)
    sheet("Curriculum",
          ["class_id", "subject_id", "hours", "teacher_id", "blocks", "groups", "room_type",
           "core", "week"], rows)
    sheet("Options",
          ["id", "subject_id", "teacher_id", "hours", "blocks", "classes", "room_type", "band"],
          [[o["id"], o["subject"], o["teacher"], o["hours"], o["blocks"], ";".join(o["classes"]),
            "", o["band"]] for o in opts])
    sheet("Unavailable", ["teacher_id", "day", "period", "hard", "reason"],
          [[tid, day, p, "yes", "%s (official table)" % name] for tid, day, p, name in duty])
    sheet("Locked", ["class_id", "subject_id", "day", "period", "room_id", "why"], [])
    wb.save(out_path)
    split_days = {}
    for tid in teachers:
        ds = [d for d in DAYS if len(t_half.get((tid, d), ())) == 2]
        if ds:
            split_days[tid] = ds
    facts = dict(source=os.path.basename(xml_path), split_days=split_days,
                 duties=[dict(teacher_id=a, day=b, period=c, what=d_) for a, b, c, d_ in duty])
    facts_path = os.path.splitext(out_path)[0] + "_facts.json"
    with io.open(facts_path, "w", encoding="utf-8") as fh:
        json.dump(facts, fh, ensure_ascii=False, indent=1, sort_keys=True)

    print("wrote %s" % out_path)
    print("  facts -> %s: %d teachers come morning+afternoon on some day in the official table; "
          "%d duty cards -> Unavailable" % (os.path.basename(facts_path), len(split_days), len(duty)))
    print("  %d teachers (%d matched to school.xlsx for training day / day off), %d classes, "
          "%d rooms, %d subjects" % (len(teachers), matched, len(classes), len(rooms), len(subjects)))
    print("  %d curriculum rows (%d split, %d fortnight A/B, %d ALT), %d option groups in %d bands, "
          "%d cards skipped" % (len(rows), sum(1 for r in rows if r[5] > 1),
                                sum(1 for r in rows if r[8] in ("A", "B")),
                                sum(1 for r in rows if r[8] in ("ALT", "ALT2")), len(opts),
                                len(comp_ids), skipped))
    print("  small classes (used the Group room): %s" % ", ".join(classes[c]["name"] for c in small))
    if unmatched:
        print("  teachers NOT matched in school.xlsx (%d): %s" % (len(unmatched), ", ".join(unmatched)))
    for f in flags[:15]:
        print("  FLAG:", f)
    if len(flags) > 15:
        print("  ...and %d more flags" % (len(flags) - 15))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Recover each teacher's REAL day off from last year's finished timetable.

Majd 2026-08-25: the imported workbook data/school_lastyear.xlsx had day_off
blank for all 101 teachers, so the solver was free to invent a day off for
everyone. That is an EASIER job than the one the humans actually did, and it
made the machine-vs-human duel dishonest in the machine's favour.

The real days off are recoverable: a teacher's day off is a school day on
which they have no card at all. To stay honest we only write a day off when
there is EXACTLY ONE such day - that is unambiguously the designated day off.
A teacher with several empty days is a part-timer, and gets left blank so the
solver still chooses (H7-flex), exactly as before.

    python tools/extract_daysoff.py            (updates the workbook in place)
    python tools/extract_daysoff.py --dry-run  (report only, change nothing)
"""
import collections
import glob
import os
import sys
import xml.etree.ElementTree as ET

import openpyxl

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
XLSX = os.path.join(HERE, "data", "school_lastyear.xlsx")


def load_reference():
    hits = glob.glob(os.path.join(HERE, "data", "reference", "**", "*.xml"),
                     recursive=True)
    if not hits:
        sys.exit("no reference XML under data/reference/")
    raw = open(hits[0], "rb").read().decode("cp1256", errors="replace")
    return ET.fromstring(raw.replace("windows-1252", "utf-8")), hits[0]


def main():
    dry = "--dry-run" in sys.argv
    root, src = load_reference()

    import json
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    days = list(cfg["days"])

    lessons = {el.get("id"): el for el in root.iter("lesson")}
    # teacher id -> set of days they actually taught
    taught = collections.defaultdict(set)
    seen_teachers = set()
    for L in lessons.values():
        for tid in (L.get("teacherids") or "").split(","):
            if tid:
                seen_teachers.add(tid)
    for c in root.iter("card"):
        L = lessons.get(c.get("lessonid"))
        mask = c.get("days") or ""
        if L is None or "1" not in mask:
            continue
        for i, ch in enumerate(mask):
            if ch != "1" or i >= len(days):
                continue
            for tid in (L.get("teacherids") or "").split(","):
                if tid:
                    taught[tid].add(days[i])

    wb = openpyxl.load_workbook(XLSX)
    ws = wb["Teachers"]
    hdr = [str(c.value).strip() if c.value else "" for c in ws[1]]
    if "id" not in hdr or "day_off" not in hdr:
        sys.exit("Teachers sheet has no id / day_off column")
    c_id, c_off = hdr.index("id") + 1, hdr.index("day_off") + 1

    exact, several, none_free, missing, wrote = 0, 0, 0, 0, []
    for r in range(2, ws.max_row + 1):
        tid = ws.cell(r, c_id).value
        if not tid:
            continue
        tid = str(tid).strip()
        if tid not in taught:
            missing += 1
            continue
        free = [d for d in days if d not in taught[tid]]
        if len(free) == 1:
            exact += 1
            wrote.append((tid, free[0]))
            if not dry:
                ws.cell(r, c_off).value = free[0]
        elif len(free) > 1:
            several += 1
        else:
            none_free += 1

    print("reference: %s" % os.path.basename(src))
    print("  %d teachers had EXACTLY ONE empty day -> written as their day off"
          % exact)
    print("  %d had several empty days   -> left blank (solver still chooses)"
          % several)
    print("  %d taught on all %d days     -> no day off to record"
          % (none_free, len(days)))
    if missing:
        print("  %d workbook teachers appear in no lesson at all" % missing)
    if dry:
        print("\n--dry-run: nothing written.")
        return
    wb.save(XLSX)
    print("\nwrote %d days off into %s" % (exact, os.path.relpath(XLSX, HERE)))
    print("The duel is now fair: the machine must respect the same days off")
    print("the humans did. H7 joins the rule ladder, so if those days off")
    print("genuinely cannot all be honoured, the solver PROVES it and says so.")


if __name__ == "__main__":
    main()

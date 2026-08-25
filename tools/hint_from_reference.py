# -*- coding: utf-8 -*-
"""Seed the solver with LAST YEAR'S REAL placements.

Majd's school runs at ~91% room occupancy: finding even ONE legal
timetable from scratch is the hard part, and the search can spend an hour
without a single complete table. But a working timetable already exists -
last year's. This writes it into out/solution.json in the solver's own
format, so `solve.py --continue` starts from a real, working week and
spends its whole budget IMPROVING instead of hunting.

    python tools/hint_from_reference.py            (-> out/solution.json)
"""
import collections
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "solver"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import data as D          # noqa: E402
import solve as S         # noqa: E402

XLSX = os.path.join(HERE, "data", "school_lastyear.xlsx")
OUT = os.path.join(HERE, "out", "solution.json")


def weeks_of(mask):
    m = (mask or "").strip()
    if m == "10":
        return ("A",)
    if m == "01":
        return ("B",)
    return ("", )          # every week


def main():
    cfg = D.load_config()
    s = D.load_school(XLSX, cfg)
    sessions = S.expand(s)

    hits = glob.glob(os.path.join(HERE, "data", "reference", "**", "*.xml"),
                     recursive=True)
    raw = open(hits[0], "rb").read().decode("cp1256", errors="replace")
    root = ET.fromstring(raw.replace("windows-1252", "utf-8"))
    days = list(cfg.days)

    gnum, per_class = {}, collections.Counter()
    for el in root.iter("group"):
        if (el.get("entireclass") or "0") in ("1", "true", "True"):
            continue
        per_class[el.get("classid")] += 1
        gnum[el.get("id")] = per_class[el.get("classid")]
    lessons = {el.get("id"): el for el in root.iter("lesson")}

    # (class, subject, group, week) -> {day: [periods]}
    slots = collections.defaultdict(lambda: collections.defaultdict(list))
    for c in root.iter("card"):
        L = lessons.get(c.get("lessonid"))
        mask = c.get("days") or ""
        if L is None or mask.count("1") != 1:
            continue
        cids = [x for x in (L.get("classids") or "").split(",") if x]
        if len(cids) != 1:
            continue                      # option lessons: left to the solver
        g = 0
        for gid in (L.get("groupids") or "").split(","):
            if gid in gnum:
                g = gnum[gid]
                break
        for w in weeks_of(c.get("weeks")):
            slots[cids[0], L.get("subjectid"), g, w][days[mask.index("1")]] \
                .append(int(float(c.get("period"))))

    # each key's cards -> contiguous runs (day, first period, length)
    runs = collections.defaultdict(list)
    for key, byday in slots.items():
        for d, ps in byday.items():
            ps.sort()
            start, prev = ps[0], ps[0]
            for p in ps[1:]:
                if p != prev + 1:
                    runs[key].append((d, start, prev - start + 1))
                    start = p
                prev = p
            runs[key].append((d, start, prev - start + 1))

    # match our sessions to those runs, longest first so a 2h block gets a
    # 2h run when one exists
    by_key = collections.defaultdict(list)
    for se in sessions:
        by_key[se.class_id, se.subject_id, se.group, se.week].append(se)

    placement, hinted, missed = {}, 0, 0
    for key, ses in by_key.items():
        pool = sorted(runs.get(key, []), key=lambda r: -r[2])
        for se in sorted(ses, key=lambda x: -x.length):
            match = next((r for r in pool if r[2] == se.length), None) \
                or (pool[0] if pool else None)
            if match is None:
                missed += 1
                continue
            pool.remove(match)
            d, p0, _ln = match
            for t in range(se.length):
                placement[S.uid_of(se, t)] = [d, p0 + t]
            hinted += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dict(penalty=-1, elapsed_seconds=0, solution_number=0,
                       placement=placement), f)
    print("seeded %s from last year's real timetable" % OUT)
    print("  %d of %d sessions hinted (%d had no matching run)"
          % (hinted, len(sessions), missed))
    print("  run:  python solver/solve.py data/school_lastyear.xlsx --continue")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Score ANY aSc timetable XML on universal comfort metrics - the same
ruler for a hand-made table and a solver table.

CAVEAT (Majd 2026-08-25): the reference in data/reference/ is a WORK IN
PROGRESS copy from last year, NOT the finished table - its numbers are a
floor for the hand-made quality, not the truth. Score a FINAL export
before claiming victory over human tables.

Counts (per week view, A/B averaged; the lunch break is never a hole):
  - teacher hole-hours (free periods trapped inside a half-day)
  - teacher one-hour days (coming in for a single lesson)
  - pupil hole-hours (class view)
  - lessons in the last period of the day
No names are printed - aggregates only.

    python tools/score_table.py path/to/export.xml
"""
import collections
import glob
import os
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENING = {7, 8, 9, 10}          # periods after the lunch break
LAST = 10


def weeks_of(mask):
    m = (mask or "").strip()
    if m == "10":
        return ("A",)
    if m == "01":
        return ("B",)
    return ("A", "B")


def half_holes(ps):
    n = 0
    for half in ([p for p in ps if p not in EVENING],
                 [p for p in ps if p in EVENING]):
        if len(half) > 1:
            n += (max(half) - min(half) + 1) - len(half)
    return n


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        hits = glob.glob(os.path.join(HERE, "data", "reference", "**", "*.xml"),
                         recursive=True)
        if not hits:
            sys.exit("Give a path to an aSc XML export.")
        path = hits[0]
    root = ET.parse(path).getroot()
    lessons = {}
    for el in root.iter("lesson"):
        lessons[el.get("id")] = (
            [t for t in (el.get("teacherids") or "").split(",") if t],
            [c for c in (el.get("classids") or "").split(",") if c])
    t_at = collections.defaultdict(set)   # (teacher, week) -> {(dayix, period)}
    c_at = collections.defaultdict(set)
    n_cards = last_p = 0
    for el in root.iter("card"):
        L = lessons.get(el.get("lessonid"))
        mask = el.get("days") or ""
        if not L or mask.count("1") != 1:
            continue
        d = mask.index("1")
        p = int(float(el.get("period")))
        n_cards += 1
        if p == LAST:
            last_p += 1
        for w in weeks_of(el.get("weeks")):
            for t in L[0]:
                t_at[t, w].add((d, p))
            for c in L[1]:
                c_at[c, w].add((d, p))

    def stats(at):
        holes = solos = 0
        for (_who, _w), sl in at.items():
            byday = collections.defaultdict(list)
            for (d, p) in sl:
                byday[d].append(p)
            for d, ps in byday.items():
                holes += half_holes(sorted(ps))
                if len(ps) == 1:
                    solos += 1
        return holes / 2.0, solos / 2.0     # averaged over the two weeks

    th, ts = stats(t_at)
    ch, _cs = stats(c_at)
    n_t = len({t for (t, w) in t_at})
    n_c = len({c for (c, w) in c_at})
    print("Scored: %s" % os.path.basename(path))
    print("  %d placed cards, %d teachers, %d classes" % (n_cards, n_t, n_c))
    print("  teacher hole-hours per week ......... %.1f" % th)
    print("  teacher one-hour days per week ...... %.1f" % ts)
    print("  pupil (class) hole-hours per week ... %.1f" % ch)
    print("  lessons in the last period .......... %d" % last_p)
    print("(lunch break never counts as a hole; weeks A/B averaged)")


if __name__ == "__main__":
    main()

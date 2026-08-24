"""Read last year's aSc export and report its SHAPE. No names are printed.

This exists to answer the question that blocks the whole model: how do 40
classes fit into 20 rooms? Rather than ask, measure it from the real file.

    python tools/analyze_reference.py [path-to-export.xml]

IMPORTANT: aSc labels its export encoding="windows-1252" but writes Arabic as
windows-1256. Decoding as utf-8 silently DELETES Arabic. See docs/ASC_XML.md.
"""
import collections
import glob
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    raw = open(path, "rb").read()
    text = raw.decode("cp1256", errors="replace")
    # strip the (wrong) encoding declaration so ElementTree accepts the str
    if text.lstrip().startswith("<?xml"):
        text = text[text.index("?>") + 2:]
    return ET.fromstring(text)


def rows(root, table, tag):
    return root.findall("./%s/%s" % (table, tag))


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        hits = glob.glob(os.path.join(HERE, "data", "reference", "**", "*.xml"),
                         recursive=True)
        if not hits:
            sys.exit("Put the aSc 2012 XML export in data/reference/ first.")
        path = max(hits, key=os.path.getsize)
    print("Reading %s" % os.path.basename(path))
    print("")
    root = load(path)

    teachers = rows(root, "teachers", "teacher")
    classes = rows(root, "classes", "class")
    rooms_ = rows(root, "classrooms", "classroom")
    subjects = rows(root, "subjects", "subject")
    groups = rows(root, "groups", "group")
    periods = rows(root, "periods", "period")
    daysdefs = rows(root, "daysdefs", "daysdef")
    weeksdefs = rows(root, "weeksdefs", "weeksdef")
    lessons = rows(root, "lessons", "lesson")
    cards = rows(root, "cards", "card")

    print("=== SIZE ===")
    for label, n in (("teachers", len(teachers)), ("classes", len(classes)),
                     ("classrooms", len(rooms_)), ("subjects", len(subjects)),
                     ("groups", len(groups)), ("lessons", len(lessons)),
                     ("placed cards", len(cards))):
        print("  %-14s %d" % (label, n))

    # --- week shape ---
    daylen = max((len(d.get("days") or "") for d in daysdefs), default=0)
    print("")
    print("=== WEEK ===")
    print("  periods per day      %d" % len(periods))
    print("  day-mask length      %d   <-- THE NUMBER OUR MASKS MUST MATCH" % daylen)
    if periods:
        times = [(p.get("period"), p.get("starttime"), p.get("endtime")) for p in periods]
        print("  period clock times:")
        for pid, st, en in times:
            print("     period %-3s %s - %s" % (pid, st or "?", en or "?"))
    nweeks = max((len(w.get("weeks") or "") for w in weeksdefs), default=0)
    if nweeks > 1:
        print("  weeks defined        %d  (alternating-week lessons exist)" % nweeks)

    # --- where cards actually sit ---
    per_slot = collections.Counter()
    per_day = collections.Counter()
    unplaced = 0
    for c in cards:
        mask = c.get("days") or ""
        p = c.get("period")
        if "1" not in mask or p in (None, ""):
            unplaced += 1
            continue
        for i, ch in enumerate(mask):
            if ch == "1":
                per_slot[i, p] += 1
                per_day[i] += 1

    print("")
    print("=== THE ROOM QUESTION ===")
    if per_slot:
        busiest = max(per_slot.values())
        print("  lessons running at once, busiest period:  %d" % busiest)
        print("  classrooms defined in the file:           %d" % len(rooms_))
        if busiest > len(rooms_):
            print("  -> more simultaneous lessons than rooms: some lessons")
            print("     share a room or happen outside (stadium, yard).")
        avg = sum(per_slot.values()) / float(len(per_slot))
        print("  average lessons per occupied period:      %.1f" % avg)
        print("  occupied (day, period) combinations:      %d" % len(per_slot))
    if unplaced:
        print("  cards with no day/period (unplaced):      %d" % unplaced)

    print("")
    print("  lessons per day index (0 = first day of the mask):")
    for i in sorted(per_day):
        print("     day %d : %d" % (i, per_day[i]))

    # --- load per class and per teacher ---
    lesson_by_id = {l.get("id"): l for l in lessons}
    cls_hours = collections.Counter()
    tch_hours = collections.Counter()
    for c in cards:
        mask = c.get("days") or ""
        n = mask.count("1")
        if not n:
            continue
        L = lesson_by_id.get(c.get("lessonid"))
        if L is None:
            continue
        for cid in (L.get("classids") or "").split(","):
            if cid:
                cls_hours[cid] += n
        for tid in (L.get("teacherids") or "").split(","):
            if tid:
                tch_hours[tid] += n

    def spread(counter, label):
        if not counter:
            print("  %s: nothing placed" % label)
            return
        v = sorted(counter.values())
        tot = sum(v)
        print("  %-9s count=%-4d total=%-6d min=%-3d median=%-3d max=%-3d avg=%.1f"
              % (label, len(v), tot, v[0], v[len(v) // 2], v[-1],
                 float(tot) / len(v)))

    print("")
    print("=== WEEKLY HOURS ===")
    spread(cls_hours, "classes")
    spread(tch_hours, "teachers")

    # --- rooms actually used ---
    used = collections.Counter()
    for c in cards:
        for rid in (c.get("classroomids") or "").split(","):
            if rid:
                used[rid] += 1
    print("")
    print("=== ROOMS ===")
    print("  rooms that actually hold lessons: %d of %d defined"
          % (len(used), len(rooms_)))
    caps = [r.get("capacity") for r in rooms_ if r.get("capacity")]
    if caps:
        print("  capacities present in the file:   %s"
              % ", ".join(sorted(set(caps), key=lambda x: (len(x), x))[:12]))

    # --- group splitting ---
    print("")
    print("=== SPLIT GROUPS ===")
    tags = collections.Counter(g.get("divisiontag") for g in groups)
    whole = sum(1 for g in groups if (g.get("entireclass") or "") == "1")
    print("  groups: %d   (entire-class: %d, real subdivisions: %d)"
          % (len(groups), whole, len(groups) - whole))
    if tags:
        print("  divisiontag values: %s"
              % ", ".join("%s x%d" % (k, v) for k, v in sorted(
                  tags.items(), key=lambda kv: str(kv[0]))[:10]))
    multi = sum(1 for l in lessons
                if len((l.get("classids") or "").split(",")) > 1)
    print("  lessons spanning MORE THAN ONE class: %d" % multi)
    multi_t = sum(1 for l in lessons
                  if len((l.get("teacherids") or "").split(",")) > 1)
    print("  lessons with MORE THAN ONE teacher:   %d" % multi_t)
    print("")
    print("(No names printed. Real data stays in data/reference/.)")


if __name__ == "__main__":
    main()

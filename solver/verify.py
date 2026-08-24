"""INDEPENDENT checker. Does not trust the solver.

This deliberately re-reads out/timetable.xml FROM DISK - the same bytes aSc
will read - and re-checks every hard rule from scratch against the source data.
It shares no logic with solve.py on purpose. Two separate programs agreeing is
the actual guarantee.

If this prints anything other than ALL GREEN, do not use the timetable.

Usage:  python solver/verify.py [path/to/school.xlsx]
"""
import collections
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402

XML = os.path.join(D.HERE, "out", "timetable.xml")
EXC = os.path.join(D.HERE, "out", "exceptions.json")

# Only these rules may ever be excused by a rescue-mode exceptions file.
# A clash or a wrong room is never an acceptable exception.
EXCUSABLE = {"H7", "H17"}


def read_xml(path):
    """Return (lessons, cards) exactly as aSc would see them."""
    root = ET.parse(path).getroot()
    lessons = {}
    for el in root.findall("./lessons/lesson"):
        lessons[el.get("id")] = dict(
            subject=el.get("subjectid"),
            classes=[c for c in (el.get("classids") or "").split(",") if c],
            teachers=[t for t in (el.get("teacherids") or "").split(",") if t],
            per_week=int(el.get("periodsperweek") or 0),
        )
    cards = []
    for el in root.findall("./cards/card"):
        cards.append(dict(
            lesson=el.get("lessonid"),
            period=int(el.get("period")),
            days=el.get("days") or "",
            room=el.get("classroomids") or "",
        ))
    return lessons, cards


def main():
    # A rescue-mode run declares its exceptions in out/exceptions.json.
    # We still detect every violation ourselves; the file only decides
    # whether a violation was DECLARED. Declared H7/H17 violations are
    # listed separately instead of failing; anything undeclared fails.
    accepted = set()
    if os.path.exists(EXC):
        try:
            with open(EXC, encoding="utf-8") as f:
                for e in json.load(f).get("exceptions", []):
                    if e.get("rule") in EXCUSABLE:
                        accepted.add((e["rule"], e["teacher_id"], e["day"]))
        except (ValueError, KeyError):
            pass  # a broken exceptions file excuses nothing

    fails, excused = [], []
    def fail(rule, msg, key=None):
        if key is not None and (rule, key[0], key[1]) in accepted:
            excused.append("%-4s %s" % (rule, msg))
        else:
            fails.append("%-4s %s" % (rule, msg))

    cfg = D.load_config()
    s = D.load_school(sys.argv[1] if len(sys.argv) > 1 else None, cfg)

    if not os.path.exists(XML):
        print("No " + XML + " - run solver/solve.py first.")
        return 1
    lessons, cards = read_xml(XML)
    days = cfg.days
    open_slots = set(cfg.slots)

    # --- decode every card into (day, period) -----------------------------
    placed = []   # (day, period, room, lesson_id)
    for c in cards:
        mask = c["days"]
        if len(mask) != len(days):
            fail("XML", "card for %s has days mask %r of length %d, but the week "
                        "has %d days." % (c["lesson"], mask, len(mask), len(days)))
            continue
        on = [days[i] for i, ch in enumerate(mask) if ch == "1"]
        if len(on) != 1:
            fail("XML", "card for %s has mask %r selecting %d days; expected exactly 1."
                 % (c["lesson"], mask, len(on)))
            continue
        placed.append((on[0], c["period"], c["room"], c["lesson"]))

    # --- every card lands in an open period -------------------------------
    for d, p, r, lid in placed:
        if (d, p) not in open_slots:
            fail("H0", "a lesson is placed at %s period %d, when the school is shut." % (d, p))

    # --- H5: required hours delivered exactly -----------------------------
    want = collections.Counter()
    for row in s.curriculum:
        want[row["class_id"], row["subject_id"]] += row["hours"]
    got = collections.Counter()
    for d, p, r, lid in placed:
        L = lessons.get(lid)
        if not L:
            fail("XML", "card refers to unknown lesson id %s." % lid)
            continue
        for cid in L["classes"]:
            got[cid, L["subject"]] += 1
    for key in set(want) | set(got):
        if want[key] != got[key]:
            fail("H5", "class %s subject %s: needs %d hours, timetable has %d."
                 % (key[0], key[1], want[key], got[key]))

    # --- H1 teacher clash / H2 class clash / H3 room clash ----------------
    t_at = collections.defaultdict(list)
    c_at = collections.defaultdict(list)
    r_at = collections.defaultdict(list)
    for d, p, r, lid in placed:
        L = lessons.get(lid)
        if not L:
            continue
        for t in L["teachers"]:
            t_at[t, d, p].append(lid)
        for cid in L["classes"]:
            c_at[cid, d, p].append(lid)
        if r:
            r_at[r, d, p].append(lid)

    for (t, d, p), v in t_at.items():
        if len(v) > 1:
            fail("H1", "teacher %s is in %d places at %s period %d." % (t, len(v), d, p))
    for (c, d, p), v in c_at.items():
        if len(v) > 1:
            fail("H2", "class %s is in %d places at %s period %d." % (c, len(v), d, p))
    for (r, d, p), v in r_at.items():
        if len(v) > 1:
            fail("H3", "room %s holds %d lessons at %s period %d." % (r, len(v), d, p))

    # --- H4: never more lessons at once than rooms exist ------------------
    per_slot = collections.Counter((d, p) for d, p, r, lid in placed)
    for (d, p), n in per_slot.items():
        if n > len(s.rooms):
            fail("H4", "%d lessons at %s period %d but only %d rooms exist."
                 % (n, d, p, len(s.rooms)))

    # --- H6: right kind of room -------------------------------------------
    need_type = {}
    for row in s.curriculum:
        need_type[row["class_id"], row["subject_id"]] = s.room_type_for(row)
    for d, p, r, lid in placed:
        L = lessons.get(lid)
        if not L:
            continue
        for cid in L["classes"]:
            want_t = need_type.get((cid, L["subject"]))
            if not r:
                fail("H6", "lesson %s/%s at %s period %d has no room."
                     % (cid, L["subject"], d, p))
            elif r not in s.rooms:
                fail("H6", "lesson %s/%s uses unknown room %s." % (cid, L["subject"], r))
            elif want_t and s.rooms[r]["type"] != want_t:
                fail("H6", "%s/%s needs a '%s' room but sits in %s which is '%s'."
                     % (cid, L["subject"], want_t, r, s.rooms[r]["type"]))

    # --- H9: block patterns ------------------------------------------------
    # Each block of a class+subject must sit as ONE run of consecutive
    # periods on ONE day, and the run lengths across the week must be exactly
    # the declared pattern (blank blocks = all single hours, on separate days).
    cs_day = collections.defaultdict(list)   # (class, subject, day) -> periods
    for d, p, r, lid in placed:
        L = lessons.get(lid)
        if not L:
            continue
        for cid in L["classes"]:
            cs_day[cid, L["subject"], d].append(p)

    runs = collections.defaultdict(list)     # (class, subject) -> run lengths
    for (cid, subj, d), ps in cs_day.items():
        ps.sort()
        run = 1
        for a, b in zip(ps, ps[1:]):
            if b == a + 1:
                run += 1
            else:
                runs[cid, subj].append(run)
                run = 1
        runs[cid, subj].append(run)

    for row in s.curriculum:
        if not str(row.get("blocks", "")).strip():
            continue   # blank pattern imposes nothing (spreading is soft)
        want_bl, berr = D.parse_blocks(row.get("blocks", ""), row["hours"])
        if berr or not want_bl or sum(want_bl) != row["hours"]:
            continue   # unreadable pattern is a data error, reported elsewhere
        got_bl = runs.get((row["class_id"], row["subject_id"]), [])
        if sorted(got_bl) != sorted(want_bl):
            fail("H9", "class %s subject %s: blocks say %s but the timetable "
                       "has runs of %s (each block must be consecutive hours "
                       "on its own day)."
                 % (row["class_id"], row["subject_id"],
                    "+".join(map(str, want_bl)),
                    "+".join(map(str, sorted(got_bl, reverse=True))) or "none"))

    # --- H15: daylight-only subjects ---------------------------------------
    for d, p, r, lid in placed:
        L = lessons.get(lid)
        if not L:
            continue
        sub = s.subjects.get(L["subject"], {})
        lp = sub.get("latest_period") or 0
        if lp and p > lp:
            fail("H15", "%s runs at %s period %d but may not go past period %d "
                        "(no daylight)." % (L["subject"], d, p, lp))

    # --- H7: day off AND training day are empty ----------------------------
    for (t, d, p), v in t_at.items():
        rec = s.teachers.get(t, {})
        if rec.get("day_off", "") == d:
            fail("H7", "teacher %s teaches on %s, which is their day off." % (t, d),
                 key=(t, d))
        if rec.get("training_day", "") == d:
            fail("H7", "teacher %s teaches on %s, their training day." % (t, d),
                 key=(t, d))

    # --- H17: never more than 6 teaching hours in one day ------------------
    day_load = collections.Counter()
    for (t, d, p), v in t_at.items():
        day_load[t, d] += len(v)
    for (t, d), n in sorted(day_load.items()):
        if n > 6:
            fail("H17", "teacher %s teaches %d hours on %s; the ministry caps "
                        "the day at 6 (circular II.2)." % (t, n, d), key=(t, d))

    # --- H8: declared unavailable ------------------------------------------
    for un in s.unavailable:
        if un["hard"] != "yes":
            continue
        for (t, d, p), v in t_at.items():
            if t != un["teacher_id"]:
                continue
            if un["day"] in ("*", d) and (un["period"] == "*" or str(p) == str(un["period"])):
                fail("H8", "teacher %s teaches at %s period %d but declared "
                           "unavailable (%s)." % (t, d, p, un["reason"] or "no reason given"))

    # --- H18: day off never adjacent to training day (inspector's rule) ----
    day_list = list(cfg.days)
    for t in s.teachers.values():
        off, tr = t.get("day_off", ""), t.get("training_day", "")
        if off in day_list and tr in day_list and off != tr:
            if abs(day_list.index(off) - day_list.index(tr)) == 1:
                fail("H18", "teacher %s has day_off %s adjacent to training_day "
                            "%s - two consecutive free days." % (t["id"], off, tr))

    # --- H10: contracted hours --------------------------------------------
    load = collections.Counter()
    for (t, d, p), v in t_at.items():
        load[t] += len(v)
    for t, n in load.items():
        cap = s.teachers.get(t, {}).get("hours", 0)
        if cap and n > cap:
            fail("H10", "teacher %s teaches %d hours, contract is %d." % (t, n, cap))

    # --- Locked: the user's pins were honoured -----------------------------
    for lk in s.locked:
        hit = False
        for d, p, r, lid in placed:
            L = lessons.get(lid)
            if L and lk["class_id"] in L["classes"] and L["subject"] == lk["subject_id"] \
                    and d == lk["day"] and p == lk["period"]:
                hit = True
                break
        if not hit:
            fail("LOCK", "you pinned %s/%s to %s period %d and it is not there."
                 % (lk["class_id"], lk["subject_id"], lk["day"], lk["period"]))

    # ---------------------------------------------------------------------
    print("Independently checked %d placed lessons from %s" % (len(placed), XML))
    print("  %d teachers, %d classes, %d rooms, %d open periods/week"
          % (len(s.teachers), len(s.classes), len(s.rooms), len(cfg.slots)))
    print("")
    if fails:
        print("!!! %d VIOLATION(S) - DO NOT USE THIS TIMETABLE !!!" % len(fails))
        print("")
        for f in fails[:60]:
            print("  " + f)
        if len(fails) > 60:
            print("  ...and %d more." % (len(fails) - 60))
        return 1
    if excused:
        print("GREEN WITH DECLARED EXCEPTIONS (rescue mode).")
        print("The strict rules admitted no timetable; these deliberate,")
        print("declared exceptions were taken and are listed in out/report.md:")
        print("")
        for f in excused:
            print("  " + f)
        print("")
        print("Everything else holds. Fix the cause and re-run for a fully")
        print("legal timetable.")
        return 0
    print("ALL GREEN - every hard rule holds.")
    print("H1 no teacher clash | H2 no class clash | H3 no room clash")
    print("H4 room count | H5 hours exact | H6 room type | H7 day off+training")
    print("H8 unavailable | H9 block patterns | H10 contract hours")
    print("H15 daylight | H17 max 6h/day | H18 free-day adjacency | LOCK pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())

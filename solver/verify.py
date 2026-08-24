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


def _group_no(groupids):
    """'GRP_<classid>_<n>' -> n; no groupids (or entire class) -> 0."""
    g = (groupids or "").split(",")[0].strip()
    if not g:
        return 0
    try:
        return int(g.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def _weeks_of_mask(mask):
    """A card's weeks mask -> which weeks it exists in. Single-week files
    ('1', or no mask at all) exist in 'both' weeks - the distinction only
    matters once A/B lessons appear."""
    m = (mask or "").strip()
    if m == "10":
        return ("A",)
    if m == "01":
        return ("B",)
    return ("A", "B")


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
            group=_group_no(el.get("groupids")),
        )
    cards = []
    for el in root.findall("./cards/card"):
        cards.append(dict(
            lesson=el.get("lessonid"),
            period=int(el.get("period")),
            days=el.get("days") or "",
            room=el.get("classroomids") or "",
            weeks=_weeks_of_mask(el.get("weeks")),
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

    # --- decode every card into (day, period, weeks) ----------------------
    placed = []   # (day, period, room, lesson_id, weeks_tuple)
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
        placed.append((on[0], c["period"], c["room"], c["lesson"], c["weeks"]))

    # --- every card lands in an open period -------------------------------
    for d, p, r, lid, wks in placed:
        if (d, p) not in open_slots:
            fail("H0", "a lesson is placed at %s period %d, when the school is shut." % (d, p))

    # --- H5: required hours delivered exactly -----------------------------
    # Per (class, subject, group, week): every group of a split row gets the
    # row's hours; a week-A row delivers in week A. An every-week card counts
    # in both week views, and so does an every-week row.
    want = collections.Counter()
    for row in s.curriculum:
        n_groups = max(1, row.get("groups", 1))
        rweek = row.get("week", "")
        for g in (range(1, n_groups + 1) if n_groups > 1 else [0]):
            for w in ("A", "B"):
                if rweek in ("", w):
                    want[row["class_id"], row["subject_id"], g, w] += row["hours"]
    got = collections.Counter()
    for d, p, r, lid, wks in placed:
        L = lessons.get(lid)
        if not L:
            fail("XML", "card refers to unknown lesson id %s." % lid)
            continue
        for cid in L["classes"]:
            for w in wks:
                got[cid, L["subject"], L["group"], w] += 1
    for key in set(want) | set(got):
        if want[key] != got[key]:
            grp = ("group %d" % key[2]) if key[2] else "whole class"
            fail("H5", "class %s subject %s (%s, week %s): needs %d hours, "
                       "timetable has %d."
                 % (key[0], key[1], grp, key[3], want[key], got[key]))

    # --- H1 teacher clash / H2 class clash / H3 room clash ----------------
    # All three are per WEEK: a week-A card and a week-B card never meet.
    # H2 is per class PART: group 1 clashes with group 1 and with the whole
    # class, but groups 1 and 2 may sit in parallel (the proven aSc split).
    t_at = collections.defaultdict(list)
    c_at = collections.defaultdict(list)
    r_at = collections.defaultdict(list)
    for d, p, r, lid, wks in placed:
        L = lessons.get(lid)
        if not L:
            continue
        for w in wks:
            for t in L["teachers"]:
                t_at[t, d, p, w].append(lid)
            for cid in L["classes"]:
                c_at[cid, d, p, w].append(L["group"])
            if r:
                r_at[r, d, p, w].append(lid)

    def wtag(w):
        return " (week %s)" % w

    for (t, d, p, w), v in t_at.items():
        if len(v) > 1:
            fail("H1", "teacher %s is in %d places at %s period %d%s."
                 % (t, len(v), d, p, wtag(w)))
    for (c, d, p, w), gs in c_at.items():
        if len(gs) > 1 and (0 in gs or len(set(gs)) < len(gs)):
            fail("H2", "class %s is in %d places at %s period %d%s "
                       "(groups %s - only DIFFERENT groups may overlap)."
                 % (c, len(gs), d, p, wtag(w),
                    ", ".join(str(g) for g in sorted(gs))))
    for (r, d, p, w), v in r_at.items():
        if len(v) > 1:
            fail("H3", "room %s holds %d lessons at %s period %d%s."
                 % (r, len(v), d, p, wtag(w)))

    # --- H4: never more lessons at once than rooms exist ------------------
    per_slot = collections.Counter()
    for d, p, r, lid, wks in placed:
        for w in wks:
            per_slot[d, p, w] += 1
    for (d, p, w), n in per_slot.items():
        if n > len(s.rooms):
            fail("H4", "%d lessons at %s period %d%s but only %d rooms exist."
                 % (n, d, p, wtag(w), len(s.rooms)))

    # --- H6: right kind of room -------------------------------------------
    need_type = {}
    for row in s.curriculum:
        need_type[row["class_id"], row["subject_id"]] = s.room_type_for(row)
    for d, p, r, lid, wks in placed:
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
    # Each block must sit as ONE run of consecutive periods on ONE day, per
    # GROUP copy and per WEEK view; the run lengths must match the declared
    # pattern(s). When a subject has several rows (theory + fortnight extra),
    # the expectation is the union of their patterns in that week.
    cs_day = collections.defaultdict(list)  # (class, subj, group, week, day) -> periods
    for d, p, r, lid, wks in placed:
        L = lessons.get(lid)
        if not L:
            continue
        for cid in L["classes"]:
            for w in wks:
                cs_day[cid, L["subject"], L["group"], w, d].append(p)

    runs = collections.defaultdict(list)    # (class, subj, group, week) -> runs
    for (cid, subj, g, w, d), ps in cs_day.items():
        ps.sort()
        run = 1
        for a, b in zip(ps, ps[1:]):
            if b == a + 1:
                run += 1
            else:
                runs[cid, subj, g, w].append(run)
                run = 1
        runs[cid, subj, g, w].append(run)

    expect = collections.defaultdict(list)  # (class, subj, group, week) -> blocks
    unverifiable = set()                    # a blank-pattern row is in the mix
    for row in s.curriculum:
        n_groups = max(1, row.get("groups", 1))
        rweek = row.get("week", "")
        blank = not str(row.get("blocks", "")).strip()
        want_bl, berr = D.parse_blocks(row.get("blocks", ""), row["hours"])
        bad = berr or not want_bl or sum(want_bl) != row["hours"]
        for g in (range(1, n_groups + 1) if n_groups > 1 else [0]):
            for w in ("A", "B"):
                if rweek not in ("", w):
                    continue
                key = (row["class_id"], row["subject_id"], g, w)
                if blank or bad:
                    unverifiable.add(key)
                else:
                    expect[key].extend(want_bl)
    for key, want_bl in expect.items():
        if key in unverifiable:
            continue   # mixed with a free-form row - runs cannot be predicted
        got_bl = runs.get(key, [])
        if sorted(got_bl) != sorted(want_bl):
            grp = ("group %d" % key[2]) if key[2] else "whole class"
            fail("H9", "class %s subject %s (%s, week %s): blocks say %s but "
                       "the timetable has runs of %s (each block must be "
                       "consecutive hours on its own day)."
                 % (key[0], key[1], grp, key[3],
                    "+".join(map(str, sorted(want_bl, reverse=True))),
                    "+".join(map(str, sorted(got_bl, reverse=True))) or "none"))

    # --- H19: 24 hours between sessions of a gap24 subject -----------------
    # On consecutive days, the later session must not start earlier in the
    # day than the first one did (circular III.2, the PE 24-hour note).
    # Checked inside each week view - sessions of different weeks never meet.
    day_order = {d: k for k, d in enumerate(cfg.days)}
    seen_h19 = set()
    for row in s.curriculum:
        if not str(row.get("blocks", "")).strip():
            continue
        if s.subjects.get(row["subject_id"], {}).get("gap24") != "yes":
            continue
        n_groups = max(1, row.get("groups", 1))
        for g in (range(1, n_groups + 1) if n_groups > 1 else [0]):
            for w in ("A", "B"):
                key = (row["class_id"], row["subject_id"], g, w)
                if key in seen_h19 or row.get("week", "") not in ("", w):
                    continue
                seen_h19.add(key)
                starts = {}
                for (cid, subj, gg, ww, d), ps in cs_day.items():
                    if (cid, subj, gg, ww) == key:
                        starts[day_order[d]] = min(ps)
                for k in sorted(starts):
                    if k + 1 in starts and starts[k + 1] < starts[k]:
                        fail("H19", "class %s subject %s: sessions on consecutive "
                                    "days start at period %d then %d - less than "
                                    "24 hours apart (circular III.2)."
                             % (row["class_id"], row["subject_id"],
                                starts[k], starts[k + 1]))

    # --- H15: daylight-only subjects ---------------------------------------
    for d, p, r, lid, wks in placed:
        L = lessons.get(lid)
        if not L:
            continue
        sub = s.subjects.get(L["subject"], {})
        lp = sub.get("latest_period") or 0
        if lp and p > lp:
            fail("H15", "%s runs at %s period %d but may not go past period %d "
                        "(no daylight)." % (L["subject"], d, p, lp))

    # --- H7: day off AND training day are empty ----------------------------
    for (t, d) in sorted({(t, d) for (t, d, p, w) in t_at}):
        rec = s.teachers.get(t, {})
        if rec.get("day_off", "") == d:
            fail("H7", "teacher %s teaches on %s, which is their day off." % (t, d),
                 key=(t, d))
        if rec.get("training_day", "") == d:
            fail("H7", "teacher %s teaches on %s, their training day." % (t, d),
                 key=(t, d))

    # --- H7-flex: a BLANK day_off means the solver CHOSE a day off ---------
    # Majd's rule: flexible unless fixed in the data. The XML does not record
    # which day was chosen, so verify the promise itself: at least one
    # H18-legal day (never adjacent to the training day, Sunday wrap
    # included) is completely free of lessons.
    day_list = list(cfg.days)
    taught_days = collections.defaultdict(set)
    for (t, d, p, w), v in t_at.items():
        taught_days[t].add(d)
    for t in s.teachers.values():
        if (t.get("day_off") or "").strip():
            continue          # fixed day handled above; "(none)" = no day off
        if t["id"] not in taught_days:
            continue          # teaches nothing - trivially free
        tr = t.get("training_day", "")
        cands = []
        for d in day_list:
            if d == tr:
                continue
            if tr in day_list:
                gap = abs(day_list.index(d) - day_list.index(tr))
                if gap == 1 or gap == len(day_list) - 1:
                    continue
            cands.append(d)
        if not cands or any(d not in taught_days[t["id"]] for d in cands):
            continue
        if any(("H7", t["id"], d) in accepted for d in cands):
            excused.append("H7   teacher %s has no fully free legal day - "
                           "declared rescue exception." % t["id"])
        else:
            fails.append("H7   teacher %s has NO fully free H18-legal day - "
                         "a blank day_off promises one (solver-chosen)."
                         % t["id"])

    # --- H17: never more than 6 teaching hours in one day ------------------
    # Per week: an every-week hour loads both weeks, a week-A hour only A.
    day_load = collections.Counter()
    for (t, d, p, w), v in t_at.items():
        day_load[t, d, w] += len(v)
    reported_h17 = set()
    for (t, d, w), n in sorted(day_load.items()):
        if n > 6 and (t, d) not in reported_h17:
            reported_h17.add((t, d))
            fail("H17", "teacher %s teaches %d hours on %s (week %s); the "
                        "ministry caps the day at 6 (circular II.2)."
                 % (t, n, d, w), key=(t, d))

    # --- H8: declared unavailable ------------------------------------------
    for un in s.unavailable:
        if un["hard"] != "yes":
            continue
        for (t, d, p) in sorted({(t, d, p) for (t, d, p, w) in t_at}):
            if t != un["teacher_id"]:
                continue
            if un["day"] in ("*", d) and (un["period"] == "*" or str(p) == str(un["period"])):
                fail("H8", "teacher %s teaches at %s period %d but declared "
                           "unavailable (%s)." % (t, d, p, un["reason"] or "no reason given"))

    # --- H18: day off never adjacent to training day (inspector's rule) ----
    # Majd 2026-08-24: the Sat/Mon pair is also forbidden - the Sunday rest
    # day between them would make three free days in a row.
    day_list = list(cfg.days)
    for t in s.teachers.values():
        off, tr = t.get("day_off", ""), t.get("training_day", "")
        if off in day_list and tr in day_list and off != tr:
            gap = abs(day_list.index(off) - day_list.index(tr))
            if gap == 1 or gap == len(day_list) - 1:
                fail("H18", "teacher %s has day_off %s adjacent to training_day "
                            "%s - consecutive free days (Sunday counts)." % (t["id"], off, tr))

    # --- H10: contracted hours (the busier week is what counts) ------------
    load = collections.Counter()
    for (t, d, p, w), v in t_at.items():
        load[t, w] += len(v)
    for t in sorted({t for (t, w) in load}):
        n = max(load.get((t, "A"), 0), load.get((t, "B"), 0))
        cap = s.teachers.get(t, {}).get("hours", 0)
        if cap and n > cap:
            fail("H10", "teacher %s teaches %d hours in their busier week, "
                        "contract is %d." % (t, n, cap))

    # --- Locked: the user's pins were honoured -----------------------------
    for lk in s.locked:
        hit = False
        for d, p, r, lid, wks in placed:
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
    print("H15 daylight | H17 max 6h/day | H18 free-day adjacency")
    print("H19 24h between gap24 sessions | LOCK pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())

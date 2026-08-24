"""Build the timetable with OR-Tools CP-SAT, then write the aSc XML and report.

HARD rules are constraints - the solver physically cannot return a timetable
that breaks one. SOFT rules are penalties - it minimises them and reports what
it could not achieve.

Usage:  python solver/solve.py [path/to/school.xlsx]
"""
import collections
import json
import os
import shutil
import signal
import sys
import time

# Set by Ctrl+C. The solution callback sees it and stops the search cleanly,
# so the best VALID timetable found so far is kept and written out.
STOP = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ortools.sat.python import cp_model  # noqa: E402
import data as D  # noqa: E402
import emit_asc  # noqa: E402

HERE = D.HERE
OUT = os.path.join(HERE, "out")


class Unit:
    """One single lesson-hour that must be placed somewhere."""
    __slots__ = ("uid", "class_id", "subject_id", "teacher_id", "room_type", "idx")

    def __init__(self, uid, class_id, subject_id, teacher_id, room_type, idx):
        self.uid = uid
        self.class_id = class_id
        self.subject_id = subject_id
        self.teacher_id = teacher_id
        self.room_type = room_type
        self.idx = idx


def expand(s):
    """Turn each curriculum row into one Unit per weekly hour."""
    units = []
    for row in s.curriculum:
        rt = s.room_type_for(row)
        for i in range(row["hours"]):
            uid = "%s|%s|%d" % (row["class_id"], row["subject_id"], i)
            units.append(Unit(uid, row["class_id"], row["subject_id"],
                              row["teacher_id"], rt, i))
    return units


class Progress(cp_model.CpSolverSolutionCallback):
    """Print each improvement, and save it so a crash costs nothing.

    An overnight run that dies at hour 7 to a power cut must not lose the
    work. Every improvement is written to out/solution.json (throttled, so
    hundreds of quick improvements do not thrash the disk), and the very best
    is always saved. Resume later with --continue.
    """

    def __init__(self, t0, units=None, x=None, slots=None, every=15.0):
        super().__init__()
        self.t0 = t0
        self.n = 0
        self.units = units
        self.x = x
        self.slots = slots
        self.every = every
        self.last_save = 0.0
        self.best = None

    def snapshot(self):
        """{unit id: [day, period]} for the solution currently in hand."""
        out = {}
        for u in self.units:
            for i in range(len(self.slots)):
                if self.Value(self.x[u.uid, i]):
                    d, p = self.slots[i]
                    out[u.uid] = [d, p]
                    break
        return out

    def save(self, force=False):
        if self.units is None:
            return
        now = time.time()
        if not force and now - self.last_save < self.every:
            return
        self.last_save = now
        payload = dict(
            penalty=int(self.ObjectiveValue()),
            elapsed_seconds=round(now - self.t0, 1),
            solution_number=self.n,
            placement=self.snapshot(),
        )
        os.makedirs(OUT, exist_ok=True)
        tmp = os.path.join(OUT, "solution.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        # atomic replace, so a crash mid-write cannot corrupt the saved file
        os.replace(tmp, os.path.join(OUT, "solution.json"))
        self.best = payload

    def on_solution_callback(self):
        self.n += 1
        el = time.time() - self.t0
        print("   %6.1fs  solution %-3d penalty %s"
              % (el, self.n, int(self.ObjectiveValue())), flush=True)
        self.save()
        if STOP:
            self.save(force=True)
            print("   Ctrl+C - keeping this solution and stopping.", flush=True)
            self.StopSearch()


def build(s, units):
    m = cp_model.CpModel()
    slots = s.cfg.slots                      # [(day, period), ...]
    S = len(slots)
    slot_ix = {sl: i for i, sl in enumerate(slots)}
    W = s.cfg.weights
    evening = set(s.cfg.evening)

    # ---- variable: unit u sits in slot i ----------------------------------
    x = {}
    for u in units:
        for i in range(S):
            x[u.uid, i] = m.NewBoolVar("x_%s_%d" % (u.uid, i))

    # ---- H5: every unit is placed exactly once ---------------------------
    for u in units:
        m.AddExactlyOne(x[u.uid, i] for i in range(S))

    by_class = collections.defaultdict(list)
    by_teacher = collections.defaultdict(list)
    by_type = collections.defaultdict(list)
    for u in units:
        by_class[u.class_id].append(u)
        if u.teacher_id:
            by_teacher[u.teacher_id].append(u)
        by_type[u.room_type].append(u)

    # ---- H2: a class is in one place at a time ---------------------------
    for cid, us in by_class.items():
        for i in range(S):
            m.AddAtMostOne(x[u.uid, i] for u in us)

    # ---- H1: a teacher is in one place at a time -------------------------
    for tid, us in by_teacher.items():
        for i in range(S):
            m.AddAtMostOne(x[u.uid, i] for u in us)

    # ---- H3 + H4 + H6: never need more rooms of a type than exist --------
    # Rooms are interchangeable within a type, so counting is enough here.
    # assign_rooms() below turns the counts into concrete room numbers, and
    # verify.py checks the concrete result independently.
    for rt, us in by_type.items():
        n_rooms = len(s.rooms_of_type(rt))
        for i in range(S):
            m.Add(sum(x[u.uid, i] for u in us) <= n_rooms)

    # ---- H7: the teacher's day off is completely empty -------------------
    for tid, us in by_teacher.items():
        off = s.teachers.get(tid, {}).get("day_off", "")
        if not off or off == "(none)":
            continue
        for i, (d, p) in enumerate(slots):
            if d == off:
                for u in us:
                    m.Add(x[u.uid, i] == 0)

    # ---- H8: declared unavailable slots ----------------------------------
    for un in s.unavailable:
        if un["hard"] != "yes":
            continue
        us = by_teacher.get(un["teacher_id"], [])
        for i, (d, p) in enumerate(slots):
            if un["day"] not in ("*", d):
                continue
            if un["period"] != "*" and str(p) != str(un["period"]):
                continue
            for u in us:
                m.Add(x[u.uid, i] == 0)

    # ---- Locked sheet: the user's pinned placements are immovable --------
    locked_used = set()
    for lk in s.locked:
        i = slot_ix.get((lk["day"], lk["period"]))
        if i is None:
            continue
        for u in units:
            if (u.class_id == lk["class_id"] and u.subject_id == lk["subject_id"]
                    and u.uid not in locked_used):
                m.Add(x[u.uid, i] == 1)
                locked_used.add(u.uid)
                break

    penalties = []

    # ---- presence grid, reused by several soft rules ----------------------
    def presence(group_units, key):
        """pres[(day, period)] = 1 if this teacher/class is busy then."""
        pres = {}
        for i, (d, p) in enumerate(slots):
            b = m.NewBoolVar("pres_%s_%s_%d" % (key, d, p))
            m.Add(b == sum(x[u.uid, i] for u in group_units))
            pres[d, p] = b
        return pres

    def add_gap_penalty(pres, key, weight, also_one_hour=False, also_day_count=False):
        """S1/S7 no holes, S2 no 1-hour days, S8 fewest days present."""
        for d in s.cfg.days:
            ps = [p for (dd, p) in slots if dd == d]
            if len(ps) < 2:
                continue
            lo, hi = min(ps), max(ps)
            taught = sum(pres[d, p] for p in ps)

            here = m.NewBoolVar("here_%s_%s" % (key, d))
            m.Add(taught >= 1).OnlyEnforceIf(here)
            m.Add(taught == 0).OnlyEnforceIf(here.Not())

            first = m.NewIntVar(lo, hi, "first_%s_%s" % (key, d))
            last = m.NewIntVar(lo, hi, "last_%s_%s" % (key, d))
            for p in ps:
                m.Add(first <= p).OnlyEnforceIf(pres[d, p])
                m.Add(last >= p).OnlyEnforceIf(pres[d, p])

            gaps = m.NewIntVar(0, len(ps), "gaps_%s_%s" % (key, d))
            m.Add(gaps == last - first + 1 - taught).OnlyEnforceIf(here)
            m.Add(gaps == 0).OnlyEnforceIf(here.Not())
            penalties.append((weight, gaps))

            if also_one_hour:
                solo = m.NewBoolVar("solo_%s_%s" % (key, d))
                m.Add(taught == 1).OnlyEnforceIf(solo)
                m.Add(taught != 1).OnlyEnforceIf(solo.Not())
                penalties.append((W["one_hour_day"], solo))
            if also_day_count:
                penalties.append((W["extra_day_present"], here))

    # S1 teacher holes, S2 one-hour days, S8 fewest days
    for tid, us in by_teacher.items():
        pres = presence(us, "T" + tid)
        add_gap_penalty(pres, "T" + tid, W["teacher_gap"],
                        also_one_hour=True, also_day_count=True)

    # S7 pupils get no holes either
    for cid, us in by_class.items():
        pres = presence(us, "C" + cid)
        add_gap_penalty(pres, "C" + cid, W["class_gap"])

    # ---- S3: hard subjects belong in the morning -------------------------
    hard_units = [u for u in units
                  if s.subjects.get(u.subject_id, {}).get("difficulty") == "hard"]
    ev_ix = [i for i, (d, p) in enumerate(slots) if p in evening]
    if hard_units and ev_ix:
        n_ev = m.NewIntVar(0, len(hard_units), "hard_in_evening")
        m.Add(n_ev == sum(x[u.uid, i] for u in hard_units for i in ev_ix))
        penalties.append((W["hard_subject_evening"], n_ev))

    # ---- S6: spread a subject across the week ----------------------------
    per_cs = collections.defaultdict(list)
    for u in units:
        per_cs[u.class_id, u.subject_id].append(u)
    for (cid, sid), us in per_cs.items():
        if len(us) < 2:
            continue
        for d in s.cfg.days:
            ix = [i for i, (dd, p) in enumerate(slots) if dd == d]
            extra = m.NewIntVar(0, len(us), "twice_%s_%s_%s" % (cid, sid, d))
            m.Add(extra >= sum(x[u.uid, i] for u in us for i in ix) - 1)
            penalties.append((W["same_subject_twice_a_day"], extra))

    m.Minimize(sum(w * v for w, v in penalties))
    return m, x, slots


def assign_rooms(s, units, placement):
    """Turn 'a room of type X' into a concrete room id.

    The model guaranteed enough rooms of each type exist in every slot, so a
    simple pass always succeeds. Home rooms are preferred to reduce moving.
    """
    by_slot = collections.defaultdict(list)
    for u in units:
        by_slot[placement[u.uid]].append(u)

    rooms_by_type = collections.defaultdict(list)
    for r in s.rooms.values():
        rooms_by_type[r["type"]].append(r["id"])
    for k in rooms_by_type:
        rooms_by_type[k].sort()

    out = {}
    for slot, us in by_slot.items():
        taken = set()
        # first pass: give each class its home room when the type is right
        for u in us:
            home = s.classes.get(u.class_id, {}).get("home_room", "")
            if (home and home in s.rooms and home not in taken
                    and s.rooms[home]["type"] == u.room_type):
                out[u.uid] = home
                taken.add(home)
        # second pass: anything free of the right type
        for u in us:
            if u.uid in out:
                continue
            for rid in rooms_by_type.get(u.room_type, []):
                if rid not in taken:
                    out[u.uid] = rid
                    taken.add(rid)
                    break
            else:
                out[u.uid] = ""  # should never happen; verify.py will catch it
    return out


def report(s, units, placement, rooms, solver, status, elapsed):
    """Plain-language explanation of what was and was not achieved."""
    slots = s.cfg.slots
    L = []
    A = L.append
    A("# Timetable report")
    A("")
    A("Generated in %.1f seconds. Solver said: **%s**." % (elapsed, solver.StatusName(status)))
    if solver.StatusName(status) == "FEASIBLE":
        A("")
        A("*FEASIBLE means: a valid timetable, but the time limit stopped the search "
          "before it could prove no better one exists. Raise `time_limit_seconds` "
          "in config.json to let it keep improving.*")
    A("")
    A("- %d lessons placed" % len(units))
    A("- %d teachers, %d classes, %d rooms, %d open periods per week"
      % (len(s.teachers), len(s.classes), len(s.rooms), len(slots)))
    A("- total penalty score: **%d** (lower is better; 0 is perfect)"
      % int(solver.ObjectiveValue()))
    A("")

    # --- teacher-by-teacher truth ---
    t_slots = collections.defaultdict(set)
    for u in units:
        if u.teacher_id:
            t_slots[u.teacher_id].add(placement[u.uid])

    gaps, solos, days_used = [], [], {}
    for tid, sl in t_slots.items():
        byday = collections.defaultdict(list)
        for (d, p) in sl:
            byday[d].append(p)
        days_used[tid] = len(byday)
        for d, ps in byday.items():
            ps.sort()
            holes = (ps[-1] - ps[0] + 1) - len(ps)
            if holes:
                gaps.append((tid, d, holes, ps))
            if len(ps) == 1:
                solos.append((tid, d, ps[0]))

    A("## S1 - holes in a teacher's day")
    total_t = max(1, len(t_slots))
    A("")
    A("%d of %d teachers have a completely clean week (**%.0f%%**)."
      % (total_t - len({g[0] for g in gaps}), total_t,
         100.0 * (total_t - len({g[0] for g in gaps})) / total_t))
    if gaps:
        A("")
        A("| teacher | day | holes | periods taught |")
        A("|---|---|---|---|")
        for tid, d, h, ps in sorted(gaps)[:40]:
            A("| %s (%s) | %s | %d | %s |"
              % (s.teachers.get(tid, {}).get("name", tid), tid, d, h,
                 ", ".join(str(p) for p in ps)))
        if len(gaps) > 40:
            A("")
            A("*...and %d more.*" % (len(gaps) - 40))
    A("")

    A("## S2 - teachers coming in for a single hour")
    A("")
    if solos:
        A("%d cases:" % len(solos))
        A("")
        for tid, d, p in sorted(solos)[:30]:
            A("- %s (%s) - %s, only period %d"
              % (s.teachers.get(tid, {}).get("name", tid), tid, d, p))
    else:
        A("**None.** No teacher travels to school for one hour.")
    A("")

    A("## S3 - hard subjects in the morning")
    ev = set(s.cfg.evening)
    hard_total = hard_ev = 0
    for u in units:
        if s.subjects.get(u.subject_id, {}).get("difficulty") == "hard":
            hard_total += 1
            if placement[u.uid][1] in ev:
                hard_ev += 1
    A("")
    if hard_total:
        A("%d of %d hard-subject hours are in the morning (**%.0f%%**)."
          % (hard_total - hard_ev, hard_total,
             100.0 * (hard_total - hard_ev) / hard_total))
    else:
        A("No subjects are marked `hard` in the Subjects sheet.")
    A("")

    A("## S7 - holes in a pupil's day")
    c_slots = collections.defaultdict(set)
    for u in units:
        c_slots[u.class_id].add(placement[u.uid])
    cgap = 0
    for cid, sl in c_slots.items():
        byday = collections.defaultdict(list)
        for (d, p) in sl:
            byday[d].append(p)
        for d, ps in byday.items():
            cgap += (max(ps) - min(ps) + 1) - len(ps)
    A("")
    A("%d free periods trapped inside pupils' days, across all %d classes."
      % (cgap, len(c_slots)))
    A("")

    A("## Room usage")
    A("")
    use = collections.Counter(placement[u.uid] for u in units)
    busiest = use.most_common(1)[0][1] if use else 0
    A("- busiest period uses **%d of %d** rooms" % (busiest, len(s.rooms)))
    A("- average %.1f rooms in use per open period"
      % (float(len(units)) / max(1, len(slots))))
    A("")
    A("---")
    A("")
    A("*Every number above was measured from the finished timetable, not "
      "predicted. `verify.py` re-checks all of it independently.*")
    return "\n".join(L)


def main():
    t0 = time.time()
    cfg = D.load_config()
    # --time=600 overrides config.json for one run, without editing the file.
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for a in sys.argv[1:]:
        if a.startswith("--time="):
            cfg.time_limit = int(a.split("=", 1)[1])
    path = args[0] if args else None
    s = D.load_school(path, cfg)

    errs, notes = D.check(s)
    for n in notes:
        print("NOTE :", n)
    if errs:
        for e in errs:
            print("ERROR:", e)
        print("\nFix the data first. Nothing was solved.")
        return 1

    units = expand(s)
    print("\nPlacing %d lesson-hours into %d open periods across %d rooms."
          % (len(units), len(s.cfg.slots), len(s.rooms)))
    print("Building the model...", flush=True)
    m, x, slots = build(s, units)

    def on_sigint(signum, frame):
        global STOP
        STOP = True
        print("   Stopping after the next solution...", flush=True)

    signal.signal(signal.SIGINT, on_sigint)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(cfg.time_limit)
    solver.parameters.num_search_workers = os.cpu_count() or 8
    solver.parameters.log_search_progress = False
    print("Solving (limit %ds, Ctrl+C keeps the best found so far):"
          % cfg.time_limit, flush=True)

    # --continue: start from the last saved solution instead of from nothing.
    # AddHint is only a suggestion - it never overrides a constraint, so a
    # stale hint can slow the search but can never make the result wrong.
    if "--continue" in sys.argv:
        prev = os.path.join(OUT, "solution.json")
        if os.path.exists(prev):
            with open(prev, encoding="utf-8") as f:
                saved = json.load(f)
            place = saved.get("placement", {})
            slot_ix = {sl: i for i, sl in enumerate(slots)}
            hinted = 0
            for u in units:
                got = place.get(u.uid)
                if not got:
                    continue
                i = slot_ix.get((got[0], got[1]))
                if i is not None:
                    m.AddHint(x[u.uid, i], 1)
                    hinted += 1
            print("Resuming from out/solution.json - penalty %s, %d of %d "
                  "lessons hinted." % (saved.get("penalty"), hinted, len(units)))
        else:
            print("--continue given but no out/solution.json yet; starting fresh.")

    cb = Progress(t0, units=units, x=x, slots=slots)
    status = solver.Solve(m, cb)
    cb.save(force=True)
    elapsed = time.time() - t0

    name = solver.StatusName(status)
    if name in ("INFEASIBLE", "MODEL_INVALID"):
        print("\nNO TIMETABLE EXISTS with these rules and this data.")
        print("That is information, not a bug: something you asked for is")
        print("impossible. Loosen a rule or change the data, then re-run.")
        return 2
    if name == "UNKNOWN":
        print("\nNo solution found inside the time limit.")
        print("Raise time_limit_seconds in config.json and re-run.")
        return 3

    placement = {}
    for u in units:
        for i in range(len(slots)):
            if solver.Value(x[u.uid, i]):
                placement[u.uid] = slots[i]
                break
    rooms = assign_rooms(s, units, placement)

    os.makedirs(OUT, exist_ok=True)
    xml_path = os.path.join(OUT, "timetable.xml")
    emit_asc.write(s, units, placement, rooms, xml_path)
    rep = report(s, units, placement, rooms, solver, status, elapsed)
    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
        f.write(rep)

    # Timestamped archive, so a good result is never silently overwritten by a
    # worse one on the next run. Keeps the XML, the report and the raw solution.
    stamp = time.strftime("%Y-%m-%d_%H%M")
    arch = os.path.join(OUT, "archive")
    os.makedirs(arch, exist_ok=True)
    tag = "%s_penalty%d" % (stamp, int(solver.ObjectiveValue()))
    shutil.copy(xml_path, os.path.join(arch, tag + ".xml"))
    shutil.copy(os.path.join(OUT, "report.md"), os.path.join(arch, tag + ".md"))
    sol = os.path.join(OUT, "solution.json")
    if os.path.exists(sol):
        shutil.copy(sol, os.path.join(arch, tag + ".json"))

    print("\nDone in %.1fs - status %s, penalty %d"
          % (elapsed, name, int(solver.ObjectiveValue())))
    print("  out/timetable.xml  -> import into aSc TimeTables")
    print("  out/report.md      -> what it could and could not satisfy")
    print("\nNow run:  python solver/verify.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

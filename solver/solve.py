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


# In rescue mode a relaxable hard rule may be broken, but each broken hour
# costs this much - far above anything the soft rules could ever trade it
# against. The solver only pays it when the strict rules admit NO timetable.
RESCUE_WEIGHT = 10000


def build(s, units, rescue=False):
    """Build the CP-SAT model.

    rescue=False - every hard rule is a real constraint (the normal mode).
    rescue=True  - the RELAXABLE hard rules (H7 day off / training day, H17
                   daily cap) become violations costing RESCUE_WEIGHT per hour,
                   so a livable timetable can exist even when the strict rules
                   are impossible. H1-H6, H8, H15, closed periods and locks are
                   NEVER relaxed. Every violation is reported, never hidden.

    Returns (model, x, slots, viols); viols is a list of
    (rule, teacher_id, day, int_var, description) used to report exceptions.
    """
    m = cp_model.CpModel()
    slots = s.cfg.slots                      # [(day, period), ...]
    S = len(slots)
    slot_ix = {sl: i for i, sl in enumerate(slots)}
    W = s.cfg.weights
    evening = set(s.cfg.evening)
    viols = []
    penalties = []

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

    # ---- H7: the teacher's day off AND training day are completely empty --
    # (circular II.1: respect the pedagogical training days)
    # Relaxable in rescue mode: teaching on a free day is livable in extremis;
    # it is reported as an exception, never silently.
    for tid, us in by_teacher.items():
        t = s.teachers.get(tid, {})
        for kind in ("day_off", "training_day"):
            off = t.get(kind, "")
            if not off or off == "(none)":
                continue
            ix = [i for i, (d, p) in enumerate(slots) if d == off]
            if not ix:
                continue
            if not rescue:
                for u in us:
                    for i in ix:
                        m.Add(x[u.uid, i] == 0)
            else:
                v = m.NewIntVar(0, len(ix), "vH7_%s_%s" % (tid, kind))
                m.Add(v == sum(x[u.uid, i] for u in us for i in ix))
                penalties.append((RESCUE_WEIGHT, v))
                viols.append(("H7", tid, off, v,
                              "teaches on their %s" % kind.replace("_", " ")))

    # ---- H17: a teacher never teaches more than 6 hours in one day --------
    # Circular 51/2018 II.2, repeated by the inspectorate text. Relaxable in
    # rescue mode (a 7-hour day is livable in extremis; a clash is not).
    for tid, us in by_teacher.items():
        for d in s.cfg.days:
            ix = [i for i, (dd, p) in enumerate(slots) if dd == d]
            if len(ix) <= 6:
                continue
            day_sum = sum(x[u.uid, i] for u in us for i in ix)
            if not rescue:
                m.Add(day_sum <= 6)
            else:
                over = m.NewIntVar(0, len(ix) - 6, "vH17_%s_%s" % (tid, d))
                m.Add(day_sum <= 6 + over)
                penalties.append((RESCUE_WEIGHT, over))
                viols.append(("H17", tid, d, over, "hours beyond 6 in one day"))

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

    # ---- H15: daylight-only subjects never run past latest_period --------
    # Sport has no stadium lighting, so it may not sit after 16:00 (period 8
    # in a 10-period day starting 08:00). Expressed generally so any subject
    # can carry a time limit.
    for u in units:
        lp = s.subjects.get(u.subject_id, {}).get("latest_period") or 0
        if not lp:
            continue
        for i, (d, p) in enumerate(slots):
            if p > lp:
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

    # S1 teacher holes, S2 one-hour days. S8 is the MINISTRY version now
    # (circular II.2: hours balanced across working days): by default a
    # teacher's overloaded days are penalised, which spreads the week.
    # compact=yes in the Teachers sheet keeps the old packed week instead -
    # the exception Majd grants to teachers with long journeys.
    for tid, us in by_teacher.items():
        pres = presence(us, "T" + tid)
        compact = s.teachers.get(tid, {}).get("compact", "") == "yes"
        add_gap_penalty(pres, "T" + tid, W["teacher_gap"],
                        also_one_hour=True, also_day_count=compact)
        if not compact:
            # S8 (ministry): every taught hour beyond 4 on one day is a
            # sign of cramming; H17 caps the day at 6 outright.
            for d in s.cfg.days:
                ps = [p for (dd, p) in slots if dd == d]
                if len(ps) <= 4:
                    continue
                over = m.NewIntVar(0, len(ps) - 4, "crowd_%s_%s" % (tid, d))
                m.Add(over >= sum(pres[d, p] for p in ps) - 4)
                penalties.append((W.get("overloaded_day", 40), over))

        # S5 (circular II.4): alternation - nobody teaches only mornings or
        # only evenings. Penalise |morning - evening| beyond a slack of 2.
        m_ix = [i for i, (d, p) in enumerate(slots) if p not in evening]
        e_ix = [i for i, (d, p) in enumerate(slots) if p in evening]
        if m_ix and e_ix:
            mh = sum(x[u.uid, i] for u in us for i in m_ix)
            eh = sum(x[u.uid, i] for u in us for i in e_ix)
            imb = m.NewIntVar(0, len(slots), "imb_%s" % tid)
            m.Add(imb >= mh - eh - 2)
            m.Add(imb >= eh - mh - 2)
            penalties.append((W.get("morning_evening_imbalance", 60), imb))

    # S7 pupils get no holes either
    for cid, us in by_class.items():
        pres = presence(us, "C" + cid)
        add_gap_penalty(pres, "C" + cid, W["class_gap"])

    # ---- S15: a class never comes in for a single lone hour ---------------
    # Circular I.2: minimum 2 hours in any morning or evening - for pupils
    # too. The circular exempts PE and optional subjects (minmax_exempt=yes
    # in the Subjects sheet): a lone PE hour is fine.
    halves = {"am": [p for p in range(1, s.cfg.periods_per_day + 1)
                     if p not in evening],
              "pm": sorted(evening)}
    for cid, us in by_class.items():
        exempt = [u for u in us
                  if s.subjects.get(u.subject_id, {}).get("minmax_exempt") == "yes"]
        counted = [u for u in us if u not in exempt]
        for d in s.cfg.days:
            for half, ps in halves.items():
                ix = [i for i, (dd, p) in enumerate(slots) if dd == d and p in ps]
                if len(ix) < 2:
                    continue
                tot = sum(x[u.uid, i] for u in us for i in ix)
                cnt = sum(x[u.uid, i] for u in counted for i in ix)
                solo = m.NewBoolVar("csolo_%s_%s_%s" % (cid, d, half))
                # solo <=> (exactly 1 hour in this half-day, and it counts)
                m.Add(tot == 1).OnlyEnforceIf(solo)
                m.Add(cnt >= 1).OnlyEnforceIf(solo)
                b_tot1 = m.NewBoolVar("ctot1_%s_%s_%s" % (cid, d, half))
                m.Add(tot == 1).OnlyEnforceIf(b_tot1)
                m.Add(tot != 1).OnlyEnforceIf(b_tot1.Not())
                b_cnt1 = m.NewBoolVar("ccnt1_%s_%s_%s" % (cid, d, half))
                m.Add(cnt >= 1).OnlyEnforceIf(b_cnt1)
                m.Add(cnt == 0).OnlyEnforceIf(b_cnt1.Not())
                m.AddBoolAnd([b_tot1, b_cnt1]).OnlyEnforceIf(solo)
                m.AddBoolOr([b_tot1.Not(), b_cnt1.Not()]).OnlyEnforceIf(solo.Not())
                penalties.append((W.get("class_one_hour_session", 85), solo))

    # ---- S16: subject-specific late-hour avoidance ------------------------
    # Soft cousin of H15. Ministry: Maths avoids the evening and never after
    # 16:00 if it must (M-MA3); Physics avoids 17:00-18:00 (M-PH5).
    for u in units:
        aa = s.subjects.get(u.subject_id, {}).get("avoid_after") or 0
        if not aa:
            continue
        late = [i for i, (d, p) in enumerate(slots) if p > aa]
        for i in late:
            penalties.append((W.get("late_subject", 50), x[u.uid, i]))

    # ---- S14: the last period of the day is a slot of last resort ---------
    # Majd: "try to avoid 17 to 18 as much as possible its late". Ministry
    # backing: the inspectorate tells Physics the same (M-PH5). Applies to
    # everyone; soft, because banning it would cost too much capacity.
    last_p = s.cfg.periods_per_day
    last_ix = [i for i, (d, p) in enumerate(slots) if p == last_p]
    for u in units:
        for i in last_ix:
            penalties.append((W.get("last_period", 55), x[u.uid, i]))

    # ---- S13: no Friday evening for bac classes (local preference) --------
    # ---- S17: bac classes get a free afternoon Mon-Thu (circular I.6) -----
    first_four = s.cfg.days[:4]
    for cid, us in by_class.items():
        if s.classes.get(cid, {}).get("is_bac", "") != "yes":
            continue
        fri_ev = [i for i, (d, p) in enumerate(slots)
                  if d == "Fri" and p in evening]
        for u in us:
            for i in fri_ev:
                penalties.append((W.get("bac_friday_evening", 30), x[u.uid, i]))
        # S17: at least one of the first four days' evenings entirely free
        free_days = []
        for d in first_four:
            ix = [i for i, (dd, p) in enumerate(slots) if dd == d and p in evening]
            if not ix:
                continue
            b = m.NewBoolVar("bacfree_%s_%s" % (cid, d))
            m.Add(sum(x[u.uid, i] for u in us for i in ix) == 0).OnlyEnforceIf(b)
            m.Add(sum(x[u.uid, i] for u in us for i in ix) >= 1).OnlyEnforceIf(b.Not())
            free_days.append(b)
        if free_days:
            none_free = m.NewBoolVar("bacnofree_%s" % cid)
            m.AddBoolAnd([b.Not() for b in free_days]).OnlyEnforceIf(none_free)
            m.AddBoolOr(free_days).OnlyEnforceIf(none_free.Not())
            penalties.append((W.get("bac_no_free_afternoon", 70), none_free))

    # ---- S3: hard subjects belong in the morning -------------------------
    hard_units = [u for u in units
                  if s.subjects.get(u.subject_id, {}).get("difficulty") == "hard"]
    ev_ix = [i for i, (d, p) in enumerate(slots) if p in evening]
    if hard_units and ev_ix:
        n_ev = m.NewIntVar(0, len(hard_units), "hard_in_evening")
        m.Add(n_ev == sum(x[u.uid, i] for u in hard_units for i in ev_ix))
        penalties.append((W["hard_subject_evening"], n_ev))

    # ---- S12: daylight subjects PREFER the morning -----------------------
    # "morning and max 14h to 16h" - the late window is a fallback, not the
    # target. Penalise every daylight-limited hour that lands outside morning.
    daylight_units = [u for u in units
                      if (s.subjects.get(u.subject_id, {}).get("latest_period") or 0)]
    morning = set(s.cfg.morning)
    late_ix = [i for i, (d, p) in enumerate(slots) if p not in morning]
    if daylight_units and late_ix:
        n_late = m.NewIntVar(0, len(daylight_units), "daylight_outside_morning")
        m.Add(n_late == sum(x[u.uid, i] for u in daylight_units for i in late_ix))
        penalties.append((W.get("daylight_not_morning", 45), n_late))

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
    return m, x, slots, viols


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


def report(s, units, placement, rooms, solver, status, elapsed, exceptions=None):
    """Plain-language explanation of what was and was not achieved."""
    slots = s.cfg.slots
    L = []
    A = L.append
    A("# Timetable report")
    A("")
    A("Generated in %.1f seconds. Solver said: **%s**." % (elapsed, solver.StatusName(status)))
    if exceptions:
        A("")
        A("## ⚠ RULE EXCEPTIONS - this timetable was built in RESCUE MODE")
        A("")
        A("The strict rules admitted **no timetable at all**, so the solver was")
        A("allowed to make the following livable exceptions. Everything else")
        A("follows the rules. Fix the underlying cause (data or workload) and")
        A("re-run to get a fully legal timetable.")
        A("")
        A("| rule | teacher | day | how much | what happened |")
        A("|---|---|---|---|---|")
        for e in exceptions:
            t = s.teachers.get(e["teacher_id"], {})
            A("| %s | %s (%s) | %s | %d | %s |"
              % (e["rule"], t.get("name", e["teacher_id"]), e["teacher_id"],
                 e["day"], e["amount"], e["what"]))
        A("")
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

    A("## S15 - classes coming in for a single hour (circular I.2)")
    ev = set(s.cfg.evening)
    lone = []
    by_class_day = collections.defaultdict(list)
    for u in units:
        d, p = placement[u.uid]
        ex = s.subjects.get(u.subject_id, {}).get("minmax_exempt") == "yes"
        by_class_day[u.class_id, d, "pm" if p in ev else "am"].append((p, ex))
    for (cid, d, half), hours in by_class_day.items():
        if len(hours) == 1 and not hours[0][1]:
            lone.append((cid, d, half, hours[0][0]))
    A("")
    if lone:
        A("%d lone-hour half-days (pupils travel in for one hour):" % len(lone))
        A("")
        for cid, d, half, p in sorted(lone)[:30]:
            A("- class %s - %s %s, only period %d" % (cid, d, half, p))
    else:
        A("**None.** No class travels in for a single hour "
          "(PE and optional subjects exempt, as the circular allows).")
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
    m, x, slots, viols = build(s, units)

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

    name = solver.StatusName(status)
    exceptions = []
    exc_path = os.path.join(OUT, "exceptions.json")

    if name in ("INFEASIBLE", "MODEL_INVALID"):
        # ---- RESCUE MODE ------------------------------------------------
        # The strict rules admit no timetable at all. Rather than stop dead,
        # retry with the RELAXABLE rules (H7 day off / training day, H17
        # 6h/day cap) allowed to break at enormous cost. Clashes, the lunch
        # break, H8 declarations, daylight limits and locks stay absolute.
        # Every exception taken is listed in the report - nothing is hidden.
        print("\nNo timetable exists under the strict rules.")
        print("RESCUE MODE: retrying with livable exceptions allowed")
        print("(day off / training day / 6h-day cap only - never clashes,")
        print("never the lunch break). Every exception will be reported.")
        m, x, slots, viols = build(s, units, rescue=True)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(cfg.time_limit)
        solver.parameters.num_search_workers = os.cpu_count() or 8
        cb = Progress(t0, units=units, x=x, slots=slots)
        status = solver.Solve(m, cb)
        cb.save(force=True)
        name = solver.StatusName(status)
        if name in ("INFEASIBLE", "MODEL_INVALID"):
            print("\nNO TIMETABLE EXISTS even with the livable exceptions.")
            print("Something structural is impossible (a clash, room shortage,")
            print("or contradictory data). Check the data, then re-run.")
            return 2
        if name == "UNKNOWN":
            print("\nNo solution found inside the time limit (rescue mode).")
            print("Raise time_limit_seconds in config.json and re-run.")
            return 3
        for rule, tid, day, var, desc in viols:
            v = solver.Value(var)
            if v:
                exceptions.append(dict(rule=rule, teacher_id=tid, day=day,
                                       amount=int(v), what=desc))
        os.makedirs(OUT, exist_ok=True)
        with open(exc_path, "w", encoding="utf-8") as f:
            json.dump(dict(mode="rescue", exceptions=exceptions), f,
                      ensure_ascii=False, indent=1)
    elif name == "UNKNOWN":
        print("\nNo solution found inside the time limit.")
        print("Raise time_limit_seconds in config.json and re-run.")
        return 3
    else:
        # A strict solve succeeded: any exceptions file from an earlier
        # rescue run is stale and must not excuse anything.
        if os.path.exists(exc_path):
            os.remove(exc_path)

    elapsed = time.time() - t0

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
    rep = report(s, units, placement, rooms, solver, status, elapsed,
                 exceptions=exceptions)
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
    if exceptions:
        print("\n  ⚠ RESCUE MODE - %d rule exception(s) were needed:" % len(exceptions))
        for e in exceptions:
            print("    %s: teacher %s, %s - %s (x%d)"
                  % (e["rule"], e["teacher_id"], e["day"], e["what"], e["amount"]))
        print("  Full list in out/report.md. Fix the cause and re-run for a")
        print("  fully legal timetable.")
    print("  out/timetable.xml  -> import into aSc TimeTables")
    print("  out/report.md      -> what it could and could not satisfy")
    print("\nNow run:  python solver/verify.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build the timetable with OR-Tools CP-SAT, then write the aSc XML and report.

HARD rules are constraints - the solver physically cannot return a timetable
that breaks one. SOFT rules are penalties - it minimises them and reports what
it could not achieve.

H9 makes the unit of placement the SESSION, not the hour: a curriculum row
with blocks "2+1+1" becomes three sessions (one double, two singles). Each
session occupies numerically consecutive open periods on one day - so it can
never straddle the lunch break - and different sessions of the same subject
land on different days.

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

# Windows consoles default to a legacy codepage that turns Arabic teacher
# names into mojibake. The data is fine - only the console display breaks.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ortools.sat.python import cp_model  # noqa: E402
import data as D  # noqa: E402
import emit_asc  # noqa: E402
import emit_html  # noqa: E402

HERE = D.HERE
OUT = os.path.join(HERE, "out")

# In rescue mode a relaxable hard rule may be broken, but each broken hour
# costs this much - far above anything the soft rules could ever trade it
# against. The solver only pays it when the strict rules admit NO timetable.
RESCUE_WEIGHT = 10000


class Unit:
    """One single lesson-hour, as emitted to aSc and counted by verify."""
    __slots__ = ("uid", "class_id", "subject_id", "teacher_id", "room_type",
                 "idx", "group", "week")

    def __init__(self, uid, class_id, subject_id, teacher_id, room_type, idx,
                 group=0, week=""):
        self.uid = uid
        self.class_id = class_id
        self.subject_id = subject_id
        self.teacher_id = teacher_id
        self.room_type = room_type
        self.idx = idx
        self.group = group
        self.week = week


class Sess:
    """One placeable session: `length` consecutive hours on a single day.

    explicit=True when the curriculum row carries a written block pattern
    ("2+1+1"): then H9 also demands each block on its OWN day. A blank
    pattern leaves the solver free - single hours, soft spreading only.

    group: 0 = the whole class together; 1..N = one half/third of the class
    (T43 - two different groups of one class MAY sit in the same period).
    week: "" = every week; "A"/"B" = that week of the fortnight only (T42 -
    a week-A session and a week-B session MAY share a slot).
    """
    __slots__ = ("sid", "class_id", "subject_id", "teacher_id", "room_type",
                 "length", "hour_offset", "explicit", "group", "week")

    def __init__(self, sid, class_id, subject_id, teacher_id, room_type,
                 length, hour_offset, explicit, group=0, week=""):
        self.sid = sid
        self.class_id = class_id
        self.subject_id = subject_id
        self.teacher_id = teacher_id
        self.room_type = room_type
        self.length = length
        self.hour_offset = hour_offset
        self.explicit = explicit
        self.group = group
        self.week = week


def uid_of(se, t):
    """The per-hour uid. Historical scheme 'class|subject|idx' kept for
    every-week rows; week rows carry the week letter before the index
    ('C1|HIST|A0'), so an A-row and a B-row of one subject never collide."""
    return "%s|%s|%s%d" % (se.class_id, se.subject_id, se.week,
                           se.hour_offset + t)


def expand(s):
    """Turn each curriculum row into its sessions (H9 block pattern).

    groups=N repeats the row's pattern once per group (the teacher teaches
    it N times; each pupil attends once). The hour offsets run on per
    (class, subject, week) across rows AND groups, so uids never collide
    even when a subject has a theory row and a grouped row."""
    sessions = []
    next_off = collections.defaultdict(int)
    for row in s.curriculum:
        rt = s.room_type_for(row)
        explicit = bool(str(row.get("blocks", "")).strip())
        bl, err = D.parse_blocks(row.get("blocks", ""), row["hours"])
        if err or not bl or sum(bl) != row["hours"]:
            # check() reports this in plain language; if we are running
            # anyway (selftest skip_check), fall back to single hours.
            bl, explicit = [1] * row["hours"], False
        week = (row.get("week") or "").strip().upper()
        n_groups = max(1, int(row.get("groups", 1) or 1))
        for g in (range(1, n_groups + 1) if n_groups > 1 else [0]):
            # week=ALT: the groups TAKE TURNS - odd groups week A, even
            # groups week B. The teacher teaches the row's hours EVERY week
            # (to a different half), each pupil gets them every second week.
            # This is the school's real fortnight practice (their official
            # hour counts only add up this way). PROVISIONAL - Majd confirms.
            if week == "ALT":
                gw = "A" if g % 2 == 1 else "B"
            else:
                gw = week
            okey = (row["class_id"], row["subject_id"], gw)
            for k, L in enumerate(bl):
                sid = "%s|%s|%s|g%d|s%d.%d" % (
                    row["class_id"], row["subject_id"], gw, g, k,
                    next_off[okey])
                sessions.append(Sess(sid, row["class_id"], row["subject_id"],
                                     row["teacher_id"], rt, L, next_off[okey],
                                     explicit, g, gw))
                next_off[okey] += L
    return sessions


def hour_units(sessions):
    """Per-hour Units matching the sessions, in the historical uid scheme."""
    units = []
    for se in sessions:
        for t in range(se.length):
            units.append(Unit(uid_of(se, t), se.class_id, se.subject_id,
                              se.teacher_id, se.room_type, se.hour_offset + t,
                              se.group, se.week))
    return units


def placement_from_solver(value_of, sessions, x, starts_of, slots):
    """{per-hour uid: [day, period]} for the solution currently in hand."""
    out = {}
    for se in sessions:
        for j, (d, p0, ixs) in enumerate(starts_of(se)):
            if value_of(x[se.sid, j]):
                for t, i in enumerate(ixs):
                    dd, pp = slots[i]
                    out[uid_of(se, t)] = [dd, pp]
                break
    return out


def weeks_of(ss):
    """The week views these sessions need: [''] when nothing is fortnightly
    (one shared view), else ['A', 'B'] (every-week sessions appear in both)."""
    return ["A", "B"] if any(se.week for se in ss) else [""]


def in_week(se, w):
    """Is this session present in week view w? '' matches everything."""
    return se.week == "" or w == "" or se.week == w


class Progress(cp_model.CpSolverSolutionCallback):
    """Print each improvement, and save it so a crash costs nothing.

    An overnight run that dies at hour 7 to a power cut must not lose the
    work. Every improvement is written to out/solution.json (throttled, so
    hundreds of quick improvements do not thrash the disk), and the very best
    is always saved. Resume later with --continue.
    """

    def __init__(self, t0, sessions=None, x=None, starts_of=None, slots=None,
                 every=15.0, viols=None):
        super().__init__()
        self.t0 = t0
        self.n = 0
        self.sessions = sessions
        self.x = x
        self.starts_of = starts_of
        self.slots = slots
        self.every = every
        self.last_save = 0.0
        self.best = None
        self.last_exc = None
        self.last_soft = None
        # rescue mode only: the exception variables, so every printed version
        # says how many rule exceptions it still carries (Majd asked to watch
        # this number fall live until he stops the run or it turns OPTIMAL)
        self.viols = viols or []

    def save(self, force=False):
        if self.sessions is None:
            return
        now = time.time()
        if not force and now - self.last_save < self.every:
            return
        self.last_save = now
        placement = placement_from_solver(self.Value, self.sessions, self.x,
                                          self.starts_of, self.slots)
        payload = dict(
            penalty=int(self.ObjectiveValue()),
            elapsed_seconds=round(now - self.t0, 1),
            solution_number=self.n,
            placement=placement,
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
        # split the penalty into what Majd actually cares about: hours that
        # break a real rule (H7/H17 exceptions, RESCUE_WEIGHT each) vs soft
        # comfort points (holes, late hours, imbalance...)
        exc_hours = sum(int(self.Value(v)) for _, _, _, v, _ in self.viols)
        exc_cases = sum(1 for _, _, _, v, _ in self.viols if self.Value(v))
        soft = int(self.ObjectiveValue()) - RESCUE_WEIGHT * exc_hours
        # the heartbeat timer thread reads these to describe the best so far
        self.last_exc = exc_hours
        self.last_soft = soft
        if self.n == 1:
            print("   FIRST COMPLETE TIMETABLE:", flush=True)
        print("   %6.1fs  version %-4d exceptions %3d hours (%d teacher-days)"
              " | soft points %s"
              % (el, self.n, exc_hours, exc_cases, soft), flush=True)
        self.save()
        if STOP:
            self.save(force=True)
            print("   Ctrl+C - keeping this solution and stopping.", flush=True)
            self.StopSearch()


def build(s, sessions, rescue=False):
    """Build the CP-SAT model over sessions.

    rescue=False - every hard rule is a real constraint (the normal mode).
    rescue=True  - the RELAXABLE hard rules (H7 day off / training day, H17
                   daily cap) become violations costing RESCUE_WEIGHT per hour,
                   so a livable timetable can exist even when the strict rules
                   are impossible. H1-H6, H8, H9, H15, closed periods and locks
                   are NEVER relaxed. Every violation is reported, never hidden.

    Returns (model, x, starts_of, viols); viols is a list of
    (rule, teacher_id, day, int_var, description) used to report exceptions.
    """
    m = cp_model.CpModel()
    slots = s.cfg.slots                      # [(day, period), ...] open only
    slot_ix = {sl: i for i, sl in enumerate(slots)}
    W = s.cfg.weights
    evening = set(s.cfg.evening)
    days = list(s.cfg.days)
    day_ix = {d: k for k, d in enumerate(days)}
    viols = []
    penalties = []

    # ---- feasible starts per session length (H9 contiguity) --------------
    # A session of length L may start at period p on day d only when
    # p, p+1, ..., p+L-1 are ALL open on d. The lunch break closes 5-6, so
    # no session can straddle it - that part of H9 is free.
    open_by_day = {d: sorted(p for (dd, p) in slots if dd == d) for d in days}
    starts_by_len = {}

    def starts_for_len(L):
        if L not in starts_by_len:
            out = []
            for d in days:
                pset = set(open_by_day[d])
                for p in open_by_day[d]:
                    run = [p + o for o in range(L)]
                    if all(q in pset for q in run):
                        out.append((d, p, [slot_ix[(d, q)] for q in run]))
            starts_by_len[L] = out
        return starts_by_len[L]

    def starts_of(se):
        return starts_for_len(se.length)

    # ---- variable: session se begins at start j --------------------------
    x = {}
    for se in sessions:
        st = starts_of(se)
        for j in range(len(st)):
            x[se.sid, j] = m.NewBoolVar("x_%s_%d" % (se.sid, j))
        # H5 + H9: every session is placed exactly once, as one block
        if st:
            m.AddExactlyOne(x[se.sid, j] for j in range(len(st)))
        else:
            m.Add(sum(()) == 1)   # 0 == 1: no legal start exists at all

    # cover[(sid, slot)] = the x vars that would put this session on slot
    cover = collections.defaultdict(list)
    for se in sessions:
        for j, (d, p0, ixs) in enumerate(starts_of(se)):
            for i in ixs:
                cover[se.sid, i].append(x[se.sid, j])

    # occ[(sid, slot)] = 1 when the session occupies the slot
    occ = {}
    for (sid, i), vs in cover.items():
        b = m.NewBoolVar("o_%s_%d" % (sid, i))
        m.Add(b == sum(vs))
        occ[sid, i] = b

    def occs(group, i):
        """The occupancy vars of these sessions on slot i."""
        return [occ[se.sid, i] for se in group if (se.sid, i) in occ]

    def forbid_slot(se, i):
        for xv in cover.get((se.sid, i), ()):
            m.Add(xv == 0)

    by_class = collections.defaultdict(list)
    by_teacher = collections.defaultdict(list)
    by_type = collections.defaultdict(list)
    by_row = collections.defaultdict(list)     # (class, subject, group)
    by_cs = collections.defaultdict(list)      # (class, subject) - for locks
    for se in sessions:
        by_class[se.class_id].append(se)
        if se.teacher_id:
            by_teacher[se.teacher_id].append(se)
        by_type[se.room_type].append(se)
        by_row[se.class_id, se.subject_id, se.group].append(se)
        by_cs[se.class_id, se.subject_id].append(se)

    S = len(slots)

    # ---- H2: a class is in one place at a time ---------------------------
    # With groups (T43): the class's PARTS clash, not its cards. A whole-class
    # session (group 0) clashes with everything; group g clashes with group g
    # and with the whole class - but two DIFFERENT groups may run in parallel.
    # With weeks (T42): the clash is per week view - a week-A card and a
    # week-B card may share the slot, they never meet.
    for cid, ss in by_class.items():
        gs = sorted({se.group for se in ss if se.group})
        parts = [[se for se in ss if se.group in (0, g)] for g in gs] or [ss]
        for part in parts:
            for w in weeks_of(part):
                act = [se for se in part if in_week(se, w)]
                for i in range(S):
                    vs = occs(act, i)
                    if len(vs) > 1:
                        m.AddAtMostOne(vs)

    # ---- H1: a teacher is in one place at a time (per week view) ---------
    for tid, ss in by_teacher.items():
        for w in weeks_of(ss):
            act = [se for se in ss if in_week(se, w)]
            for i in range(S):
                vs = occs(act, i)
                if len(vs) > 1:
                    m.AddAtMostOne(vs)

    # ---- H3 + H4 + H6: never need more rooms of a type than exist --------
    # Rooms are interchangeable within a type, so counting is enough here.
    # assign_rooms() below turns the counts into concrete room numbers, and
    # verify.py checks the concrete result independently. Counted per week
    # view: an every-week lesson occupies its room in both weeks.
    for rt, ss in by_type.items():
        n_rooms = len(s.rooms_of_type(rt))
        for w in weeks_of(ss):
            act = [se for se in ss if in_week(se, w)]
            for i in range(S):
                vs = occs(act, i)
                if len(vs) > n_rooms:
                    m.Add(sum(vs) <= n_rooms)

    # ---- H9: different blocks of one subject on different days -----------
    # (The contiguity half of H9 is built into the start positions above.)
    # Hard ONLY for rows with a written pattern; a blank pattern gets the
    # soft same-day penalty below instead. Also breaks the symmetry of
    # equal-length sessions in a pattern by ordering their days.
    # Per GROUP copy (each group's own pattern lands on its own days) and per
    # WEEK view (a week-A block and the same subject's week-B block may share
    # a day - the pupils never see them together).
    day_pres_row = {}          # (class, subject, group, weekview) -> {day: b}
    for key, ss in by_row.items():
        for w in weeks_of(ss):
            act = [se for se in ss if in_week(se, w)]
            if len(act) < 2:
                continue
            explicit = any(se.explicit for se in act)
            dps = {}
            day_hours = {}
            for d in days:
                terms = []
                hour_terms = []
                for se in act:
                    for j, (dd, p0, ixs) in enumerate(starts_of(se)):
                        if dd == d:
                            terms.append(x[se.sid, j])
                            hour_terms.append(se.length * x[se.sid, j])
                if not terms:
                    continue
                if explicit:
                    m.Add(sum(terms) <= 1)
                b = m.NewBoolVar("rowday_%s_%s_g%s_%s_%s"
                                 % (key[0], key[1], key[2], w, d))
                m.Add(sum(terms) >= 1).OnlyEnforceIf(b)
                m.Add(sum(terms) == 0).OnlyEnforceIf(b.Not())
                dps[d] = b
                day_hours[d] = hour_terms
            day_pres_row[key + (w,)] = dps
            if not explicit:
                # old S6 half: pile-up on one day is discouraged, not forbidden
                for d, hour_terms in day_hours.items():
                    extra = m.NewIntVar(0, sum(se.length for se in act),
                                        "pile_%s_%s_g%s_%s_%s"
                                        % (key[0], key[1], key[2], w, d))
                    m.Add(extra >= sum(hour_terms) - 1)
                    penalties.append((W.get("same_subject_twice_a_day", 50), extra))
                continue
        # symmetry: equal-length neighbours in one week's pattern take
        # increasing days (never pairs a week-A with a week-B session)
        for a, bse in zip(ss, ss[1:]):
            if a.length != bse.length or a.week != bse.week:
                continue
            da = m.NewIntVar(0, len(days) - 1, "dv_%s" % a.sid)
            db = m.NewIntVar(0, len(days) - 1, "dv_%s" % bse.sid)
            m.Add(da == sum(day_ix[dd] * x[a.sid, j]
                            for j, (dd, p0, ixs) in enumerate(starts_of(a))))
            m.Add(db == sum(day_ix[dd] * x[bse.sid, j]
                            for j, (dd, p0, ixs) in enumerate(starts_of(bse))))
            if a.explicit and bse.explicit:
                m.Add(da < db)

    # ---- S22 / M-SN4: the group copies of one row belong together --------
    # The ministry's lab rule: the two groups' sessions run back to back.
    # Soft: penalise every day where one group's subject sits and the other
    # group's does not (same week view). Same-day + the no-holes rules (S1)
    # then pull them into adjacent periods naturally.
    grouped_cs = collections.defaultdict(int)
    for (cid, sid_, g) in by_row:
        if g:
            grouped_cs[cid, sid_] = max(grouped_cs[cid, sid_], g)
    for (cid, sid_), maxg in grouped_cs.items():
        ss = by_cs[cid, sid_]
        for w in weeks_of(ss):
            for ga, gb in zip(range(1, maxg), range(2, maxg + 1)):
                for d in days:
                    a_terms = [x[se.sid, j]
                               for se in by_row.get((cid, sid_, ga), [])
                               if in_week(se, w)
                               for j, (dd, _p, _x) in enumerate(starts_of(se))
                               if dd == d]
                    b_terms = [x[se.sid, j]
                               for se in by_row.get((cid, sid_, gb), [])
                               if in_week(se, w)
                               for j, (dd, _p, _x) in enumerate(starts_of(se))
                               if dd == d]
                    if not a_terms or not b_terms:
                        continue
                    diff = m.NewIntVar(0, max(len(a_terms), len(b_terms)),
                                       "gsync_%s_%s_%d_%s_%s" % (cid, sid_, gb, w, d))
                    m.Add(diff >= sum(a_terms) - sum(b_terms))
                    m.Add(diff >= sum(b_terms) - sum(a_terms))
                    penalties.append((W.get("tp_groups_same_day", 45), diff))

    # ---- H7: the teacher's day off AND training day are completely empty --
    # (circular II.1: respect the pedagogical training days)
    # Relaxable in rescue mode: teaching on a free day is livable in extremis;
    # it is reported as an exception, never silently.
    for tid, ss in by_teacher.items():
        t = s.teachers.get(tid, {})
        for kind in ("day_off", "training_day"):
            off = t.get(kind, "")
            if not off or off == "(none)":
                continue
            ix = [i for i, (d, p) in enumerate(slots) if d == off]
            if not ix:
                continue
            if not rescue:
                for se in ss:
                    for i in ix:
                        forbid_slot(se, i)
            else:
                terms = [v for i in ix for v in occs(ss, i)]
                v = m.NewIntVar(0, max(1, len(terms)), "vH7_%s_%s" % (tid, kind))
                m.Add(v == sum(terms))
                penalties.append((RESCUE_WEIGHT, v))
                viols.append(("H7", tid, off, v,
                              "teaches on their %s" % kind.replace("_", " ")))

    # ---- H7-flex: a BLANK day_off means the solver CHOOSES the day off ----
    # Majd 2026-08-24: "day off isnt just random, u prechoose it flexible, u
    # can change it along the way unless in data its fixed - and in data let
    # me say when its fixed and which day". So: a written day above is FIXED;
    # "(none)" means no day off at all; BLANK means the teacher still gets
    # exactly one fully free day but WHICH day is the solver's decision, free
    # to differ between runs. Candidate days already obey H18 (never adjacent
    # to the training day, Sunday wrap included).
    day_off_choice = {}
    day_list = list(s.cfg.days)
    for tid, ss in by_teacher.items():
        t = s.teachers.get(tid, {})
        if (t.get("day_off") or "").strip():
            continue          # fixed day, or explicit "(none)"
        tr = t.get("training_day", "")
        cands = []
        for d in day_list:
            if d == tr:
                continue
            if tr in day_list:
                gap = abs(day_list.index(d) - day_list.index(tr))
                if gap == 1 or gap == len(day_list) - 1:
                    continue  # H18, Sunday wrap included
            cands.append(d)
        if not cands:
            continue
        offs = {d: m.NewBoolVar("off_%s_%s" % (tid, d)) for d in cands}
        m.Add(sum(offs.values()) == 1)
        day_off_choice[tid] = offs
        for d in cands:
            terms = [v for i, (dd, p) in enumerate(slots) if dd == d
                     for v in occs(ss, i)]
            if not terms:
                continue
            if not rescue:
                m.Add(sum(terms) == 0).OnlyEnforceIf(offs[d])
            else:
                v = m.NewIntVar(0, len(terms), "vH7f_%s_%s" % (tid, d))
                m.Add(v == sum(terms)).OnlyEnforceIf(offs[d])
                m.Add(v == 0).OnlyEnforceIf(offs[d].Not())
                penalties.append((RESCUE_WEIGHT, v))
                viols.append(("H7", tid, d, v,
                              "teaches on their chosen day off"))

    # ---- H17: a teacher never teaches more than 6 hours in one day --------
    # Circular 51/2018 II.2, repeated by the inspectorate text. Relaxable in
    # rescue mode (a 7-hour day is livable in extremis; a clash is not).
    for tid, ss in by_teacher.items():
        for w in weeks_of(ss):
            act = [se for se in ss if in_week(se, w)]
            for d in days:
                ix = [i for i, (dd, p) in enumerate(slots) if dd == d]
                if len(ix) <= 6:
                    continue
                terms = [v for i in ix for v in occs(act, i)]
                if len(terms) <= 6:
                    continue
                if not rescue:
                    m.Add(sum(terms) <= 6)
                else:
                    over = m.NewIntVar(0, len(ix) - 6,
                                       "vH17_%s_%s_%s" % (tid, d, w))
                    m.Add(sum(terms) <= 6 + over)
                    penalties.append((RESCUE_WEIGHT, over))
                    viols.append(("H17", tid, d, over,
                                  "hours beyond 6 in one day"
                                  + (" (week %s)" % w if w else "")))

    # ---- H8: declared unavailable slots ----------------------------------
    for un in s.unavailable:
        if un["hard"] != "yes":
            continue
        ss = by_teacher.get(un["teacher_id"], [])
        for i, (d, p) in enumerate(slots):
            if un["day"] not in ("*", d):
                continue
            if un["period"] != "*" and str(p) != str(un["period"]):
                continue
            for se in ss:
                forbid_slot(se, i)

    # ---- H15: daylight-only subjects never run past latest_period --------
    # Sport has no stadium lighting, so it may not sit after 16:00 (period 8
    # in a 10-period day starting 08:00). Expressed generally so any subject
    # can carry a time limit.
    for se in sessions:
        lp = s.subjects.get(se.subject_id, {}).get("latest_period") or 0
        if not lp:
            continue
        for i, (d, p) in enumerate(slots):
            if p > lp:
                forbid_slot(se, i)

    # ---- H19: 24 hours between sessions of a gap24 subject ----------------
    # Circular III.2 on PE: "always respect the 24-hour separation between
    # the two PE sessions". On consecutive days that means the later session
    # must not start EARLIER in the day than the first one did. Non-adjacent
    # days are always fine; H9 already keeps them off the same day.
    for key, ss in by_row.items():
        if len(ss) < 2:
            continue
        if s.subjects.get(key[1], {}).get("gap24") != "yes":
            continue
        if not ss[0].explicit:
            continue   # a written pattern is required to reason about sessions
        for a in ss:
            for b in ss:
                if a.sid >= b.sid:
                    continue
                if a.week and b.week and a.week != b.week:
                    continue   # different weeks never meet - no 24h issue
                for ja, (da_, pa, _xa) in enumerate(starts_of(a)):
                    for jb, (db_, pb, _xb) in enumerate(starts_of(b)):
                        ka, kb = day_ix[da_], day_ix[db_]
                        if abs(ka - kb) != 1:
                            continue
                        early, late = (pa, pb) if ka < kb else (pb, pa)
                        if late < early:
                            m.AddBoolOr([x[a.sid, ja].Not(), x[b.sid, jb].Not()])

    # ---- Locked sheet: the user's pinned placements are immovable --------
    # >= 1 so a grouped subject may put EITHER group there (and with weeks,
    # either week) - the pin says "this subject sits here", not which half.
    for lk in s.locked:
        i = slot_ix.get((lk["day"], lk["period"]))
        if i is None:
            continue
        vs = occs(by_cs.get((lk["class_id"], lk["subject_id"]), []), i)
        if vs:
            m.Add(sum(vs) >= 1)
        else:
            m.Add(sum(()) == 1)   # pinned to a slot nothing can reach

    # ---- presence grid, reused by several soft rules ----------------------
    def presence(group, key, w=""):
        """pres[(day, period)] = 1 if this teacher/class-part is busy then,
        in week view w ('' = the single shared view)."""
        pres = {}
        act = [se for se in group if in_week(se, w)]
        for i, (d, p) in enumerate(slots):
            b = m.NewBoolVar("pres_%s_%s_%d" % (key, d, p))
            m.Add(b == sum(occs(act, i)))
            pres[d, p] = b
        return pres

    def add_gap_penalty(pres, key, weight, also_one_hour=False, also_day_count=False):
        """S1/S7 no holes, S2 no 1-hour days, S8-compact fewest days.

        Returns {day: here-bool} so S21 (shared transport) can compare two
        teachers' presence day by day without rebuilding it."""
        days_here = {}
        for d in s.cfg.days:
            ps = [p for (dd, p) in slots if dd == d]
            if len(ps) < 2:
                continue
            lo, hi = min(ps), max(ps)
            taught = sum(pres[d, p] for p in ps)

            here = m.NewBoolVar("here_%s_%s" % (key, d))
            m.Add(taught >= 1).OnlyEnforceIf(here)
            m.Add(taught == 0).OnlyEnforceIf(here.Not())
            days_here[d] = here

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
        return days_here

    # S1 teacher holes, S2 one-hour days. S8 is the MINISTRY version
    # (circular II.2: hours balanced across working days): by default a
    # teacher's overloaded days are penalised, which spreads the week.
    # compact=yes in the Teachers sheet keeps the old packed week instead -
    # the exception Majd grants to teachers with long journeys.
    teacher_days = {}
    for tid, ss in by_teacher.items():
        compact = s.teachers.get(tid, {}).get("compact", "") == "yes"
        wks = weeks_of(ss)
        days_by_week = []
        for w in wks:
            pres = presence(ss, "T%s%s" % (tid, w), w)
            days_by_week.append(
                add_gap_penalty(pres, "T%s%s" % (tid, w), W["teacher_gap"],
                                also_one_hour=True, also_day_count=compact))
            if not compact:
                # S8 (ministry): every taught hour beyond 4 on one day is a
                # sign of cramming; H17 caps the day at 6 outright.
                for d in s.cfg.days:
                    ps = [p for (dd, p) in slots if dd == d]
                    if len(ps) <= 4:
                        continue
                    over = m.NewIntVar(0, len(ps) - 4,
                                       "crowd_%s_%s_%s" % (tid, d, w))
                    m.Add(over >= sum(pres[d, p] for p in ps) - 4)
                    penalties.append((W.get("overloaded_day", 40), over))
        if len(days_by_week) == 1:
            teacher_days[tid] = days_by_week[0]
        else:
            # S21 needs ONE here/not-here per day: present = comes in in
            # EITHER week (they still travel that day, every second week)
            merged = {}
            for d in s.cfg.days:
                vs = [dw[d] for dw in days_by_week if d in dw]
                if not vs:
                    continue
                b = m.NewBoolVar("hereAB_%s_%s" % (tid, d))
                m.AddMaxEquality(b, vs)
                merged[d] = b
            teacher_days[tid] = merged

        # S5 (circular II.4): alternation - nobody teaches only mornings or
        # only evenings. Penalise |morning - evening| beyond a slack of 2.
        m_ix = [i for i, (d, p) in enumerate(slots) if p not in evening]
        e_ix = [i for i, (d, p) in enumerate(slots) if p in evening]
        if m_ix and e_ix:
            mh = sum(v for i in m_ix for v in occs(ss, i))
            eh = sum(v for i in e_ix for v in occs(ss, i))
            imb = m.NewIntVar(0, S, "imb_%s" % tid)
            m.Add(imb >= mh - eh - 2)
            m.Add(imb >= eh - mh - 2)
            penalties.append((W.get("morning_evening_imbalance", 60), imb))

    # ---- S21: shared transport - paired teachers come in on the same days.
    # travels_with in the Teachers sheet names the partner (one side is
    # enough, the pair is symmetric). Soft: each day where one is present
    # and the other is not costs travel_pair points. Majd asked whether this
    # is possible - it is, and this is the whole of it.
    seen_pairs = set()
    for tid, t in s.teachers.items():
        other = (t.get("travels_with") or "").strip()
        if not other:
            continue
        pair = tuple(sorted((tid, other)))
        if pair in seen_pairs or pair[0] not in teacher_days \
                or pair[1] not in teacher_days:
            continue
        seen_pairs.add(pair)
        for d in s.cfg.days:
            a = teacher_days[pair[0]].get(d)
            b = teacher_days[pair[1]].get(d)
            if a is None or b is None:
                continue
            diff = m.NewBoolVar("pair_%s_%s_%s" % (pair[0], pair[1], d))
            m.Add(a != b).OnlyEnforceIf(diff)
            m.Add(a == b).OnlyEnforceIf(diff.Not())
            penalties.append((W.get("travel_pair", 70), diff))

    # S7 pupils get no holes either - seen from each PART of the class (a
    # pupil in group 1 lives through the whole-class hours plus group 1's),
    # and per week view when the class has fortnightly rows.
    def class_parts(ss):
        gs = sorted({se.group for se in ss if se.group})
        if not gs:
            return {0: ss}
        return {g: [se for se in ss if se.group in (0, g)] for g in gs}

    halves = {"am": [p for p in range(1, s.cfg.periods_per_day + 1)
                     if p not in evening],
              "pm": sorted(evening)}
    for cid, ss in by_class.items():
        for g, part in class_parts(ss).items():
            for w in weeks_of(part):
                key = "C%s.g%s%s" % (cid, g, w)
                pres = presence(part, key, w)
                add_gap_penalty(pres, key, W["class_gap"])
                # T26/T27 (circular I.2): a PUPIL's day beyond 6 hours, or a
                # half-day beyond 4, is heavily penalised. Counted per group
                # view - group machinery made pupil-hours countable at last.
                # Majd 2026-08-25: the 10-min table was "too full" - this is
                # the rule that fights exactly that.
                for d in s.cfg.days:
                    dps = [p for (dd, p) in slots if dd == d]
                    if len(dps) > 6:
                        over6 = m.NewIntVar(0, len(dps), "pup6_%s_%s" % (key, d))
                        m.Add(over6 >= sum(pres[d, p] for p in dps) - 6)
                        penalties.append((W.get("pupil_day_over6", 120), over6))
                    for half, hp in halves.items():
                        hps = [p for p in dps if p in hp]
                        if len(hps) > 4:
                            o4 = m.NewIntVar(0, len(hps),
                                             "pup4_%s_%s_%s" % (key, d, half))
                            m.Add(o4 >= sum(pres[d, p] for p in hps) - 4)
                            penalties.append((W.get("pupil_half_over4", 100), o4))

    # ---- S15: a class never comes in for a single lone hour ---------------
    # Circular I.2: minimum 2 hours in any morning or evening - for pupils
    # too. The circular exempts PE and optional subjects (minmax_exempt=yes
    # in the Subjects sheet): a lone PE hour is fine.
    for cid, ss in by_class.items():
        for g, part in class_parts(ss).items():
            for w in weeks_of(part):
                act = [se for se in part if in_week(se, w)]
                exempt = [se for se in act
                          if s.subjects.get(se.subject_id, {}).get("minmax_exempt") == "yes"]
                counted = [se for se in act if se not in exempt]
                tag = "%s.g%s%s" % (cid, g, w)
                for d in s.cfg.days:
                    for half, ps in halves.items():
                        ix = [i for i, (dd, p) in enumerate(slots)
                              if dd == d and p in ps]
                        if len(ix) < 2:
                            continue
                        tot = sum(v for i in ix for v in occs(act, i))
                        cnt = sum(v for i in ix for v in occs(counted, i))
                        solo = m.NewBoolVar("csolo_%s_%s_%s" % (tag, d, half))
                        b_tot1 = m.NewBoolVar("ctot1_%s_%s_%s" % (tag, d, half))
                        m.Add(tot == 1).OnlyEnforceIf(b_tot1)
                        m.Add(tot != 1).OnlyEnforceIf(b_tot1.Not())
                        b_cnt1 = m.NewBoolVar("ccnt1_%s_%s_%s" % (tag, d, half))
                        m.Add(cnt >= 1).OnlyEnforceIf(b_cnt1)
                        m.Add(cnt == 0).OnlyEnforceIf(b_cnt1.Not())
                        m.AddBoolAnd([b_tot1, b_cnt1]).OnlyEnforceIf(solo)
                        m.AddBoolOr([b_tot1.Not(), b_cnt1.Not()]).OnlyEnforceIf(solo.Not())
                        penalties.append((W.get("class_one_hour_session", 85), solo))

    # ---- S3: hard subjects belong in the morning -------------------------
    hard_sess = [se for se in sessions
                 if s.subjects.get(se.subject_id, {}).get("difficulty") == "hard"]
    ev_ix = [i for i, (d, p) in enumerate(slots) if p in evening]
    if hard_sess and ev_ix:
        terms = [v for i in ev_ix for v in occs(hard_sess, i)]
        if terms:
            n_ev = m.NewIntVar(0, len(terms), "hard_in_evening")
            m.Add(n_ev == sum(terms))
            penalties.append((W["hard_subject_evening"], n_ev))

    # ---- S12: daylight subjects PREFER the morning -----------------------
    # "morning and max 14h to 16h" - the late window is a fallback, not the
    # target. Penalise every daylight-limited hour that lands outside morning.
    daylight = [se for se in sessions
                if (s.subjects.get(se.subject_id, {}).get("latest_period") or 0)]
    morning = set(s.cfg.morning)
    late_ix = [i for i, (d, p) in enumerate(slots) if p not in morning]
    if daylight and late_ix:
        terms = [v for i in late_ix for v in occs(daylight, i)]
        if terms:
            n_late = m.NewIntVar(0, len(terms), "daylight_outside_morning")
            m.Add(n_late == sum(terms))
            penalties.append((W.get("daylight_not_morning", 45), n_late))

    # ---- S6: sessions of one subject avoid consecutive days ---------------
    # Circular III.2: subjects taught 2 h/week must not fall on consecutive
    # days; the inspectorate repeats it for English, History-Geo and Arabic.
    # With H9 keeping every block on its own day, "spread" now means: no two
    # sessions of one subject on neighbouring days.
    for key, dps in day_pres_row.items():
        for da, db in zip(days, days[1:]):
            if da in dps and db in dps:
                both = m.NewIntVar(0, 1, "adj_%s_%s_%s" % (key[0], key[1], da))
                m.Add(both >= dps[da] + dps[db] - 1)
                penalties.append((W.get("same_subject_adjacent_days", 50), both))

    # ---- S18: never subject B straight after subject A --------------------
    # The inspectorate, for both 4th-year streams: never Philosophy in the
    # period right after PE. Generic: any subject may carry not_after=<ids>.
    for cid, ss in by_class.items():
        by_subj = collections.defaultdict(list)
        for se in ss:
            by_subj[se.subject_id].append(se)
        for sid_b, ses_b in by_subj.items():
            for sid_a in s.subjects.get(sid_b, {}).get("not_after", []):
                ses_a = by_subj.get(sid_a)
                if not ses_a:
                    continue
                for i, (d, p) in enumerate(slots):
                    i2 = slot_ix.get((d, p + 1))
                    if i2 is None:
                        continue
    # (grouped subjects can put TWO cards in one slot - the aggregation vars
    #  below must be wide enough for that, or the model turns infeasible)
                    va = occs(ses_a, i)
                    vb = occs(ses_b, i2)
                    if not va or not vb:
                        continue
                    both = m.NewIntVar(0, len(va) + len(vb),
                                       "na_%s_%s_%s_%s_%d" % (cid, sid_a, sid_b, d, p))
                    m.Add(both >= sum(va) + sum(vb) - 1)
                    penalties.append((W.get("not_after", 60), both))

    # ---- S4 / M-P6: no two same-nature subjects back to back --------------
    # Inspectorate pupil-rule 8: avoid consecutive subjects of the same
    # nature (literary / scientific / social). A DOUBLE of one subject is a
    # prescribed pattern and stays allowed - only a DIFFERENT same-nature
    # subject in the next period is penalised. Inert until the Subjects
    # sheet carries the `nature` column.
    for cid, ss in by_class.items():
        by_nat = collections.defaultdict(lambda: collections.defaultdict(list))
        for se in ss:
            nat = s.subjects.get(se.subject_id, {}).get("nature", "")
            if nat:
                by_nat[nat][se.subject_id].append(se)
        for nat, subj_map in by_nat.items():
            if len(subj_map) < 2:
                continue
            for i, (d, p) in enumerate(slots):
                i2 = slot_ix.get((d, p + 1))
                if i2 is None:
                    continue
                for sid_b, ses_b in subj_map.items():
                    vb = occs(ses_b, i2)
                    if not vb:
                        continue
                    others = [se for osid, oss in subj_map.items()
                              if osid != sid_b for se in oss]
                    va = occs(others, i)
                    if not va:
                        continue
                    pair = m.NewIntVar(0, len(va) + len(vb),
                                       "nat_%s_%s_%s_%d" % (cid, nat, sid_b, i))
                    m.Add(pair >= sum(va) + sum(vb) - 1)
                    penalties.append((W.get("same_nature_adjacent", 80), pair))

    # ---- S19: core subjects get three quarters of their hours in the ------
    # morning (circular III.2). Rows flagged core=yes in the Curriculum
    # sheet may sit in the evening for at most a quarter of their hours.
    row_core = {(c["class_id"], c["subject_id"]): c.get("core", "") == "yes"
                for c in s.curriculum}
    ev_ix_all = [i for i, (d, p) in enumerate(slots) if p in evening]
    for key, ss in by_row.items():
        if not row_core.get(key[:2]):
            continue
        hours = sum(se.length for se in ss)
        allowed_ev = hours // 4
        terms = [v for i in ev_ix_all for v in occs(ss, i)]
        if not terms:
            continue
        over = m.NewIntVar(0, hours, "core_ev_%s_%s_g%s" % key)
        m.Add(over >= sum(terms) - allowed_ev)
        penalties.append((W.get("core_morning", 65), over))

    # ---- S10: last-period fairness for teachers ---------------------------
    # Nobody is stuck with the final period every single day: beyond two
    # last-period days a week, each further one is penalised.
    last_p_num = s.cfg.periods_per_day
    last_ix_all = [i for i, (d, p) in enumerate(slots) if p == last_p_num]
    for tid, ss in by_teacher.items():
        terms = [v for i in last_ix_all for v in occs(ss, i)]
        if len(terms) <= 2:
            continue
        over = m.NewIntVar(0, len(terms), "lastfair_%s" % tid)
        m.Add(over >= sum(terms) - 2)
        penalties.append((W.get("last_period_fairness", 35), over))

    # ---- S16: subject-specific late-hour avoidance ------------------------
    # Soft cousin of H15. Ministry: Maths avoids the evening and never after
    # 16:00 if it must (M-MA3); Physics avoids 17:00-18:00 (M-PH5).
    for se in sessions:
        aa = s.subjects.get(se.subject_id, {}).get("avoid_after") or 0
        if not aa:
            continue
        for i, (d, p) in enumerate(slots):
            if p > aa and (se.sid, i) in occ:
                penalties.append((W.get("late_subject", 50), occ[se.sid, i]))

    # ---- S14: the last period of the day is a slot of last resort ---------
    # Majd: "try to avoid 17 to 18 as much as possible its late". Ministry
    # backing: the inspectorate tells Physics the same (M-PH5). Applies to
    # everyone; soft, because banning it would cost too much capacity.
    last_p = s.cfg.periods_per_day
    for se in sessions:
        for i, (d, p) in enumerate(slots):
            if p == last_p and (se.sid, i) in occ:
                penalties.append((W.get("last_period", 55), occ[se.sid, i]))

    # ---- S13: no Friday evening for bac classes (local preference) --------
    # ---- S17: bac classes get a free afternoon Mon-Thu (circular I.6) -----
    first_four = days[:4]
    for cid, ss in by_class.items():
        if s.classes.get(cid, {}).get("is_bac", "") != "yes":
            continue
        fri_ev = [i for i, (d, p) in enumerate(slots)
                  if d == "Fri" and p in evening]
        for i in fri_ev:
            for v in occs(ss, i):
                penalties.append((W.get("bac_friday_evening", 30), v))
        # S17: at least one of the first four days' evenings entirely free
        free_days = []
        for d in first_four:
            ix = [i for i, (dd, p) in enumerate(slots) if dd == d and p in evening]
            if not ix:
                continue
            terms = [v for i in ix for v in occs(ss, i)]
            b = m.NewBoolVar("bacfree_%s_%s" % (cid, d))
            m.Add(sum(terms) == 0).OnlyEnforceIf(b)
            m.Add(sum(terms) >= 1).OnlyEnforceIf(b.Not())
            free_days.append(b)
        if free_days:
            none_free = m.NewBoolVar("bacnofree_%s" % cid)
            m.AddBoolAnd([b.Not() for b in free_days]).OnlyEnforceIf(none_free)
            m.AddBoolOr(free_days).OnlyEnforceIf(none_free.Not())
            penalties.append((W.get("bac_no_free_afternoon", 70), none_free))

    m.Minimize(sum(w * v for w, v in penalties))
    # main() reads the flexible day-off choice from here after solving, to
    # report which day each teacher was given. Kept as an attribute so the
    # (m, x, starts_of, viols) signature the selftests rely on stays stable.
    m.day_off_choice = day_off_choice
    return m, x, starts_of, viols


def assign_rooms(s, sessions, placement):
    """Turn 'a room of type X' into a concrete room id, per SESSION.

    A double hour should not change room halfway through, so rooms are
    chosen per session, kept identical across its hours where possible.
    The model guaranteed enough rooms of each type exist in every slot; if
    the same-room-for-the-whole-session preference cannot be met, the
    session falls back to per-hour assignment, which always succeeds.
    """
    def hour_uids(se):
        return [uid_of(se, t) for t in range(se.length)]

    rooms_by_type = collections.defaultdict(list)
    for r in s.rooms.values():
        rooms_by_type[r["type"]].append(r["id"])
    for k in rooms_by_type:
        rooms_by_type[k].sort()

    # (day, period) -> {room id: set of weeks occupied}. An every-week lesson
    # occupies {'A','B'}; a fortnight lesson only its own week, so a week-A
    # and a week-B lesson can share one room in one period.
    taken = collections.defaultdict(dict)
    out = {}

    def wset(se):
        return {"A", "B"} if not se.week else {se.week}

    def slot_of(uid):
        d, p = placement[uid]
        return (d, p)

    def room_free(se, rid, sl):
        return not (taken[sl].get(rid, set()) & wset(se))

    def take(se, rid, sl):
        taken[sl].setdefault(rid, set()).update(wset(se))

    def try_room(se, rid):
        us = hour_uids(se)
        if any(not room_free(se, rid, slot_of(u)) for u in us):
            return False
        for u in us:
            out[u] = rid
            take(se, rid, slot_of(u))
        return True

    ordered = sorted(sessions, key=lambda se: -se.length)
    # first pass: home rooms, longest sessions first
    for se in ordered:
        home = s.classes.get(se.class_id, {}).get("home_room", "")
        if (home and home in s.rooms
                and s.rooms[home]["type"] == se.room_type):
            try_room(se, home)
    # second pass: any room of the right type, same room across the session
    for se in ordered:
        if hour_uids(se)[0] in out:
            continue
        for rid in rooms_by_type.get(se.room_type, []):
            if try_room(se, rid):
                break
        else:
            # fall back to per-hour rooms; H3/H6 still hold
            for u in hour_uids(se):
                for rid in rooms_by_type.get(se.room_type, []):
                    if room_free(se, rid, slot_of(u)):
                        out[u] = rid
                        take(se, rid, slot_of(u))
                        break
                else:
                    out[u] = ""  # should never happen; verify.py will catch it
    return out


def report(s, units, placement, rooms, solver, status, elapsed, exceptions=None,
           day_offs=None):
    """Plain-language explanation of what was and was not achieved."""
    slots = s.cfg.slots
    L = []
    A = L.append
    A("# Timetable report")
    A("")
    A("Generated in %.1f seconds. Solver said: **%s**." % (elapsed, solver.StatusName(status)))
    if day_offs:
        A("")
        A("## Day offs chosen by the solver")
        A("")
        A("A blank `day_off` in the Teachers sheet lets the solver pick the day")
        A("(Majd's rule: flexible unless fixed in the data). This run chose:")
        A("")
        A("| day | teachers |")
        A("|---|---|")
        by_day = {}
        for tid, d in sorted(day_offs.items()):
            by_day.setdefault(d, []).append(
                s.teachers.get(tid, {}).get("name", tid))
        for d in s.cfg.days:
            if d in by_day:
                A("| %s | %s |" % (d, "، ".join(by_day[d])))
        A("")
        A("A DIFFERENT run may choose differently - to freeze a teacher's day,")
        A("write it in the `day_off` column and it becomes a hard rule.")
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
    A("- %d lesson-hours placed" % len(units))
    A("- %d teachers, %d classes, %d rooms, %d open periods per week"
      % (len(s.teachers), len(s.classes), len(s.rooms), len(slots)))
    A("- total penalty score: **%d** (lower is better; 0 is perfect)"
      % int(solver.ObjectiveValue()))
    A("")

    # --- teacher-by-teacher truth ---
    t_slots = collections.defaultdict(set)
    for u in units:
        if u.teacher_id:
            t_slots[u.teacher_id].add(tuple(placement[u.uid]))

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

    A("## H9 - block patterns")
    A("")
    by_day_subj = collections.defaultdict(list)
    for u in units:
        d, p = placement[u.uid]
        by_day_subj[u.class_id, u.subject_id, d].append(p)
    n_multi = sum(1 for ps in by_day_subj.values() if len(ps) > 1)
    A("%d multi-hour blocks were placed as consecutive runs on a single day "
      "(checked independently by verify.py)." % n_multi)
    A("")

    A("## S7 - holes in a pupil's day")
    c_slots = collections.defaultdict(set)
    for u in units:
        c_slots[u.class_id].add(tuple(placement[u.uid]))
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
    use = collections.Counter(tuple(placement[u.uid]) for u in units)
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


def n_workers():
    """How many parallel search workers to run.

    Default: half the CPUs, at most 4. On this 8 GB machine a full 8-worker
    search on the real school ran out of memory and died with a segfault -
    fewer workers search a little slower but never crash. Override with
    --workers=N when the machine is free.
    """
    chosen = None
    for a in sys.argv[1:]:
        if a.startswith("--workers="):
            chosen = max(1, int(a.split("=", 1)[1]))   # last one wins,
    if chosen is not None:                             # so run.bat's default
        return chosen                                  # can be overridden
    return max(1, min(4, (os.cpu_count() or 4) // 2))


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

    sessions = expand(s)
    n_hours = sum(se.length for se in sessions)
    n_blocks = sum(1 for se in sessions if se.length > 1)
    print("\nPlacing %d lesson-hours (%d sessions, %d multi-hour blocks) into "
          "%d open periods across %d rooms."
          % (n_hours, len(sessions), n_blocks, len(s.cfg.slots), len(s.rooms)))
    print("Building the model...", flush=True)
    # --rescue: skip the strict attempt and allow the livable exceptions from
    # the start. Honest shortcut for the real school, where the strict model
    # is INFEASIBLE but too big to prove so within the limit: exceptions still
    # cost 10,000 per hour, so a zero-exception timetable always wins when one
    # exists - forcing rescue can never invent exceptions.
    rescue_now = "--rescue" in sys.argv
    if rescue_now:
        print("--rescue: strict attempt skipped, livable exceptions allowed "
              "(each costs 10,000 - the solver still prefers none).")
    m, x, starts_of, viols = build(s, sessions, rescue=rescue_now)

    def on_sigint(signum, frame):
        global STOP
        STOP = True
        print("   Stopping after the next solution...", flush=True)

    signal.signal(signal.SIGINT, on_sigint)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(cfg.time_limit)
    solver.parameters.num_search_workers = n_workers()
    solver.parameters.log_search_progress = False

    # Honest time guidance, MEASURED on this school (2026-08-25 runs), not
    # promised: CP-SAT cannot predict when it will finish, but experience
    # with this size (about 1300 hours, 40 classes) says roughly this.
    # Majd asked for it after the 10-minute table came out rough.
    print("""
  How long for a good table? (measured on this school, not a promise)
     10 min   -> a first DRAFT. Rough: comfort rules still losing.
     1-2 h    -> usable: most comfort rules settle down.
     4-8 h    -> good: run it during the evening.
     overnight-> best this data allows. Ctrl+C always keeps the best.
  The real fix for quality is missing DATA (real days off, training
  days, sizes) - time alone cannot beat missing data.""")
    print("Solving (limit %ds = %dmin, Ctrl+C keeps the best found so far):"
          % (cfg.time_limit, cfg.time_limit // 60), flush=True)

    # heartbeat: one line per minute, even when no new version appears, so
    # the terminal always shows a live TIMER of elapsed / limit
    import threading
    hb_stop = threading.Event()

    cb_holder = {}

    def heartbeat():
        while not hb_stop.wait(60.0):
            cb_ref = cb_holder.get("cb")
            el = time.time() - t0
            if cb_ref is not None and cb_ref.last_exc is not None:
                best = ("best so far: %d exception-hours, soft %d"
                        % (cb_ref.last_exc, cb_ref.last_soft))
            else:
                best = "no complete timetable yet - still building one"
            print("   TIMER %2d:%02d / %d:00 min - %s"
                  % (el // 60, el % 60, cfg.time_limit // 60, best),
                  flush=True)

    threading.Thread(target=heartbeat, daemon=True).start()

    # --continue: start from the last saved solution instead of from nothing.
    # AddHint is only a suggestion - it never overrides a constraint, so a
    # stale hint can slow the search but can never make the result wrong.
    if "--continue" in sys.argv:
        prev = os.path.join(OUT, "solution.json")
        if os.path.exists(prev):
            with open(prev, encoding="utf-8") as f:
                saved = json.load(f)
            place = saved.get("placement", {})
            hinted = 0
            for se in sessions:
                uid0 = uid_of(se, 0)
                got = place.get(uid0)
                if not got:
                    continue
                for j, (d, p0, ixs) in enumerate(starts_of(se)):
                    if d == got[0] and p0 == got[1]:
                        m.AddHint(x[se.sid, j], 1)
                        hinted += 1
                        break
            print("Resuming from out/solution.json - penalty %s, %d of %d "
                  "sessions hinted." % (saved.get("penalty"), hinted, len(sessions)))
        else:
            print("--continue given but no out/solution.json yet; starting fresh.")

    cb = Progress(t0, sessions=sessions, x=x, starts_of=starts_of, slots=s.cfg.slots, viols=viols)
    cb_holder["cb"] = cb
    status = solver.Solve(m, cb)
    cb.save(force=True)

    name = solver.StatusName(status)
    exceptions = []
    exc_path = os.path.join(OUT, "exceptions.json")

    if name in ("INFEASIBLE", "MODEL_INVALID") and rescue_now:
        print("\nNO TIMETABLE EXISTS even with the livable exceptions.")
        print("Something structural is impossible (a clash, room shortage,")
        print("or contradictory data). Check the data, then re-run.")
        return 2

    if name in ("INFEASIBLE", "MODEL_INVALID"):
        # ---- RESCUE MODE ------------------------------------------------
        # The strict rules admit no timetable at all. Rather than stop dead,
        # retry with the RELAXABLE rules (H7 day off / training day, H17
        # 6h/day cap) allowed to break at enormous cost. Clashes, the lunch
        # break, H8 declarations, daylight limits, H9 blocks and locks stay
        # absolute. Every exception taken is listed in the report.
        rescue_now = True
        print("\nNo timetable exists under the strict rules.")
        print("RESCUE MODE: retrying with livable exceptions allowed")
        print("(day off / training day / 6h-day cap only - never clashes,")
        print("never the lunch break). Every exception will be reported.")
        m, x, starts_of, viols = build(s, sessions, rescue=True)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(cfg.time_limit)
        solver.parameters.num_search_workers = n_workers()
        cb = Progress(t0, sessions=sessions, x=x, starts_of=starts_of, slots=s.cfg.slots, viols=viols)
        cb_holder["cb"] = cb
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
    elif rescue_now:
        # Forced --rescue solve succeeded: read the exception vars directly.
        for rule, tid, day, var, desc in viols:
            v = solver.Value(var)
            if v:
                exceptions.append(dict(rule=rule, teacher_id=tid, day=day,
                                       amount=int(v), what=desc))
        os.makedirs(OUT, exist_ok=True)
        if exceptions:
            with open(exc_path, "w", encoding="utf-8") as f:
                json.dump(dict(mode="rescue", exceptions=exceptions), f,
                          ensure_ascii=False, indent=1)
        elif os.path.exists(exc_path):
            # rescue was allowed but not needed - the timetable is fully legal
            os.remove(exc_path)
    else:
        # A strict solve succeeded: any exceptions file from an earlier
        # rescue run is stale and must not excuse anything.
        if os.path.exists(exc_path):
            os.remove(exc_path)

    hb_stop.set()
    elapsed = time.time() - t0

    placement = placement_from_solver(solver.Value, sessions, x, starts_of,
                                      s.cfg.slots)
    units = hour_units(sessions)
    rooms = assign_rooms(s, sessions, placement)

    # which day off did the solver choose for each blank-day_off teacher?
    chosen_offs = {}
    for tid, offs in getattr(m, "day_off_choice", {}).items():
        for d, var in offs.items():
            if solver.Value(var):
                chosen_offs[tid] = d
                break
    if chosen_offs:
        print("  Flexible day offs chosen for %d teachers - the list is in "
              "the report." % len(chosen_offs))
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "dayoffs.json"), "w", encoding="utf-8") as f:
            json.dump(chosen_offs, f, ensure_ascii=False, indent=1)

    os.makedirs(OUT, exist_ok=True)
    xml_path = os.path.join(OUT, "timetable.xml")
    emit_asc.write(s, units, placement, rooms, xml_path)
    emit_html.write(s, units, placement, rooms, os.path.join(OUT, "view.html"),
                    day_offs=chosen_offs)
    emit_html.write_teachers(s, os.path.join(OUT, "teachers.html"))
    rep = report(s, units, placement, rooms, solver, status, elapsed,
                 exceptions=exceptions, day_offs=chosen_offs)
    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
        f.write(rep)
    emit_html.write_report_html(rep, os.path.join(OUT, "report.html"))

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
    print("  out/timetable.xml  -> import into aSc TimeTables (the real table)")
    print("  out/view.html      -> printable timetable per class / teacher")
    print("  out/teachers.html  -> who teaches what, hours vs contract")
    print("  out/report.html    -> the stats: exceptions, soft rules, load")
    print("\nNow run:  python solver/verify.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

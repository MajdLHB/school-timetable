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


class _Tee:
    """Mirror everything printed into out/last_run.log, so a run that is
    interrupted or killed still leaves evidence of what happened."""

    def __init__(self, stream, path):
        self.stream = stream
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8", errors="replace")

    def write(self, text):
        self.stream.write(text)
        try:
            self.fh.write(text)
            self.fh.flush()
        except (OSError, ValueError):
            pass
        return len(text)

    def flush(self):
        self.stream.flush()
        try:
            self.fh.flush()
        except (OSError, ValueError):
            pass


_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "out", "last_run.log")
try:
    sys.stdout = _Tee(sys.stdout, _LOG)
    sys.stderr = _Tee(sys.stderr, _LOG)
except OSError:
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

# Majd 2026-08-25: "make rules applied in a better way". A single weighted
# sum lets a hundred cheap rules outvote one that matters. So the solve is
# STAGED: tier 1 is optimised first and then FROZEN at its best value, then
# tier 2 on top of it, and only then the rest. A rule can never be traded
# away by rules of a lower tier.
TIERS = {
    # TIER 1 - DIGNITY. What makes a staff room hate a timetable, and what
    # a human planner would never sign. Nothing below may trade these away.
    1: ("groups_back_to_back",   # the two halves of a TP, glued together
        "one_hour_day",          # a teacher travelling in for ONE lesson
        "teacher_lone_half",     # one lonely hour stuck beside the break
        "class_one_hour_session",  # pupils coming in for one lone hour
        "hard_subject_last"),    # maths/philosophy at 17:00-18:00
    # TIER 2 - COMFORT. Majd: "comfort is important too, i can already make
    # a NORMAL timetable by hand" - so this is the tier that must beat him:
    # holes, protected bac afternoons, hard subjects out of the evening.
    2: ("teacher_gap", "class_gap", "flexible_day_off",
        "bac_no_free_afternoon", "hard_subject_evening", "late_subject",
        "last_period"),
    # TIER 3 (everything else) - polish: patterns, spreading, pairing,
    # walking distance, morning/evening balance.
}


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
            elif week == "ALT2":
                # the SWAP side of the TP carousel (Majd 2026-08-25: while
                # group 1 is in the SVT lab, group 2 is in the TECH lab -
                # next week they trade). ALT puts odd groups in week A;
                # ALT2 puts them in week B, so an ALT subject and an ALT2
                # subject interleave perfectly in the same slot.
                gw = "B" if g % 2 == 1 else "A"
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

    # ---- H14: option bands (Majd's five answers, 2026-08-25) --------------
    # Every pupil takes exactly one option, so while the band runs the WHOLE
    # class is in an option - modelled as a whole-class pseudo-subject
    # "OPT:<band>" per member class. build() ties the member classes'
    # copies to the SAME slots and binds the option teachers and rooms.
    if s.options and not s.option_bands:
        D.compute_option_bands(s)
    for band in s.option_bands:
        bl, err = D.parse_blocks(band["blocks"], band["hours"])
        explicit = bool(str(band["blocks"]).strip())
        if err or not bl or sum(bl) != band["hours"]:
            bl, explicit = [1] * band["hours"], False
        for cid in band["classes"]:
            off = 0
            for k, L in enumerate(bl):
                sid = "%s|OPT:%s||g0|s%d" % (cid, band["id"], k)
                sessions.append(Sess(sid, cid, "OPT:" + band["id"], "",
                                     "__opt__", L, off, explicit, 0, ""))
                off += L
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
                 every=15.0, viols=None, exceptions_only=False):
        super().__init__()
        self.exceptions_only = exceptions_only
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
        if self.exceptions_only:
            # rescue PHASE 1: the objective IS the exception hours
            self.last_exc = int(self.ObjectiveValue())
            self.last_soft = 0
            print("   %6.1fs  PHASE 1 version %-3d exceptions down to %d hours"
                  % (el, self.n, self.last_exc), flush=True)
            self.save()
            if STOP:
                self.save(force=True)
                self.StopSearch()
            return
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


def build(s, sessions, rescue=False, objective="full", exc_cap=None):
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

    pen_map = collections.defaultdict(list)   # key -> [(weight, var)]

    def add_pen(key, default, var):
        """One comfort penalty - or, when the Weights sheet says HARD for
        this key, an unbreakable constraint (var == 0). Majd's promotion
        mechanism: build right first, instead of repairing later."""
        w = W.get(key, default)
        if w == "HARD":
            m.Add(var == 0)
        else:
            penalties.append((w, var))
            pen_map[key].append((w, var))

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

    # ---- H14: bind the option bands ---------------------------------------
    # 1) ALIGNMENT - every member class's copy of the band sits in the SAME
    #    slots (a pupil not in this option is in another one of the band).
    # 2) TEACHERS - every option group's teacher is busy in the band's slots,
    #    so their clashes, day off, 6h cap and comfort rules all see it.
    # 3) ROOMS - the band needs one room PER OPTION GROUP; counted below in
    #    the room-type constraint via band_room_terms.
    band_rep = {}                     # band id -> rep class's sessions
    band_room_terms = collections.defaultdict(list)   # room type -> (occvar, n)
    for band in s.option_bands:
        copies = {cid: sorted(by_cs.get((cid, "OPT:" + band["id"]), []),
                              key=lambda se: se.hour_offset)
                  for cid in band["classes"]}
        rep = band["classes"][0]
        band_rep[band["id"]] = copies[rep]
        for cid in band["classes"][1:]:
            for a, b in zip(copies[rep], copies[cid]):
                for j in range(len(starts_of(a))):
                    m.Add(x[a.sid, j] == x[b.sid, j])
        for tid in {g["teacher_id"] for g in band["groups"] if g["teacher_id"]}:
            # (a teacher with TWO parallel groups in one band is impossible
            #  and is refused by the data check, not modelled here)
            by_teacher[tid].extend(band_rep[band["id"]])
        by_room_need = collections.Counter(D.option_room_type(s, g)
                                           for g in band["groups"])
        for rt, n_need in by_room_need.items():
            for se in band_rep[band["id"]]:
                band_room_terms[rt].append((se, n_need))

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
    # Majd 2026-08-25: "physics and svt labs can give normal tutoring too"
    # and "u can put small classes study in a lab in a normal session when
    # needed". So NORMAL lessons may borrow the science labs: each lab type
    # keeps its own bound (lab lessons always fit), and normal+labs share a
    # pooled bound. IT / tech / engineering / gym rooms serve ONLY their
    # own subjects, as he said.
    # measured from last year: فيز2 hosted French/Arabic/English,
    # علوم1 hosted Gestion, تقنية 2 hosted French and maths.
    SPARE = ("lab_phys", "lab_sci", "tech")
    n_spare = sum(len(s.rooms_of_type(t_)) for t_ in SPARE)

    for rt in sorted(set(by_type) | set(band_room_terms)):
        if rt == "__opt__":
            continue   # the band pseudo-rows book rooms via band_room_terms
        ss = by_type.get(rt, [])
        n_rooms = len(s.rooms_of_type(rt))
        extra = band_room_terms.get(rt, [])
        for w in weeks_of(ss + [se for se, _n in extra]):
            act = [se for se in ss if in_week(se, w)]
            for i in range(S):
                vs = occs(act, i)
                ex = [(occ[se.sid, i], n) for se, n in extra
                      if (se.sid, i) in occ]
                if not vs and not ex:
                    continue
                # In rescue mode a room shortage is DECLARED, not refused:
                # Majd's school runs its IT rooms at 98% and the ordinary
                # pool at 91%, so a single tight period must not make the
                # whole week impossible. Every overflow costs RESCUE_WEIGHT
                # and is listed in the report ("this period needs one more
                # IT room"), exactly like the H7/H17 exceptions.
                def bound(terms, cap, tag):
                    if not rescue:
                        m.Add(sum(terms) <= cap)
                        return
                    over = m.NewIntVar(0, max(1, len(terms)),
                                       "vROOM_%s_%s_%d" % (tag, w, i))
                    m.Add(sum(terms) <= cap + over)
                    penalties.append((RESCUE_WEIGHT, over))
                    viols.append(("H4", "", "%s p%d" % slots[i], over,
                                  "not enough '%s' rooms" % tag))

                if rt == "normal" and n_spare:
                    # pooled: normal lessons + lab lessons <= normal + labs
                    lab_v = [v for t_ in SPARE
                             for v in occs([se for se in by_type.get(t_, [])
                                            if in_week(se, w)], i)]
                    terms = vs + lab_v + [n * v for v, n in ex]
                    if len(vs) + len(lab_v) + sum(n for _v, n in ex) > n_rooms + n_spare:
                        bound(terms, n_rooms + n_spare, "normal+labs")
                elif len(vs) + sum(n for _v, n in ex) > n_rooms:
                    bound(vs + [n * v for v, n in ex], n_rooms, rt)

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
                    add_pen("same_subject_twice_a_day", 50, extra)
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

    # ---- H20 / M-SN4 (Majd 2026-08-25, over a morning/afternoon split:
    # "group sessions should be back to back next to each other"): when two
    # groups of one row share a WEEK, their sessions sit on the same day in
    # ADJACENT periods. Default HARD; the Weights sheet key
    # groups_back_to_back can make it a (heavy) preference instead when the
    # school is too packed to obey it everywhere. Carousel groups (ALT/ALT2)
    # are exempt - they live in different weeks and never meet.
    def day_start_vars(se, tag):
        st = starts_of(se)
        dv = m.NewIntVar(0, len(days) - 1, "d_%s_%s" % (se.sid, tag))
        pv = m.NewIntVar(0, s.cfg.periods_per_day, "p_%s_%s" % (se.sid, tag))
        m.Add(dv == sum(day_ix[dd] * x[se.sid, j]
                        for j, (dd, p0, ixs) in enumerate(st)))
        m.Add(pv == sum(p0 * x[se.sid, j]
                        for j, (dd, p0, ixs) in enumerate(st)))
        return dv, pv

    too_long_pairs = []
    for (cid, sid_, g), sa in sorted(by_row.items()):
        if g < 1:
            continue
        sb = by_row.get((cid, sid_, g + 1))
        if not sb:
            continue
        # pair WITHIN each week: a row may have both a week-A and a week-B
        # part, and sorting by offset alone could pair across weeks - which
        # this rule then skipped, leaving the groups unconstrained (caught
        # by verify.py on last year's data, 2026-08-25).
        pairs = []
        weeks_here = {se.week for se in sa} | {se.week for se in sb}
        for wk in sorted(weeks_here):
            aw = sorted((se for se in sa if se.week == wk),
                        key=lambda se: se.hour_offset)
            bw = sorted((se for se in sb if se.week == wk),
                        key=lambda se: se.hour_offset)
            pairs.extend(zip(aw, bw))
        for k, (a, b) in enumerate(pairs):
            # A pair can only sit back to back if BOTH fit consecutively
            # inside one half-day. A 4h group session x2 would need 8 in a
            # row - physically impossible (Majd 2026-08-25: my strict rule
            # declared his REAL school infeasible; those subjects run in
            # PARALLEL with a partner subject instead, swapping groups).
            # When it cannot fit, prefer the same DAY and let S20 pair the
            # groups with another subject.
            if not any(dd == dd2 and abs(p1 - p2) == a.length
                       for dd, p1, _i in starts_of(a)
                       for dd2, p2, _j in starts_of(b)):
                da, pa = day_start_vars(a, "a%d" % k)
                db, pb = day_start_vars(b, "b%d" % k)
                same = m.NewBoolVar("b2bSD_%s_%s_%d_%d" % (cid, sid_, g, k))
                m.Add(da == db).OnlyEnforceIf(same)
                m.Add(da != db).OnlyEnforceIf(same.Not())
                add_pen("groups_same_day", 60, same.Not())
                too_long_pairs.append((cid, sid_, a.length))
                continue
            da, pa = day_start_vars(a, "a%d" % k)
            db, pb = day_start_vars(b, "b%d" % k)
            # b right after a, or a right after b, on the same day
            first = m.NewBoolVar("b2b1_%s_%s_%d_%d" % (cid, sid_, g, k))
            m.Add(db == da).OnlyEnforceIf(first)
            m.Add(pb == pa + a.length).OnlyEnforceIf(first)
            second = m.NewBoolVar("b2b2_%s_%s_%d_%d" % (cid, sid_, g, k))
            m.Add(db == da).OnlyEnforceIf(second)
            m.Add(pa == pb + b.length).OnlyEnforceIf(second)
            apart = m.NewBoolVar("b2bX_%s_%s_%d_%d" % (cid, sid_, g, k))
            m.AddExactlyOne([first, second, apart])
            add_pen("groups_back_to_back", "HARD", apart)

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
                    add_pen("tp_groups_same_day", 45, diff)

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
        # Majd 2026-08-25, looking at a scattered week: "day off teaching -
        # make it less important, keep it there but for better results maybe
        # let him teach then". So the CHOSEN day off is now a strong SOFT
        # preference (flexible_day_off per taught hour), never a chain - a
        # WRITTEN day in the sheet stays absolutely hard as before.
        offs = {d: m.NewBoolVar("off_%s_%s" % (tid, d)) for d in cands}
        m.Add(sum(offs.values()) == 1)
        day_off_choice[tid] = offs
        for d in cands:
            terms = [v for i, (dd, p) in enumerate(slots) if dd == d
                     for v in occs(ss, i)]
            if not terms:
                continue
            v = m.NewIntVar(0, len(terms), "vH7f_%s_%s" % (tid, d))
            m.Add(v == sum(terms)).OnlyEnforceIf(offs[d])
            m.Add(v == 0).OnlyEnforceIf(offs[d].Not())
            add_pen("flexible_day_off", 200, v)

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

    def add_gap_penalty(pres, key, weight_key, also_one_hour=False, also_day_count=False):
        """S1/S7 no holes, S2 no 1-hour days, S8-compact fewest days.

        Holes are counted WITHIN each half-day (Majd 2026-08-25: the score
        looked huge - the old span crossed the lunch break, charging every
        morning+evening day two phantom holes. Lunch is not a hole).

        Returns {day: here-bool} so S21 (shared transport) can compare two
        teachers' presence day by day without rebuilding it."""
        days_here = {}
        for d in s.cfg.days:
            ps_all = [p for (dd, p) in slots if dd == d]
            if len(ps_all) < 2:
                continue
            taught_day = sum(pres[d, p] for p in ps_all)

            here = m.NewBoolVar("here_%s_%s" % (key, d))
            m.Add(taught_day >= 1).OnlyEnforceIf(here)
            m.Add(taught_day == 0).OnlyEnforceIf(here.Not())
            days_here[d] = here

            half_busy = {}
            for half, tag in ((sorted(p for p in ps_all if p not in evening), "am"),
                              (sorted(p for p in ps_all if p in evening), "pm")):
                if len(half) < 2:
                    continue
                lo, hi = half[0], half[-1]
                taught = sum(pres[d, p] for p in half)
                busy = m.NewBoolVar("hbusy_%s_%s_%s" % (key, d, tag))
                m.Add(taught >= 1).OnlyEnforceIf(busy)
                m.Add(taught == 0).OnlyEnforceIf(busy.Not())
                half_busy[tag] = busy
                first = m.NewIntVar(lo, hi, "first_%s_%s_%s" % (key, d, tag))
                last = m.NewIntVar(lo, hi, "last_%s_%s_%s" % (key, d, tag))
                for p in half:
                    m.Add(first <= p).OnlyEnforceIf(pres[d, p])
                    m.Add(last >= p).OnlyEnforceIf(pres[d, p])
                gaps = m.NewIntVar(0, len(half), "gaps_%s_%s_%s" % (key, d, tag))
                m.Add(gaps == last - first + 1 - taught).OnlyEnforceIf(busy)
                m.Add(gaps == 0).OnlyEnforceIf(busy.Not())
                add_pen(weight_key, 100, gaps)
                if also_one_hour:
                    # Majd 2026-08-25: "they came 11 and sat there doing
                    # nothing" - a teacher's half-day with exactly ONE
                    # lesson is the real pain around the lunch break.
                    lone = m.NewBoolVar("hlone_%s_%s_%s" % (key, d, tag))
                    m.Add(taught == 1).OnlyEnforceIf(lone)
                    m.Add(taught != 1).OnlyEnforceIf(lone.Not())
                    add_pen("teacher_lone_half", 70, lone)

            if also_one_hour:
                solo = m.NewBoolVar("solo_%s_%s" % (key, d))
                m.Add(taught_day == 1).OnlyEnforceIf(solo)
                m.Add(taught_day != 1).OnlyEnforceIf(solo.Not())
                add_pen("one_hour_day", 50, solo)
                if len(half_busy) == 2:
                    # crossing the lunch at all costs a little: teachers who
                    # cannot go home sit through it. Tunable; 0 switches it
                    # off, HARD would demand single-half days for everyone.
                    cross = m.NewBoolVar("cross_%s_%s" % (key, d))
                    m.AddBoolAnd(list(half_busy.values())).OnlyEnforceIf(cross)
                    m.AddBoolOr([b.Not() for b in half_busy.values()]).OnlyEnforceIf(cross.Not())
                    add_pen("cross_lunch", 15, cross)
            if also_day_count:
                add_pen("extra_day_present", 50, here)
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
                add_gap_penalty(pres, "T%s%s" % (tid, w), "teacher_gap",
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
                    add_pen("overloaded_day", 40, over)
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
            add_pen("morning_evening_imbalance", 60, imb)

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
            add_pen("travel_pair", 70, diff)

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
                add_gap_penalty(pres, key, "class_gap")
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
                        add_pen("pupil_day_over6", 120, over6)
                    for half, hp in halves.items():
                        hps = [p for p in dps if p in hp]
                        if len(hps) > 4:
                            o4 = m.NewIntVar(0, len(hps),
                                             "pup4_%s_%s_%s" % (key, d, half))
                            m.Add(o4 >= sum(pres[d, p] for p in hps) - 4)
                            add_pen("pupil_half_over4", 100, o4)

    # ---- M-P7 / M-AR11 / M-HG2: each CLASS balanced morning vs evening ----
    # (we already do this per teacher, S5; the inspectorate asks for it per
    # class too - Majd 2026-08-25: "make sure rules in the pdfs are applied")
    for cid, ss in by_class.items():
        for w in weeks_of(ss):
            act = [se for se in ss if in_week(se, w)]
            m_ix = [i for i, (d, p) in enumerate(slots) if p not in evening]
            e_ix = [i for i, (d, p) in enumerate(slots) if p in evening]
            mh = [v for i in m_ix for v in occs(act, i)]
            eh = [v for i in e_ix for v in occs(act, i)]
            if not mh or not eh:
                continue
            imb = m.NewIntVar(0, S, "cimb_%s_%s" % (cid, w))
            m.Add(imb >= sum(mh) - sum(eh) - 4)
            m.Add(imb >= sum(eh) - sum(mh) - 4)
            add_pen("class_morning_evening", 60, imb)

    # ---- M-SN3 / M-ISL1: subjects that PREFER the morning ------------------
    # "TP in the morning for 3rd and 4th experimental science"; the optional
    # Islamic Thought hour in the morning. Subjects sheet: prefer_morning=yes
    pm = [se for se in sessions
          if s.subjects.get(se.subject_id, {}).get("prefer_morning") == "yes"]
    if pm:
        ev_all = [i for i, (d, p) in enumerate(slots) if p in evening]
        terms = [v for i in ev_all for v in occs(pm, i)]
        if terms:
            n_pm = m.NewIntVar(0, len(terms), "prefer_morning_missed")
            m.Add(n_pm == sum(terms))
            add_pen("prefer_morning", 120, n_pm)

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
                        add_pen("class_one_hour_session", 85, solo)

    # ---- S3: hard subjects belong in the morning -------------------------
    hard_sess = [se for se in sessions
                 if s.subjects.get(se.subject_id, {}).get("difficulty") == "hard"]
    ev_ix = [i for i, (d, p) in enumerate(slots) if p in evening]
    if hard_sess and ev_ix:
        terms = [v for i in ev_ix for v in occs(hard_sess, i)]
        if terms:
            n_ev = m.NewIntVar(0, len(terms), "hard_in_evening")
            m.Add(n_ev == sum(terms))
            add_pen("hard_subject_evening", 50, n_ev)
    # Majd 2026-08-25: "try not to put hard subjects and important ones the
    # afternoon and ESPECIALLY the last session" - a hard subject in the
    # final period costs extra, on top of the general afternoon penalties.
    last_ix_hard = [i for i, (d, p) in enumerate(slots)
                    if p == s.cfg.periods_per_day]
    if hard_sess and last_ix_hard:
        terms = [v for i in last_ix_hard for v in occs(hard_sess, i)]
        if terms:
            n_last = m.NewIntVar(0, len(terms), "hard_in_last")
            m.Add(n_last == sum(terms))
            add_pen("hard_subject_last", 120, n_last)

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
            add_pen("daylight_not_morning", 45, n_late)

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
                add_pen("same_subject_adjacent_days", 50, both)

    # ---- rules.pdf, English: never two CONSECUTIVE hours of this subject
    # for one class, at any level (Subjects sheet: no_doubles=yes) ---------
    nd_subj = {sid for sid, sub in s.subjects.items()
               if sub.get("no_doubles") == "yes"}
    if nd_subj:
        for cid, ss in by_class.items():
            for sid_ in sorted(nd_subj):
                ses = [se for se in ss if se.subject_id == sid_]
                if not ses:
                    continue
                for w in weeks_of(ses):
                    act = [se for se in ses if in_week(se, w)]
                    for i, (d, p) in enumerate(slots):
                        i2 = slot_ix.get((d, p + 1))
                        if i2 is None:
                            continue
                        va, vb = occs(act, i), occs(act, i2)
                        if not va or not vb:
                            continue
                        both = m.NewIntVar(0, 1, "nodbl_%s_%s_%s_%d"
                                           % (cid, sid_, w, i))
                        m.Add(both >= sum(va) + sum(vb) - 1)
                        add_pen("no_doubles", 300, both)

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
                    add_pen("not_after", 60, both)

    # ---- S20: grouped subjects PAIR UP and swap (Majd 2026-08-25: "they ---
    # alternate between tech and svt in groups"). While group 1 sits in
    # subject A, group 2 sits in subject B in the same period, then they
    # swap. Soft: every period where one grouped subject runs without the
    # other costs group_pair_swap points. Judged per week view.
    grouped_subj = collections.defaultdict(set)
    for (cid, sid_, g) in by_row:
        if g:
            grouped_subj[cid].add(sid_)
    for cid, sids in grouped_subj.items():
        sids = sorted(sids)
        for a_i in range(len(sids)):
            for b_i in range(a_i + 1, len(sids)):
                ga = [se for se in by_cs[cid, sids[a_i]] if se.group]
                gb = [se for se in by_cs[cid, sids[b_i]] if se.group]
                for w in weeks_of(ga + gb):
                    for i in range(S):
                        va = occs([se for se in ga if in_week(se, w)], i)
                        vb = occs([se for se in gb if in_week(se, w)], i)
                        if not va and not vb:
                            continue
                        diff = m.NewIntVar(0, max(len(va), len(vb)),
                                           "s20_%s_%s_%s_%s_%d"
                                           % (cid, sids[a_i], sids[b_i], w, i))
                        m.Add(diff >= sum(va) - sum(vb))
                        m.Add(diff >= sum(vb) - sum(va))
                        add_pen("group_pair_swap", 35, diff)

    # ---- T37: subject pairs that must not share a day (soft) --------------
    # Ministry: History and Geography never on the same day. Generic: any
    # subject may carry not_same_day=<ids> in the Subjects sheet; one side
    # of the pair is enough. Judged per week view.
    for cid, ss in by_class.items():
        subj_here = {se.subject_id for se in ss}
        pairs = set()
        for sid_b in subj_here:
            for sid_a in s.subjects.get(sid_b, {}).get("not_same_day", []):
                if sid_a in subj_here and sid_a != sid_b:
                    pairs.add(tuple(sorted((sid_a, sid_b))))
        for sid_a, sid_b in sorted(pairs):
                ses_a = [se for se in ss if se.subject_id == sid_a]
                ses_b = [se for se in ss if se.subject_id == sid_b]
                for w in weeks_of(ses_a + ses_b):
                    for d in days:
                        ta = [x[se.sid, j] for se in ses_a if in_week(se, w)
                              for j, (dd, _p, _x) in enumerate(starts_of(se))
                              if dd == d]
                        tb = [x[se.sid, j] for se in ses_b if in_week(se, w)
                              for j, (dd, _p, _x) in enumerate(starts_of(se))
                              if dd == d]
                        if not ta or not tb:
                            continue
                        ba = m.NewBoolVar("nsdA_%s_%s_%s_%s_%s" % (cid, sid_a, sid_b, d, w))
                        m.Add(sum(ta) >= 1).OnlyEnforceIf(ba)
                        m.Add(sum(ta) == 0).OnlyEnforceIf(ba.Not())
                        bb = m.NewBoolVar("nsdB_%s_%s_%s_%s_%s" % (cid, sid_a, sid_b, d, w))
                        m.Add(sum(tb) >= 1).OnlyEnforceIf(bb)
                        m.Add(sum(tb) == 0).OnlyEnforceIf(bb.Not())
                        both = m.NewIntVar(0, 1, "nsd_%s_%s_%s_%s_%s" % (cid, sid_a, sid_b, d, w))
                        m.Add(both >= ba + bb - 1)
                        add_pen("not_same_day", 60, both)

    # ---- T41: a double belongs at the TOP of its half-day -----------------
    # A 2h+ block that starts mid-run leaves a stub before it; the ministry
    # habit is doubles first thing in the morning or first thing in the
    # evening. Soft, small weight - capacity beats aesthetics.
    run_starts = {d: {ps[0]} | {p for prev, p in zip(ps, ps[1:]) if p != prev + 1}
                  for d, ps in open_by_day.items() if ps}
    for se in sessions:
        if se.length < 2:
            continue
        for j, (d, p0, ixs) in enumerate(starts_of(se)):
            if p0 not in run_starts.get(d, ()):
                add_pen("double_not_at_start", 25, x[se.sid, j])

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
                    add_pen("same_nature_adjacent", 80, pair)

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
        add_pen("core_morning", 65, over)

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
        add_pen("last_period_fairness", 35, over)

    # ---- S16: subject-specific late-hour avoidance ------------------------
    # Soft cousin of H15. Ministry: Maths avoids the evening and never after
    # 16:00 if it must (M-MA3); Physics avoids 17:00-18:00 (M-PH5).
    for se in sessions:
        aa = s.subjects.get(se.subject_id, {}).get("avoid_after") or 0
        if not aa:
            continue
        for i, (d, p) in enumerate(slots):
            if p > aa and (se.sid, i) in occ:
                add_pen("late_subject", 50, occ[se.sid, i])

    # ---- S14: the last period of the day is a slot of last resort ---------
    # Majd: "try to avoid 17 to 18 as much as possible its late". Ministry
    # backing: the inspectorate tells Physics the same (M-PH5). Applies to
    # everyone; soft, because banning it would cost too much capacity.
    last_p = s.cfg.periods_per_day
    for se in sessions:
        for i, (d, p) in enumerate(slots):
            if p == last_p and (se.sid, i) in occ:
                add_pen("last_period", 55, occ[se.sid, i])

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
                add_pen("bac_friday_evening", 30, v)
        # S17 two layers (Majd 2026-08-25: "free as much afternoons for bac
        # as possible"): every BUSY bac afternoon Mon-Thu costs a little, so
        # the solver frees as many as capacity allows; a bac class left with
        # NO free afternoon at all costs a lot (the ministry's minimum, I.6).
        busy_days = []
        for d in first_four:
            ix = [i for i, (dd, p) in enumerate(slots) if dd == d and p in evening]
            if not ix:
                continue
            terms = [v for i in ix for v in occs(ss, i)]
            busy = m.NewBoolVar("bacbusy_%s_%s" % (cid, d))
            m.Add(sum(terms) >= 1).OnlyEnforceIf(busy)
            m.Add(sum(terms) == 0).OnlyEnforceIf(busy.Not())
            busy_days.append(busy)
            add_pen("bac_busy_afternoon", 60, busy)
        if busy_days:
            none_free = m.NewBoolVar("bacnofree_%s" % cid)
            m.AddBoolAnd(busy_days).OnlyEnforceIf(none_free)
            m.AddBoolOr([b.Not() for b in busy_days]).OnlyEnforceIf(none_free.Not())
            add_pen("bac_no_free_afternoon", 200, none_free)

    # objective="exceptions" (rescue phase 1): count ONLY the exception
    # hours, so the solver can PROVE the minimum - Majd's "so I know it's
    # doable" question. exc_cap then freezes that minimum for phase 2, which
    # optimises comfort without ever adding an exception back.
    if exc_cap is not None:
        m.Add(sum(v for _r, _t, _d, v, _w in viols) <= exc_cap)
    if objective == "exceptions":
        m.Minimize(sum(v for _r, _t, _d, v, _w in viols))
    else:
        m.Minimize(sum(w * v for w, v in penalties))
    # main() reads the flexible day-off choice from here after solving, to
    # report which day each teacher was given. Kept as an attribute so the
    # (m, x, starts_of, viols) signature the selftests rely on stays stable.
    m.day_off_choice = day_off_choice
    m.pen_map = pen_map
    m.too_long_pairs = too_long_pairs
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

    # T45 room proximity (Majd 2026-08-25: "assume data is 0, will edit
    # later"): the Rooms sheet zone column groups nearby rooms. When picking
    # a room, prefer the zone of the class's neighbouring periods, so pupils
    # do not cross the school between two lessons. All-blank zones = one big
    # zone = zero effect, exactly as asked.
    zone_of = {rid: (r.get("zone") or "") for rid, r in s.rooms.items()}
    czone = {}   # (class_id, day, period) -> zone of the room used

    def take(se, rid, sl):
        taken[sl].setdefault(rid, set()).update(wset(se))
        z = zone_of.get(rid, "")
        if z:
            czone[(se.class_id,) + sl] = z
        class_room_use[se.class_id, rid] += 1

    def try_room(se, rid):
        us = hour_uids(se)
        if any(not room_free(se, rid, slot_of(u)) for u in us):
            return False
        for u in us:
            out[u] = rid
            take(se, rid, slot_of(u))
        return True

    class_room_use = collections.Counter()

    def pref_rooms(se):
        """Rooms of the right type, nearest zone first. A NORMAL lesson may
        fall back to a science lab when the ordinary rooms are full (Majd's
        rule) - always AFTER every ordinary room has been tried. Within the
        same zone, rooms this class already uses come first (rules.pdf: do
        not scatter one class across many rooms)."""
        cands = list(rooms_by_type.get(se.room_type, []))
        if se.room_type == "normal":
            for t_ in ("lab_sci", "lab_phys", "tech"):
                cands += rooms_by_type.get(t_, [])
        cands.sort(key=lambda rid: -class_room_use[se.class_id, rid])
        near = set()
        for u in hour_uids(se):
            d, p = placement[u]
            for q in (p - 1, p + 1):
                z = czone.get((se.class_id, d, q))
                if z:
                    near.add(z)
        if not near:
            return cands
        return sorted(cands,
                      key=lambda rid: 0 if zone_of.get(rid, "") in near else 1)

    ordered = sorted([se for se in sessions if se.room_type != "__opt__"],
                     key=lambda se: -se.length)
    # first pass: home rooms, longest sessions first
    for se in ordered:
        home = s.classes.get(se.class_id, {}).get("home_room", "")
        if (home and home in s.rooms
                and s.rooms[home]["type"] == se.room_type):
            try_room(se, home)
    # second pass: any room of the right type (nearest zone first), same
    # room across the session
    for se in ordered:
        if hour_uids(se)[0] in out:
            continue
        for rid in pref_rooms(se):
            if try_room(se, rid):
                break
        else:
            # fall back to per-hour rooms; H3/H6 still hold
            for u in hour_uids(se):
                for rid in pref_rooms(se):
                    if room_free(se, rid, slot_of(u)):
                        out[u] = rid
                        take(se, rid, slot_of(u))
                        break
                else:
                    out[u] = ""  # should never happen; verify.py will catch it

    # ---- H14: one concrete room per option GROUP at the band's slots ------
    # The model already guaranteed the counts fit; here each group gets its
    # room id for the aSc cards, under the key "OPT|<group id>|<hour>".
    for band in getattr(s, "option_bands", []):
        rep = band["classes"][0]
        for g in band["groups"]:
            rt = D.option_room_type(s, g)
            for t in range(band["hours"]):
                uid = "%s|OPT:%s|%d" % (rep, band["id"], t)
                if uid not in placement:
                    continue
                sl = tuple(placement[uid])
                key = "OPT|%s|%d" % (g["id"], t)
                for rid in rooms_by_type.get(rt, []):
                    if not taken[sl].get(rid, set()):
                        out[key] = rid
                        taken[sl].setdefault(rid, set()).update({"A", "B"})
                        break
                else:
                    out[key] = ""
    return out


def report(s, units, placement, rooms, solver, status, elapsed, exceptions=None,
           day_offs=None, rule_costs=None):
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

    ev_set = set(s.cfg.evening)

    def half_holes(ps):
        """Holes inside each half-day; the lunch break is never a hole."""
        n = 0
        for half in ([p for p in ps if p not in ev_set],
                     [p for p in ps if p in ev_set]):
            if len(half) > 1:
                n += (max(half) - min(half) + 1) - len(half)
        return n

    gaps, solos, days_used = [], [], {}
    for tid, sl in t_slots.items():
        byday = collections.defaultdict(list)
        for (d, p) in sl:
            byday[d].append(p)
        days_used[tid] = len(byday)
        for d, ps in byday.items():
            ps.sort()
            holes = half_holes(ps)
            if holes:
                gaps.append((tid, d, holes, ps))
            if len(ps) == 1:
                solos.append((tid, d, ps[0]))

    if rule_costs:
        A("## Where the points went - cost per comfort rule")
        A("")
        A("| rule (Weights sheet key) | points | times hit |")
        A("|---|---|---|")
        for key, total, hits in rule_costs:
            if total:
                A("| %s | %d | %d |" % (key, total, hits))
        free = [key for key, total, _h in rule_costs if total == 0
                and key != "extra_day_present"]
        if free:
            A("")
            A("**Zero-cost this run - safe to set HARD in the Weights sheet "
              "(free speed, nothing lost):** " + ", ".join(sorted(free)))
        A("")

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
            cgap += half_holes(sorted(ps))
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

    A("## T45 - walks between zones")
    A("")
    zgrid = {}
    for u in units:
        d, p = placement[u.uid]
        z = s.rooms.get(rooms.get(u.uid, ""), {}).get("zone", "")
        if z:
            zgrid[u.class_id, d, p] = z
    walks = sum(1 for (cid, d, p), z in zgrid.items()
                if zgrid.get((cid, d, p + 1), z) != z)
    A("%d times a class changes zone between two consecutive periods "
      "(stays 0 until the `zone` column of the Rooms sheet is filled)." % walks)
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

    # an interrupted run must not leave a stale timetable behind: the next
    # step would verify the WRONG file (Majd hit exactly this).
    stale = os.path.join(OUT, "timetable.xml")
    if os.path.exists(stale):
        os.makedirs(os.path.join(OUT, "archive"), exist_ok=True)
        try:
            os.replace(stale, os.path.join(OUT, "archive", "previous.xml"))
        except OSError:
            pass

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
    exc_cap = None
    hint_from = None
    if rescue_now:
        print("--rescue: strict attempt skipped, livable exceptions allowed "
              "(each costs 10,000 - the solver still prefers none).")
        # ---- PHASE 1: what is the MINIMUM number of exceptions? -----------
        # Majd 2026-08-25: "at least he should do it with least amount of
        # exceptions... so i know its doable so i let it run". This phase
        # optimises ONLY the exception count; OPTIMAL here is a PROOF.
        print("\nPHASE 1 - finding the minimum possible exceptions "
              "(0 = a fully legal table exists)...", flush=True)
        m1, x1, so1, v1 = build(s, sessions, rescue=True,
                                objective="exceptions")
        s1 = cp_model.CpSolver()
        s1.parameters.max_time_in_seconds = min(
            max(60.0, cfg.time_limit / 3.0), max(60.0, cfg.time_limit - 60.0))
        s1.parameters.num_search_workers = n_workers()
        cb1 = Progress(t0, sessions=sessions, x=x1, starts_of=so1,
                       slots=s.cfg.slots, viols=v1, exceptions_only=True)
        n1 = s1.StatusName(s1.Solve(m1, cb1))
        if n1 in ("INFEASIBLE", "MODEL_INVALID"):
            print("\nNO TIMETABLE EXISTS even with the livable exceptions.")
            print("Something structural is impossible (a clash, room shortage,")
            print("or contradictory data). Check the data, then re-run.")
            return 2
        if n1 in ("OPTIMAL", "FEASIBLE"):
            exc_cap = int(s1.ObjectiveValue())
            if n1 == "OPTIMAL" and exc_cap == 0:
                print("  PROVEN: a FULLY LEGAL timetable exists. Doable, "
                      "0 exceptions.")
            elif n1 == "OPTIMAL":
                print("  PROVEN MINIMUM: %d exception-hours. No timetable "
                      "for this data can do better - fix data, not time."
                      % exc_cap)
            else:
                print("  Best found: %d exception-hours (NOT proven minimal "
                      "- a longer run may still lower it)." % exc_cap)
            print("PHASE 2 - exceptions locked at %d, optimising comfort..."
                  % exc_cap, flush=True)
            hint_from = (s1, x1)
        else:
            print("  Phase 1 found no complete table in its time share; "
                  "continuing without a proven minimum.", flush=True)
    m, x, starts_of, viols = build(s, sessions, rescue=rescue_now,
                                   exc_cap=exc_cap)
    if hint_from is not None:
        s1v, x1v = hint_from
        for se in sessions:
            for j in range(len(starts_of(se))):
                if s1v.Value(x1v[se.sid, j]):
                    m.AddHint(x[se.sid, j], 1)
                    break

    def on_sigint(signum, frame):
        global STOP
        STOP = True
        print("   Stopping after the next solution...", flush=True)

    signal.signal(signal.SIGINT, on_sigint)

    solver = cp_model.CpSolver()
    # phase 2 (or the only phase) gets whatever the limit has left
    solver.parameters.max_time_in_seconds = max(
        60.0, float(cfg.time_limit) - (time.time() - t0))
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

    # ---- PHASE 0: find ANY legal timetable first -------------------------
    # Majd's school runs at 91-98% room occupancy. Optimising comfort while
    # still hunting for the FIRST legal table left it unsolvable for hours;
    # with the objective switched off it lands in under a minute. So: find
    # a table, then spend every remaining second improving it.
    pen_map = getattr(m, "pen_map", {})
    full_obj = [(w, v) for entries in pen_map.values() for w, v in entries]
    if full_obj:
        print("\n  PHASE 0 - finding a first legal timetable "
              "(comfort switched off)...", flush=True)
        m.Minimize(0)
        f_solver = cp_model.CpSolver()
        f_solver.parameters.max_time_in_seconds = min(
            600.0, max(120.0, float(cfg.time_limit) * 0.15))
        f_solver.parameters.num_search_workers = n_workers()
        f_name = f_solver.StatusName(f_solver.Solve(m))
        if f_name in ("OPTIMAL", "FEASIBLE"):
            print("     found one in %.0fs - now improving it."
                  % f_solver.WallTime(), flush=True)
            for se in sessions:
                for j in range(len(starts_of(se))):
                    if f_solver.Value(x[se.sid, j]):
                        m.AddHint(x[se.sid, j], 1)
                        break
        else:
            print("     no legal timetable found yet (%s) - continuing."
                  % f_name, flush=True)
        m.Minimize(sum(w * v for w, v in full_obj))
        solver.parameters.max_time_in_seconds = max(
            120.0, float(cfg.time_limit) - (time.time() - t0))

    # ---- staged solve: freeze each tier's best before moving on ---------
    budget = solver.parameters.max_time_in_seconds
    staged = "--flat" not in sys.argv and pen_map
    if staged:
        for tier in sorted(TIERS):
            terms = [(w, v) for key in TIERS[tier]
                     for w, v in pen_map.get(key, [])]
            if not terms:
                continue
            share = min(max(120.0, budget * 0.2), budget / 3.0)
            print("\n  TIER %d - optimising %s (up to %d min)..."
                  % (tier, ", ".join(TIERS[tier]), share // 60), flush=True)
            m.Minimize(sum(w * v for w, v in terms))
            st_solver = cp_model.CpSolver()
            st_solver.parameters.max_time_in_seconds = share
            st_solver.parameters.num_search_workers = n_workers()
            st = st_solver.StatusName(st_solver.Solve(m))
            if st in ("OPTIMAL", "FEASIBLE"):
                best = int(st_solver.ObjectiveValue())
                # freeze: later tiers may never make this tier worse
                m.Add(sum(w * v for w, v in terms) <= best)
                print("     tier %d best = %d%s - frozen."
                      % (tier, best, " (proven optimal)" if st == "OPTIMAL" else ""),
                      flush=True)
                for se in sessions:      # warm-start the next stage
                    for j in range(len(starts_of(se))):
                        if st_solver.Value(x[se.sid, j]):
                            m.AddHint(x[se.sid, j], 1)
                            break
            else:
                print("     tier %d: no complete timetable in its slice - "
                      "moving on without freezing." % tier, flush=True)
        # restore the full objective for the final, longest phase
        m.Minimize(sum(w * v for w, v in
                       [(w, v) for entries in pen_map.values() for w, v in entries]))
        solver.parameters.max_time_in_seconds = max(
            120.0, float(cfg.time_limit) - (time.time() - t0))
        print("\n  FINAL - polishing everything else with the tiers frozen...",
              flush=True)

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

    # where did the points go? cost per comfort rule, for the report and
    # for Majd's hardening decisions ("apply all the rules from the start"):
    # a rule at ZERO cost can be set HARD in the Weights sheet for free.
    rule_costs = []
    for key, entries in sorted(getattr(m, "pen_map", {}).items()):
        total = sum(w * solver.Value(v) for w, v in entries)
        hits = sum(1 for _w, v in entries if solver.Value(v))
        rule_costs.append((key, total, hits))
    rule_costs.sort(key=lambda kc: -kc[1])

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
                 exceptions=exceptions, day_offs=chosen_offs,
                 rule_costs=rule_costs)
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

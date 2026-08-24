"""Prove each hard rule is actually WIRED UP, not just written down.

The danger with a large timetable is not a rule that is wrong. It is a rule
that was never connected - written in RULES.md, believed to be enforced, and
silently doing nothing. On 1,682 lessons you would never notice by eye.

So every hard rule gets a PAIR of tiny tests:

    BREAK   - build a school where obeying the rule is impossible.
              The solver must answer INFEASIBLE.
    RELAX   - remove only that rule's cause, change nothing else.
              The solver must now answer FEASIBLE.

The pair matters. A BREAK test alone proves nothing: the school might be
infeasible for some unrelated reason, and a disconnected rule would still
"pass". Only BREAK-then-RELAX shows the outcome hinges on that rule.

Runs in a few seconds on schools of 2-6 lessons. Run it after EVERY change.

    python tools/selftest.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "solver"))

from ortools.sat.python import cp_model  # noqa: E402
import data as D  # noqa: E402
import solve as S  # noqa: E402

WEIGHTS = {
    "teacher_gap": 100, "one_hour_day": 90, "class_gap": 85,
    "class_one_hour_session": 85, "hard_subject_evening": 70,
    "morning_evening_imbalance": 60, "same_subject_twice_a_day": 50,
    "late_subject": 50, "overloaded_day": 40, "extra_day_present": 40,
}


def tiny(days=("Mon", "Tue"), periods=2, closed=None):
    """A 2x2 = 4-slot school. Small enough to reason about completely."""
    cfg = D.Config(
        days=list(days), periods_per_day=periods,
        morning=[1], evening=[2], closed=closed or {},
        time_limit=10, weights=dict(WEIGHTS), weeks_per_cycle=1,
    )
    s = D.School(cfg=cfg)
    s.rooms["R1"] = dict(id="R1", name="R1", type="normal", capacity=99)
    s.subjects["MA"] = dict(id="MA", name="Maths", short="Ma",
                            difficulty="hard", room_type="normal",
                            latest_period=0)
    s.subjects["AR"] = dict(id="AR", name="Arabe", short="Ar",
                            difficulty="medium", room_type="normal",
                            latest_period=0)
    return s


def teacher(s, tid, hours=40, day_off=""):
    s.teachers[tid] = dict(id=tid, name=tid, short=tid, subjects=[],
                           hours=hours, day_off=day_off, notes="")


def klass(s, cid):
    s.classes[cid] = dict(id=cid, name=cid, grade="1", cohort="ALL",
                          home_room="", size=30)


def teach(s, cid, sid, hours, tid):
    s.curriculum.append(dict(class_id=cid, subject_id=sid, hours=hours,
                             teacher_id=tid, blocks="", room_type=""))


def status(s, skip_check=False):
    """Solve and return the status name.

    skip_check=False -> the normal path: the validator gets first refusal.
    skip_check=True  -> bypass the validator so the SOLVER must refuse on its
                        own. This is the stronger test: it is the only way to
                        tell a wired-up constraint from a rule that merely has
                        a friendly error message in front of it.
    """
    if not skip_check:
        errs, _notes = D.check(s)
        if errs:
            return "DATA_ERROR"
    units = S.expand(s)
    m, _x, _slots, _viols = S.build(s, units)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    solver.parameters.num_search_workers = 4
    return solver.StatusName(solver.Solve(m))


# --------------------------------------------------------------------------
# Each case returns (school_that_must_fail, school_that_must_then_work)
# --------------------------------------------------------------------------

def case_H1_teacher_two_places():
    """One teacher owes 4 hours to two classes but only 4 slots exist,
    and the classes cannot share him. RELAX: give the second class its own
    teacher."""
    def base(shared):
        s = tiny()
        teacher(s, "T1")
        teacher(s, "T2")
        klass(s, "C1")
        klass(s, "C2")
        s.rooms["R2"] = dict(id="R2", name="R2", type="normal", capacity=99)
        teach(s, "C1", "MA", 4, "T1")
        teach(s, "C2", "MA", 4, "T1" if shared else "T2")
        return s
    return base(True), base(False)


def case_H2_class_two_places():
    """A class needs 5 hours but its week has only 4 slots.
    RELAX: ask for 4."""
    def base(hours):
        s = tiny()
        teacher(s, "T1")
        klass(s, "C1")
        teach(s, "C1", "MA", hours, "T1")
        return s
    return base(5), base(4)


def case_H3_H4_rooms():
    """Two classes both need all 4 slots, but there is one room.
    RELAX: add a second room."""
    def base(nrooms):
        s = tiny()
        if nrooms > 1:
            s.rooms["R2"] = dict(id="R2", name="R2", type="normal", capacity=99)
        teacher(s, "T1")
        teacher(s, "T2")
        klass(s, "C1")
        klass(s, "C2")
        teach(s, "C1", "MA", 4, "T1")
        teach(s, "C2", "MA", 4, "T2")
        return s
    return base(1), base(2)


def case_H6_room_type():
    """A subject needs a lab and no lab exists. RELAX: build the lab."""
    def base(with_lab):
        s = tiny()
        if with_lab:
            s.rooms["L1"] = dict(id="L1", name="Lab", type="lab_sci", capacity=99)
        s.subjects["SC"] = dict(id="SC", name="SVT", short="SN",
                                difficulty="hard", room_type="lab_sci")
        teacher(s, "T1")
        klass(s, "C1")
        teach(s, "C1", "SC", 2, "T1")
        return s
    return base(False), base(True)


def case_H7_day_off():
    """Teacher owes 4 hours; his day off removes half the week.
    RELAX: no day off."""
    def base(off):
        s = tiny()
        teacher(s, "T1", day_off=off)
        klass(s, "C1")
        teach(s, "C1", "MA", 4, "T1")
        return s
    return base("Mon"), base("")


def case_H8_unavailable():
    """Teacher owes 4 hours and declares Monday unavailable.
    RELAX: drop the declaration."""
    def base(block):
        s = tiny()
        teacher(s, "T1")
        klass(s, "C1")
        teach(s, "C1", "MA", 4, "T1")
        if block:
            s.unavailable.append(dict(teacher_id="T1", day="Mon", period="*",
                                      hard="yes", reason="selftest"))
        return s
    return base(True), base(False)


def case_H10_contract_hours():
    """Teacher is handed 4 hours on a 2-hour contract. RELAX: 4-hour contract."""
    def base(cap):
        s = tiny()
        teacher(s, "T1", hours=cap)
        klass(s, "C1")
        teach(s, "C1", "MA", 4, "T1")
        return s
    return base(2), base(4)


def case_H15_daylight():
    """Sport needs 4 hours but may only use period 1, and there are 2 days -
    so only 2 legal slots exist. RELAX: allow both periods."""
    def base(latest):
        s = tiny()
        s.subjects["EP"] = dict(id="EP", name="Sport", short="EP",
                                difficulty="easy", room_type="normal",
                                latest_period=latest)
        teacher(s, "T1")
        klass(s, "C1")
        teach(s, "C1", "EP", 4, "T1")
        return s
    return base(1), base(2)


def case_H17_six_hour_day():
    """One 8-period day; a teacher owes 7 hours to one class. Any placement
    puts 7 hours in one day, over the ministry cap of 6 (circular II.2).
    RELAX: give the school a second day - 6+1 becomes possible."""
    def base(days):
        s = tiny(days=days, periods=8)
        s.cfg.morning = [1, 2, 3, 4]
        s.cfg.evening = [5, 6, 7, 8]
        teacher(s, "T1")
        klass(s, "C1")
        teach(s, "C1", "MA", 7, "T1")
        return s
    return base(("Mon",)), base(("Mon", "Tue"))


def check_rescue_mode():
    """Prove rescue mode does what Majd asked: when the strict rules admit no
    timetable, a livable one appears WITH the violation counted and reported -
    and the exception variables say exactly what was broken."""
    s = tiny()
    teacher(s, "T1", day_off="Mon")   # 4 hours owed, day off kills half the week
    klass(s, "C1")
    teach(s, "C1", "MA", 4, "T1")
    units = S.expand(s)

    m, _x, _sl, _v = S.build(s, units)                 # strict: must refuse
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = 10.0
    if not sv.StatusName(sv.Solve(m)).startswith("INFEASIBLE"):
        return False, "strict solve should be INFEASIBLE"

    m, _x, _sl, viols = S.build(s, units, rescue=True)  # rescue: must succeed
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = 10.0
    st = sv.StatusName(sv.Solve(m))
    if st not in ("OPTIMAL", "FEASIBLE"):
        return False, "rescue solve should be FEASIBLE, got " + st
    broken = [(r, t, d, sv.Value(v)) for r, t, d, v, _ in viols if sv.Value(v)]
    if not broken:
        return False, "rescue solved but declared no exception - it must confess"
    if not any(r == "H7" and t == "T1" and d == "Mon" and n == 2
               for r, t, d, n in broken):
        return False, "expected H7/T1/Mon x2 declared, got %r" % broken
    return True, "strict refused; rescue solved and declared H7 T1 Mon x2"


def case_LOCK_conflict():
    """Two different subjects of one class pinned to the same slot.
    RELAX: pin them to different slots."""
    def base(same):
        s = tiny()
        teacher(s, "T1")
        teacher(s, "T2")
        klass(s, "C1")
        s.rooms["R2"] = dict(id="R2", name="R2", type="normal", capacity=99)
        teach(s, "C1", "MA", 1, "T1")
        teach(s, "C1", "AR", 1, "T2")
        s.locked.append(dict(class_id="C1", subject_id="MA", day="Mon",
                             period=1, room_id="", why="selftest"))
        s.locked.append(dict(class_id="C1", subject_id="AR", day="Mon",
                             period=1 if same else 2, room_id="", why="selftest"))
        return s
    return base(True), base(False)


# (label, builder, which layer MUST catch it)
#   "solver"    - a placement constraint; the solver itself must refuse
#   "validator" - a property of the DATA that no placement can change, so a
#                 solver constraint would be a no-op that only looks reassuring
def check_H5_hours_delivered():
    """H5 cannot be made INFEASIBLE - AddExactlyOne means it either places
    every hour or finds nothing. So it needs a different kind of test: solve a
    small school, then COUNT what actually landed and compare to what was
    asked for. This is the only rule tested by inspecting output."""
    s = tiny(days=("Mon", "Tue", "Wed"), periods=2)
    teacher(s, "T1")
    teacher(s, "T2")
    klass(s, "C1")
    teach(s, "C1", "MA", 3, "T1")
    teach(s, "C1", "AR", 2, "T2")
    units = S.expand(s)
    m, x, slots, _viols = S.build(s, units)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    st = solver.StatusName(solver.Solve(m))
    if st not in ("OPTIMAL", "FEASIBLE"):
        return False, "school should have been solvable, got " + st
    got = {}
    for u in units:
        placed = [i for i in range(len(slots)) if solver.Value(x[u.uid, i])]
        if len(placed) != 1:
            return False, u.uid + " placed " + str(len(placed)) + " times, expected once"
        got[u.subject_id] = got.get(u.subject_id, 0) + 1
    if got.get("MA") != 3 or got.get("AR") != 2:
        return False, "asked MA=3 AR=2, got MA=%s AR=%s" % (got.get("MA"), got.get("AR"))
    return True, "MA 3/3, AR 2/2 hours delivered exactly"


CASES = [
    ("H1  teacher in two places", case_H1_teacher_two_places, "solver"),
    ("H2  class in two places", case_H2_class_two_places, "solver"),
    ("H3/H4 room capacity", case_H3_H4_rooms, "solver"),
    ("H6  wrong room type", case_H6_room_type, "solver"),
    ("H7  day off not empty", case_H7_day_off, "solver"),
    ("H8  declared unavailable", case_H8_unavailable, "solver"),
    # A teacher's weekly total is fixed by the curriculum - moving lessons
    # around cannot change it. So H10 is a DATA invariant, not a placement
    # constraint. It is caught by data.check() before solving and re-checked
    # by verify.py on the finished file. A CP-SAT constraint here would always
    # be trivially true and would give false confidence.
    ("H10 over contracted hours", case_H10_contract_hours, "validator"),
    ("H15 daylight cutoff", case_H15_daylight, "solver"),
    ("H17 max 6 hours a day", case_H17_six_hour_day, "solver"),
    ("LOCK conflicting pins", case_LOCK_conflict, "solver"),
]


def main():
    print("")
    print("Deliberate-failure tests. Each rule must BREAK the school when")
    print("violated, and stop breaking it when relaxed.")
    print("")
    print("  %-28s %-9s %-20s %-11s" % ("rule", "must be", "caught by", "relaxed"))
    print("  " + "-" * 82)

    bad = 0
    for label, fn, must in CASES:
        broken, relaxed = fn()
        by_validator = status(broken) == "DATA_ERROR"
        st_solver = status(broken, skip_check=True)
        st_relax = status(relaxed, skip_check=True)

        by_solver = st_solver.startswith("INFEASIBLE")
        relax_ok = st_relax in ("OPTIMAL", "FEASIBLE")
        if must == "solver":
            ok = by_solver and relax_ok
        else:
            ok = by_validator and relax_ok
        if not ok:
            bad += 1
        caught = []
        if by_validator:
            caught.append("validator")
        if by_solver:
            caught.append("solver")
        print("  %-28s %-9s %-20s %-11s %s"
              % (label, must, "+".join(caught) or "NOTHING", st_relax,
                 "ok" if ok else "<-- FAILED"))
        if must == "solver" and by_validator and not by_solver:
            print("      ^ only the validator stops this, but it is supposed to")
            print("        be a placement constraint. Anything bypassing the")
            print("        validator would slip through. Wire it into build().")
        if not ok and not (by_validator or by_solver):
            print("      ^ NOTHING stopped an impossible school. The rule is")
            print("        written down but not enforced anywhere.")
        if not relax_ok:
            print("      ^ relaxing did not help - the test is not measuring")
            print("        what it claims. Fix the test, not the solver.")

    ok5, msg5 = check_H5_hours_delivered()
    if not ok5:
        bad += 1
    print("  %-28s %-9s %-20s %-11s %s"
          % ("H5  hours delivered exactly", "output", "output count", "-",
             "ok" if ok5 else "<-- FAILED"))
    if not ok5:
        print("      ^ " + msg5)

    okr, msgr = check_rescue_mode()
    if not okr:
        bad += 1
    print("  %-28s %-9s %-20s %-11s %s"
          % ("RESCUE declared exceptions", "output", "exception vars", "-",
             "ok" if okr else "<-- FAILED"))
    print("      ^ " + msgr)

    print("")
    if bad:
        print("%d RULE(S) NOT PROPERLY ENFORCED. Do not trust the output." % bad)
        return 1
    print("All %d hard rules proven enforced (plus rescue-mode honesty)." % (len(CASES) + 1))
    print("(This proves the rules are WIRED UP. Whether each rule says what")
    print(" Majd meant is a separate question - that is what RULES.md is for.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

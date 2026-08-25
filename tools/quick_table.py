# -*- coding: utf-8 -*-
"""Build a timetable the way a human does: one card at a time, never breaking
a rule.

Majd, 2026-08-25:
    "when i make the table i regard all rules before placing any ricket -
     you don't do that, you do whatever then you spend an age fixing and
     it's always wrong"
    "couldn't u write a stupid code for this - its a python code cant u
     write it"

He is right, and this is that code. No solver, no objective function, no
hour-long search. For every card:

    1. work out EVERY slot where the card would break no rule
    2. score those slots by how comfortable they are
    3. put the card in the best one
    4. move to the next card

A card is never placed somewhere illegal, so there is nothing to repair
afterwards. When a card has no legal slot at all, the placer displaces a card
that is in the way and re-places it (the way a human lifts one card to make
room), and if that fails it says so instead of pretending.

This will NOT beat the CP-SAT solver on comfort - it never backtracks far
enough for that. What it gives is a legal, readable timetable in SECONDS, and
an honest floor: whatever this produces, the real solver must beat.

    python tools/quick_table.py                          (this year)
    python tools/quick_table.py data/school_lastyear.xlsx
    python tools/quick_table.py data/school_lastyear.xlsx --tries=40
"""
import collections
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "solver"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import data as D          # noqa: E402
import solve as S         # noqa: E402
import emit_asc           # noqa: E402
import emit_html          # noqa: E402

OUT = os.path.join(HERE, "out")


def wks(se):
    """The weeks a session occupies. A normal weekly session fills both."""
    return ("A", "B") if not se.week else (se.week,)


class Board:
    """Who is where. Every question a rule needs to ask, answered in O(1)."""

    def __init__(self, s):
        self.s = s
        self.cfg = s.cfg
        self.days = list(s.cfg.days)
        self.open_p = {d: sorted(p for (dd, p) in s.cfg.slots if dd == d)
                       for d in self.days}
        self.open_set = set(s.cfg.slots)
        self.cls = collections.defaultdict(set)    # (cid,d,p,w) -> {groups}
        self.tch = {}                              # (tid,d,p,w) -> sid
        self.rt = collections.Counter()            # (type,d,p,w) -> count
        self.tday = collections.Counter()          # (tid,d,w) -> hours
        self.place = {}                            # sid -> (day, start)

        self.n_room = {t: len(s.rooms_of_type(t)) for t in
                       {r["type"] for r in s.rooms.values()}}
        self.n_spare = sum(self.n_room.get(t, 0) for t in D.SPARE_FOR_NORMAL)
        self.n_normal = self.n_room.get("normal", 0)
        # H15 / subject deadlines
        self.latest = {}
        for sid_, sub in s.subjects.items():
            try:
                self.latest[sid_] = int(sub.get("latest_period") or 0)
            except (TypeError, ValueError):
                self.latest[sid_] = 0
        self.offdays = {}
        for tid, t in s.teachers.items():
            bad = set()
            for k in ("day_off", "training_day"):
                v = (t.get(k) or "").strip()
                if v and v != "(none)":
                    bad.add(v)
            self.offdays[tid] = bad

    # ---- the rules, asked one card at a time ---------------------------
    def starts(self, se):
        """Every (day, first period) where this session physically fits."""
        out = []
        for d in self.days:
            ps = self.open_p[d]
            for p in ps:
                if all((p + k) in ps for k in range(se.length)):
                    out.append((d, p))
        return out

    def legal(self, se, d, p0):
        """True when placing se at (d, p0) breaks NO hard rule."""
        if se.teacher_id and d in self.offdays.get(se.teacher_id, ()):
            return False
        late = self.latest.get(se.subject_id, 0)
        if late and p0 + se.length - 1 > late:
            return False
        weeks = wks(se)
        for k in range(se.length):
            p = p0 + k
            if (d, p) not in self.open_set:
                return False
            for w in weeks:
                # H2: the class (or this group of it) is free
                here = self.cls.get((se.class_id, d, p, w))
                if here:
                    if se.group == 0 or 0 in here or se.group in here:
                        return False
                # H1: the teacher is free
                if se.teacher_id and (se.teacher_id, d, p, w) in self.tch:
                    return False
                # H4/H6: a room of the right kind is still available
                if not self._room_ok(se, d, p, w):
                    return False
        # H17: never more than 6 hours in one day
        if se.teacher_id:
            for w in weeks:
                if self.tday[se.teacher_id, d, w] + se.length > 6:
                    return False
        return True

    def _room_ok(self, se, d, p, w):
        t = se.room_type
        if t == "__opt__":
            return True
        if t != "normal":
            return self.rt[t, d, p, w] + 1 <= self.n_room.get(t, 0)
        used = self.rt["normal", d, p, w] + 1
        borrowed = sum(self.rt[x, d, p, w] for x in D.SPARE_FOR_NORMAL)
        return used + borrowed <= self.n_normal + self.n_spare

    # ---- putting a card down, and lifting it again ----------------------
    def put(self, se, d, p0):
        for k in range(se.length):
            p = p0 + k
            for w in wks(se):
                self.cls[se.class_id, d, p, w].add(se.group)
                if se.teacher_id:
                    self.tch[se.teacher_id, d, p, w] = se.sid
                if se.room_type != "__opt__":
                    self.rt[se.room_type, d, p, w] += 1
        if se.teacher_id:
            for w in wks(se):
                self.tday[se.teacher_id, d, w] += se.length
        self.place[se.sid] = (d, p0)

    def lift(self, se):
        d, p0 = self.place.pop(se.sid)
        for k in range(se.length):
            p = p0 + k
            for w in wks(se):
                self.cls[se.class_id, d, p, w].discard(se.group)
                if se.teacher_id:
                    self.tch.pop((se.teacher_id, d, p, w), None)
                if se.room_type != "__opt__":
                    self.rt[se.room_type, d, p, w] -= 1
        if se.teacher_id:
            for w in wks(se):
                self.tday[se.teacher_id, d, w] -= se.length
        return d, p0

    # ---- how GOOD is a legal slot (lower is better) ---------------------
    def score(self, se, d, p0):
        pen = 0
        ps = self.open_p[d]
        last = ps[-1]
        w0 = wks(se)[0]

        # pupils: glue the card to what the class already has that day, and
        # never leave a one-hour island
        cls_here = [p for p in ps
                    if self.cls.get((se.class_id, d, p, w0))]
        if cls_here:
            gap = min(abs(p0 - q) for q in cls_here)
            pen += 0 if gap <= se.length else 40 * gap      # holes hurt
        # teachers: the same, and a lone hour is the thing Majd hates most
        if se.teacher_id:
            t_here = [p for p in ps
                      if self.tch.get((se.teacher_id, d, p, w0))]
            after = self.tday[se.teacher_id, d, w0] + se.length
            if after == 1:
                pen += 900                       # a whole day for one hour
            if t_here:
                gap = min(abs(p0 - q) for q in t_here)
                pen += 0 if gap <= se.length else 55 * gap
            else:
                # a brand-new day for this teacher: mild, they add up
                pen += 25
        # groups of one row belong back to back, same day
        if se.group >= 2:
            for other, (od, op) in self.place.items():
                if other.startswith("%s|%s|" % (se.class_id, se.subject_id)):
                    if od != d:
                        pen += 300
                    elif abs(op - p0) != se.length:
                        pen += 120
                    break
        if p0 + se.length - 1 >= last:
            pen += 45                            # the last hour of the day
        pen += 3 * self.days.index(d)            # fill the week from Monday
        return pen


def build_once(s, sessions, order, board_cls=Board):
    """One full pass: place every card, best legal slot first."""
    b = board_cls(s)
    starts = {se.sid: b.starts(se) for se in sessions}
    by_sid = {se.sid: se for se in sessions}
    unplaced = []
    same_day_block = collections.defaultdict(set)   # (cid,subj,group) -> days

    for se in order:
        key = (se.class_id, se.subject_id, se.group)
        best, best_pen = None, None
        for d, p0 in starts[se.sid]:
            # H9: two blocks of one subject never share a day
            if d in same_day_block[key]:
                continue
            if not b.legal(se, d, p0):
                continue
            pen = b.score(se, d, p0)
            if best_pen is None or pen < best_pen:
                best, best_pen = (d, p0), pen
        if best is None:
            # nothing legal: lift ONE card that is in the way and try again,
            # exactly like sliding a card aside by hand
            best = _make_room(b, se, starts, by_sid, same_day_block)
        if best is None:
            unplaced.append(se)
            continue
        b.put(se, *best)
        same_day_block[key].add(best[0])
    return b, unplaced


def _make_room(b, se, starts, by_sid, same_day_block):
    """Lift one blocking card, place ours, then re-place the lifted one."""
    for d, p0 in starts[se.sid]:
        if d in same_day_block[(se.class_id, se.subject_id, se.group)]:
            continue
        blockers = set()
        for k in range(se.length):
            p = p0 + k
            for w in wks(se):
                if se.teacher_id:
                    other = b.tch.get((se.teacher_id, d, p, w))
                    if other:
                        blockers.add(other)
        if len(blockers) != 1:
            continue
        victim = by_sid[blockers.pop()]
        vkey = (victim.class_id, victim.subject_id, victim.group)
        vd, _vp = b.lift(victim)
        same_day_block[vkey].discard(vd)
        if b.legal(se, d, p0):
            b.put(se, d, p0)
            for d2, q2 in starts[victim.sid]:
                if d2 in same_day_block[vkey]:
                    continue
                if b.legal(victim, d2, q2):
                    b.put(victim, d2, q2)
                    same_day_block[vkey].add(d2)
                    return (d, p0)
            b.lift(se)                       # could not re-home the victim
        b.put(victim, vd, _vp)               # put everything back
        same_day_block[vkey].add(vd)
    return None


def orders(sessions, tries):
    """Different orders to try. Hardest cards first is the human instinct:
    long blocks, special rooms and split groups have the fewest homes."""
    def hardness(se):
        special = 0 if se.room_type in ("normal", "__opt__") else 1
        return (-special, -se.length, -se.group, se.sid)

    base = sorted(sessions, key=hardness)
    yield base
    rng = random.Random(20260825)
    for _ in range(max(0, tries - 1)):
        shuffled = list(base)
        # jiggle only within the hardness bands, so hard cards stay first
        for i in range(0, len(shuffled), 25):
            chunk = shuffled[i:i + 25]
            rng.shuffle(chunk)
            shuffled[i:i + 25] = chunk
        yield shuffled


def comfort(b, s, sessions):
    """The numbers Majd actually judges a table by."""
    by_sid = {se.sid: se for se in sessions}
    lone_days = lone_halves = holes = 0
    evening = set(s.cfg.evening)
    per = collections.defaultdict(list)        # (tid,d,w) -> periods
    for sid_, (d, p0) in b.place.items():
        se = by_sid[sid_]
        if not se.teacher_id:
            continue
        for w in wks(se):
            per[se.teacher_id, d, w].extend(range(p0, p0 + se.length))
    for (_t, _d, _w), ps in per.items():
        if len(ps) == 1:
            lone_days += 1
        for half in (0, 1):
            hp = sorted(p for p in ps if (p in evening) == bool(half))
            if len(hp) == 1:
                lone_halves += 1
            elif len(hp) > 1:
                holes += (hp[-1] - hp[0] + 1) - len(hp)
    return dict(lone_days=lone_days / 2.0, lone_halves=lone_halves / 2.0,
                teacher_holes=holes / 2.0)


def main():
    t0 = time.time()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tries = 12
    for a in sys.argv[1:]:
        if a.startswith("--tries="):
            tries = int(a.split("=", 1)[1])

    cfg = D.load_config()
    s = D.load_school(args[0] if args else None, cfg)
    errs, notes = D.check(s)
    for n in notes[:3]:
        print("NOTE :", n)
    if errs:
        for e in errs:
            print("ERROR:", e)
        return 1

    sessions = S.expand(s)
    print("\nPlacing %d cards, one at a time, never breaking a rule."
          % sum(se.length for se in sessions))

    best = None
    for n, order in enumerate(orders(sessions, tries), start=1):
        b, unplaced = build_once(s, sessions, order)
        c = comfort(b, s, sessions)
        # fewest cards left over first, then the most comfortable week
        rank = (len(unplaced), c["lone_days"] * 100 + c["lone_halves"] * 60
                + c["teacher_holes"])
        print("   try %2d: %4d card(s) with no legal slot | lone days %.1f | "
              "lonely halves %.1f | teacher holes %.1f"
              % (n, len(unplaced), c["lone_days"], c["lone_halves"],
                 c["teacher_holes"]), flush=True)
        if best is None or rank < best[0]:
            best = (rank, b, unplaced, c)

    _rank, b, unplaced, c = best
    placement = {}
    by_sid = {se.sid: se for se in sessions}
    for sid_, (d, p0) in b.place.items():
        se = by_sid[sid_]
        for k in range(se.length):
            placement[S.uid_of(se, k)] = [d, p0 + k]

    # assign_rooms expects every session it is given to be placed, so hand it
    # only the ones that found a home. A card left out has no room either.
    placed_sessions = [se for se in sessions
                       if all(S.uid_of(se, k) in placement
                              for k in range(se.length))]
    units = [u for u in S.hour_units(placed_sessions) if u.uid in placement]
    rooms = S.assign_rooms(s, placed_sessions, placement)
    os.makedirs(OUT, exist_ok=True)
    xml = os.path.join(OUT, "quick_timetable.xml")
    htm = os.path.join(OUT, "quick_view.html")
    emit_asc.write(s, units, placement, rooms, xml)
    emit_html.write(s, units, placement, rooms, htm)

    print("\n  %d of %d lesson-hours placed in %.1f seconds."
          % (len(placement), sum(se.length for se in sessions),
             time.time() - t0))
    print("  teacher lone-hour days   %.1f per week" % c["lone_days"])
    print("  teacher lonely half-days %.1f per week" % c["lone_halves"])
    print("  teacher hole-hours       %.1f per week" % c["teacher_holes"])
    if unplaced:
        print("\n  %d card(s) had NO legal slot and were left out - the table "
              "is incomplete:" % len(unplaced))
        for se in unplaced[:12]:
            print("     %s / %s (%dh)"
                  % (s.classes.get(se.class_id, {}).get("name", se.class_id),
                     s.subjects.get(se.subject_id, {}).get("name",
                                                           se.subject_id),
                     se.length))
    print("\n  open:  out/quick_view.html")
    print("  aSc:   out/quick_timetable.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())

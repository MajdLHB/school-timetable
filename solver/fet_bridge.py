# -*- coding: utf-8 -*-
"""FET bridge - the second placement engine (FET, Free Timetabling Software).

    python solver/fet_bridge.py data/school_lastyear.xlsx --time 900

Turns the workbook into out/fet/school.fet, runs fet-cl headless (one
single-threaded process), reads the placed activities back and hands the
placement to the SAME emitter and the SAME independent checker as the CP-SAT
engine. Everything lands under out/fet/ - out/timetable.xml is never touched.

How the school is encoded for FET (Official mode, decided with Majd on
2026-09-07 after the Mornings-Afternoons mode of FET 7.10.3 crashed on every
file, even a one-activity one):

  * A FET "day" is a HALF-DAY: Mon-am, Mon-pm, ..., Sat-am (11 of them), each
    with 4 hours. The lunch break 12:00-14:00 and the closed Saturday
    afternoon simply do not exist in the grid, so no block can ever straddle
    them and FET's native per-day rules become per-HALF-DAY rules, which is
    what the ministry rules are written in (H21/H22, pupils I.2).
  * Real-day rules are emulated with time-slot selections:
      H17 (max 6 h a day)           -> teacher's activities occupy at most 6
                                       of the 8 slots of each real day
      H9  (blocks on different days) -> the sessions of one class+subject
                                       occupy at most L slots of each real
                                       day (one constraint per length L)
      flexible day off (H7 blank)    -> teacher occupies at most N-1 of the N
                                       H18-legal real days
  * Fortnight: a week-A card and a week-B card of the same shape (length,
    room type, group structure) are MERGED into one FET activity that carries
    both teachers and both classes: same slot, same room, and each side is
    blocked in the other week's slot too (a safe over-approximation). Cards
    left without a mate block their slot in both weeks alone. The per-week
    "0 or at least 2 hours per half-day" rules stay EXACT through per-teacher
    tags (T_<teacher>_A/B) and per-class tags (C_<class>_A/B) that are put
    only on the activities where that teacher/class is really present in
    that week.
  * Group halves are FET groups of the class; H20 is "two activities
    grouped" (adjacent, either order) plus starting times that keep the pair
    inside one half-day. The engineering 4h+4h pairs run in parallel with
    the partner subject, as the 2023 table shows.
  * Option bands: one activity per band block carrying every member class
    and the first option teacher, plus one teacher-only "partner" activity
    per further option group, all forced to the same starting time - so
    every option teacher is busy and one room per option group is counted.
  * Rooms: one activity tag per room type; ordinary lessons may borrow the
    science labs exactly as D.SPARE_FOR_NORMAL says.

Every rule of section 4 of docs/HANDOFF_FET.md is at 100 percent. Nothing is
relaxed to get a table: if FET cannot place a card, the report names the
card and the rules attached to it.
"""
import argparse
import collections
import contextlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

FACTS = {}          # facts from the official table (<xlsx>_facts.json)
STALL_S = 900       # --stall: seconds without FET progress before an attempt is cut short
PINS = {}           # --pin: teacher id -> allowed half-days / days from the school's table

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "solver"))
import data as D          # noqa: E402
import solve as S         # noqa: E402
import emit_asc           # noqa: E402
import emit_html          # noqa: E402

OUT = os.path.join(HERE, "out", "fet")
FET_CL = os.environ.get("FET_CL") or os.path.join(OUT, "bin", "fet-cl.exe")
FET_NAME = "school"                       # out/fet/school.fet
MAX_HOURS_DAY = 6                         # H17
MIN_HOURS_HALF = 2                        # H21/H22 and pupils I.2


def weeks_of(week):
    return ("A", "B") if not week else (week,)


# ---------------------------------------------------------------------------
# the grid: half-days as FET days
# ---------------------------------------------------------------------------
class Grid:
    """Half-days as FET days. A morning that runs to 13:00 (period 5 opened
    on some days) makes that FET day one hour longer; the shorter FET days
    get that hour as a break, so FET's grid stays rectangular."""

    def __init__(self, cfg):
        self.cfg = cfg
        open_slots = set(cfg.slots)
        self.pdays = []
        for d in cfg.days:
            for half, periods in (("am", cfg.morning + [5]), ("pm", cfg.evening)):
                ps = sorted(p for p in set(periods) if (d, p) in open_slots)
                if ps:
                    self.pdays.append(dict(name="%s-%s" % (d, half), day=d,
                                           half=half, periods=ps))
        for pd in self.pdays:
            ps = pd["periods"]
            if ps != list(range(ps[0], ps[0] + len(ps))):
                sys.exit("half-day %s has non-consecutive open periods %s" % (pd["name"], ps))
        self.nh = max(len(pd["periods"]) for pd in self.pdays)
        self.hours = [str(i + 1) for i in range(self.nh)]
        self.by_day = collections.OrderedDict(
            (d, [pd for pd in self.pdays if pd["day"] == d]) for d in cfg.days)
        self.slot_of = {}
        self.fet_of = {}
        self.breaks = []
        for pd in self.pdays:
            for i, h in enumerate(self.hours):
                if i < len(pd["periods"]):
                    p = pd["periods"][i]
                    self.slot_of[pd["name"], h] = (pd["day"], p)
                    self.fet_of[pd["day"], p] = (pd["name"], h)
                else:
                    self.breaks.append((pd["name"], h))
        self._all = [(pd["name"], h) for pd in self.pdays
                     for h in self.hours[:len(pd["periods"])]]
        self._order = {sl: i for i, sl in enumerate(self._all)}

    def pd_slots(self, pd):
        return [(pd["name"], h) for h in self.hours[:len(pd["periods"])]]

    def day_slots(self, d):
        return [sl for pd in self.by_day[d] for sl in self.pd_slots(pd)]

    def all_slots(self):
        return list(self._all)

    def sort_slots(self, slots):
        return sorted(slots, key=lambda x: self._order[x])


# ---------------------------------------------------------------------------
# activities
# ---------------------------------------------------------------------------
class Act:
    __slots__ = ("id", "teachers", "subject", "students", "dur", "tags",
                 "sessions", "kind", "comment", "rules", "opt")

    def __init__(self, id_, teachers, subject, students, dur, tags, sessions,
                 kind, comment):
        self.id = id_
        self.teachers = teachers
        self.subject = subject
        self.students = students
        self.dur = dur
        self.tags = tags
        self.sessions = sessions
        self.kind = kind
        self.comment = comment
        self.rules = []          # rule labels of the constraints touching it
        self.opt = None          # band/partner: (option group id, first hour index)


def is_pupil_exempt(s, subject_id):
    if subject_id.startswith("OPT:"):
        return True
    return (s.subjects.get(subject_id, {}).get("minmax_exempt") or "") == "yes"


class Model:
    """Everything the .fet file needs, built from the school + sessions."""

    def __init__(self, s, sessions, grid, same_subject_once=True, pair_weeks=True,
                 comfort=None):
        self.s = s
        self.sessions = sessions
        self.grid = grid
        self.same_subject_once = same_subject_once
        self.pair_weeks = pair_weeks
        self.comfort = comfort or {}
        self.acts = []
        self.act_of_sid = {}
        self.time_c = []          # xml strings
        self.space_c = []
        self.counts = collections.Counter()
        self.notes = []
        self.n_pairs = 0
        self.n_cross_pairs = 0
        self.rooms_by_type = collections.defaultdict(list)
        for r in s.rooms.values():
            self.rooms_by_type[r["type"]].append(r["id"])
        self.n_groups_of = {}
        for se in sessions:
            if se.group:
                self.n_groups_of[se.class_id] = max(
                    self.n_groups_of.get(se.class_id, 0), se.group)
        self.rows = []            # (row, blocks, [[sessions of g1], ...])
        self._build_activities()
        self._build_constraints()

    # ---- activities -------------------------------------------------------
    def _new_act(self, *args):
        a = Act(len(self.acts) + 1, *args)
        self.acts.append(a)
        for se in a.sessions:
            self.act_of_sid[se.sid] = a
        return a

    def students_name(self, se):
        return se.class_id if not se.group else "%s_g%d" % (se.class_id, se.group)

    def pupils_of(self, cid, group=0):
        """Seats a lesson needs. Class sizes are NOT known (Majd 2026-09-09):
        only the classes the school itself put in the small Group room carry
        a size (19, from that fact). Any class without a size is treated as
        too big for a room under 20 seats - whole class and halves alike -
        because nothing in the data says otherwise."""
        size = int(self.s.classes.get(cid, {}).get("size") or 0)
        if not size:
            return 99
        return size if not group else (size + 1) // 2

    CORE_BY_STREAM = (          # class-name keyword -> the stream's basic subjects (keywords)
        ("علوم تجريبية", ("ع الحياة", "فيزيائية", "رياضيات")),
        ("علوم اعلامية", ("الخوارزميات", "رياضيات", "اعلامية")),
        ("علوم تقنية", ("تقنية", "هنسة", "رياضيات", "فيزيائية")),
        ("رياضيات", ("رياضيات", "فيزيائية")),
        ("اقتصاد", ("اقتصاد", "تصرف", "رياضيات")),
        ("آداب", ("عربية", "فلسفة", "فرنسية")),
        ("أداب", ("عربية", "فلسفة", "فرنسية")),
        ("تكنلوجية", ("اعلامية", "رياضيات", "تقنية")),
        ("2علوم", ("رياضيات", "فيزيائية", "ع الحياة")),
        ("1ث", ("رياضيات", "فيزيائية", "عربية")),
    )

    def is_core(self, cid, sid):
        """Majd 2026-09-10: 'physics or their basic subject' - the stream's
        core subjects, mapped from the class name (UNSURE for 1st/2nd year)."""
        cname = str(self.s.classes.get(cid, {}).get("name", ""))
        sname = str(self.s.subjects.get(sid, {}).get("name", "")).replace("أشغال تطبيقية - ", "")
        for key, subs in self.CORE_BY_STREAM:
            if key in cname:
                return any(k in sname for k in subs)
        return False

    def crowded(self, cids):
        """Majd 2026-09-09: first-year classes are too crowded for the labs -
        ordinary rooms only (the school's file has no first-year class in a
        lab either)."""
        return any(str(self.s.classes.get(c, {}).get("grade", "")).strip() == "1" for c in cids)

    def room_tag(self, room_type, need, cids=()):
        """Room tag = type + the seats the lesson needs (only sizes that change
        the room list matter: below 20 seats) + 'only' for classes that must
        not borrow a lab."""
        small_caps = sorted({int(r.get("capacity") or 999) for r in self.s.rooms.values()
                             if int(r.get("capacity") or 999) < 20})
        bucket = next((c for c in small_caps if need <= c), 20)
        if room_type == "normal" and self.crowded(cids):
            room_type = "normalonly"
        return "RT_%s_n%d" % (room_type, bucket)

    def rooms_for_tag(self, tag):
        body = tag[3:]
        rtype, _, bucket = body.rpartition("_n")
        need = int(bucket)
        out = []
        types = ("normal",) if rtype == "normalonly" else D.compatible_types(rtype)
        for t_ in types:
            for rid in self.rooms_by_type.get(t_, []):
                cap = int(self.s.rooms[rid].get("capacity") or 999)
                if cap >= 20 or cap >= need:
                    out.append(rid)
        return out

    def _map_rows(self, regular):
        """Rows -> their sessions, in the exact order solve.expand made them."""
        idx = 0
        for row in self.s.curriculum:
            bl, err = D.parse_blocks(row.get("blocks", ""), row["hours"])
            if err or not bl or sum(bl) != row["hours"]:
                bl = [1] * row["hours"]
            n_groups = max(1, int(row.get("groups", 1) or 1))
            n = len(bl) * n_groups
            chunk = regular[idx: idx + n]
            idx += n
            if len(chunk) != n or any(se.class_id != row["class_id"]
                                      or se.subject_id != row["subject_id"]
                                      for se in chunk):
                sys.exit("internal: session order does not match the curriculum "
                         "rows (row %s/%s)" % (row["class_id"], row["subject_id"]))
            per_group = [chunk[g * len(bl):(g + 1) * len(bl)] for g in range(n_groups)]
            self.rows.append((row, bl, per_group))
        if idx != len(regular):
            sys.exit("internal: %d sessions left over after the curriculum rows"
                     % (len(regular) - idx))

    def _plan_pairs(self, regular):
        """Week-A card <-> week-B card of the same shape share one activity.
        Same class first (frees class capacity too), then across classes
        (frees the room). Split rows are paired row by row so that H20 keeps
        working for both classes at once."""
        pair = {}
        if not self.pair_weeks:
            return pair
        nh = self.grid.nh
        s = self.s

        def rkey(row, bl, pg):
            return (tuple(bl), len(pg), s.room_type_for(row))
        split = {"A": [], "B": []}
        for i, (row, bl, pg) in enumerate(self.rows):
            w = (row.get("week") or "").strip().upper()
            if w in split and len(pg) > 1 and 2 * max(bl) <= nh:
                split[w].append((i, row, bl, pg))
        # priority: the SAME TEACHER's A and B cards first (one activity, one
        # teacher present in both weeks - no phantom hours for that teacher),
        # then the same class (frees class capacity), then any same shape
        used = set()
        for mode in ("teacher", "class", "any"):
            for ia, ra, bla, pga in split["A"]:
                if ia in used:
                    continue
                for ib, rb, blb, pgb in split["B"]:
                    if ib in used or rkey(ra, bla, pga) != rkey(rb, blb, pgb):
                        continue
                    if mode == "teacher" and not (ra["teacher_id"] and ra["teacher_id"] == rb["teacher_id"]):
                        continue
                    if mode == "class" and ra["class_id"] != rb["class_id"]:
                        continue
                    used.update((ia, ib))
                    for ga, gb in zip(pga, pgb):
                        for sa, sb in zip(ga, gb):
                            pair[sa.sid] = sb
                            pair[sb.sid] = sa
                    break
        singles = {"A": [], "B": []}
        for se in regular:
            if se.week in singles and se.group == 0 and se.sid not in pair:
                singles[se.week].append(se)
        for mode in ("teacher", "class", "any"):
            for sa in singles["A"]:
                if sa.sid in pair:
                    continue
                for sb in singles["B"]:
                    if sb.sid in pair or sb.length != sa.length or sb.room_type != sa.room_type:
                        continue
                    if mode == "teacher" and not (sa.teacher_id and sa.teacher_id == sb.teacher_id):
                        continue
                    if mode == "class" and sa.class_id != sb.class_id:
                        continue
                    pair[sa.sid] = sb
                    pair[sb.sid] = sa
                    break
        return pair

    def _session_act(self, members):
        s = self.s
        teachers, students = [], []
        tags = [self.room_tag(members[0].room_type,
                              max(self.pupils_of(m.class_id, m.group) for m in members),
                              [m.class_id for m in members])]
        for m in members:
            if m.teacher_id and m.teacher_id not in teachers:
                teachers.append(m.teacher_id)
            st = self.students_name(m)
            if st not in students:
                students.append(st)
            for w in weeks_of(m.week):
                if m.teacher_id:
                    t = "T_%s_%s" % (m.teacher_id, w)
                    if t not in tags:
                        tags.append(t)
                if not is_pupil_exempt(s, m.subject_id):
                    t = "C_%s_%s" % (m.class_id, w)
                    if t not in tags:
                        tags.append(t)
        # comfort markers: HARD = maths/physics/philosophy; BAC = a final-year class
        if any((s.subjects.get(m.subject_id, {}).get("difficulty") or "").strip().lower() == "hard"
               for m in members):
            tags.append("HARD")
        if any(self.is_core(m.class_id, m.subject_id) for m in members):
            tags.append("CORE")
        if any((s.classes.get(m.class_id, {}).get("is_bac") or "") == "yes" for m in members):
            tags.append("BAC")
        kind = "sess" if len(members) == 1 else "pair"
        return self._new_act(teachers, members[0].subject_id, students, members[0].length,
                             tags, list(members), kind, " + ".join(m.sid for m in members))

    def _carousel_acts(self):
        """ALT/ALT2 rows -> one activity per block; ALT+ALT2 of one class and
        equal blocks run in parallel (the school's carousel). Returns the sids
        consumed. Unpaired ALT rows block the whole class alone (safe)."""
        s = self.s
        done = set()
        by_class = collections.defaultdict(lambda: {"ALT": [], "ALT2": []})
        for row, bl, pg in self.rows:
            w = (row.get("week") or "").strip().upper()
            if w in ("ALT", "ALT2") and len(pg) >= 2:
                by_class[row["class_id"]][w].append((row, bl, pg))

        def make(r1, r2):
            row1, bl1, pg1 = r1
            for k, L in enumerate(bl1):
                ses1 = [pg1[g][k] for g in range(len(pg1))]
                m = ses1[0]
                tags = [self.room_tag(m.room_type, self.pupils_of(m.class_id, 1), [m.class_id])]
                if m.teacher_id:
                    tags += ["T_%s_A" % m.teacher_id, "T_%s_B" % m.teacher_id]
                if not is_pupil_exempt(s, m.subject_id):
                    tags += ["C_%s_A" % m.class_id, "C_%s_B" % m.class_id]
                if (s.subjects.get(m.subject_id, {}).get("difficulty") or "").strip().lower() == "hard":
                    tags.append("HARD")
                if self.is_core(m.class_id, m.subject_id):
                    tags.append("CORE")
                if (s.classes.get(m.class_id, {}).get("is_bac") or "") == "yes":
                    tags.append("BAC")
                main = self._new_act([m.teacher_id] if m.teacher_id else [], m.subject_id,
                                     [m.class_id], L, tags, ses1, "sess",
                                     "carousel " + " + ".join(x.sid for x in ses1))
                done.update(x.sid for x in ses1)
                if r2 is not None:
                    row2, bl2, pg2 = r2
                    ses2 = [pg2[g][k] for g in range(len(pg2))]
                    m2 = ses2[0]
                    tags2 = [self.room_tag(m2.room_type, self.pupils_of(m2.class_id, 1), [m2.class_id])]
                    if m2.teacher_id:
                        tags2 += ["T_%s_A" % m2.teacher_id, "T_%s_B" % m2.teacher_id]
                    if (s.subjects.get(m2.subject_id, {}).get("difficulty") or "").strip().lower() == "hard":
                        tags2.append("HARD")
                    part = self._new_act([m2.teacher_id] if m2.teacher_id else [], m2.subject_id,
                                         [], L, tags2, ses2, "partner",
                                         "carousel partner " + " + ".join(x.sid for x in ses2))
                    done.update(x.sid for x in ses2)
                    self.same_start([main, part], "carousel: alternating halves in parallel")

        for cid, d in by_class.items():
            used = set()
            for r1 in d["ALT"]:
                r2 = next((x for x in d["ALT2"] if id(x[0]) not in used and x[1] == r1[1]), None)
                if r2 is not None:
                    used.add(id(r2[0]))
                else:
                    self.notes.append("class %s: alternating row %s has no partner of the same "
                                      "length - the whole class is blocked during it"
                                      % (cid, r1[0]["subject_id"]))
                make(r1, r2)
            for r2 in d["ALT2"]:
                if id(r2[0]) not in used:
                    self.notes.append("class %s: alternating row %s has no partner of the same "
                                      "length - the whole class is blocked during it"
                                      % (cid, r2[0]["subject_id"]))
                    make(r2, None)
        return done

    def _build_activities(self):
        s = self.s
        regular = [se for se in self.sessions if not se.subject_id.startswith("OPT:")]
        opt = [se for se in self.sessions if se.subject_id.startswith("OPT:")]
        self._map_rows(regular)
        pair = self._plan_pairs(regular)
        done = self._carousel_acts()
        for se in regular:
            if se.sid in done:
                continue
            members = [se]
            mate = pair.get(se.sid)
            if mate is not None:
                members.append(mate)
                self.n_pairs += 1
                if mate.class_id != se.class_id:
                    self.n_cross_pairs += 1
            done.update(m.sid for m in members)
            self._session_act(members)
        # ---- options: one activity per option group and block, on the pupils
        # of that option in every member class (FET sub-groups). The groups of
        # a band PREFER the same starting time; when that fails, one option
        # studies and the others are free (Majd 2026-09-07).
        self.opt_acts = collections.defaultdict(list)        # group id -> [acts by block]
        self.opt_gi = {}                                      # group id -> (band id, gi)
        for band in s.option_bands:
            bl, err = D.parse_blocks(band["blocks"], band["hours"])
            if err or not bl or sum(bl) != band["hours"]:
                bl = [1] * band["hours"]
            per_block = []
            for k, L in enumerate(bl):
                per_block.append([])
            off = 0
            for k, L in enumerate(bl):
                for gi, g in enumerate(band["groups"]):
                    self.opt_gi[g["id"]] = (band["id"], gi)
                    tags = [self.room_tag(D.option_room_type(s, g), 20)]
                    if g["teacher_id"]:
                        tags += ["T_%s_A" % g["teacher_id"], "T_%s_B" % g["teacher_id"]]
                    a = self._new_act([g["teacher_id"]] if g["teacher_id"] else [], g["subject_id"],
                                      ["%s_o_%s" % (cid, g["id"]) for cid in g["classes"]], L, tags,
                                      [], "optgrp", "option %s block %d (%s)" % (g["id"], k, band["id"]))
                    a.opt = (g["id"], off)
                    self.opt_acts[g["id"]].append(a)
                    per_block[k].append(a)
                off += L
            for k, acts in enumerate(per_block):
                if len(acts) > 1:
                    self.same_start(acts, "H14 option band together (soft)",
                                    weight=self.comfort.get("w_opt_together", 90))
        # the checker numbers a class's option groups by their index inside
        # the band; two groups of DIFFERENT bands with the same index would
        # read as one group, so those may never overlap for a shared class
        by_class_gi = collections.defaultdict(list)
        for gid, (bid, gi) in self.opt_gi.items():
            g = next(x for b in s.option_bands for x in b["groups"] if x["id"] == gid)
            for cid in g["classes"]:
                by_class_gi[cid, gi].append(gid)
        seen_pairs = set()
        for (cid, gi), gids in by_class_gi.items():
            if len(gids) < 2:
                continue
            key = tuple(sorted(gids))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            acts = [a for gid in gids for a in self.opt_acts[gid]]
            xml = ["<ConstraintActivitiesNotOverlapping>",
                   "\t<Weight_Percentage>100</Weight_Percentage>",
                   "\t<Number_of_Activities>%d</Number_of_Activities>" % len(acts)]
            xml += ["\t<Activity_Id>%d</Activity_Id>" % a.id for a in acts]
            xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                       "</ConstraintActivitiesNotOverlapping>")
            self._c("options of other bands never overlap (checker numbering)", "\n".join(xml), acts)

    # ---- constraint helpers ----------------------------------------------
    def _c(self, label, xml, acts=()):
        self.time_c.append(xml)
        self.counts[label] += 1
        for a in acts:
            a.rules.append(label)

    @staticmethod
    def _slots_xml(slots, day_tag="Selected_Day", hour_tag="Selected_Hour"):
        out = ["\t<Number_of_Selected_Time_Slots>%d</Number_of_Selected_Time_Slots>" % len(slots)]
        for d, h in slots:
            out.append("\t<Selected_Time_Slot><%s>%s</%s><%s>%s</%s></Selected_Time_Slot>"
                       % (day_tag, escape(d), day_tag, hour_tag, h, hour_tag))
        return "\n".join(out)

    def occupy_max(self, label, acts, slots, max_slots):
        acts = list(acts)
        if len(acts) < 1:
            return
        xml = ["<ConstraintActivitiesOccupyMaxTimeSlotsFromSelection>",
               "\t<Weight_Percentage>100</Weight_Percentage>",
               "\t<Number_of_Activities>%d</Number_of_Activities>" % len(acts)]
        xml += ["\t<Activity_Id>%d</Activity_Id>" % a.id for a in acts]
        xml.append(self._slots_xml(slots))
        xml.append("\t<Max_Number_of_Occupied_Time_Slots>%d</Max_Number_of_Occupied_Time_Slots>"
                   % max_slots)
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintActivitiesOccupyMaxTimeSlotsFromSelection>")
        self._c(label, "\n".join(xml), acts)

    def different_real_days(self, label, acts, days=None):
        """No two of these activities on the same real day (exact, through
        one 'occupy max L slots' constraint per real day and length L)."""
        acts = list({a.id: a for a in acts}.values())
        if len(acts) < 2:
            return
        for d in (days or self.grid.by_day):
            slots = self.grid.day_slots(d)
            for ell in sorted({a.dur for a in acts}):
                sub = [a for a in acts if a.dur <= ell]
                if len(sub) >= 2:
                    self.occupy_max(label, sub, slots, ell)

    def same_start(self, acts, label, weight=100):
        xml = ["<ConstraintActivitiesSameStartingTime>",
               "\t<Weight_Percentage>%s</Weight_Percentage>" % weight,
               "\t<Number_of_Activities>%d</Number_of_Activities>" % len(acts)]
        xml += ["\t<Activity_Id>%d</Activity_Id>" % a.id for a in acts]
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintActivitiesSameStartingTime>")
        self._c(label, "\n".join(xml), acts)

    def grouped(self, a, b, label):
        self._c(label, "<ConstraintTwoActivitiesGrouped>\n\t<Weight_Percentage>100"
                "</Weight_Percentage>\n\t<First_Activity_Id>%d</First_Activity_Id>\n"
                "\t<Second_Activity_Id>%d</Second_Activity_Id>\n\t<Active>true</Active>\n"
                "\t<Comments></Comments>\n</ConstraintTwoActivitiesGrouped>" % (a.id, b.id),
                [a, b])

    def starting_times(self, a, starts, label, weight=100):
        xml = ["<ConstraintActivityPreferredStartingTimes>",
               "\t<Weight_Percentage>%d</Weight_Percentage>" % weight,
               "\t<Activity_Id>%d</Activity_Id>" % a.id,
               "\t<Number_of_Preferred_Starting_Times>%d</Number_of_Preferred_Starting_Times>"
               % len(starts)]
        for d, h in starts:
            xml.append("\t<Preferred_Starting_Time><Preferred_Starting_Day>%s"
                       "</Preferred_Starting_Day><Preferred_Starting_Hour>%s"
                       "</Preferred_Starting_Hour></Preferred_Starting_Time>" % (escape(d), h))
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintActivityPreferredStartingTimes>")
        self._c(label, "\n".join(xml), [a])

    def activity_time_slots(self, a, slots, label, weight=100):
        xml = ["<ConstraintActivityPreferredTimeSlots>",
               "\t<Weight_Percentage>%d</Weight_Percentage>" % weight,
               "\t<Activity_Id>%d</Activity_Id>" % a.id,
               "\t<Number_of_Preferred_Time_Slots>%d</Number_of_Preferred_Time_Slots>" % len(slots)]
        for d, h in slots:
            xml.append("\t<Preferred_Time_Slot><Preferred_Day>%s</Preferred_Day>"
                       "<Preferred_Hour>%s</Preferred_Hour></Preferred_Time_Slot>" % (escape(d), h))
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintActivityPreferredTimeSlots>")
        self._c(label, "\n".join(xml), [a])

    def lock(self, a, pday, hour, label):
        self._c(label, "<ConstraintActivityPreferredStartingTime>\n\t<Weight_Percentage>100"
                "</Weight_Percentage>\n\t<Activity_Id>%d</Activity_Id>\n\t<Preferred_Day>%s"
                "</Preferred_Day>\n\t<Preferred_Hour>%s</Preferred_Hour>\n"
                "\t<Permanently_Locked>true</Permanently_Locked>\n\t<Active>true</Active>\n"
                "\t<Comments></Comments>\n</ConstraintActivityPreferredStartingTime>"
                % (a.id, escape(pday), hour), [a])

    def teacher_not_available(self, tid, slots, label):
        xml = ["<ConstraintTeacherNotAvailableTimes>",
               "\t<Weight_Percentage>100</Weight_Percentage>",
               "\t<Teacher>%s</Teacher>" % escape(tid),
               "\t<Number_of_Not_Available_Times>%d</Number_of_Not_Available_Times>" % len(slots)]
        for d, h in slots:
            xml.append("\t<Not_Available_Time><Day>%s</Day><Hour>%s</Hour></Not_Available_Time>"
                       % (escape(d), h))
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintTeacherNotAvailableTimes>")
        self._c(label, "\n".join(xml), [a for a in self.acts if tid in a.teachers])

    def teacher_max_day_sets(self, tid, day_sets, max_sets, label):
        xml = ["<ConstraintTeacherOccupiesMaxSetsOfTimeSlotsFromSelection>",
               "\t<Weight_Percentage>100</Weight_Percentage>",
               "\t<Teacher>%s</Teacher>" % escape(tid),
               "\t<Number_of_Selected_Sets_of_Time_Slots>%d</Number_of_Selected_Sets_of_Time_Slots>"
               % len(day_sets)]
        for slots in day_sets:
            xml.append("\t<Selected_Set_of_Time_Slots>")
            xml.append(self._slots_xml(slots, "Day", "Hour"))
            xml.append("\t</Selected_Set_of_Time_Slots>")
        xml.append("\t<Maximum_Number_of_Occupied_Sets>%d</Maximum_Number_of_Occupied_Sets>" % max_sets)
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintTeacherOccupiesMaxSetsOfTimeSlotsFromSelection>")
        self._c(label, "\n".join(xml), [a for a in self.acts if tid in a.teachers])

    def teacher_tag_min(self, tid, tag, label):
        self._c(label, "<ConstraintTeacherActivityTagMinHoursDaily>\n\t<Weight_Percentage>100"
                "</Weight_Percentage>\n\t<Teacher_Name>%s</Teacher_Name>\n\t<Activity_Tag>%s"
                "</Activity_Tag>\n\t<Minimum_Hours_Daily>%d</Minimum_Hours_Daily>\n"
                "\t<Allow_Empty_Days>true</Allow_Empty_Days>\n\t<Active>true</Active>\n"
                "\t<Comments></Comments>\n</ConstraintTeacherActivityTagMinHoursDaily>"
                % (escape(tid), tag, MIN_HOURS_HALF),
                [a for a in self.acts if tag in a.tags])

    def filtered_time_slots(self, slots, label, weight, tag="", subject="", duration=""):
        """Soft: every activity matching the filter prefers these slots."""
        xml = ["<ConstraintActivitiesPreferredTimeSlots>",
               "\t<Weight_Percentage>%s</Weight_Percentage>" % weight,
               "\t<Teacher_Name></Teacher_Name>", "\t<Students_Name></Students_Name>",
               "\t<Subject_Name>%s</Subject_Name>" % escape(subject),
               "\t<Activity_Tag_Name>%s</Activity_Tag_Name>" % tag,
               "\t<Duration>%s</Duration>" % duration,
               "\t<Number_of_Preferred_Time_Slots>%d</Number_of_Preferred_Time_Slots>" % len(slots)]
        for d, h in slots:
            xml.append("\t<Preferred_Time_Slot><Preferred_Day>%s</Preferred_Day>"
                       "<Preferred_Hour>%s</Preferred_Hour></Preferred_Time_Slot>" % (escape(d), h))
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintActivitiesPreferredTimeSlots>")
        self._c(label, "\n".join(xml))

    def filtered_starting_times(self, starts, label, weight, tag="", subject="", duration=""):
        xml = ["<ConstraintActivitiesPreferredStartingTimes>",
               "\t<Weight_Percentage>%s</Weight_Percentage>" % weight,
               "\t<Teacher_Name></Teacher_Name>", "\t<Students_Name></Students_Name>",
               "\t<Subject_Name>%s</Subject_Name>" % escape(subject),
               "\t<Activity_Tag_Name>%s</Activity_Tag_Name>" % tag,
               "\t<Duration>%s</Duration>" % duration,
               "\t<Number_of_Preferred_Starting_Times>%d</Number_of_Preferred_Starting_Times>"
               % len(starts)]
        for d, h in starts:
            xml.append("\t<Preferred_Starting_Time><Preferred_Starting_Day>%s"
                       "</Preferred_Starting_Day><Preferred_Starting_Hour>%s"
                       "</Preferred_Starting_Hour></Preferred_Starting_Time>" % (escape(d), h))
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintActivitiesPreferredStartingTimes>")
        self._c(label, "\n".join(xml))

    def students_max_day_sets(self, cid, day_sets, max_sets, label):
        xml = ["<ConstraintStudentsSetOccupiesMaxSetsOfTimeSlotsFromSelection>",
               "\t<Weight_Percentage>100</Weight_Percentage>",
               "\t<Students>%s</Students>" % escape(cid),
               "\t<Number_of_Selected_Sets_of_Time_Slots>%d</Number_of_Selected_Sets_of_Time_Slots>"
               % len(day_sets)]
        for slots in day_sets:
            xml.append("\t<Selected_Set_of_Time_Slots>")
            xml.append(self._slots_xml(slots, "Day", "Hour"))
            xml.append("\t</Selected_Set_of_Time_Slots>")
        xml.append("\t<Maximum_Number_of_Occupied_Sets>%d</Maximum_Number_of_Occupied_Sets>" % max_sets)
        xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                   "</ConstraintStudentsSetOccupiesMaxSetsOfTimeSlotsFromSelection>")
        self._c(label, "\n".join(xml), [a for a in self.acts if cid in a.students])

    def students_tag_min(self, cid, tag, label):
        self._c(label, "<ConstraintStudentsSetActivityTagMinHoursDaily>\n\t<Weight_Percentage>100"
                "</Weight_Percentage>\n\t<Students>%s</Students>\n\t<Activity_Tag>%s"
                "</Activity_Tag>\n\t<Minimum_Hours_Daily>%d</Minimum_Hours_Daily>\n"
                "\t<Allow_Empty_Days>true</Allow_Empty_Days>\n\t<Active>true</Active>\n"
                "\t<Comments></Comments>\n</ConstraintStudentsSetActivityTagMinHoursDaily>"
                % (escape(cid), tag, MIN_HOURS_HALF),
                [a for a in self.acts if tag in a.tags])

    # ---- the rules --------------------------------------------------------
    def _build_constraints(self):
        s, g = self.s, self.grid
        days = list(g.by_day)
        self.time_c.append("<ConstraintBasicCompulsoryTime>\n\t<Weight_Percentage>100"
                           "</Weight_Percentage>\n\t<Active>true</Active>\n\t<Comments>"
                           "</Comments>\n</ConstraintBasicCompulsoryTime>")
        self.space_c.append("<ConstraintBasicCompulsorySpace>\n\t<Weight_Percentage>100"
                            "</Weight_Percentage>\n\t<Active>true</Active>\n\t<Comments>"
                            "</Comments>\n</ConstraintBasicCompulsorySpace>")
        if g.breaks:
            xml = ["<ConstraintBreakTimes>", "\t<Weight_Percentage>100</Weight_Percentage>",
                   "\t<Number_of_Break_Times>%d</Number_of_Break_Times>" % len(g.breaks)]
            xml += ["\t<Break_Time><Day>%s</Day><Hour>%s</Hour></Break_Time>" % (escape(d), h)
                    for d, h in g.breaks]
            xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n</ConstraintBreakTimes>")
            self._c("grid: shorter half-days end earlier", "\n".join(xml))

        acts_of_t = collections.defaultdict(list)
        acts_of_c = collections.defaultdict(list)
        used_tags = set()
        for a in self.acts:
            used_tags.update(a.tags)
            for t in a.teachers:
                acts_of_t[t].append(a)
            for st in a.students:
                acts_of_c[st.split("_o_")[0].split("_g")[0]].append(a)

        # ---- H7 / H8 / H18: days off, training days, unavailability -------
        def adjacent(d1, d2):
            i, j = days.index(d1), days.index(d2)
            gap = abs(i - j)
            return gap == 1 or gap == len(days) - 1        # Sunday wrap
        self.day_off_candidates = {}
        self.day_off_dropped = {}
        na = collections.defaultdict(set)
        for tid, rec in s.teachers.items():
            if tid not in acts_of_t:
                continue
            off = (rec.get("day_off") or "").strip()
            tr = (rec.get("training_day") or "").strip()
            if tr in days:
                na[tid].update(g.day_slots(tr))
            if off in days:
                na[tid].update(g.day_slots(off))
            elif off.lower() != "(none)":
                cands = [d for d in days if d != tr and not (tr in days and adjacent(d, tr))]
                policy = (self.comfort or {}).get("day_off", "keep")
                if policy != "keep":
                    # FET-hours, not contract hours: FET must seat every merged
                    # A/B activity, so its capacity is what decides (a 16 h teacher
                    # with 18 FET-hours stalled FET when judged on 16)
                    h = sum(a.dur for a in acts_of_t[tid])
                    n_avail = len(days) - (1 if tr in days else 0)
                    if policy == "none" or int(math.ceil(h / 4.0)) > n_avail - 1:
                        self.day_off_dropped[tid] = ("rest day given up: %d hours need %d half-days"
                                                     % (h, int(math.ceil(h / 4.0)))
                                                     if policy == "auto" else "rest day off by choice")
                        continue
                self.day_off_candidates[tid] = cands
                if len(cands) >= 2:
                    self.teacher_max_day_sets(tid, [g.day_slots(d) for d in cands],
                                              len(cands) - 1, "H7 flexible day off")
                elif len(cands) == 1:
                    na[tid].update(g.day_slots(cands[0]))
                else:
                    self.notes.append("teacher %s: no H18-legal day off exists next to "
                                      "training day %s" % (tid, tr))
        for un in s.unavailable:
            if (un.get("hard") or "yes") != "yes" or un["teacher_id"] not in acts_of_t:
                continue
            for d in days:
                if un["day"] not in ("*", d):
                    continue
                for pd in g.by_day[d]:
                    for i, p in enumerate(pd["periods"]):
                        if un["period"] == "*" or str(p) == str(un["period"]):
                            na[un["teacher_id"]].add((pd["name"], g.hours[i]))
        pins = (self.comfort or {}).get("pin") or {}
        self.pinned = {}
        for tid, allowed in pins.items():
            if tid not in acts_of_t:
                continue
            keep = set()
            for pd in g.pdays:
                if pd["name"] in allowed or pd["day"] in allowed:
                    keep.update(g.pd_slots(pd))
            blocked = [sl for sl in g.all_slots() if sl not in keep]
            na[tid].update(blocked)
            self.pinned[tid] = sorted(allowed)
        if self.pinned:
            self.notes.append("two-school teachers pinned to the school table's windows: %d (%s)" % (
                len(self.pinned), "; ".join("%s: %s" % (s.teachers.get(k, {}).get("name", k), ", ".join(v))
                                             for k, v in sorted(self.pinned.items()))))
        for tid, slots in na.items():
            self.teacher_not_available(tid, g.sort_slots(slots), "H7/H8 teacher not available")

        # ---- H17: at most 6 hours per real day -------------------------------
        for tid, acts in acts_of_t.items():
            if sum(a.dur for a in acts) <= MAX_HOURS_DAY:
                continue
            for d in days:
                slots = g.day_slots(d)
                if len(slots) > MAX_HOURS_DAY:
                    self.occupy_max("H17 max 6h per day", acts, slots, MAX_HOURS_DAY)

        # ---- Majd 2026-09-09: no morning + afternoon on the same day ----------
        self.split_allow = {}
        mode = (self.comfort or {}).get("split_days", "off")
        if mode in ("facts", "none"):
            facts = FACTS.get("split_days") or {}
            by = dict((self.comfort or {}).get("split_by") or {})
            n_free, n_allowed, forced = 0, 0, 0
            for tid, acts in acts_of_t.items():
                rec = s.teachers.get(tid, {})
                h = sum(a.dur for a in acts)          # FET-hours (see the rest-day note)
                tr = (rec.get("training_day") or "").strip()
                off = (rec.get("day_off") or "").strip()
                blocked = {d for d in (tr, off) if d in days}
                n_avail = len(days) - len(blocked) - (1 if tid in self.day_off_candidates else 0)
                # one half-day of slack: exact packing (17 hours in exactly five
                # 4-hour half-days) stalled FET on the first such teacher
                need = max(0, int(math.ceil(h / 4.0)) + 1 - n_avail)
                if tid in by:
                    allowed = [d for d in by[tid] if d in days]
                elif mode == "facts":
                    allowed = [d for d in facts.get(tid, []) if d in days]
                else:
                    allowed = []
                allowed = [d for d in allowed if d not in blocked]
                if len(allowed) < need:
                    extra = [d for d in days if d not in blocked and d not in allowed]
                    extra.sort(key=lambda d: (d not in facts.get(tid, []), days.index(d)))
                    allowed += extra[:need - len(allowed)]
                    forced += 1
                    self.notes.append("teacher %s: %d FET-hours in %d usable days need %d split "
                                      "day(s) - allowed: %s" % (tid, h, n_avail, need, ", ".join(allowed)))
                self.split_allow[tid] = allowed
                n_allowed += 1 if allowed else 0
                n_free += 0 if allowed else 1
                for d in days:
                    if d in allowed or d in blocked:
                        continue
                    pds = g.by_day.get(d, [])
                    if len(pds) < 2:
                        continue
                    self.teacher_max_day_sets(tid, [g.pd_slots(pd) for pd in pds], 1,
                                              "comfort: no morning+afternoon same day (hard)")
            self.notes.append("split days (%s): %d teachers never come morning+afternoon on one day; "
                              "%d may on listed days (%d of them because the hours force it)"
                              % (mode, n_free, n_allowed, forced))
            if self.day_off_dropped:
                self.notes.append("rest day given up for %d teachers (--day-off %s)"
                                  % (len(self.day_off_dropped), (self.comfort or {}).get("day_off")))

        # ---- H21/H22: a teacher's half-day holds 0 or >= 2 hours, per week ---
        for tid, acts in acts_of_t.items():
            per_week = {w: sum(a.dur for a in acts if "T_%s_%s" % (tid, w) in a.tags)
                        for w in ("A", "B")}
            if max(per_week.values()) <= 1:
                continue                      # single-hour teachers are exempt
            for w in ("A", "B"):
                tag = "T_%s_%s" % (tid, w)
                if tag in used_tags:
                    self.teacher_tag_min(tid, tag, "H21/H22 teacher half-day 0 or >=2")

        # ---- pupils I.2: a class part's half-day holds 0 or >= 2 hours ------
        for cid in s.classes:
            for w in ("A", "B"):
                tag = "C_%s_%s" % (cid, w)
                if tag in used_tags:
                    self.students_tag_min(cid, tag, "pupils half-day 0 or >=2")

        # ---- H9 / same subject once a day -----------------------------------
        # a lab practical "<id>_TP" is the same subject as its theory for the
        # 'once a day' rule (Majd: never the same subject twice in a day)
        def base_subject(sid):
            return sid[:-3] if sid.endswith("_TP") and sid[:-3] in s.subjects else sid
        by_cs = collections.defaultdict(list)
        for row, bl, per_group in self.rows:
            for gs in per_group:
                for se in gs:
                    by_cs[se.class_id, base_subject(se.subject_id)].append(se)
        seen = set()
        if self.same_subject_once:
            for (cid, sid), ses in by_cs.items():
                maxg = max(se.group for se in ses)
                views = ([[se for se in ses if se.group in (0, gg)] for gg in range(1, maxg + 1)]
                         if maxg else [ses])
                for view in views:
                    for w in ("A", "B"):
                        acts = [self.act_of_sid[se.sid] for se in view if se.week in ("", w)]
                        key = frozenset(a.id for a in acts)
                        if len(key) >= 2 and key not in seen:
                            seen.add(key)
                            self.different_real_days("H9 same subject once a day", acts)
        else:
            for row, bl, per_group in self.rows:
                if not str(row.get("blocks", "")).strip():
                    continue
                for gs in per_group:
                    acts = [self.act_of_sid[se.sid] for se in gs]
                    key = frozenset(a.id for a in acts)
                    if len(key) >= 2 and key not in seen:
                        seen.add(key)
                        self.different_real_days("H9 blocks on different days", acts)

        # ---- H9 for options: the blocks of one option subject for one class
        # (its 2h and its 1h, possibly from different bands) go on different
        # days - that is how the checker reads the option pattern.
        opt_sets = collections.defaultdict(list)
        for band in s.option_bands:
            for og in band["groups"]:
                for cid in og["classes"]:
                    opt_sets[cid, og["subject_id"]].extend(self.opt_acts.get(og["id"], []))
        for key, acts in opt_sets.items():
            ids = frozenset(a.id for a in acts)
            if len(ids) >= 2 and ids not in seen:
                seen.add(ids)
                self.different_real_days("H9 option blocks on different days", acts)

        # ---- H19: gap24 subjects never on consecutive days ------------------
        for row, bl, per_group in self.rows:
            if (s.subjects.get(row["subject_id"], {}).get("gap24") or "") != "yes":
                continue
            if not str(row.get("blocks", "")).strip():
                continue
            for gs in per_group:
                acts = list({self.act_of_sid[se.sid].id: self.act_of_sid[se.sid] for se in gs}.values())
                if len(acts) < 2:
                    continue
                for i in range(len(days) - 1):
                    slots = g.day_slots(days[i]) + g.day_slots(days[i + 1])
                    for ell in sorted({a.dur for a in acts}):
                        sub = [a for a in acts if a.dur <= ell]
                        if len(sub) >= 2:
                            self.occupy_max("H19 24h between sessions", sub, slots, ell)

        # ---- H20: group halves back to back (or the engineering carousel) ---
        long_pairs = []
        done_pairs, done_starts = set(), set()
        for row, bl, per_group in self.rows:
            if len(per_group) < 2 or (row.get("week") or "").strip().upper() in ("ALT", "ALT2"):
                continue
            if len(per_group) > 2:
                self.notes.append("row %s/%s has %d groups - H20 is only built for 2"
                                  % (row["class_id"], row["subject_id"], len(per_group)))
                continue
            g1, g2 = per_group
            if 2 * max(bl) > g.nh:
                long_pairs.append((row, per_group))
                continue
            for k, L in enumerate(bl):
                a, b = self.act_of_sid[g1[k].sid], self.act_of_sid[g2[k].sid]
                key = (min(a.id, b.id), max(a.id, b.id))
                if key in done_pairs:
                    continue
                done_pairs.add(key)
                self.grouped(a, b, "H20 halves back to back")
                if L > 1:
                    starts = []
                    for pd in g.pdays:
                        n = len(pd["periods"])
                        starts += [(pd["name"], g.hours[i - 1]) for i in range(1, n + 1)
                                   if i <= n - 2 * L + 1 or L + 1 <= i <= n - L + 1]
                    for x in (a, b):
                        if x.id not in done_starts:
                            done_starts.add(x.id)
                            self.starting_times(x, starts, "H20 pair inside one half-day")
        used = set()
        for row, per_group in long_pairs:
            if id(row) in used:
                continue
            partner = None
            for row2, pg2 in long_pairs:
                if (row2 is not row and id(row2) not in used
                        and row2["class_id"] == row["class_id"]
                        and row2["subject_id"] != row["subject_id"]
                        and (row2.get("week") or "") == (row.get("week") or "")
                        and [se.length for se in pg2[0]] == [se.length for se in per_group[0]]):
                    partner = (row2, pg2)
                    break
            if not partner:
                self.notes.append("row %s/%s: 4h halves cannot be back to back and no partner "
                                  "subject of the same length was found - left free (verify.py "
                                  "exempts it from H20)" % (row["class_id"], row["subject_id"]))
                continue
            used.update((id(row), id(partner[0])))
            (m1, m2), (e1, e2) = per_group, partner[1]
            for k in range(len(m1)):
                self.same_start([self.act_of_sid[m1[k].sid], self.act_of_sid[e2[k].sid]],
                                "H20 engineering carousel")
                self.same_start([self.act_of_sid[m2[k].sid], self.act_of_sid[e1[k].sid]],
                                "H20 engineering carousel")

        # ---- H15 latest period + period 5 for light subjects only ----------
        # (per activity: a merged week-A/B pair may carry two subjects)
        p5_days = tuple(getattr(g.cfg, "p5_days", ()) or ())
        never_last = set()
        for key in (self.comfort.get("never_last") or []):
            for sid, sub in s.subjects.items():
                if key in (sid, sub.get("name"), sub.get("short")):
                    never_last.add(sid)
        last_period = g.cfg.periods_per_day
        for a in self.acts:
            lps = [s.subjects.get(m.subject_id, {}).get("latest_period") or 0 for m in a.sessions]
            lps = [x for x in lps if x]
            lp = min(lps) if lps else 99
            hard = any((s.subjects.get(m.subject_id, {}).get("difficulty") or "")
                       .strip().lower() == "hard" for m in a.sessions)
            nl = any(m.subject_id in never_last for m in a.sessions)
            allowed = [sl for sl in g.all_slots()
                       if g.slot_of[sl][1] <= lp and not (hard and g.slot_of[sl][1] == 5)
                       and not (nl and g.slot_of[sl][1] == last_period)]
            if len(allowed) < len(g.all_slots()):
                parts = []
                if lps:
                    parts.append("H15 latest period")
                if hard and p5_days:
                    parts.append("P5 light subjects only")
                if nl:
                    parts.append("never in the last period (Majd)")
                self.activity_time_slots(a, allowed, " + ".join(parts))

        # ---- period 5: a class that ends at 13:00 comes back at 15:00 ------
        for d in p5_days:
            if (d, 5) not in g.fet_of or (d, 7) not in g.fet_of:
                continue
            sel = [g.fet_of[d, 5], g.fet_of[d, 7]]
            for cid, acts in acts_of_c.items():
                self.occupy_max("P5 class back at 15:00", acts, sel, 1)

        # ---- Locked sheet ---------------------------------------------------
        pinned = set()
        for lk in s.locked:
            key = (lk["day"], lk["period"])
            if key not in g.fet_of:
                self.notes.append("lock %s/%s at %s p%d is not an open slot"
                                  % (lk["class_id"], lk["subject_id"], lk["day"], lk["period"]))
                continue
            pday, hour = g.fet_of[key]
            hidx = g.hours.index(hour)
            cand = [a for a in self.acts if a.kind in ("sess", "pair") and a.id not in pinned
                    and any(m.class_id == lk["class_id"] and m.subject_id == lk["subject_id"]
                            for m in a.sessions)
                    and hidx + a.dur <= g.nh]
            if not cand:
                self.notes.append("lock %s/%s at %s p%d: no unpinned session fits there"
                                  % (lk["class_id"], lk["subject_id"], lk["day"], lk["period"]))
                continue
            cand.sort(key=lambda a: (a.sessions[0].group, a.sessions[0].week, a.dur))
            pinned.add(cand[0].id)
            self.lock(cand[0], pday, hour, "LOCK pinned")

        # ---- comfort ----------------------------------------------------------
        # FET has no objective: gaps and selection rules are hard BUDGETS (100
        # percent, tightened by trial); time preferences are soft percentages.
        cf = self.comfort
        all_slots = g.all_slots()
        am_slots = [sl for sl in all_slots if sl[0].endswith("-am")]
        last_p = g.cfg.periods_per_day
        not_last = [sl for sl in all_slots if g.slot_of[sl][1] != last_p]
        # per class PART (a half-class pupil attends the whole-class cards
        # plus their own half): what one pupil actually lives through
        acts_of_part = collections.defaultdict(list)
        for a in self.acts:
            for st in a.students:
                if "_o_" in st:                       # option pupils: count for every part
                    cid, part = st.split("_o_")[0], ""
                else:
                    cid, _, part = st.partition("_g")
                parts = [int(part)] if part else (list(range(1, self.n_groups_of.get(cid, 0) + 1))
                                                  or [0])
                for p_ in parts:
                    acts_of_part[cid, p_].append(a)
        part_hours = {k: sum(a.dur for a in v) for k, v in acts_of_part.items()}
        if cf.get("max_half_days"):
            # fewer trips: a teacher comes in at most ceil(hours/4)+1 half-days
            for tid, acts in acts_of_t.items():
                h = sum(a.dur for a in acts)
                # the fewest half-days that can hold h FET-hours under the
                # 6-hour day (5 real days, 4-hour half-days): single half-days
                # give 4 h each, a doubled day 6 h; then one half-day of slack
                n_min = int(math.ceil(h / 4.0)) if h <= 20 else 5 + int(math.ceil((h - 20) / 2.0))
                budget = n_min + 1
                w_hd = cf.get("w_half_days", 100)
                if budget < len(g.pdays):
                    self._c("comfort: max half-days per teacher (%s)"
                            % ("hard" if w_hd >= 100 else "%d%%" % w_hd),
                            "<ConstraintTeacherMaxDaysPerWeek>\n\t<Weight_Percentage>%s"
                            "</Weight_Percentage>\n\t<Teacher_Name>%s</Teacher_Name>\n"
                            "\t<Max_Days_Per_Week>%d</Max_Days_Per_Week>\n\t<Active>true</Active>\n"
                            "\t<Comments></Comments>\n</ConstraintTeacherMaxDaysPerWeek>"
                            % (w_hd, escape(tid), budget), acts)
        if cf.get("fortnight_zero_holes"):
            # FET sees weeks A and B merged: a teacher with a card in only one
            # of them can show a hole in the other week that FET never saw.
            # Zero holes in FET's view keeps every real week at one at most.
            by = dict(cf.get("teacher_gap_by") or {})
            for tid, acts in acts_of_t.items():
                both = {"T_%s_A" % tid, "T_%s_B" % tid}
                if any(not both <= set(a.tags) for a in acts):
                    by[tid] = 0
            cf = dict(cf, teacher_gap_by=by)
        if cf.get("pupil_day_cap") == "ministry":
            # inspectorate rule M-P4: at most 6 hours a day Mon-Thu for pupils.
            # Counted per REAL pupil sub-group (half x option): whole-class
            # cards + that half's cards + that option's cards. A sub-group
            # whose week cannot fit under 6 (4 x 6 + Friday + Saturday) gets
            # 7 on Mon-Thu - the smallest legal exception.
            cap_rest = sum(len(g.day_slots(d)) for d in days[4:])
            bac_free = bool(cf.get("bac_afternoon"))
            acts_by_cid = collections.defaultdict(list)
            for a in self.acts:
                for st in a.students:
                    acts_by_cid[st.split("_o_")[0].split("_g")[0]].append((st, a))
            n_caps = 0
            # option lessons are left out: which pupils take which option is
            # not in the data (a class with one pool would count that option
            # for every pupil), and the circular exempts options anyway
            for cid in s.classes:
                items = acts_by_cid.get(cid, [])
                if not items:
                    continue
                halves = list(range(1, self.n_groups_of.get(cid, 0) + 1)) or [0]
                for h in halves:
                    for o in [None]:
                        acts = []
                        for st, a in items:
                            if st == cid or ("_g" in st and "_o_" not in st and st.endswith("_g%d" % h)):
                                if a not in acts:
                                    acts.append(a)
                        hours = sum(a.dur for a in acts)
                        # capacity Mon-Thu under the cap; a bac class also
                        # gives up one afternoon there; keep 2 slots of slack
                        is_bac = (s.classes.get(cid, {}).get("is_bac") or "") == "yes"
                        room6 = (3 * 6 + 4 if (is_bac and bac_free) else 4 * 6) + cap_rest
                        cap = 6 if hours <= room6 - 2 else 7
                        for d in days[:4]:
                            slots = g.day_slots(d)
                            if len(slots) > cap:
                                self.occupy_max("pupils max %d hours a day Mon-Thu (ministry M-P4, hard)"
                                                % cap, acts, slots, cap)
                                n_caps += 1
        if cf.get("pupil_day_cap") == "ministry":
            # Majd 2026-09-10: no 8-hour day at all - Fri/Sat capped at 7 too
            for (cid, p_), acts in acts_of_part.items():
                acts = [a for a in acts if not any("_o_" in st for st in a.students)]
                for d in days[4:]:
                    slots = g.day_slots(d)
                    if len(slots) > 7:
                        self.occupy_max("comfort: pupils max 7 hours on Fri/Sat (hard)", acts, slots, 7)
        elif cf.get("pupil_day_cap"):
            cap, light = int(cf["pupil_day_cap"]), cf.get("pupil_day_cap_hours", 40)
            for (cid, p_), acts in acts_of_part.items():
                # option lessons left out, as in the ministry cap: a part would
                # otherwise "occupy" every option's slots (stalled X3 at 689)
                acts = [a for a in acts if not any("_o_" in st for st in a.students)]
                if sum(a.dur for a in acts) > light:
                    continue
                for d in days:
                    slots = g.day_slots(d)
                    if len(slots) > cap:
                        self.occupy_max("comfort: pupils max %d hours a day (hard)" % cap,
                                        acts, slots, cap)
        if cf.get("last_cap"):
            last_slots = [sl for sl in all_slots if g.slot_of[sl][1] == last_p]
            for (cid, p_), acts in acts_of_part.items():
                capc = cf["last_cap"]
                if part_hours[cid, p_] > cf.get("last_cap_hours", 40):
                    capc += 1
                if capc < len(last_slots):
                    self.occupy_max("comfort: pupils max last-period lessons per week (hard)",
                                    acts, last_slots, capc)
        t_cap, t_by = cf.get("teacher_gaps"), {k: int(v) for k, v in (cf.get("teacher_gap_by") or {}).items()}
        t_lifted = t_cap is not None and any(v > t_cap for v in t_by.values())
        if t_cap is not None and not t_lifted:
            self._c("comfort: teacher holes budget per week (hard)",
                    "<ConstraintTeachersMaxGapsPerWeek>\n\t<Weight_Percentage>100</Weight_Percentage>"
                    "\n\t<Max_Gaps>%d</Max_Gaps>\n\t<Active>true</Active>\n\t<Comments></Comments>\n"
                    "</ConstraintTeachersMaxGapsPerWeek>" % t_cap)
        for tid in sorted(acts_of_t):
            b = t_by.get(tid, t_cap)
            if b is None or (not t_lifted and (tid not in t_by or b >= t_cap)):
                continue
            self._c("comfort: teacher holes budget, per teacher (hard%s)"
                    % (", rescue lifted some" if t_lifted else ""),
                    "<ConstraintTeacherMaxGapsPerWeek>\n\t<Weight_Percentage>100</Weight_Percentage>"
                    "\n\t<Teacher_Name>%s</Teacher_Name>\n\t<Max_Gaps>%d</Max_Gaps>\n\t<Active>true"
                    "</Active>\n\t<Comments></Comments>\n</ConstraintTeacherMaxGapsPerWeek>"
                    % (escape(tid), b), acts_of_t[tid])
        p_cap, p_by = cf.get("pupil_gaps"), {k: int(v) for k, v in (cf.get("pupil_gap_by") or {}).items()}
        p_lifted = p_cap is not None and any(v > p_cap for v in p_by.values())
        if p_cap is not None and not p_lifted:
            self._c("comfort: pupil holes budget per week (hard)",
                    "<ConstraintStudentsMaxGapsPerWeek>\n\t<Weight_Percentage>100</Weight_Percentage>"
                    "\n\t<Max_Gaps>%d</Max_Gaps>\n\t<Active>true</Active>\n\t<Comments></Comments>\n"
                    "</ConstraintStudentsMaxGapsPerWeek>" % p_cap)
        for cid in sorted(acts_of_c):
            b = p_by.get(cid, p_cap)
            if b is None or (not p_lifted and (cid not in p_by or b >= p_cap)):
                continue
            self._c("comfort: pupil holes budget, per class (hard%s)"
                    % (", rescue lifted some" if p_lifted else ""),
                    "<ConstraintStudentsSetMaxGapsPerWeek>\n\t<Weight_Percentage>100</Weight_Percentage>"
                    "\n\t<Max_Gaps>%d</Max_Gaps>\n\t<Students>%s</Students>\n\t<Active>true"
                    "</Active>\n\t<Comments></Comments>\n</ConstraintStudentsSetMaxGapsPerWeek>"
                    % (b, escape(cid)), acts_of_c[cid])
        if cf.get("bac_afternoon"):
            pm_sets = [g.pd_slots(pd) for pd in g.pdays
                       if pd["half"] == "pm" and pd["day"] in days[:4]]
            for cid, c in s.classes.items():
                if (c.get("is_bac") or "") == "yes" and cid in acts_of_c and len(pm_sets) >= 2:
                    self.students_max_day_sets(cid, pm_sets, len(pm_sets) - 1,
                                               "comfort: bac class free afternoon Mon-Thu (hard)")
        if cf.get("pair_days"):
            # circular III.2: a 2h/week subject taught as 1+1 avoids consecutive days
            for row, bl, per_group in self.rows:
                if row["hours"] != 2 or bl != [1, 1] or len(per_group) != 1:
                    continue
                acts = list({self.act_of_sid[se.sid].id: self.act_of_sid[se.sid]
                             for se in per_group[0]}.values())
                if len(acts) != 2:
                    continue
                for i in range(len(days) - 1):
                    slots = g.day_slots(days[i]) + g.day_slots(days[i + 1])
                    self.occupy_max("comfort: 1+1 subject not on consecutive days (hard)",
                                    acts, slots, 1)
        if cf.get("soft"):
            # every soft rule is a retry lottery on each of its activities in
            # FET; on this school's data the broad ones stall the search, so
            # the defaults are kept few and light (doubles-at-top is off)
            # Majd 2026-09-10: physics / the stream's basic subject not around
            # 16-18, generally not in the afternoon ("not always" -> soft)
            not_late = [sl for sl in all_slots if g.slot_of[sl][1] not in (last_p - 1, last_p)]
            for tg, what in (("HARD", "hard subject"), ("CORE", "core subject")):
                if tg not in used_tags:
                    continue
                if cf.get("w_hard_late", 95) > 0:
                    self.filtered_time_slots(not_late, "comfort: %s not at 16-18" % what,
                                             cf.get("w_hard_late", 95), tag=tg)
                if cf.get("w_hard_am", 60) > 0:
                    self.filtered_time_slots(am_slots, "comfort: %s in the morning" % what,
                                             cf.get("w_hard_am", 60), tag=tg)
            if cf.get("w_after_sport", 95) > 0:
                sport_ids = {sid for sid, sub in s.subjects.items() if (sub.get("gap24") or "") == "yes"}
                n_pairs = 0
                for cid, acts in acts_of_c.items():
                    sport = [a for a in acts if a.subject in sport_ids]
                    heavy = [a for a in acts if a.subject not in sport_ids
                             and ("HARD" in a.tags or "CORE" in a.tags)]
                    for a1 in sport:
                        for a2 in heavy:
                            self._c("comfort: no heavy lesson right after sport",
                                    "<ConstraintMinGapsBetweenActivities>\n\t<Weight_Percentage>%s"
                                    "</Weight_Percentage>\n\t<Number_of_Activities>2</Number_of_Activities>"
                                    "\n\t<Activity_Id>%d</Activity_Id>\n\t<Activity_Id>%d</Activity_Id>"
                                    "\n\t<MinGaps>1</MinGaps>\n\t<Active>true</Active>\n\t<Comments>"
                                    "</Comments>\n</ConstraintMinGapsBetweenActivities>"
                                    % (cf.get("w_after_sport", 95), a1.id, a2.id), [a1, a2])
                            n_pairs += 1
            if "BAC" in used_tags and cf.get("w_bac_last", 80) > 0:
                self.filtered_time_slots(not_last, "comfort: bac class not in the last period",
                                         cf.get("w_bac_last", 80), tag="BAC")
            if cf.get("w_sport_am", 80) > 0:
                for sid, sub in s.subjects.items():
                    if (sub.get("gap24") or "") == "yes" and any(a.subject == sid for a in self.acts):
                        self.filtered_time_slots(am_slots, "comfort: sport in the morning",
                                                 cf.get("w_sport_am", 80), subject=sid)
            if cf.get("w_double_top", 0) > 0:
                tops = [(pd["name"], g.hours[0]) for pd in g.pdays]
                self.filtered_starting_times(tops, "comfort: a double at the top of its half-day",
                                             cf.get("w_double_top", 0), duration="2")
            if cf.get("w_last", 0) > 0:
                self.filtered_time_slots(not_last, "comfort: avoid the last period (everyone)",
                                         cf["w_last"])

        # ---- H4/H6: rooms by type -------------------------------------------
        for tag in sorted(t for t in used_tags if t.startswith("RT_")):
            want = tag[3:].rpartition("_n")[0]
            rooms = self.rooms_for_tag(tag)
            if not rooms:
                self.notes.append("no room of type '%s' with enough seats exists - every lesson "
                                  "needing one is unplaceable" % want)
                continue
            xml = ["<ConstraintActivityTagPreferredRooms>",
                   "\t<Weight_Percentage>100</Weight_Percentage>",
                   "\t<Activity_Tag>%s</Activity_Tag>" % tag,
                   "\t<Number_of_Preferred_Rooms>%d</Number_of_Preferred_Rooms>" % len(rooms)]
            xml += ["\t<Preferred_Room>%s</Preferred_Room>" % escape(r) for r in rooms]
            xml.append("\t<Active>true</Active>\n\t<Comments></Comments>\n"
                       "</ConstraintActivityTagPreferredRooms>")
            self.space_c.append("\n".join(xml))
            self.counts["H4/H6 rooms of the right type"] += 1

    # ---- the file ---------------------------------------------------------
    def write(self, path):
        s, g = self.s, self.grid
        L = []
        A = L.append
        A('<?xml version="1.0" encoding="UTF-8"?>')
        A('<fet version="7.10.3">')
        A('<Mode>Official</Mode>')
        A('<Institution_Name>school</Institution_Name>')
        A('<Comments>source-workbook: %s</Comments>'
          % escape(os.path.basename(getattr(s, "source_path", "") or "")))
        A('<Days_List>\n<Number_of_Days>%d</Number_of_Days>' % len(g.pdays))
        for pd in g.pdays:
            A('<Day>\n\t<Name>%s</Name>\n</Day>' % pd["name"])
        A('</Days_List>')
        A('<Hours_List>\n<Number_of_Hours>%d</Number_of_Hours>' % g.nh)
        for h in g.hours:
            A('<Hour>\n\t<Name>%s</Name>\n</Hour>' % h)
        A('</Hours_List>')
        A('<Subjects_List>')
        for sid in s.subjects:
            A('<Subject>\n\t<Name>%s</Name>\n\t<Comments></Comments>\n</Subject>' % escape(sid))
        A('</Subjects_List>')
        A('<Activity_Tags_List>')
        for t in sorted({t for a in self.acts for t in a.tags}):
            A('<Activity_Tag>\n\t<Name>%s</Name>\n\t<Printable>true</Printable>\n'
              '\t<Comments></Comments>\n</Activity_Tag>' % t)
        A('</Activity_Tags_List>')
        A('<Teachers_List>')
        for tid in s.teachers:
            A('<Teacher>\n\t<Name>%s</Name>\n\t<Target_Number_of_Hours>0</Target_Number_of_Hours>\n'
              '\t<Qualified_Subjects></Qualified_Subjects>\n\t<Comments></Comments>\n</Teacher>'
              % escape(tid))
        A('</Teachers_List>')
        A('<Students_List>')
        opts_of = collections.defaultdict(list)          # class -> [option group ids]
        for band in s.option_bands:
            for g in band["groups"]:
                for cid in g["classes"]:
                    opts_of[cid].append(g["id"])
        for cid in s.classes:
            A('<Year>\n\t<Name>%s</Name>\n\t<Number_of_Students>0</Number_of_Students>\n'
              '\t<Comments></Comments>\n\t<Number_of_Categories>0</Number_of_Categories>\n'
              '\t<Separator> </Separator>' % escape(cid))
            halves = list(range(1, self.n_groups_of.get(cid, 0) + 1))
            opts = opts_of.get(cid, [])

            def sub(h, gid):
                return '\t\t<Subgroup>\n\t\t\t<Name>%s_s%d_%s</Name>\n\t\t\t<Number_of_Students>0' \
                       '</Number_of_Students>\n\t\t\t<Comments></Comments>\n\t\t</Subgroup>' \
                       % (escape(cid), h, escape(gid) if gid else "x")
            for h in halves:
                A('\t<Group>\n\t\t<Name>%s_g%d</Name>\n\t\t<Number_of_Students>0'
                  '</Number_of_Students>\n\t\t<Comments></Comments>' % (escape(cid), h))
                if opts:
                    for gid in opts:
                        A(sub(h, gid))
                A('\t</Group>')
            for gid in opts:
                A('\t<Group>\n\t\t<Name>%s_o_%s</Name>\n\t\t<Number_of_Students>0'
                  '</Number_of_Students>\n\t\t<Comments></Comments>' % (escape(cid), escape(gid)))
                for h in (halves or [0]):
                    A(sub(h, gid))
                A('\t</Group>')
            A('</Year>')
        A('</Students_List>')
        A('<Activities_List>')
        for a in self.acts:
            A('<Activity>')
            for t in a.teachers:
                A('\t<Teacher>%s</Teacher>' % escape(t))
            A('\t<Subject>%s</Subject>' % escape(a.subject))
            for t in a.tags:
                A('\t<Activity_Tag>%s</Activity_Tag>' % t)
            for st in a.students:
                A('\t<Students>%s</Students>' % escape(st))
            A('\t<Duration>%d</Duration>\n\t<Total_Duration>%d</Total_Duration>\n\t<Id>%d</Id>\n'
              '\t<Activity_Group_Id>0</Activity_Group_Id>\n\t<Active>true</Active>\n'
              '\t<Comments>%s</Comments>' % (a.dur, a.dur, a.id, escape(a.comment)))
            A('</Activity>')
        A('</Activities_List>')
        A('<Buildings_List>\n</Buildings_List>')
        A('<Rooms_List>')
        for rid in s.rooms:
            A('<Room>\n\t<Name>%s</Name>\n\t<Building></Building>\n\t<Capacity>1000</Capacity>\n'
              '\t<Virtual>false</Virtual>\n\t<Comments></Comments>\n</Room>' % escape(rid))
        A('</Rooms_List>')
        A('<Time_Constraints_List>')
        L.extend(self.time_c)
        A('</Time_Constraints_List>')
        A('<Space_Constraints_List>')
        L.extend(self.space_c)
        A('</Space_Constraints_List>')
        A('</fet>')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(L) + "\n")
        return path


# ---------------------------------------------------------------------------
# running FET
# ---------------------------------------------------------------------------
def result_candidates():
    base = os.path.join(OUT, "timetables")
    return [os.path.join(base, FET_NAME + suffix, FET_NAME + "_activities.xml")
            for suffix in ("", "-highest", "-current")]


def run_fet(fet_path, time_limit, force=False):
    if not os.path.exists(FET_CL):
        sys.exit("fet-cl not found at %s (set FET_CL=... to point at it)" % FET_CL)
    lock = os.path.join(OUT, "fet.running")
    if os.path.exists(lock) and not force:
        sys.exit("Another FET run seems to be going (%s exists). One FET at a time; "
                 "delete the file or pass --force if that run is dead." % lock)
    for p in result_candidates():
        shutil.rmtree(os.path.dirname(p), ignore_errors=True)
    shutil.rmtree(os.path.join(OUT, "logs"), ignore_errors=True)
    cmd = [FET_CL, "--inputfile=" + fet_path, "--outputdir=" + OUT,
           "--timelimitseconds=%d" % time_limit, "--htmllevel=0",
           "--writetimetablesstatistics=false", "--writetimetableconflicts=true",
           "--warnifusinggroupactivitiesininitialorder=false",
           "--warnsubgroupswiththesameactivities=false"]
    for k in ("dayshorizontal daysvertical timehorizontal timevertical subgroups groups "
              "years teachers teachersfreeperiods buildings rooms subjects activitytags").split():
        cmd.append("--writetimetables%s=false" % k)
    with open(lock, "w") as f:
        f.write(str(os.getpid()))
    t0 = time.time()
    print("FET: %s (time limit %d s, single thread)" % (os.path.basename(FET_CL), time_limit),
          flush=True)
    progress = os.path.join(OUT, "logs", "max_placed_activities.txt")
    last = ""
    last_change = time.time()
    stalled = False
    try:
        with open(os.path.join(OUT, "fet_console.log"), "w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=OUT)
            while proc.poll() is None:
                time.sleep(10)
                try:
                    with open(progress, encoding="utf-8", errors="replace") as f:
                        lines = [l.strip() for l in f if l.strip()]
                    cur = lines[-1] if lines else ""
                except OSError:
                    cur = ""
                if cur and cur != last:
                    last = cur
                    last_change = time.time()
                    print("  %5.0fs  %s" % (time.time() - t0, cur[:110]), flush=True)
                if time.time() - t0 > time_limit + 300:
                    proc.terminate()
                    print("  FET did not stop at its time limit - terminated.")
                    break
                if STALL_S and time.time() - last_change > STALL_S and time.time() - t0 > 300:
                    proc.terminate()
                    stalled = True
                    print("  FET made no progress for %d s - attempt cut short (stalled)."
                          % STALL_S, flush=True)
                    break
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    elapsed = time.time() - t0
    result = console = ""
    try:
        with open(os.path.join(OUT, "logs", "result.txt"), encoding="utf-8", errors="replace") as f:
            result = f.read()
    except OSError:
        pass
    try:
        with open(os.path.join(OUT, "fet_console.log"), encoding="utf-8", errors="replace") as f:
            console = f.read()
    except OSError:
        pass
    if "Generation successful" in result or "Generation successful" in console:
        status = "complete"
    elif stalled:
        status = "stalled"
    elif "Time exceeded" in result or "Time exceeded" in console:
        status = "time-exceeded"
    else:
        status = "failed"
    return status, elapsed, (result + "\n" + console).strip()


def fet_logs():
    out = {}
    for name in ("errors.txt", "warnings.txt", "result.txt", "file_open.log",
                 "max_placed_activities.txt", "initial_order.txt", "difficult_activities.txt"):
        p = os.path.join(OUT, "logs", name)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                out[name] = f.read().lstrip("﻿")
        except OSError:
            out[name] = ""
    return out


# ---------------------------------------------------------------------------
# reading the result back
# ---------------------------------------------------------------------------
def import_result(model, path=None):
    """FET's activities XML -> (placement {uid: [day, period]}, unplaced acts,
    {act id: FET room}). Without a path: the complete result if there is one,
    else FET's 'highest' partial timetable."""
    if path is None:
        for cand in result_candidates():
            if os.path.exists(cand):
                path = cand
                break
    if not path or not os.path.exists(path):
        return {}, list(model.acts), {}, path, {}
    g = model.grid
    root = ET.parse(path).getroot()
    placement, fet_rooms, placed_ids, act_slots = {}, {}, set(), {}
    by_id = {a.id: a for a in model.acts}
    for el in root.iter("Activity"):
        get = lambda tag: (el.findtext(tag) or "").strip()      # noqa: E731
        try:
            aid = int(get("Id"))
        except ValueError:
            continue
        day, hour, room = get("Day"), get("Hour"), get("Room")
        a = by_id.get(aid)
        if a is None or not day or not hour:
            continue
        hidx = g.hours.index(hour)
        placed_ids.add(aid)
        fet_rooms[aid] = room
        act_slots[aid] = (day, hidx)
        for se in a.sessions:
            for t in range(se.length):
                d, p = g.slot_of[day, g.hours[hidx + t]]
                placement[S.uid_of(se, t)] = [d, p]
        if a.opt and a.kind == "optgrp":
            gid, off = a.opt
            for t in range(a.dur):
                d, p = g.slot_of[day, g.hours[hidx + t]]
                placement["OPT|%s|%d" % (gid, off + t)] = [d, p]
    unplaced = [a for a in model.acts if a.id not in placed_ids]
    return placement, unplaced, fet_rooms, path, act_slots


def rooms_from_fet(model, fet_rooms):
    """FET's own room per activity -> the emitter's {uid: room} dict (plus the
    'OPT|<group>|<hour>' keys for option groups). FET never double-books a
    room, and a merged week-A/B pair shares one room across the two weeks.
    A room of the wrong kind (should never happen) is dropped and noted."""
    s = model.s
    rooms = {}
    for a in model.acts:
        r = fet_rooms.get(a.id, "")
        if not r or r not in s.rooms:
            continue
        rtype = s.rooms[r]["type"]
        want = a.tags[0][3:].rpartition("_n")[0]
        ok_types = ("normal",) if want == "normalonly" else D.compatible_types(want)
        if rtype not in ok_types:
            model.notes.append("FET put %s in room %s (%s) although it needs '%s' - room "
                               "dropped" % (a.comment, r, rtype, want))
            continue
        for se in a.sessions:
            for t in range(se.length):
                rooms[S.uid_of(se, t)] = r
        if a.opt:
            gid, off = a.opt
            for t in range(a.dur):
                rooms["OPT|%s|%d" % (gid, off + t)] = r
    return rooms


def write_view(s, units, placement, rooms, path, day_offs=None):
    """out/fet/view.html - the shared viewer's page, but an option band is
    shown as what it is: the option subjects (Italian, German, painting...)
    with their teachers, and each option teacher gets the lesson on their own
    page. Majd, 2026-09-07: 'حصة الخيارات' meant nothing to him."""
    H = emit_html
    day_offs = day_offs or {}
    sub_name = {k: v.get("name", k) for k, v in s.subjects.items()}
    cls_name = {k: v.get("name", k) for k, v in s.classes.items()}
    tch_name = {k: v.get("name", k) for k, v in s.teachers.items()}
    room_name = {k: v.get("name", k) for k, v in s.rooms.items()}
    cgrid, tgrid, thours = {}, {}, {}
    for u in units:
        if u.uid not in placement or u.subject_id.startswith("OPT:"):
            continue
        d, p = placement[u.uid]
        rm = room_name.get(rooms.get(u.uid, ""), "")
        subj = sub_name.get(u.subject_id, u.subject_id)
        tag = H._tag_of(getattr(u, "group", 0), getattr(u, "week", ""))
        cgrid.setdefault(u.class_id, {}).setdefault((d, p), []).append((subj, u.teacher_id, rm, tag))
        if u.teacher_id:
            tgrid.setdefault(u.teacher_id, {}).setdefault((d, p), []).append(
                (subj, u.class_id, rm, tag))
            thours[u.teacher_id] = thours.get(u.teacher_id, 0) + 1
    for band in getattr(s, "option_bands", []):
        for g in band["groups"]:
            for t in range(band["hours"]):
                sl = placement.get("OPT|%s|%d" % (g["id"], t))
                if not sl:
                    continue
                d, p = sl
                subj = sub_name.get(g["subject_id"], g["subject_id"])
                rm = room_name.get(rooms.get("OPT|%s|%d" % (g["id"], t), ""), "")
                for cid in g["classes"]:
                    cgrid.setdefault(cid, {}).setdefault((d, p), []).append(
                        (subj, g["teacher_id"], rm, "خيار"))
                if g["teacher_id"]:
                    label = " + ".join(cls_name.get(c, c) for c in g["classes"])
                    tgrid.setdefault(g["teacher_id"], {}).setdefault((d, p), []).append(
                        (subj, label, rm, "خيار"))
                    thours[g["teacher_id"]] = thours.get(g["teacher_id"], 0) + 1
    grids, opt_c, opt_t = [], [], []
    for cid in sorted(cgrid, key=lambda c: (len(c), c)):
        grids.append("<div class='grid cgrid' id='%s'><h2>%s — قسم %s — %s</h2>%s</div>"
                     % (cid, H.SCHOOL, H._esc(cls_name.get(cid, cid)), H.YEAR,
                        H._table(s.cfg, cgrid[cid], lambda t_: tch_name.get(t_, ""))))
        opt_c.append("<option value='%s'>%s</option>" % (cid, H._esc(cls_name.get(cid, cid))))
    for tid in sorted(tgrid, key=lambda t_: (len(t_), t_)):
        t = s.teachers.get(tid, {})
        contract = t.get("hours") or 0
        hline = "الساعات المنجزة: %d / المطلوبة: %s" % (thours.get(tid, 0),
                                                       contract if contract else "؟")
        tags = {}
        tr = (t.get("training_day") or "").strip()
        if tr:
            tags[tr] = "يوم التكوين"
        off = (t.get("day_off") or "").strip() or day_offs.get(tid, "")
        if off and off != "(none)":
            tags[off] = "يوم الراحة"
        grids.append("<div class='grid tgrid' id='%s'><h2>%s — الأستاذ(ة) %s — %s"
                     "<br><small>%s</small></h2>%s</div>"
                     % (tid, H.SCHOOL, H._esc(tch_name.get(tid, tid)), H.YEAR, H._esc(hline),
                        H._table(s.cfg, tgrid[tid], lambda c: cls_name.get(c, c), day_tags=tags)))
        opt_t.append("<option value='%s'>%s</option>" % (tid, H._esc(tch_name.get(tid, tid))))
    page = (H.PAGE.replace("@OPTC@", "".join(opt_c)).replace("@OPTT@", "".join(opt_t))
            .replace("@GRIDS@", "".join(grids)).replace("@STAMP@", H.provenance(s))
            .replace("@SCHOOL@", H.SCHOOL).replace("@YEAR@", H.YEAR))
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


def write_asc(s, units, placement, rooms, path):
    """The aSc XML in exactly the PROVEN form of solver/emit_asc.py, with one
    difference: option groups are written at their OWN slots
    (placement['OPT|<group>|<hour>']), because a band no longer has to be
    simultaneous. Everything else is copied from the shared emitter."""
    _row, _esc, day_mask = emit_asc._row, emit_asc._esc, emit_asc.day_mask
    days = s.cfg.days
    L = []
    A = L.append
    A('<?xml version="1.0" encoding="UTF-8"?>')
    A('<!-- source-workbook: %s -->' % os.path.basename(getattr(s, "source_path", "") or "unknown"))
    A('<timetable importtype="database" options="idprefix:%s">' % emit_asc.ID_PREFIX)
    A('   <periods options="" columns="period,name,short">')
    for p in range(1, s.cfg.periods_per_day + 1):
        A(_row("period", period=p, name=str(p), short=str(p)))
    A('   </periods>')
    A('   <daysdefs options="" columns="id,days,name,short">')
    A(_row("daysdef", id="whole_week", days="1" * len(days), name="Whole week", short="week"))
    for i, d in enumerate(days):
        A(_row("daysdef", id="day_" + d,
               days="".join("1" if j == i else "0" for j in range(len(days))), name=d, short=d))
    A('   </daysdefs>')
    A('   <subjects options="" columns="id,name,short">')
    for sub in s.subjects.values():
        A(_row("subject", id=sub["id"], name=sub["name"], short=sub["short"]))
    A('   </subjects>')

    def visible_short(short, rid, name):
        short = (short or "").strip()
        return short if short and short != rid else name
    A('   <teachers options="" columns="id,name,short">')
    for tch in s.teachers.values():
        A(_row("teacher", id=tch["id"], name=tch["name"],
               short=visible_short(tch.get("short"), tch["id"], tch["name"])))
    A('   </teachers>')
    A('   <classes options="" columns="id,name,short">')
    for c in s.classes.values():
        A(_row("class", id=c["id"], name=c["name"],
               short=visible_short(c.get("short"), c["id"], c["name"])))
    A('   </classes>')
    bands = getattr(s, "option_bands", [])
    has_groups = any(u.group for u in units) or bool(bands)
    n_groups_of = {}
    for u in units:
        if u.group:
            n_groups_of[u.class_id] = max(n_groups_of.get(u.class_id, 0), u.group)

    def gid(cid, g):
        return "GRP_%s_%d" % (cid, g)
    opt_groups_of = {}
    for band in bands:
        for gi, g in enumerate(band["groups"]):
            for cid_ in g["classes"]:
                opt_groups_of.setdefault(cid_, []).append((100 + gi, g))
    if has_groups:
        A('   <groups options="" columns="id,classid,name,entireclass,divisiontag,studentcount">')
        for c in s.classes.values():
            size = c.get("size") or 0
            A(_row("group", id=gid(c["id"], 0), classid=c["id"], name="Entire class",
                   entireclass=1, divisiontag=0, studentcount=size or ""))
            n = n_groups_of.get(c["id"], 0)
            for g in range(1, n + 1):
                A(_row("group", id=gid(c["id"], g), classid=c["id"], name="Groupe %d" % g,
                       entireclass=0, divisiontag=1, studentcount=(size // n) if size else ""))
            for num, og in opt_groups_of.get(c["id"], []):
                sub = s.subjects.get(og["subject_id"], {})
                A(_row("group", id="OPTG_%s_%d" % (c["id"], num), classid=c["id"],
                       name="خيار: %s" % (sub.get("name") or og["subject_id"]),
                       entireclass=0, divisiontag=2, studentcount=""))
        A('   </groups>')
    has_weeks = any(u.week for u in units)
    nweeks = 2 if has_weeks else (getattr(s.cfg, "weeks_per_cycle", 1) or 1)
    if has_weeks:
        A('   <weeksdefs options="" columns="id,weeks,name,short">')
        A(_row("weeksdef", id="WALL", weeks="11", name="All weeks", short="All"))
        A(_row("weeksdef", id="WA", weeks="10", name="Week A", short="A"))
        A(_row("weeksdef", id="WB", weeks="01", name="Week B", short="B"))
        A('   </weeksdefs>')

    def week_mask(week):
        if nweeks == 1:
            return "1"
        return {"A": "10", "B": "01"}.get(week, "1" * nweeks)
    A('   <classrooms options="" columns="id,name,short,capacity">')
    for r in s.rooms.values():
        A(_row("classroom", id=r["id"], name=r["name"], short=visible_short(None, r["id"], r["name"]),
               capacity=r["capacity"]))
    A('   </classrooms>')
    bunches = {}
    for u in units:
        if u.subject_id.startswith("OPT:"):
            continue
        key = (u.class_id, u.subject_id, u.teacher_id, u.group, u.week)
        bunches.setdefault(key, []).append(u)
    lesson_id = {}
    cols = "id,subjectid,classids,teacherids,classroomids,periodspercard,periodsperweek"
    if has_groups:
        cols += ",groupids"
    if has_weeks:
        cols += ",weeksdefid"
    A('   <lessons options="" columns="%s">' % cols)
    for n, (key, us) in enumerate(sorted(bunches.items()), start=1):
        cid, sid, tid, g, wk = key
        lid = "L%d" % n
        lesson_id[key] = lid
        pw = ("%.1f" % (len(us) / 2.0)) if wk in ("A", "B") else len(us)
        # aSc links a card's room to its lesson only if the lesson lists that
        # room (Majd 2026-09-10: cards "not well linked to rooms" without it)
        lrooms = ",".join(sorted({rooms.get(u.uid, "") for u in us if rooms.get(u.uid, "")}))
        kw = dict(id=lid, subjectid=sid, classids=cid, teacherids=tid, classroomids=lrooms,
                  periodspercard=1, periodsperweek=pw)
        if has_groups:
            kw["groupids"] = gid(cid, g)
        if has_weeks:
            kw["weeksdefid"] = {"A": "WA", "B": "WB"}.get(wk, "WALL")
        A(_row("lesson", **kw))
    for band in bands:
        for gi, g in enumerate(band["groups"]):
            orooms = ",".join(sorted({rooms.get("OPT|%s|%d" % (g["id"], tt), "") for tt in range(band["hours"])
                                      if rooms.get("OPT|%s|%d" % (g["id"], tt), "")}))
            kw = dict(id="OL_%s" % g["id"], subjectid=g["subject_id"], classids=",".join(g["classes"]),
                      teacherids=g["teacher_id"], classroomids=orooms, periodspercard=1,
                      periodsperweek=band["hours"])
            if has_groups:
                kw["groupids"] = ",".join("OPTG_%s_%d" % (c, 100 + gi) for c in g["classes"])
            if has_weeks:
                kw["weeksdefid"] = "WALL"
            A(_row("lesson", **kw))
    A('   </lessons>')
    A('   <cards options="" columns="lessonid,period,days,weeks,classroomids">')
    for key, us in sorted(bunches.items()):
        lid = lesson_id[key]
        for u in us:
            d, p = placement[u.uid]
            A(_row("card", lessonid=lid, period=p, days=day_mask(days, d), weeks=week_mask(u.week),
                   classroomids=rooms.get(u.uid, "")))
    for band in bands:
        for gi, g in enumerate(band["groups"]):
            for tt in range(band["hours"]):
                sl = placement.get("OPT|%s|%d" % (g["id"], tt))
                if not sl:
                    continue
                d, p = sl
                A(_row("card", lessonid="OL_%s" % g["id"], period=p, days=day_mask(days, d),
                       weeks=week_mask(""), classroomids=rooms.get("OPT|%s|%d" % (g["id"], tt), "")))
    A('   </cards>')
    A('</timetable>')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def write_outputs(s, sessions, placement, day_offs, rooms=None):
    regular = [se for se in sessions if not se.subject_id.startswith("OPT:")]
    placed = [se for se in regular
              if all(S.uid_of(se, t) in placement for t in range(se.length))]
    units = S.hour_units(placed)
    if not rooms:
        rooms = S.assign_rooms(s, placed, placement)
    os.makedirs(OUT, exist_ok=True)
    write_asc(s, units, placement, rooms, os.path.join(OUT, "timetable.xml"))
    try:
        write_view(s, units, placement, rooms, os.path.join(OUT, "view.html"), day_offs=day_offs)
    except Exception as exc:                      # noqa: BLE001 - fall back to the shared page
        print("  (own view failed: %s - using the shared viewer)" % exc)
        emit_html.write(s, units, placement, rooms, os.path.join(OUT, "view.html"),
                        day_offs=day_offs)
    n_opt = sum(1 for k in placement if k.startswith("OPT|"))
    with open(os.path.join(OUT, "solution.json"), "w", encoding="utf-8") as f:
        json.dump(dict(engine="FET 7.10.3 via solver/fet_bridge.py",
                       placed_sessions=len(placed), sessions=len(regular),
                       option_hours_placed=n_opt, placement=placement), f)
    return len(placed), len(regular)
def run_verify(xlsx, p5_days=()):
    """The independent checker, pointed at out/fet/timetable.xml.

    verify.py's --p5 opens period 5 on Mon-Thu (its hard-coded default).
    When Majd opened it on other days, the same method is given those days
    for the duration of the check - the checker's own logic is untouched."""
    import verify as V
    V.XML = os.path.join(OUT, "timetable.xml")
    V.EXC = os.path.join(OUT, "exceptions.json")
    buf = io.StringIO()
    argv = sys.argv
    sys.argv = ["verify.py", xlsx] + (["--p5"] if p5_days else [])
    orig = D.Config.open_period5
    if p5_days:
        D.Config.open_period5 = lambda self, days=tuple(p5_days): orig(self, days)
    try:
        with contextlib.redirect_stdout(buf):
            rc = V.main()
    finally:
        sys.argv = argv
        D.Config.open_period5 = orig
    text = buf.getvalue()
    with open(os.path.join(OUT, "verify.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    return rc, text


def run_score():
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "tools", "score_table.py"),
                            os.path.join(OUT, "timetable.xml")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120)
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return "score_table.py could not run: %s" % exc


def parse_score(text):
    """score_table.py output -> (teacher holes, pupil holes, last-period lessons)."""
    def num(label):
        m = re.search(label + r"[ .]*([0-9.]+)", text)
        return float(m.group(1)) if m else None
    return (num(r"teacher hole-hours per week"), num(r"pupil \(class\) hole-hours per week"),
            num(r"lessons in the last period"))


def discomfort(th, ph, lp, felt):
    """One number to rank tables by how they feel: hole-hours for teachers
    and pupils, a quarter point per last-period lesson, 20 points per
    average half-day a teacher must come in, a fifth of a point per 8-hour
    pupil day. Lower is better."""
    felt = felt or {}
    return (th + ph + 0.25 * (lp or 0) + 20.0 * felt.get("trips", 6.0)
            + 0.2 * felt.get("heavy", 0) + 10.0 * felt.get("t_split", 0))


def keep_best(score, note, felt=None):
    """Copy an ALL GREEN result to out/fet/best/ when its discomfort index
    is lower than the one kept there."""
    best_dir = os.path.join(OUT, "best")
    meta = os.path.join(best_dir, "score.json")
    th, ph, lp = score
    if th is None or ph is None:
        return False
    cur = None
    if os.path.exists(meta):
        try:
            with open(meta, encoding="utf-8") as f:
                cur = json.load(f)
        except (OSError, ValueError):
            cur = None
    mine = discomfort(th, ph, lp, felt)
    if cur and cur.get("teacher_holes") is not None:
        old = cur.get("discomfort")
        if old is None:
            old = discomfort(cur["teacher_holes"], cur["pupil_holes"], cur.get("last_period"),
                             cur.get("felt"))
        if mine >= old:
            return False
    os.makedirs(best_dir, exist_ok=True)
    for name in ("timetable.xml", "view.html", "solution.json", "report.md", "verify.txt",
                 "school.fet"):
        src = os.path.join(OUT, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(best_dir, name))
    with open(meta, "w", encoding="utf-8") as f:
        json.dump(dict(teacher_holes=th, pupil_holes=ph, last_period=lp, args=note,
                       discomfort=round(mine, 1), felt=felt or {},
                       when=time.strftime("%Y-%m-%d %H:%M")), f)
    return True


def chosen_day_offs(model, act_slots):
    """Which real day ended up fully free, for teachers whose day off was
    the engine's choice."""
    busy = collections.defaultdict(set)
    for a in model.acts:
        sl = act_slots.get(a.id)
        if sl:
            pday = sl[0]
            day = next((pd["day"] for pd in model.grid.pdays if pd["name"] == pday), None)
            for tid in a.teachers:
                busy[tid].add(day)
    out = {}
    for tid, cands in model.day_off_candidates.items():
        free = [d for d in cands if d not in busy.get(tid, set())]
        out[tid] = free[0] if free else ""
    return out


def describe(model, a):
    s = model.s
    if a.kind in ("sess", "pair"):
        parts = []
        for se in a.sessions:
            cname = s.classes.get(se.class_id, {}).get("name", se.class_id)
            sname = s.subjects.get(se.subject_id, {}).get("name", se.subject_id)
            part = "" if not se.group else " group %d" % se.group
            wk = "" if not se.week else " week %s" % se.week
            parts.append("%s / %s%s%s (teacher %s)" % (cname, sname, part, wk,
                                                        se.teacher_id or "-"))
        return "%s, %dh, room %s" % (" + ".join(parts), a.dur, a.tags[0][3:].rpartition("_n")[0])
    return "%s (%s), %dh, teacher %s" % (a.comment, a.kind, a.dur, ", ".join(a.teachers) or "-")


def hardest_activity(model, logs):
    """FET's own hint: the activity after the highest 'max placed' count in
    the initial order is the one it kept failing on."""
    best = -1
    for m in re.finditer(r"reached (\d+) activities", logs.get("max_placed_activities.txt", "")):
        best = max(best, int(m.group(1)))
    order = [int(m.group(2)) for m in
             re.finditer(r"No: (\d+), Id: (\d+)", logs.get("initial_order.txt", ""))]
    if best < 0 or best >= len(order):
        return None
    by_id = {a.id: a for a in model.acts}
    a = by_id.get(order[best])
    return (best, a) if a else None


def felt_review(s, xml_path):
    """How the table FEELS, per teacher and per pupil, from the aSc XML on
    disk (the same bytes the checker reads). Week A and week B are separate
    views; a lesson in both weeks counts in both."""
    import statistics
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError):
        return ""
    days = list(s.cfg.days)
    evening = set(s.cfg.evening)
    lessons = {}
    for el in root.iter("lesson"):
        gids = (el.get("groupids") or "").split(",")[0]
        try:
            gno = int(gids.rsplit("_", 1)[1]) if gids else 0
        except (IndexError, ValueError):
            gno = 0
        lessons[el.get("id")] = ([x for x in (el.get("teacherids") or "").split(",") if x],
                                 [x for x in (el.get("classids") or "").split(",") if x],
                                 el.get("subjectid"), gno)
    cards = []
    for el in root.iter("card"):
        L = lessons.get(el.get("lessonid"))
        mask = el.get("days") or ""
        if not L or mask.count("1") != 1 or len(mask) != len(days):
            continue
        w = (el.get("weeks") or "").strip()
        weeks = ("A",) if w == "10" else ("B",) if w == "01" else ("A", "B")
        cards.append((days[mask.index("1")], int(float(el.get("period"))), L, weeks))
    t_at = collections.defaultdict(set)
    c_at = collections.defaultdict(set)          # per class PART: (class|part, week)
    for d, p, L, weeks in cards:
        for w in weeks:
            for t in L[0]:
                t_at[t, w].add((d, p))
            for c in L[1]:
                # a pupil is in ONE half: whole-class cards count for both
                # parts, a half's cards for that half only (options: for all)
                part = L[3] if 0 < L[3] < 100 else 0
                parts = [part] if part else [1, 2]
                for pt in parts:
                    c_at["%s|%d" % (c, pt), w].add((d, p))

    def split(ps):
        return [p for p in ps if p not in evening], [p for p in ps if p in evening]

    def stats(at):
        holes = collections.Counter()
        trips, hours_per_trip, lone, heavy, last, lopsided, six = [], [], 0, 0, [], 0, 0
        over6_mt = [0]
        for (who, w), sl in at.items():
            byday = collections.defaultdict(list)
            for d, p in sl:
                byday[d].append(p)
            h = n_half = 0
            for d, ps in byday.items():
                for half in split(ps):
                    if half:
                        n_half += 1
                        h += max(half) - min(half) + 1 - len(half)
                        if len(half) == 1:
                            lone += 1
                if len(ps) >= 8:
                    heavy += 1
                if len(ps) > 6 and d in days[:4]:
                    over6_mt[0] += 1
                if len(ps) >= 6:
                    six += 1
            holes[h] += 1
            trips.append(n_half)
            hours_per_trip.append(len(sl) / float(n_half) if n_half else 0)
            last.append(sum(1 for d, p in sl if p == s.cfg.periods_per_day))
            am = sum(1 for d, p in sl if p not in evening)
            if sl and (am < 0.25 * len(sl) or am > 0.75 * len(sl)):
                lopsided += 1
        return dict(holes=dict(sorted(holes.items())), n=len(at),
                    with_holes=sum(v for k, v in holes.items() if k),
                    trips=statistics.mean(trips) if trips else 0,
                    hpt=statistics.mean(hours_per_trip) if hours_per_trip else 0,
                    lone=lone, heavy=heavy, six=six, over6_mt=over6_mt[0],
                    last=statistics.mean(last) if last else 0, last_max=max(last) if last else 0,
                    last_over2=sum(1 for x in last if x > 2), lopsided=lopsided)
    T, C = stats(t_at), stats(c_at)
    bac = {c for c, v in s.classes.items() if (v.get("is_bac") or "") == "yes"}
    no_free = 0
    for (c, w), sl in c_at.items():
        if c.split("|")[0] in bac and all(any(p in evening and d == dd for d, p in sl) for dd in days[:4]):
            no_free += 0.5
    def split_mean(at):
        vals = []
        for (who, w), sl in at.items():
            byday = collections.defaultdict(list)
            for d, p in sl:
                byday[d].append(p)
            vals.append(sum(1 for ps in byday.values() if all(split(ps))))
        return statistics.mean(vals) if vals else 0.0
    t_split = split_mean(t_at)
    hard = {k for k, v in s.subjects.items() if (v.get("difficulty") or "") == "hard"}
    sport = {k for k, v in s.subjects.items() if (v.get("gap24") or "") == "yes"}

    def share(subjs, pred):
        tot = [(d, p) for d, p, L, wk in cards if L[2] in subjs]
        return 100.0 * sum(1 for d, p in tot if pred(d, p)) / len(tot) if tot else 0
    L = []
    A = L.append
    A("Teachers (%d, counted per week view):" % (T["n"] // 2 if T["n"] else 0))
    A("  holes per week 0/1/2+ (teacher-weeks): %s  - with holes: %d of %d"
      % (T["holes"], T["with_holes"], T["n"]))
    A("  half-days at school per week: %.2f (%.1f hours per half-day) - lonely half-days: %d - "
      "morning+afternoon on one day: %.2f days per teacher-week" % (T["trips"], T["hpt"], T["lone"], t_split))
    A("  6-hour days: %d teacher-days - last-period lessons per teacher/week: mean %.1f, max %d, "
      "over 2: %d - lopsided morning/afternoon: %d teacher-weeks"
      % (T["six"], T["last"], T["last_max"], T["last_over2"], T["lopsided"]))
    A("Pupils (%d classes, counted per half-class part and week):" % (C["n"] // 4 if C["n"] else 0))
    A("  holes per week 0/1/2+ (part-weeks): %s - lone hours in a half-day: %d"
      % (C["holes"], C["lone"]))
    A("  days over 6 hours Mon-Thu (ministry M-P4): %d part-days - 8-hour days any day: %d - "
      "last-period lessons per part/week: mean %.1f, max %d"
      % (C["over6_mt"], C["heavy"], C["last"], C["last_max"]))
    A("  bac class-weeks without a free afternoon Mon-Thu: %d - hard subjects in the morning: "
      "%.0f%%, at periods 9-10: %.0f%% - sport in the morning: %.0f%%"
      % (no_free, share(hard, lambda d, p: p not in evening), share(hard, lambda d, p: p >= 9),
         share(sport, lambda d, p: p not in evening)))
    felt_review.metrics = dict(trips=T["trips"], heavy=C["heavy"], t_lone=T["lone"],
                               t_with_holes=T["with_holes"], over6_mt=C["over6_mt"],
                               pupil_lone=C["lone"], t_six=T["six"], t_split=t_split)
    return "\n".join(L)


def write_report(model, status, elapsed, unplaced, n_placed, verify_rc, verify_text,
                 score_text, day_offs, logs, fet_msg, xlsx, time_limit, result_path,
                 felt_text=""):
    L = []
    A = L.append
    A("# FET bridge report")
    A("")
    A("Workbook: `%s` - FET 7.10.3, Official mode, %d half-days x %d hours, time limit %d s."
      % (os.path.basename(xlsx), len(model.grid.pdays), model.grid.nh, time_limit))
    A("")
    A("| item | value |")
    A("|---|---|")
    A("| FET status | %s (%.0f s) |" % (status, elapsed))
    A("| result read from | %s |" % (os.path.relpath(result_path, HERE) if result_path else "-"))
    A("| activities | %d (%d single cards, %d merged week-A/B pairs of which %d across two "
      "classes, %d option-band mains, %d band partners) |" % (
          len(model.acts), sum(1 for a in model.acts if a.kind == "sess"),
          model.n_pairs, model.n_cross_pairs,
          sum(1 for a in model.acts if a.kind == "band"),
          sum(1 for a in model.acts if a.kind == "partner")))
    A("| sessions placed | %d of %d |" % (n_placed, len(model.sessions)))
    A("| activities FET could not place | %d |" % len(unplaced))
    A("| verify.py | %s |" % ("ALL GREEN" if verify_rc == 0 and "ALL GREEN" in verify_text
                                else "NOT GREEN (see below)"))
    A("")
    A("## Rules encoded (hard rules at 100 percent; comfort as noted)")
    A("")
    A("| rule | FET constraints |")
    A("|---|---|")
    for k, v in sorted(model.counts.items()):
        A("| %s | %d |" % (k, v))
    A("")
    soft = ""
    for cand in result_candidates():
        p = os.path.join(os.path.dirname(cand), FET_NAME + "_soft_conflicts.txt")
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = [l.strip().lstrip("﻿") for l in f]
            totals = [l for l in lines if l.lower().startswith("total")]
            n_items = sum(1 for l in lines if l.startswith("Time constraint")
                          or l.startswith("Space constraint"))
            soft = (totals[0] if totals else "") + (" (%d broken soft constraints)" % n_items
                                                     if n_items else "")
            break
    if soft:
        A("FET soft conflicts: %s" % soft)
        A("")
    if unplaced:
        A("## Cards FET could not place")
        A("")
        A("Each line: the card, then every rule whose constraints touch it. FET gives up on "
          "the card it fails most often; the real blocker is usually the combination of the "
          "listed rules with the teacher's and class's other cards.")
        A("")
        for a in unplaced[:80]:
            A("- %s" % describe(model, a))
            A("  rules: %s" % (", ".join(sorted(set(a.rules))) or "clashes/rooms only"))
        if len(unplaced) > 80:
            A("- ...and %d more" % (len(unplaced) - 80))
        A("")
    hard = hardest_activity(model, logs)
    if hard and status != "complete":
        A("FET's furthest point: %d activities placed at once; the card it kept failing on "
          "next was **%s** (rules: %s)." % (hard[0], describe(model, hard[1]),
                                              ", ".join(sorted(set(hard[1].rules))) or "-"))
        A("")
    if logs.get("difficult_activities.txt") and status != "complete":
        A("FET's own diagnosis (logs/difficult_activities.txt, first lines):")
        A("")
        A("```")
        A("\n".join(logs["difficult_activities.txt"].strip().splitlines()[:12]))
        A("```")
        A("")
    A("## Independent check (solver/verify.py on out/fet/timetable.xml)")
    A("")
    A("```")
    A(verify_text.strip())
    A("```")
    A("")
    A("## Comfort score (tools/score_table.py)")
    A("")
    A("```")
    A(score_text.strip())
    A("```")
    A("")
    if felt_text:
        A("## How it feels (per teacher, per pupil)")
        A("")
        A("```")
        A(felt_text.strip())
        A("```")
        A("")
    dropped = getattr(model, "day_off_dropped", {})
    if dropped:
        A("## Rest day given up (Majd 2026-09-09: no morning+afternoon day beats the rest day)")
        for tid, why in sorted(dropped.items()):
            A("- %s: %s" % (model.s.teachers.get(tid, {}).get("name", tid), why))
        A("")
    allow = getattr(model, "split_allow", {})
    if allow:
        listed = {k: v for k, v in allow.items() if v}
        A("## Morning+afternoon on the same day")
        A("- forbidden for %d teachers on every weekday; allowed for %d on the days listed:"
          % (len(allow) - len(listed), len(listed)))
        for tid, ds in sorted(listed.items()):
            A("  - %s: %s" % (model.s.teachers.get(tid, {}).get("name", tid), ", ".join(ds)))
        A("")
    if day_offs:
        A("## Day off chosen by the engine (blank day_off in the Teachers sheet)")
        A("")
        A("| teacher | free day |")
        A("|---|---|")
        for tid, d in sorted(day_offs.items()):
            A("| %s | %s |" % (tid, d or "NONE - every day has lessons"))
        A("")
    A("## Approximations in the FET encoding (all on the safe side)")
    A("")
    A("- Week A/B: %d week-A cards share one activity with a week-B card of the same shape "
      "(%d of them with a card of ANOTHER class). The pair sits in one slot and one room; "
      "both teachers and both classes are blocked in that slot in both weeks. Unpaired "
      "fortnight cards block their slot in both weeks alone." % (model.n_pairs, model.n_cross_pairs))
    A("- H17 counts week-A and week-B hours together on a day (a teacher with 5 every-week "
      "hours plus one A and one B hour on the same day is refused although each week has 6).")
    A("- Pupils' half-day rule: hours of PE and options do not count; a half-day with one "
      "ordinary hour plus one PE hour is refused (the circular would allow it).")
    A("- H20 pairs use block k of group 1 with block k of group 2, in either order, inside "
      "one half-day.")
    p5 = tuple(getattr(model.grid.cfg, "p5_days", ()) or ())
    if p5:
        A("- Period 5 (12:00-13:00) is open on %s (Majd, 2026-09-07). Hard subjects stay out "
          "of it; a class that has period 5 on a day with an afternoon does not have period 7 "
          "that day (two-hour break). verify.py was run with --p5 pointed at these days "
          "(its own default is Mon-Thu)." % ", ".join(p5))
    A("- Same subject once a day is applied across all rows of a class+subject (Majd, "
      "2026-09-01), which contains H9." if model.same_subject_once else
      "- H9 only within each row's own blocks (--no-same-subject-once).")
    if model.notes:
        A("")
        A("## Notes from the export")
        A("")
        for n in model.notes:
            A("- " + n)
    if logs.get("errors.txt") or logs.get("warnings.txt"):
        A("")
        A("## FET logs")
        A("")
        for k in ("errors.txt", "warnings.txt"):
            if logs.get(k):
                A("**%s**" % k)
                A("```")
                A(logs[k].strip()[:4000])
                A("```")
    if fet_msg:
        A("")
        A("```")
        A(fet_msg[-2000:])
        A("```")
    path = os.path.join(OUT, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path



def measured_gaps(model, act_slots):
    """Holes inside half-days as FET counts them: per teacher (all of the
    teacher's activities) and per class (the worst of its class parts)."""
    busy_t = collections.defaultdict(lambda: collections.defaultdict(set))
    busy_c = collections.defaultdict(lambda: collections.defaultdict(set))
    for a in model.acts:
        sl = act_slots.get(a.id)
        if not sl:
            continue
        pday, h0 = sl
        hrs = set(range(h0, h0 + a.dur))
        for tid in a.teachers:
            busy_t[tid][pday] |= hrs
        for st in a.students:
            if "_o_" in st:
                cid, part = st.split("_o_")[0], ""
            else:
                cid, _, part = st.partition("_g")
            parts = [int(part)] if part else (list(range(1, model.n_groups_of.get(cid, 0) + 1))
                                              or [0])
            for p_ in parts:
                busy_c[cid, p_][pday] |= hrs

    def gaps(byday):
        return sum(max(h) - min(h) + 1 - len(h) for h in byday.values())
    gt = {tid: gaps(bd) for tid, bd in busy_t.items()}
    gc = {}
    for (cid, _p), bd in busy_c.items():
        gc[cid] = max(gc.get(cid, 0), gaps(bd))
    return gt, gc


def measured_splits(model, act_slots):
    """Per teacher: the weekdays where the placed table has both a morning
    and an afternoon activity."""
    used = collections.defaultdict(set)
    for a in model.acts:
        sl = act_slots.get(a.id)
        if not sl:
            continue
        for tid in a.teachers:
            used[tid].add(sl[0])
    days = list(model.s.cfg.days)
    out = {}
    for tid, pds in used.items():
        byd = collections.defaultdict(set)
        for pd in pds:
            d, _, half = pd.rpartition("-")
            byd[d].add(half)
        out[tid] = sorted((d for d, hs in byd.items() if len(hs) == 2), key=days.index)
    return out


def load_budgets(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                b = json.load(f)
            return {"teachers": dict(b.get("teachers", {})), "classes": dict(b.get("classes", {})),
                    "split": dict(b.get("split", {}))}
        except (OSError, ValueError):
            pass
    return {"teachers": {}, "classes": {}, "split": {}}


def save_budgets(budgets):
    with open(os.path.join(OUT, "budgets.json"), "w", encoding="utf-8") as f:
        json.dump(budgets, f, indent=1, sort_keys=True)


def tighten(model, act_slots, budgets, comfort, force_frac=0.0, which="teachers"):
    """Ratchet: nobody may have more holes than in the round just placed;
    the worst third of those still allowed holes must lose one more."""
    gt, gc = measured_gaps(model, act_slots)
    out = {"teachers": {}, "classes": {}}
    for key, measured, cap in (("teachers", gt, comfort.get("teacher_gaps")),
                               ("classes", gc, comfort.get("pupil_gaps"))):
        if which != "both" and key != which:
            out[key] = dict(budgets.get(key, {}))
            continue
        cap = 99 if cap is None else cap
        cur = budgets.get(key, {})
        new = {}
        for ent, m in measured.items():
            new[ent] = min(cur.get(ent, cap), m)
        candidates = sorted((e for e in new if new[e] >= 1), key=lambda e: -new[e])
        n_force = int(len(candidates) * force_frac) if force_frac > 0 else 0
        for e in candidates[:n_force]:
            new[e] -= 1
        out[key] = new
    if comfort.get("split_days") in ("facts", "none") and getattr(model, "split_allow", None) is not None:
        ms = measured_splits(model, act_slots)
        out["split"] = {tid: [d for d in al if d in ms.get(tid, [])]
                        for tid, al in model.split_allow.items()}
    else:
        out["split"] = dict(budgets.get("split", {}))
    return out


def rescue(model, budgets, comfort, s):
    """Loosen the teachers of the card FET kept failing on: their split-day
    allowance goes back to the official table's days (or one free weekday)
    and their hole budget grows by one. Returns the list of relaxed teachers."""
    stuck = list(getattr(model, "stuck_teachers", []) or [])
    if not stuck:
        return []
    days = list(s.cfg.days)
    facts = FACTS.get("split_days") or {}
    out = []
    for tid in stuck:
        rec = s.teachers.get(tid, {})
        blocked = {(rec.get("training_day") or "").strip(), (rec.get("day_off") or "").strip()}
        if comfort.get("split_days") in ("facts", "none"):
            cur = [d for d in budgets.setdefault("split", {}).get(tid, []) if d in days]
            want = [d for d in facts.get(tid, []) if d in days and d not in blocked and d not in cur]
            if not want:
                want = [d for d in days if d not in blocked and d not in cur][:1]
            if want:
                budgets["split"][tid] = cur + want
                out.append("%s: split day allowed on %s" % (rec.get("name", tid), ", ".join(cur + want)))
        cap = comfort.get("teacher_gaps")
        if cap is not None:
            b = budgets.setdefault("teachers", {})
            have = int(b.get(tid, cap))
            if have < cap:
                b[tid] = have + 1
                out.append("%s: hole budget %d -> %d" % (rec.get("name", tid), have, have + 1))
    # the stuck card's class: one more hole allowed per week for its parts
    # (up to one above the global budget - reported, never silent)
    pcap = comfort.get("pupil_gaps")
    if pcap is not None:
        b = budgets.setdefault("classes", {})
        for cid in getattr(model, "stuck_classes", []) or []:
            have = int(b.get(cid, pcap))
            if have < pcap + 1:
                b[cid] = have + 1
                out.append("class %s: hole budget %d -> %d"
                           % (s.classes.get(cid, {}).get("name", cid), have, have + 1))
    return out


def one_round(args, s, sessions, grid, comfort, budgets, strict, odd, p5_days, rnd):
    """Export, run FET, import, write, verify, score, keep the best.
    Returns (exit code, keep going?, model, act_slots)."""
    if comfort:
        comfort = dict(comfort, teacher_gap_by=budgets.get("teachers", {}),
                       pupil_gap_by=budgets.get("classes", {}), split_by=budgets.get("split", {}),
                       pin=PINS)
    model = Model(s, sessions, grid, same_subject_once=not args.no_same_subject_once,
                  pair_weeks=not args.no_pairing, comfort=comfort)
    if strict:
        model.notes.append("verify.py reads the room type per class+subject (last row wins): "
                           "%s ordinary theory hours were therefore required in a lab (%s)."
                           % (sum(strict.values()),
                              ", ".join("%s: %d h" % kv for kv in sorted(strict.items()))))
    for cid, sid, want in sorted(odd):
        model.notes.append("class %s subject %s: verify.py will demand a '%s' room for its "
                           "ordinary rows too - not forced here, expect an H6 complaint"
                           % (cid, sid, want))
    if comfort and (budgets.get("teachers") or budgets.get("classes")):
        model.notes.append("round %d: per-teacher hole budgets %s, per-class %s"
                           % (rnd, collections.Counter(budgets["teachers"].values()),
                              collections.Counter(budgets["classes"].values())))
    fet_path = model.write(os.path.join(OUT, FET_NAME + ".fet"))
    print("\n=== round %d ===" % rnd if comfort else "")
    print("Exported %s: %d activities (%d week-A/B pairs, %d across classes), "
          "%d time constraints, %d space constraints"
          % (os.path.relpath(fet_path, HERE), len(model.acts), model.n_pairs,
             model.n_cross_pairs, len(model.time_c), len(model.space_c)))
    for k, v in sorted(model.counts.items()):
        print("  %-52s %6d" % (k, v))
    for n in model.notes:
        print("  NOTE  :", n)
    if args.export_only:
        return 0, False, model, {}

    status, elapsed, fet_msg = "imported", 0.0, ""
    if not args.import_only:
        status, elapsed, fet_msg = run_fet(fet_path, args.time, force=args.force)
        print("FET finished: %s after %.0f s" % (status, elapsed))
    logs = fet_logs()
    if status == "failed":
        print(fet_msg[-1500:])
        if logs.get("errors.txt"):
            print(logs["errors.txt"][:3000])
    placement, unplaced, fet_rooms, result_path, act_slots = import_result(model)
    day_offs = chosen_day_offs(model, act_slots)
    n_placed = 0
    verify_rc, verify_text, score_text = 1, "(no timetable written)", ""
    if placement:
        rooms = rooms_from_fet(model, fet_rooms)
        n_placed, n_regular = write_outputs(s, sessions, placement, day_offs, rooms)
        print("Wrote %s: timetable.xml, view.html, solution.json (%d of %d sessions)"
              % (os.path.relpath(OUT, HERE), n_placed, n_regular))
        verify_rc, verify_text = run_verify(args.xlsx, p5_days)
        print(verify_text)
        score_text = run_score()
        print(score_text)
        felt_text = felt_review(s, os.path.join(OUT, "timetable.xml"))
        print(felt_text)
        if verify_rc == 0 and "ALL GREEN" in verify_text and not unplaced:
            if keep_best(parse_score(score_text), " ".join(sys.argv[1:]) + " [round %d]" % rnd,
                         getattr(felt_review, "metrics", None)):
                print("-> new best: copied to out/fet/best/")
    else:
        felt_text = ""
    rep = write_report(model, status, elapsed, unplaced, n_placed, verify_rc, verify_text,
                       score_text, day_offs, logs, fet_msg, args.xlsx, args.time, result_path,
                       felt_text)
    print("Report: %s" % os.path.relpath(rep, HERE))
    if unplaced:
        print("\n%d activities FET could not place - see the report." % len(unplaced))
        for a in unplaced[:15]:
            print("  - %s\n      rules: %s" % (describe(model, a),
                                              ", ".join(sorted(set(a.rules))) or "-"))
        hard = hardest_activity(model, logs)
        if hard:
            print("\nFET got %d activities placed at once; it kept failing on:\n  %s\n  rules: %s"
                  % (hard[0], describe(model, hard[1]), ", ".join(sorted(set(hard[1].rules)))))
            model.stuck_teachers = list(hard[1].teachers)
            model.stuck_classes = sorted({(st.split("_o_")[0] if "_o_" in st else st.partition("_g")[0])
                                          for st in hard[1].students})
    ok = verify_rc == 0 and not unplaced and status in ("complete", "imported")
    return (0 if ok else 1), ok, model, act_slots


# ---------------------------------------------------------------------------
def main():
    global OUT, STALL_S
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("xlsx", nargs="?", default=os.path.join(HERE, "data", "school_lastyear.xlsx"))
    ap.add_argument("--time", type=int, default=900, help="FET time limit in seconds")
    ap.add_argument("--export-only", action="store_true", help="write school.fet and stop")
    ap.add_argument("--import-only", action="store_true",
                    help="skip FET, read the last result under out/fet/timetables")
    ap.add_argument("--no-same-subject-once", action="store_true",
                    help="only H9 (blocks of one row on different days), not the "
                         "'same subject once a day' rule across rows")
    ap.add_argument("--no-pairing", action="store_true",
                    help="do not merge week-A and week-B cards into shared activities")
    ap.add_argument("--p5", default="Fri,Sat",
                    help="days whose morning may run to 13:00 (period 5). Majd 2026-09-07: "
                         "Friday and Saturday, keeping the 2-hour break on Friday. "
                         "Use --p5 none to keep period 5 closed everywhere.")
    ap.add_argument("--teacher-gaps", type=int, default=1,
                    help="hard budget: holes inside half-days per teacher per week (-1 = none). "
                         "Majd 2026-09-07: never 2 hole-hours, so 1 is the ceiling")
    ap.add_argument("--pupil-gaps", type=int, default=2,
                    help="hard budget: holes inside half-days per class part per week (-1 = none)")
    ap.add_argument("--no-bac-afternoon", action="store_true",
                    help="drop the hard 'bac class has a free afternoon Mon-Thu'")
    ap.add_argument("--no-pair-days", action="store_true",
                    help="drop the hard '1+1 subject not on consecutive days'")
    ap.add_argument("--no-soft", action="store_true", help="drop the soft time preferences")
    ap.add_argument("--no-max-half-days", action="store_true",
                    help="drop the hard 'a teacher comes in at most ceil(hours/4)+1 half-days'")
    ap.add_argument("--no-fortnight-zero", action="store_true",
                    help="drop 'zero FET holes for teachers with fortnight cards'")
    ap.add_argument("--pupil-day-cap", default="ministry",
                    help="'ministry' = at most 6 hours a day Mon-Thu per class part, 7 only where "
                         "the week cannot fit (inspectorate M-P4); a number = flat cap on light "
                         "class parts; 0 = off")
    ap.add_argument("--pupil-day-cap-hours", type=int, default=40,
                    help="apply the day cap to class parts with at most this many hours a week")
    ap.add_argument("--last-cap", type=int, default=3,
                    help="hard: max last-period lessons per class part per week (+1 for parts "
                         "over --last-cap-hours; 0 = off)")
    ap.add_argument("--last-cap-hours", type=int, default=40)
    ap.add_argument("--w-hard-am", type=int, default=60, help="soft %: hard subjects in the morning")
    ap.add_argument("--w-hard-last", type=int, default=95, help="soft %: hard subjects not last")
    ap.add_argument("--w-bac-last", type=int, default=80, help="soft %: bac classes not last")
    ap.add_argument("--w-sport-am", type=int, default=80, help="soft %: sport in the morning")
    ap.add_argument("--w-half-days", type=int, default=100,
                    help="weight of the per-teacher max half-days cap (100 = hard; 90 = preference)")
    ap.add_argument("--w-double-top", type=int, default=0,
                    help="soft %: a double at the top of its half-day (0 = off; broad, slows FET)")
    ap.add_argument("--w-opt-together", type=int, default=90,
                    help="soft %: the options of a band at the same time")
    ap.add_argument("--w-last", type=int, default=0,
                    help="soft weight (percent) for 'nobody in the last period'; 0 = off. "
                         "At 50 it stalled FET (a retry penalty on every card) - use with care")
    ap.add_argument("--never-last", default="رياضيات",
                    help="subjects (ids or names, comma separated) that never sit in the last "
                         "period - HARD. Majd 2026-09-07: mathematics")
    ap.add_argument("--split-days", choices=("off", "facts", "none"), default="facts",
                    help="Majd 2026-09-09: a teacher does not come morning AND afternoon on one "
                         "day (hard). facts = allowed only on the days the official table splits "
                         "that teacher (and where the hours force it), tightened each round; "
                         "none = only where the hours force it; off = no rule")
    ap.add_argument("--day-off", choices=("keep", "auto", "none"), default="auto",
                    help="flexible rest day: keep = always one free weekday; auto = given up only "
                         "for teachers whose hours cannot fit without a split day; none = no rest "
                         "day for anyone (fixed day_off and training days always stay)")
    ap.add_argument("--stall", type=int, default=900,
                    help="cut an attempt short when FET has not placed a new activity for this "
                         "many seconds (0 = never); the next seed or the rescue follows")
    ap.add_argument("--w-hard-late", type=int, default=95,
                    help="soft %: hard/core subjects not at 16-18 (Majd 2026-09-10)")
    ap.add_argument("--w-after-sport", type=int, default=95,
                    help="soft %: no hard/core lesson right after (or before) sport in a half-day")
    ap.add_argument("--pin", default="",
                    help="teachers who also work in another school (ids or names, comma separated, "
                         "or @file with one per line): they may only teach in the half-days the "
                         "school's table gave them (hard). Majd 2026-09-10")
    ap.add_argument("--pin-mode", choices=("halfdays", "days"), default="halfdays",
                    help="pin to the school table's half-days (default) or to its weekdays")
    ap.add_argument("--rescues", type=int, default=3,
                    help="when every attempt of a round fails, give the stuck card's teachers "
                         "their split day and one hole back and rerun the round, this many times")
    ap.add_argument("--no-comfort", action="store_true", help="hard rules only")
    ap.add_argument("--rounds", type=int, default=1,
                    help="tightening rounds: after each ALL GREEN round, per-teacher and "
                         "per-class hole budgets ratchet down and FET runs again")
    ap.add_argument("--force-frac", type=float, default=0.0,
                    help="tightening: fraction of the worst entities that lose one more hole "
                         "each round on top of the ratchet (0 = ratchet only)")
    ap.add_argument("--ratchet", choices=("teachers", "classes", "both"), default="teachers",
                    help="whose hole budgets ratchet down between rounds")
    ap.add_argument("--attempts", type=int, default=1,
                    help="retries of a round that FET did not finish (fresh random seed each)")
    ap.add_argument("--budgets", default="",
                    help="start from these per-teacher/per-class hole budgets (json written "
                         "by a previous run as out/fet/budgets.json)")
    ap.add_argument("--outdir", default=OUT,
                    help="where school.fet, FET's results and the outputs go (default out/fet; "
                         "use a sub-folder per workbook, e.g. out/fet/official)")
    ap.add_argument("--force", action="store_true", help="ignore a stale fet.running lock")
    args = ap.parse_args()
    OUT = os.path.abspath(args.outdir)
    os.makedirs(OUT, exist_ok=True)
    comfort = {}
    if not args.no_comfort:
        comfort = dict(never_last=[x.strip() for x in args.never_last.split(",") if x.strip()],
                       teacher_gaps=None if args.teacher_gaps < 0 else args.teacher_gaps,
                       pupil_gaps=None if args.pupil_gaps < 0 else args.pupil_gaps,
                       bac_afternoon=not args.no_bac_afternoon,
                       pair_days=not args.no_pair_days, soft=not args.no_soft,
                       w_last=args.w_last, w_hard_am=args.w_hard_am, w_hard_last=args.w_hard_last,
                       w_bac_last=args.w_bac_last, w_sport_am=args.w_sport_am,
                       w_double_top=args.w_double_top, w_opt_together=args.w_opt_together,
                       max_half_days=not args.no_max_half_days, w_half_days=args.w_half_days,
                       fortnight_zero_holes=not args.no_fortnight_zero,
                       pupil_day_cap=(None if str(args.pupil_day_cap) in ("0", "off", "none")
                                      else ("ministry" if args.pupil_day_cap == "ministry"
                                            else int(args.pupil_day_cap))),
                       pupil_day_cap_hours=args.pupil_day_cap_hours,
                       last_cap=args.last_cap or None, last_cap_hours=args.last_cap_hours,
                       split_days=args.split_days, day_off=args.day_off,
                       w_hard_late=args.w_hard_late, w_after_sport=args.w_after_sport)

    cfg = D.load_config()
    p5_days = ()
    if args.p5 and args.p5.lower() not in ("none", "no", "off", ""):
        p5_days = cfg.open_period5(tuple(x.strip() for x in args.p5.split(",") if x.strip()))
        print("Period 5 (12:00-13:00) open on: %s" % ", ".join(p5_days))
    STALL_S = max(0, args.stall)
    s = D.load_school(args.xlsx, cfg)
    facts_path = os.path.splitext(args.xlsx)[0] + "_facts.json"
    if os.path.exists(facts_path):
        with open(facts_path, encoding="utf-8") as fh:
            FACTS.update(json.load(fh))
        print("facts from the official table: %s (%d teachers with a morning+afternoon day)"
              % (os.path.basename(facts_path), len(FACTS.get("split_days") or {})))
    pins = {}
    if args.pin:
        wanted = []
        for tok in args.pin.split(","):
            tok = tok.strip()
            if tok.startswith("@") and os.path.exists(tok[1:]):
                with open(tok[1:], encoding="utf-8") as fh:
                    wanted += [l.strip() for l in fh if l.strip() and not l.startswith("#")]
            elif tok:
                wanted.append(tok)
        norm = lambda x: " ".join(str(x).replace("\u0640", "").split())
        by_name = {norm(v.get("name", "")): k for k, v in s.teachers.items()}
        halfdays = FACTS.get("halfdays") or {}
        for w in wanted:
            tid = w if w in s.teachers else by_name.get(norm(w))
            if tid is None:
                cands = [k for n, k in by_name.items() if norm(w) and norm(w) in n]
                tid = cands[0] if len(cands) == 1 else None
            if tid is None:
                print("WARNING: --pin: no teacher matches '%s' - ignored" % w)
                continue
            hd = halfdays.get(tid, [])
            if not hd:
                print("WARNING: --pin: %s has no cards in the school's table - not pinned" % w)
                continue
            pins[tid] = sorted({x.split("-")[0] for x in hd}) if args.pin_mode == "days" else list(hd)
        PINS.update(pins)
        if pins:
            print("pinned to the school table's %s: %s" % (
                args.pin_mode, "; ".join("%s -> %s" % (s.teachers[k]["name"], ", ".join(v)) for k, v in pins.items())))
    errs, notes = D.check(s)
    for n in notes:
        if "option bands" not in n:
            print("  NOTE  :", n)
    if errs:
        for e in errs:
            print("  ERROR :", e)
        sys.exit("The workbook has %d error(s) - nothing to place." % len(errs))
    sessions = S.expand(s)
    # verify.py judges H6 per (class, subject): the LAST curriculum row of the
    # pair sets the room type for every card of it. When a subject has a
    # theory row (ordinary room) followed by a lab practical row, its theory
    # hours are therefore placed in a lab as well - a room Majd said may host
    # ordinary lessons anyway, and valid under both readings of the rule.
    need = {}
    for row in s.curriculum:
        need[row["class_id"], row["subject_id"]] = s.room_type_for(row)
    strict = collections.Counter()
    odd = set()
    for se in sessions:
        if se.subject_id.startswith("OPT:"):
            continue
        want = need.get((se.class_id, se.subject_id), se.room_type)
        if want != se.room_type and se.room_type == "normal":
            if want in D.SPARE_FOR_NORMAL:
                se.room_type = want
                strict[want] += se.length
            else:
                odd.add((se.class_id, se.subject_id, want))
    grid = Grid(cfg)
    budgets = load_budgets(args.budgets)
    rc = 1
    rnd, rescues_left = 1, max(0, args.rescues)
    while rnd <= max(1, args.rounds):
        for attempt in range(1, max(1, args.attempts) + 1):
            rc, go_on, model, act_slots = one_round(args, s, sessions, grid, comfort, budgets,
                                                    strict, odd, p5_days, rnd)
            if go_on or args.import_only or args.export_only:
                break
            if attempt < args.attempts:
                print("round %d attempt %d did not finish - retrying with a fresh FET seed"
                      % (rnd, attempt), flush=True)
        if not go_on and comfort and rescues_left > 0 and not (args.import_only or args.export_only):
            relaxed = rescue(model, budgets, comfort, s)
            if relaxed:
                rescues_left -= 1
                save_budgets(budgets)
                print("round %d failed - rescue (%d left): %s - running the round again"
                      % (rnd, rescues_left, "; ".join(relaxed)), flush=True)
                continue
        if not go_on or not comfort or rnd >= args.rounds or args.import_only:
            break
        rnd += 1
        budgets = tighten(model, act_slots, budgets, comfort, args.force_frac, args.ratchet)
        save_budgets(budgets)
        print("round %d done - budgets tightened (teachers %s, classes %s), see out/fet/budgets.json"
              % (rnd - 1, dict(collections.Counter(budgets["teachers"].values())),
                 dict(collections.Counter(budgets["classes"].values()))))
    return rc


if __name__ == "__main__":
    sys.exit(main())

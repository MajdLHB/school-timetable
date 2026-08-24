"""Load the school data from data/school.xlsx and sanity-check it.

This file knows nothing about solving. If check() is happy, the data is
internally consistent. That does NOT mean a timetable exists - only that the
numbers make sense.
"""
import json
import os
import sys
from dataclasses import dataclass, field

# Windows consoles default to cp1252, which cannot encode Arabic and raises
# UnicodeEncodeError mid-print. Force UTF-8 so real names are printable.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The workbook has a grey hint row at row 2 which must be skipped.
FIRST_DATA_ROW = 2


@dataclass
class Config:
    days: list
    periods_per_day: int
    morning: list
    evening: list
    closed: dict
    time_limit: int
    weights: dict
    weeks_per_cycle: int = 1

    @property
    def slots(self):
        """Every (day, period) the school is open, in time order."""
        out = []
        for d in self.days:
            shut = set(self.closed.get(d, []))
            for p in range(1, self.periods_per_day + 1):
                if p not in shut:
                    out.append((d, p))
        return out

    def day_slots(self, day):
        return [(d, p) for (d, p) in self.slots if d == day]


@dataclass
class School:
    cfg: Config
    teachers: dict = field(default_factory=dict)
    classes: dict = field(default_factory=dict)
    rooms: dict = field(default_factory=dict)
    subjects: dict = field(default_factory=dict)
    curriculum: list = field(default_factory=list)
    unavailable: list = field(default_factory=list)
    locked: list = field(default_factory=list)

    def room_type_for(self, cur_row):
        """Which kind of room this curriculum row needs."""
        if cur_row.get("room_type"):
            return cur_row["room_type"]
        subj = self.subjects.get(cur_row["subject_id"], {})
        return subj.get("room_type", "normal") or "normal"

    def rooms_of_type(self, t):
        return [r for r in self.rooms.values() if r["type"] == t]


def load_config(path=None):
    path = path or os.path.join(HERE, "config.json")
    with open(path, encoding="utf-8") as f:
        c = json.load(f)
    closed = {k: v for k, v in c.get("closed", {}).items() if not k.startswith("_")}
    return Config(
        days=c["days"],
        periods_per_day=c["periods_per_day"],
        morning=c["morning_periods"],
        evening=c["evening_periods"],
        closed=closed,
        time_limit=c.get("time_limit_seconds", 120),
        weights=c["weights"],
        weeks_per_cycle=c.get("weeks_per_cycle", 1),
    )


def _rows(ws):
    """Yield dicts from an openpyxl sheet, skipping the hint row and blanks."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    for r in rows[FIRST_DATA_ROW:]:
        if r is None or all(v is None or str(v).strip() == "" for v in r):
            continue
        rec = {}
        for h, v in zip(header, r):
            if h:
                rec[h] = "" if v is None else str(v).strip()
        if rec.get(header[0]):
            yield rec


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def parse_blocks(blocks, hours):
    """H9: '2+1+1' -> [2, 1, 1]. Blank -> all single hours.

    Returns (list, error_message). error_message is None when the value is
    readable; the CONSISTENCY of the list (sum vs hours, fitting the week)
    is judged in check(), where it can be reported in plain language.
    """
    t = str(blocks or "").strip()
    if not t:
        return ([1] * hours if hours > 0 else [], None)
    parts = [p for p in t.replace(" ", "").split("+") if p]
    try:
        out = [int(float(p)) for p in parts]
    except ValueError:
        return (None, "blocks '%s' is unreadable - write it like 2+1+1" % blocks)
    if not out or any(v <= 0 for v in out):
        return (None, "blocks '%s' must be positive numbers joined by +" % blocks)
    return (out, None)


def longest_open_run(cfg):
    """The longest run of NUMERICALLY consecutive open periods on any day.
    A block longer than this cannot be placed anywhere (the lunch break
    interrupts every day, so on the real config this is 4)."""
    best = 0
    for d in cfg.days:
        ps = sorted(p for (dd, p) in cfg.slots if dd == d)
        run = 0
        prev = None
        for p in ps:
            run = run + 1 if prev is not None and p == prev + 1 else 1
            prev = p
            best = max(best, run)
    return best


def load_school(xlsx=None, cfg=None):
    from openpyxl import load_workbook

    cfg = cfg or load_config()
    xlsx = xlsx or os.path.join(HERE, "data", "school.xlsx")
    if not os.path.exists(xlsx):
        sys.exit(
            "No data file at " + xlsx + "\n"
            "  python tools/make_workbook.py   -> blank workbook to fill in\n"
            "  python tools/make_demo.py       -> demo school, to try the tool"
        )
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    s = School(cfg=cfg)

    for r in _rows(wb["Teachers"]):
        s.teachers[r["id"]] = dict(
            id=r["id"],
            name=r.get("name") or r["id"],
            short=r.get("short") or r["id"],
            subjects=[x for x in (r.get("subjects") or "").split(";") if x],
            hours=_int(r.get("hours")),
            day_off=(r.get("day_off") or "").strip(),
            # M-T6 / circular II.1: the pedagogical training day stays empty,
            # exactly like a day off. Blank = no training day.
            training_day=(r.get("training_day") or "").strip(),
            # S8: ministry default is hours spread over most days (II.2).
            # compact=yes keeps the packed week - the exception Majd grants to
            # teachers with long journeys. Blank = ministry default.
            compact=(r.get("compact") or "").strip().lower(),
            # S21 shared transport: the partner's teacher id. Filling one
            # side is enough - the pair is symmetric.
            travels_with=(r.get("travels_with") or "").strip(),
            notes=r.get("notes", ""),
        )
    for r in _rows(wb["Classes"]):
        s.classes[r["id"]] = dict(
            id=r["id"],
            name=r.get("name") or r["id"],
            grade=r.get("grade", ""),
            stream=(r.get("stream") or "").strip(),
            # yes = final year. Drives S13 (no Friday evening, local
            # preference) and S17 (free afternoon Mon-Thu, circular I.6).
            is_bac=(r.get("is_bac") or "").strip().lower(),
            cohort=(r.get("cohort") or "ALL").upper(),
            home_room=r.get("home_room", ""),
            size=_int(r.get("size")),
        )
    for r in _rows(wb["Rooms"]):
        s.rooms[r["id"]] = dict(
            id=r["id"],
            name=r.get("name") or r["id"],
            type=(r.get("type") or "normal").strip(),
            capacity=_int(r.get("capacity"), 999),
        )
    for r in _rows(wb["Subjects"]):
        s.subjects[r["id"]] = dict(
            id=r["id"],
            name=r.get("name") or r["id"],
            short=r.get("short") or r["id"],
            difficulty=(r.get("difficulty") or "medium").strip(),
            room_type=(r.get("room_type") or "normal").strip(),
            # H15: last period this subject may occupy. Blank = no limit.
            # Older workbooks have no such column, hence the tolerant get().
            latest_period=_int(r.get("latest_period"), 0),
            # S16: soft version - prefer not to sit after this period.
            # Ministry: Maths before 16:00 (M-MA3), Physics not 17-18 (M-PH5).
            avoid_after=_int(r.get("avoid_after"), 0),
            # Circular I.2 note: the min-2h/session rules do not apply to PE
            # and optional subjects. yes = exempt from S15.
            minmax_exempt=(r.get("minmax_exempt") or "").strip().lower(),
            # H19, circular III.2 note on PE: always 24 hours between the two
            # sessions. yes = on consecutive days the later session must not
            # start earlier than the first one did.
            gap24=(r.get("gap24") or "").strip().lower(),
            # S18: subjects this one must not FOLLOW immediately (same class,
            # adjacent periods). The inspectorate: never Philosophy straight
            # after PE - so PHIL carries not_after=SPORT. ; separated ids.
            not_after=[v for v in (r.get("not_after") or "").replace(",", ";").split(";")
                       if v.strip()],
            # S4 / M-P6: the subject's nature (literary / scientific /
            # social). Two DIFFERENT subjects of the same nature back to
            # back are penalised; a double of one subject is fine.
            nature=(r.get("nature") or "").strip().lower(),
        )
    for r in _rows(wb["Curriculum"]):
        s.curriculum.append(dict(
            class_id=r["class_id"],
            subject_id=r["subject_id"],
            hours=_int(r.get("hours")),
            teacher_id=r.get("teacher_id", ""),
            blocks=r.get("blocks", ""),
            # How many groups this class splits into for THIS subject.
            # Default 1 - never assume a split. Proved necessary by last
            # year's file: 4رياضيات1 ran Computer Science whole-class while
            # splitting for Natural Sciences and Physics.
            groups=max(1, _int(r.get("groups"), 1)),
            room_type=r.get("room_type", ""),
            # S19, circular III.2: core / stream-specific subjects get three
            # quarters of their hours in the morning. yes = this row is one.
            core=(r.get("core") or "").strip().lower(),
            # Week A/B (the ministry fortnight patterns, T42): blank = every
            # week; A or B = that week of the two-week cycle only. hours are
            # the hours IN that week. Older workbooks have no such column.
            week=(r.get("week") or "").strip().upper(),
        ))
    if "Unavailable" in wb.sheetnames:
        for r in _rows(wb["Unavailable"]):
            s.unavailable.append(dict(
                teacher_id=r["teacher_id"],
                day=r.get("day", "*") or "*",
                period=r.get("period", "*") or "*",
                hard=(r.get("hard") or "yes").lower(),
                reason=r.get("reason", ""),
            ))
    if "Locked" in wb.sheetnames:
        for r in _rows(wb["Locked"]):
            s.locked.append(dict(
                class_id=r["class_id"],
                subject_id=r["subject_id"],
                day=r["day"],
                period=_int(r.get("period")),
                room_id=r.get("room_id", ""),
                why=r.get("why", ""),
            ))
    wb.close()
    return s


def check(s):
    """Plain-language validation. Returns (errors, notes)."""
    errs, notes = [], []
    days = set(s.cfg.days)

    max_run = longest_open_run(s.cfg)
    for c in s.curriculum:
        where = "Curriculum row " + c["class_id"] + " / " + c["subject_id"]
        if c.get("week", "") not in ("", "A", "B"):
            errs.append(where + " - week '" + c["week"] + "' must be blank "
                        "(every week), A or B.")
        if c["class_id"] not in s.classes:
            errs.append(where + " - class '" + c["class_id"] + "' is not in the Classes sheet.")
        if c["subject_id"] not in s.subjects:
            errs.append(where + " - subject '" + c["subject_id"] + "' is not in the Subjects sheet.")
        if c["teacher_id"] and c["teacher_id"] not in s.teachers:
            errs.append(where + " - teacher '" + c["teacher_id"] + "' is not in the Teachers sheet.")
        if c["hours"] <= 0:
            errs.append(where + " - hours must be greater than 0.")
        # H9: an EXPLICIT block pattern must be readable and must fit the
        # week. A blank pattern imposes nothing - the solver places single
        # hours freely (spreading is then a soft rule, not a promise).
        if str(c.get("blocks", "")).strip():
            bl, berr = parse_blocks(c.get("blocks", ""), c["hours"])
            if berr:
                errs.append(where + " - " + berr)
            elif bl:
                if sum(bl) != c["hours"]:
                    errs.append(where + " - blocks " + str(c.get("blocks")) + " add up to " +
                                str(sum(bl)) + " but hours says " + str(c["hours"]) + ".")
                if len(bl) > len(s.cfg.days):
                    errs.append(where + " - " + str(len(bl)) + " blocks but the week only has " +
                                str(len(s.cfg.days)) + " days (each block goes on its own day, H9).")
                if max(bl) > max_run:
                    errs.append(where + " - a block of " + str(max(bl)) + " consecutive hours can "
                                "never be placed: the longest open run in any day is " +
                                str(max_run) + " (the lunch break interrupts every day).")

    for t in s.teachers.values():
        off = t["day_off"]
        if off and off not in days and off != "(none)":
            errs.append("Teacher " + t["id"] + " has day_off '" + off +
                        "' which is not a school day (" + ", ".join(s.cfg.days) + ").")
        tw = t.get("travels_with", "")
        if tw and tw not in s.teachers:
            errs.append("Teacher " + t["id"] + " travels_with '" + tw +
                        "' which is not a teacher id in the Teachers sheet.")
        if tw and tw == t["id"]:
            errs.append("Teacher " + t["id"] + " travels_with themselves - "
                        "name the OTHER teacher of the pair.")
        tr = t.get("training_day", "")
        if tr and tr not in days and tr != "(none)":
            errs.append("Teacher " + t["id"] + " has training_day '" + tr +
                        "' which is not a school day (" + ", ".join(s.cfg.days) + ").")
        if tr and tr == off and tr in days:
            notes.append("Teacher " + t["id"] + ": training_day equals day_off (" +
                         tr + "). Allowed, but check it is intended.")
        # H18 - inspector's note on the approved distribution sheet: the day
        # off must not sit next to the training day (training Thursday means
        # neither Wednesday nor Friday may be the day off). Majd: applies to
        # ALL teachers. This is a data property - no placement can fix it.
        if off in days and tr in days and off != tr:
            day_list = list(s.cfg.days)
            gap = abs(day_list.index(off) - day_list.index(tr))
            # Majd 2026-08-24: Sat + Mon also count as adjacent - the Sunday
            # rest day between them would make three free days in a row.
            if gap == 1 or gap == len(day_list) - 1:
                errs.append("Teacher " + t["id"] + ": day_off " + off +
                            " is right next to training_day " + tr +
                            " - consecutive free days, Sunday included (H18, "
                            "inspector's rule). Pick a non-adjacent day off.")

    needed = {s.room_type_for(c) for c in s.curriculum}
    have = {r["type"] for r in s.rooms.values()}
    for rt in sorted(needed - have):
        errs.append("Some lessons need a '" + rt + "' room but no room of that type exists.")

    # teacher workload vs contract. A row with groups=N is taught N times
    # (each group separately), so the teacher works hours x N. A week-A row
    # only loads week A - the binding number is the BUSIER week.
    def taught_hours(c):
        return c["hours"] * max(1, c.get("groups", 1))

    loadw = {}      # tid -> [week A hours, week B hours]
    for c in s.curriculum:
        if c["teacher_id"]:
            e = loadw.setdefault(c["teacher_id"], [0, 0])
            wk = c.get("week", "")
            if wk in ("", "A"):
                e[0] += taught_hours(c)
            if wk in ("", "B"):
                e[1] += taught_hours(c)
    load = {tid: max(e) for tid, e in loadw.items()}
    for tid in sorted(load):
        t = s.teachers.get(tid)
        if t and t["hours"] and load[tid] > t["hours"]:
            errs.append("Teacher " + tid + " (" + t["name"] + ") is given " +
                        str(load[tid]) + " hours in their busier week but the "
                        "contract says " + str(t["hours"]) + ".")
    for tid, t in s.teachers.items():
        if tid not in load:
            notes.append("Teacher " + tid + " (" + t["name"] + ") teaches nothing yet.")

    # a teacher's free days (day off + training day) and the H17 daily cap of 6
    # teaching hours bound what any placement could ever deliver
    for tid, hrs in sorted(load.items()):
        t = s.teachers.get(tid)
        if not t:
            continue
        blocked = {d for d in (t["day_off"], t.get("training_day", ""))
                   if d and d != "(none)"}
        # H17: at most 6 teaching hours on any one day (circular II.2)
        avail = sum(min(len(s.cfg.day_slots(d)), 6)
                    for d in s.cfg.days if d not in blocked)
        # a BLANK day_off is the solver's flexible choice (Majd's rule) - it
        # still costs one day; in the best case the cheapest legal day
        if not (t["day_off"] or "").strip():
            cand = [min(len(s.cfg.day_slots(d)), 6)
                    for d in s.cfg.days if d not in blocked]
            if cand:
                avail -= min(cand)
        if hrs > avail:
            errs.append("Teacher " + tid + " needs " + str(hrs) + " hours but at most " +
                        str(avail) + " are reachable: max 6 per day (H17)" +
                        (", with " + " and ".join(sorted(blocked)) + " free" if blocked else "") + ".")

    # class workload vs week length - from the PUPIL's seat: a grouped row
    # still costs each pupil `hours` periods (their own group's session), and
    # a week-A row costs nothing in week B. The binding week decides.
    week = len(s.cfg.slots)
    clw = {}
    for c in s.curriculum:
        e = clw.setdefault(c["class_id"], [0, 0])
        wk = c.get("week", "")
        if wk in ("", "A"):
            e[0] += c["hours"]
        if wk in ("", "B"):
            e[1] += c["hours"]
    for cid in sorted(clw):
        if max(clw[cid]) > week:
            errs.append("Class " + cid + " needs " + str(max(clw[cid])) +
                        " hours in its busier week but the week only has " +
                        str(week) + " open periods.")

    # H16: the ministry says do not split a class of 24 pupils or fewer
    for c in s.curriculum:
        if c.get("groups", 1) > 1:
            size = s.classes.get(c["class_id"], {}).get("size", 0)
            if size and size <= 24:
                notes.append("Class " + c["class_id"] + " has " + str(size) +
                             " pupils but " + c["subject_id"] + " is set to split into " +
                             str(c["groups"]) + " groups. The ministry says not to split at "
                             "24 or fewer (H16). Set groups=1 unless there is a reason.")

    # H15: a daylight limit that no timetable could satisfy
    for sid, sub in s.subjects.items():
        lp = sub.get("latest_period") or 0
        if not lp:
            continue
        if lp > s.cfg.periods_per_day:
            errs.append("Subject " + sid + " has latest_period " + str(lp) +
                        " but the day only has " + str(s.cfg.periods_per_day) +
                        " periods.")
            continue
        allowed = sum(1 for (d, p) in s.cfg.slots if p <= lp)
        need = max(
            sum(taught_hours(c) for c in s.curriculum
                if c["subject_id"] == sid and c.get("week", "") in ("", w))
            for w in ("A", "B"))
        n_rooms = len(s.rooms_of_type(sub.get("room_type") or "normal"))
        cap = allowed * max(1, n_rooms)
        if need > cap:
            errs.append("Subject " + sid + " needs " + str(need) +
                        " hours but may only use periods 1-" + str(lp) +
                        ", giving " + str(cap) + " slots.")

    # THE bottleneck: rooms. Grouped rows occupy a room PER GROUP; week A/B
    # rows only occupy their week - the busier week is what must fit.
    total = max(
        sum(taught_hours(c) for c in s.curriculum
            if c.get("week", "") in ("", w))
        for w in ("A", "B")) if s.curriculum else 0
    cap = len(s.rooms) * week
    if cap:
        use = 100.0 * total / cap
        line = ("Room load: " + str(total) + " lesson-hours to place into " +
                str(len(s.rooms)) + " rooms x " + str(week) + " periods = " +
                str(cap) + " room-slots (" + ("%.0f" % use) + "% full).")
        if total > cap:
            errs.append(line + "  IMPOSSIBLE - more lessons than room-slots exist.")
        elif use > 90:
            notes.append(line + "  Above 90% is extremely tight - expect poor results.")
        else:
            notes.append(line)

    # per-room-type bottleneck (again per week, groups counted)
    by_type = {}
    for c in s.curriculum:
        rt = s.room_type_for(c)
        e = by_type.setdefault(rt, [0, 0])
        wk = c.get("week", "")
        if wk in ("", "A"):
            e[0] += taught_hours(c)
        if wk in ("", "B"):
            e[1] += taught_hours(c)
    for rt in sorted(by_type):
        n = len(s.rooms_of_type(rt))
        if n and max(by_type[rt]) > n * week:
            errs.append("Rooms of type '" + rt + "': need " + str(max(by_type[rt])) +
                        " hours but only " + str(n) + " room(s) x " + str(week) +
                        " periods = " + str(n * week) + " available.")

    # a class must split into the SAME halves everywhere: rows of one class
    # that split must agree on the group count, or "group 1" would mean two
    # different sets of pupils in two subjects.
    gcount = {}
    for c in s.curriculum:
        g = max(1, c.get("groups", 1))
        if g > 1:
            prev = gcount.setdefault(c["class_id"], g)
            if prev != g:
                errs.append("Class " + c["class_id"] + " splits into " +
                            str(prev) + " groups in one subject and " + str(g) +
                            " in another. All split rows of one class must "
                            "use the same group count.")
    return errs, notes


def main():
    cfg = load_config()
    path = sys.argv[1] if len(sys.argv) > 1 else None
    s = load_school(path, cfg)
    print("Loaded: %d teachers, %d classes, %d rooms, %d subjects, %d curriculum rows"
          % (len(s.teachers), len(s.classes), len(s.rooms), len(s.subjects), len(s.curriculum)))
    print("Week: %d open periods (%d days)" % (len(s.cfg.slots), len(s.cfg.days)))
    errs, notes = check(s)
    for n in notes:
        print("  NOTE  :", n)
    for e in errs:
        print("  ERROR :", e)
    print("")
    print("DATA OK" if not errs else str(len(errs)) + " PROBLEM(S) - fix these first.")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

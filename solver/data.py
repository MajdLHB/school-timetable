"""Load the school data from data/school.xlsx and sanity-check it.

This file knows nothing about solving. If check() is happy, the data is
internally consistent. That does NOT mean a timetable exists - only that the
numbers make sense.
"""
import json
import os
import sys
from dataclasses import dataclass, field

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
            notes=r.get("notes", ""),
        )
    for r in _rows(wb["Classes"]):
        s.classes[r["id"]] = dict(
            id=r["id"],
            name=r.get("name") or r["id"],
            grade=r.get("grade", ""),
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
        )
    for r in _rows(wb["Curriculum"]):
        s.curriculum.append(dict(
            class_id=r["class_id"],
            subject_id=r["subject_id"],
            hours=_int(r.get("hours")),
            teacher_id=r.get("teacher_id", ""),
            blocks=r.get("blocks", ""),
            room_type=r.get("room_type", ""),
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

    for c in s.curriculum:
        where = "Curriculum row " + c["class_id"] + " / " + c["subject_id"]
        if c["class_id"] not in s.classes:
            errs.append(where + " - class '" + c["class_id"] + "' is not in the Classes sheet.")
        if c["subject_id"] not in s.subjects:
            errs.append(where + " - subject '" + c["subject_id"] + "' is not in the Subjects sheet.")
        if c["teacher_id"] and c["teacher_id"] not in s.teachers:
            errs.append(where + " - teacher '" + c["teacher_id"] + "' is not in the Teachers sheet.")
        if c["hours"] <= 0:
            errs.append(where + " - hours must be greater than 0.")

    for t in s.teachers.values():
        off = t["day_off"]
        if off and off not in days and off != "(none)":
            errs.append("Teacher " + t["id"] + " has day_off '" + off +
                        "' which is not a school day (" + ", ".join(s.cfg.days) + ").")

    needed = {s.room_type_for(c) for c in s.curriculum}
    have = {r["type"] for r in s.rooms.values()}
    for rt in sorted(needed - have):
        errs.append("Some lessons need a '" + rt + "' room but no room of that type exists.")

    # teacher workload vs contract
    load = {}
    for c in s.curriculum:
        if c["teacher_id"]:
            load[c["teacher_id"]] = load.get(c["teacher_id"], 0) + c["hours"]
    for tid in sorted(load):
        t = s.teachers.get(tid)
        if t and t["hours"] and load[tid] > t["hours"]:
            errs.append("Teacher " + tid + " (" + t["name"] + ") is given " +
                        str(load[tid]) + " hours but the contract says " + str(t["hours"]) + ".")
    for tid, t in s.teachers.items():
        if tid not in load:
            notes.append("Teacher " + tid + " (" + t["name"] + ") teaches nothing yet.")

    # a teacher with a day off cannot need more hours than the remaining days hold
    for tid, hrs in sorted(load.items()):
        t = s.teachers.get(tid)
        if not t or not t["day_off"] or t["day_off"] == "(none)":
            continue
        avail = sum(len(s.cfg.day_slots(d)) for d in s.cfg.days if d != t["day_off"])
        if hrs > avail:
            errs.append("Teacher " + tid + " needs " + str(hrs) + " hours but only " +
                        str(avail) + " periods exist outside their day off (" + t["day_off"] + ").")

    # class workload vs week length
    week = len(s.cfg.slots)
    cl = {}
    for c in s.curriculum:
        cl[c["class_id"]] = cl.get(c["class_id"], 0) + c["hours"]
    for cid in sorted(cl):
        if cl[cid] > week:
            errs.append("Class " + cid + " needs " + str(cl[cid]) +
                        " hours but the week only has " + str(week) + " open periods.")

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
        need = sum(c["hours"] for c in s.curriculum if c["subject_id"] == sid)
        n_rooms = len(s.rooms_of_type(sub.get("room_type") or "normal"))
        cap = allowed * max(1, n_rooms)
        if need > cap:
            errs.append("Subject " + sid + " needs " + str(need) +
                        " hours but may only use periods 1-" + str(lp) +
                        ", giving " + str(cap) + " slots.")

    # THE bottleneck: rooms
    total = sum(c["hours"] for c in s.curriculum)
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

    # per-room-type bottleneck
    by_type = {}
    for c in s.curriculum:
        rt = s.room_type_for(c)
        by_type[rt] = by_type.get(rt, 0) + c["hours"]
    for rt in sorted(by_type):
        n = len(s.rooms_of_type(rt))
        if n and by_type[rt] > n * week:
            errs.append("Rooms of type '" + rt + "': need " + str(by_type[rt]) +
                        " hours but only " + str(n) + " room(s) x " + str(week) +
                        " periods = " + str(n * week) + " available.")
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

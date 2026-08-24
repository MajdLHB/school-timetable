"""Write the finished timetable as aSc TimeTables XML.

The format here is the one PROVEN to work against the real roz.exe on
2026-08-24 (see docs/ASC_XML.md):

  * explicit <lessons> carrying our own ids
  * <cards> that reference lessonid  (NOT the flat day=/period= form, which
    aSc accepts but silently leaves unplaced)
  * days as a BITMASK STRING, one character per school day: 10000 = Monday

Do not "simplify" this back to the flat card form. It was tested and it fails.
"""
import os
from xml.sax.saxutils import quoteattr

ID_PREFIX = "SOLVER"


def _esc(v):
    return quoteattr("" if v is None else str(v))


def _row(tag, **kw):
    parts = ["%s=%s" % (k, _esc(v)) for k, v in kw.items()]
    return "      <%s %s/>" % (tag, " ".join(parts))


def day_mask(days, day):
    """Monday in a 6-day week is '100000', not '10000'. Length matters."""
    return "".join("1" if d == day else "0" for d in days)


def write(s, units, placement, rooms, path, include_periods=True):
    days = s.cfg.days
    L = []
    A = L.append
    # utf-8, and PROVEN working: Majd imported this into aSc on 2026-08-24
    # and the grid showed full Arabic (an earlier ???? was an aSc-side
    # setting, not this file). Do not "fix" the encoding to 1252/1256 -
    # that mimicry was tried and reverted the same evening.
    A('<?xml version="1.0" encoding="UTF-8"?>')
    A('<timetable importtype="database" options="idprefix:%s">' % ID_PREFIX)

    if include_periods:
        # If aSc misbehaves on import, delete this block and set the periods
        # by hand in aSc instead - it is the one element not covered by Test 1.
        A('   <periods options="" columns="period,name,short">')
        for p in range(1, s.cfg.periods_per_day + 1):
            A(_row("period", period=p, name=str(p), short=str(p)))
        A('   </periods>')

    # Tell aSc explicitly how many days the week has. The card masks below
    # MUST be exactly this long or aSc silently fails to place the cards -
    # that is what produced the empty Tue/Wed/Thu on 2026-08-24.
    A('   <daysdefs options="" columns="id,days,name,short">')
    A(_row("daysdef", id="whole_week", days="1" * len(days),
           name="Whole week", short="week"))
    for i, d in enumerate(days):
        A(_row("daysdef", id="day_" + d,
               days="".join("1" if j == i else "0" for j in range(len(days))),
               name=d, short=d))
    A('   </daysdefs>')

    A('   <subjects options="" columns="id,name,short">')
    for sub in s.subjects.values():
        A(_row("subject", id=sub["id"], name=sub["name"], short=sub["short"]))
    A('   </subjects>')

    # aSc prints the SHORT in the grid cells. Majd wants Arabic there, not
    # codes - so whenever the short is missing or is just the id (T001, C01),
    # fall back to the real name instead.
    def visible_short(short, rid, name):
        short = (short or "").strip()
        return short if short and short != rid else name

    A('   <teachers options="" columns="id,name,short">')
    for t in s.teachers.values():
        A(_row("teacher", id=t["id"], name=t["name"],
               short=visible_short(t.get("short"), t["id"], t["name"])))
    A('   </teachers>')

    A('   <classes options="" columns="id,name,short">')
    for c in s.classes.values():
        A(_row("class", id=c["id"], name=c["name"],
               short=visible_short(c.get("short"), c["id"], c["name"])))
    A('   </classes>')

    # ---- groups (T43): the format PROVEN by test C1 on 2026-08-24 --------
    # Majd imported test/testC1_groups.xml into the real aSc: the two half-
    # class cards stacked in one period with no clash. Every class gets its
    # entire-class group; split classes get their halves on divisiontag 1.
    has_groups = any(u.group for u in units)
    n_groups_of = {}
    for u in units:
        if u.group:
            n_groups_of[u.class_id] = max(n_groups_of.get(u.class_id, 0), u.group)

    def gid(cid, g):
        return "GRP_%s_%d" % (cid, g)

    if has_groups:
        A('   <groups options="" columns="id,classid,name,entireclass,'
          'divisiontag,studentcount">')
        for c in s.classes.values():
            size = c.get("size") or 0
            A(_row("group", id=gid(c["id"], 0), classid=c["id"],
                   name="Entire class", entireclass=1, divisiontag=0,
                   studentcount=size or ""))
            n = n_groups_of.get(c["id"], 0)
            for g in range(1, n + 1):
                A(_row("group", id=gid(c["id"], g), classid=c["id"],
                       name="Groupe %d" % g, entireclass=0, divisiontag=1,
                       studentcount=(size // n) if size else ""))
        A('   </groups>')

    # ---- weeks (T42): the format of test C2 - cards carry a week mask ----
    # Majd's import on 2026-08-24 PLACED the week-A cards correctly from the
    # card masks. (aSc 2013 seems to ignore the lesson-level weeksdefid and
    # then shows phantom unplaced copies - test C3 probes the fix; the mask
    # on each card is the part proven to place correctly.)
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
        A(_row("classroom", id=r["id"], name=r["name"],
               short=visible_short(None, r["id"], r["name"]),
               capacity=r["capacity"]))
    A('   </classrooms>')

    # ---- lessons: one per (class, subject, teacher, group, week) ----------
    bunches = {}
    for u in units:
        key = (u.class_id, u.subject_id, u.teacher_id, u.group, u.week)
        bunches.setdefault(key, []).append(u)

    lesson_id = {}
    cols = "id,subjectid,classids,teacherids,periodspercard,periodsperweek"
    if has_groups:
        cols += ",groupids"
    if has_weeks:
        cols += ",weeksdefid"
    A('   <lessons options="" columns="%s">' % cols)
    for n, (key, us) in enumerate(sorted(bunches.items()), start=1):
        cid, sid, tid, g, wk = key
        lid = "L%d" % n
        lesson_id[key] = lid
        kw = dict(id=lid, subjectid=sid, classids=cid, teacherids=tid,
                  periodspercard=1, periodsperweek=len(us))
        if has_groups:
            kw["groupids"] = gid(cid, g)
        if has_weeks:
            kw["weeksdefid"] = {"A": "WA", "B": "WB"}.get(wk, "WALL")
        A(_row("lesson", **kw))
    A('   </lessons>')

    # ---- cards: one per placed hour ---------------------------------------
    # weeks mask: "1" for a single-week cycle; in a 2-week project "11" =
    # every week, "10" = week A, "01" = week B. Length MUST equal the aSc
    # project week count, exactly like the days mask - same silent-failure
    # trap. Import into a project already set to 2 weeks when A/B is used.
    A('   <cards options="" columns="lessonid,period,days,weeks,classroomids">')
    for key, us in sorted(bunches.items()):
        lid = lesson_id[key]
        for u in us:
            d, p = placement[u.uid]
            A(_row("card", lessonid=lid, period=p, days=day_mask(days, d),
                   weeks=week_mask(u.week), classroomids=rooms.get(u.uid, "")))
    A('   </cards>')

    A('</timetable>')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path

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
    A('<?xml version="1.0" encoding="UTF-8"?>')
    A('<timetable importtype="database" options="idprefix:%s">' % ID_PREFIX)

    if include_periods:
        # If aSc misbehaves on import, delete this block and set the periods
        # by hand in aSc instead - it is the one element not covered by Test 1.
        A('   <periods options="" columns="period,name,short">')
        for p in range(1, s.cfg.periods_per_day + 1):
            A(_row("period", period=p, name=str(p), short=str(p)))
        A('   </periods>')

    A('   <subjects options="" columns="id,name,short">')
    for sub in s.subjects.values():
        A(_row("subject", id=sub["id"], name=sub["name"], short=sub["short"]))
    A('   </subjects>')

    A('   <teachers options="" columns="id,name,short">')
    for t in s.teachers.values():
        A(_row("teacher", id=t["id"], name=t["name"], short=t["short"]))
    A('   </teachers>')

    A('   <classes options="" columns="id,name,short">')
    for c in s.classes.values():
        A(_row("class", id=c["id"], name=c["name"], short=c.get("short") or c["id"]))
    A('   </classes>')

    A('   <classrooms options="" columns="id,name,short,capacity">')
    for r in s.rooms.values():
        A(_row("classroom", id=r["id"], name=r["name"],
               short=r["id"], capacity=r["capacity"]))
    A('   </classrooms>')

    # ---- lessons: one per (class, subject, teacher) -----------------------
    groups = {}
    for u in units:
        key = (u.class_id, u.subject_id, u.teacher_id)
        groups.setdefault(key, []).append(u)

    lesson_id = {}
    A('   <lessons options="" columns='
      '"id,subjectid,classids,teacherids,periodspercard,periodsperweek">')
    for n, (key, us) in enumerate(sorted(groups.items()), start=1):
        cid, sid, tid = key
        lid = "L%d" % n
        lesson_id[key] = lid
        A(_row("lesson", id=lid, subjectid=sid, classids=cid, teacherids=tid,
               periodspercard=1, periodsperweek=len(us)))
    A('   </lessons>')

    # ---- cards: one per placed hour ---------------------------------------
    A('   <cards options="" columns="lessonid,period,days,classroomids">')
    for key, us in sorted(groups.items()):
        lid = lesson_id[key]
        for u in us:
            d, p = placement[u.uid]
            A(_row("card", lessonid=lid, period=p, days=day_mask(days, d),
                   classroomids=rooms.get(u.uid, "")))
    A('   </cards>')

    A('</timetable>')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path

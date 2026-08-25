# -*- coding: utf-8 -*-
"""Write out/view.html - a human-readable timetable next to the aSc XML.

Majd asked for this directly: a view he can open, print, and hand out without
touching aSc. One self-contained file, no internet, nothing leaves the
machine (out/ is behind the privacy firewall like all real data).

Screen: two dropdowns - any class or any teacher, one grid at a time.
Print: the print buttons use the browser's printing, so "save as PDF" in the
print dialog is the download. Each grid prints on its own A4 landscape page
with a clean black-on-white style; "print all classes" pages through the
whole school in one go.
"""
import html


DAY_AR = {"Mon": "الإثنين", "Tue": "الثلاثاء", "Wed": "الأربعاء",
          "Thu": "الخميس", "Fri": "الجمعة", "Sat": "السبت", "Sun": "الأحد"}

SCHOOL = "معهد العالية"
YEAR = "2026/2027"


def _esc(x):
    return html.escape(str(x or ""))


def _time_of(p):
    # Periods are one hour from 08:00 (period 1 = 08:00-09:00). If the bell
    # times ever change, change them here and in the aSc project together.
    return "%02d:00" % (7 + p)


def _tag_of(group, week):
    """The label on a card. Majd asked for groups and weeks to be OBVIOUS:
    "فوج 1" spelled out, and "أسبوع أ/ب" rather than a bare letter."""
    bits = []
    if group:
        bits.append("فوج %d" % group)
    if week:
        bits.append("أسبوع %s" % {"A": "أ", "B": "ب"}.get(week, week))
    return " · ".join(bits)


def _table(cfg, grid, second_line, day_tags=None):
    """One printable table.
    grid: (day, period) -> [(subject, other, room, tag), ...] - several
    entries when two half-class groups share the slot, or when a week-A and
    a week-B lesson alternate there.

    day_tags: {day: label} - e.g. يوم الراحة / يوم التكوين. The label prints
    in the day's header and the whole column is shaded, so a lesson placed
    there (a declared rescue exception) is instantly visible."""
    day_tags = day_tags or {}
    L = ["<table><tr><th class='t'>التوقيت</th>"]
    for d in cfg.days:
        tag = day_tags.get(d)
        L.append("<th>%s%s</th>" % (DAY_AR.get(d, d),
                 "<br><small>%s</small>" % _esc(tag) if tag else ""))
    L.append("</tr>")
    for p in range(1, cfg.periods_per_day + 1):
        L.append("<tr><td class='t'>%s</td>" % _time_of(p))
        for d in cfg.days:
            if p in cfg.closed.get(d, []):
                L.append("<td class='closed'></td>")
                continue
            free = " rest" if d in day_tags else ""
            cell = grid.get((d, p))
            if cell:
                parts = []
                for subj, other, room, tag in cell:
                    parts.append("<b>%s%s</b><span>%s</span><small>%s</small>"
                                 % (_esc(subj),
                                    " <em>%s</em>" % _esc(tag) if tag else "",
                                    _esc(second_line(other)), _esc(room)))
                L.append("<td class='l%s'>%s</td>"
                         % (free, "<hr>".join(parts)))
            else:
                L.append("<td class='%s'></td>" % free.strip())
        L.append("</tr>")
    L.append("</table>")
    return "".join(L)


def write(s, units, placement, rooms, path, day_offs=None):
    """day_offs: {teacher_id: day} - the solver's flexible day-off choices
    for this run (a FIXED day comes from the sheet and wins)."""
    day_offs = day_offs or {}
    sub_name = {k: v.get("name", k) for k, v in s.subjects.items()}
    cls_name = {k: v.get("name", k) for k, v in s.classes.items()}
    tch_name = {k: v.get("name", k) for k, v in s.teachers.items()}
    room_name = {k: v.get("name", k) for k, v in s.rooms.items()}

    cgrid, tgrid = {}, {}
    thours = {}
    for u in units:
        if u.uid not in placement:
            continue
        d, p = placement[u.uid]
        rm = room_name.get(rooms.get(u.uid, ""), "")
        subj = sub_name.get(u.subject_id, u.subject_id)
        tag = _tag_of(getattr(u, "group", 0), getattr(u, "week", ""))
        cgrid.setdefault(u.class_id, {}).setdefault((d, p), []).append(
            (subj, u.teacher_id, rm, tag))
        if u.teacher_id:
            tgrid.setdefault(u.teacher_id, {}).setdefault((d, p), []).append(
                (subj, u.class_id, rm, tag))
            thours[u.teacher_id] = thours.get(u.teacher_id, 0) + 1

    grids, opt_c, opt_t = [], [], []
    for cid in sorted(cgrid, key=lambda c: (len(c), c)):
        grids.append(
            "<div class='grid cgrid' id='%s'><h2>%s — قسم %s — %s</h2>%s</div>"
            % (cid, SCHOOL, _esc(cls_name.get(cid, cid)), YEAR,
               _table(s.cfg, cgrid[cid], lambda t: tch_name.get(t, ""))))
        opt_c.append("<option value='%s'>%s</option>"
                     % (cid, _esc(cls_name.get(cid, cid))))
    for tid in sorted(tgrid, key=lambda t: (len(t), t)):
        t = s.teachers.get(tid, {})
        # Majd asked for both numbers on the teacher's page: the hours this
        # timetable gives them, and the hours they were asked to do.
        contract = t.get("hours") or 0
        hline = "الساعات المنجزة: %d / المطلوبة: %s" % (
            thours.get(tid, 0), contract if contract else "؟")
        tags = {}
        tr = (t.get("training_day") or "").strip()
        if tr:
            tags[tr] = "يوم التكوين"
        off = (t.get("day_off") or "").strip()
        if not off:
            off = day_offs.get(tid, "")
        if off and off != "(none)":
            tags[off] = "يوم الراحة" + \
                ("" if (t.get("day_off") or "").strip() else " (اختيار البرنامج)")
        grids.append(
            "<div class='grid tgrid' id='%s'><h2>%s — الأستاذ(ة) %s — %s"
            "<br><small>%s</small></h2>%s</div>"
            % (tid, SCHOOL, _esc(tch_name.get(tid, tid)), YEAR, _esc(hline),
               _table(s.cfg, tgrid[tid], lambda c: cls_name.get(c, ""),
                      day_tags=tags)))
        opt_t.append("<option value='%s'>%s</option>"
                     % (tid, _esc(tch_name.get(tid, tid))))

    page = PAGE.replace("@OPTC@", "".join(opt_c)) \
               .replace("@OPTT@", "".join(opt_t)) \
               .replace("@GRIDS@", "".join(grids)) \
               .replace("@SCHOOL@", SCHOOL).replace("@YEAR@", YEAR)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


def write_teachers(s, path):
    """out/teachers.html - who teaches what, classes and hours vs contract."""
    per = {}
    load = {}
    unassigned = []
    for r in s.curriculum:
        cid, sid, tid = r["class_id"], r["subject_id"], r["teacher_id"]
        cname = s.classes.get(cid, {}).get("name", cid)
        sname = s.subjects.get(sid, {}).get("name", sid)
        taught = (r["hours"] or 0) * max(1, r.get("groups", 1))
        wk = (r.get("week") or "").strip()
        if wk:
            sname += " (أسبوع %s)" % {"A": "أ", "B": "ب"}.get(wk, wk)
        if max(1, r.get("groups", 1)) > 1:
            sname += " (أفواج)"
        if not tid:
            unassigned.append((cname, sname, taught))
            continue
        per.setdefault(tid, {}).setdefault(sname, []).append((cname, taught))
        # fortnightly hours count half toward the weekly average
        load[tid] = load.get(tid, 0) + (taught / 2.0 if wk else taught)

    L = ["<h1>من يدرّس ماذا — %s %s</h1>" % (SCHOOL, YEAR)]
    for tid in sorted(per):
        t = s.teachers.get(tid, {})
        contract = t.get("hours") or 0
        L.append("<h2>%s — %g س من %s</h2>"
                 % (_esc(t.get("name", tid)), load[tid], contract or "؟"))
        L.append("<table class='list'><tr><th>المادة</th><th>الأقسام</th>"
                 "<th>ساعات</th></tr>")
        for sname, lst in sorted(per[tid].items()):
            cs = "، ".join("%s (%g)" % (_esc(c), h) for c, h in sorted(lst))
            L.append("<tr><td>%s</td><td>%s</td><td>%g</td></tr>"
                     % (_esc(sname), cs, sum(h for _, h in lst)))
        L.append("</table>")
    if unassigned:
        L.append("<h2>حصص بدون أستاذ بعد (%d)</h2>"
                 "<table class='list'><tr><th>القسم</th><th>المادة</th>"
                 "<th>ساعات</th></tr>" % len(unassigned))
        for c, sname, h in sorted(unassigned):
            L.append("<tr><td>%s</td><td>%s</td><td>%g</td></tr>"
                     % (_esc(c), _esc(sname), h or 0))
        L.append("</table>")
    _write_doc(path, "من يدرّس ماذا - %s" % SCHOOL, "".join(L), rtl=True)


def write_report_html(md_text, path):
    """out/report.html - the run report, same content as report.md but as a
    clean page Majd can open and print without a markdown viewer."""
    out, in_table, in_list = [], False, False

    def close():
        nonlocal in_table, in_list
        if in_table:
            out.append("</table>")
            in_table = False
        if in_list:
            out.append("</ul>")
            in_list = False

    import re as _re

    def inline(t):
        t = _esc(t)
        t = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = _re.sub(r"`(.+?)`", r"<code>\1</code>", t)
        return t

    for line in md_text.splitlines():
        st = line.strip()
        if st.startswith("|"):
            cells = [c.strip() for c in st.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue      # the |---|---| separator row
            if not in_table:
                close()
                out.append("<table class='list'>")
                in_table = True
                out.append("<tr>" + "".join("<th>%s</th>" % inline(c)
                                            for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join("<td>%s</td>" % inline(c)
                                            for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if st.startswith("#"):
            close()
            n = len(st) - len(st.lstrip("#"))
            out.append("<h%d>%s</h%d>" % (min(n, 3), inline(st.lstrip("# ")),
                                          min(n, 3)))
        elif st.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % inline(st[2:]))
        elif st:
            close()
            out.append("<p>%s</p>" % inline(st))
        else:
            close()
    close()
    _write_doc(path, "Run report - %s" % SCHOOL, "".join(out), rtl=False)


def _write_doc(path, title, body, rtl):
    doc = DOC.replace("@TITLE@", _esc(title)) \
             .replace("@BODY@", body) \
             .replace("@DIR@", "rtl" if rtl else "ltr") \
             .replace("@LANG@", "ar" if rtl else "en")
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


DOC = """<!doctype html><html lang="@LANG@" dir="@DIR@"><head><meta charset="utf-8">
<title>@TITLE@</title><style>
body{font-family:"Segoe UI",Tahoma,sans-serif;background:#f6f5f1;color:#1c1c1c;margin:18px;max-width:1050px}
h1{font-size:1.25em}
h2{font-size:1em;background:#3d5a80;color:#fff;padding:6px 12px;border-radius:6px;margin:16px 0 4px}
h3{font-size:.95em;color:#3d5a80}
table.list{border-collapse:collapse;width:100%;background:#fff;margin-bottom:6px}
table.list td,table.list th{border:1px solid #b9b2a2;padding:4px 10px;font-size:.9em;text-align:start}
table.list th{background:#ece8dd}
code{background:#ece8dd;padding:1px 5px;border-radius:4px}
p{margin:6px 0}
@page{size:A4;margin:12mm}
@media print{body{background:#fff;margin:0}h2{background:#fff;color:#000;border:1px solid #000}}
</style></head><body>@BODY@</body></html>"""


PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>جدول الأوقات - @SCHOOL@ @YEAR@</title><style>
body{font-family:"Segoe UI",Tahoma,sans-serif;background:#f6f5f1;color:#1c1c1c;margin:14px}
h2{font-size:1.05em;margin:6px 0 8px}
.controls{background:#fff;border:1px solid #ddd6c8;border-radius:10px;padding:10px 14px;margin-bottom:12px}
select,button{font-size:1em;padding:6px 12px;margin:2px 6px 2px 0;border-radius:7px;border:1px solid #b9b2a2;background:#fff;cursor:pointer}
button{background:#3d5a80;color:#fff;border:none}
button.alt{background:#8a7d5c}
table{border-collapse:collapse;width:100%;background:#fff}
table{table-layout:fixed}
th,td{border:1px solid #b9b2a2;padding:4px 3px;text-align:center;font-size:.85em;width:13.5%;height:78px;vertical-align:middle;overflow:hidden}
th{background:#3d5a80;color:#fff}
td.t,th.t{background:#ece8dd;font-weight:bold;min-width:54px}
td.closed{background:repeating-linear-gradient(45deg,#f0ede6,#f0ede6 6px,#e3dfd4 6px,#e3dfd4 12px)}
td.rest{background:#e8f0e4}
td.l.rest{background:#fbe3e3}   /* a lesson ON a free day = declared exception, make it jump out */
td.l b{display:block;color:#1d3557}
td.l b em{display:inline-block;font-style:normal;font-size:.72em;background:#3d5a80;color:#fff;border-radius:4px;padding:0 5px;margin-inline-start:4px;font-weight:600}
td.l span{display:block;font-size:.9em}
td.l small{display:block;color:#6b6455}
td.l hr{border:none;border-top:1px dashed #b9b2a2;margin:3px 0}
td.l b{line-height:1.15}td.l span{line-height:1.1}
.grid{display:none}.grid.show{display:block}
@page{size:A4 landscape;margin:9mm}
@media print{
 body{background:#fff;margin:0}
 .controls{display:none}
 .grid{display:none}
 .grid.show{display:block}
 body.printall .grid{display:none}
 body.printall .grid.cgrid{display:block;page-break-after:always}
 table{width:100%}
 th{background:#fff;color:#000;border-color:#000}
 th,td{border-color:#000}
 td.t{background:#fff}
 td.closed{background:#f2f2f2}
 td.rest{background:#f2f2f2}
 td.l.rest{background:#e8e8e8}
}
</style></head><body>
<div class="controls">
 <b>@SCHOOL@ — @YEAR@</b> &nbsp;
 عرض قسم: <select id="selc"><option value="">—</option>@OPTC@</select>
 أو أستاذ(ة): <select id="selt"><option value="">—</option>@OPTT@</select>
 <button onclick="window.print()">طباعة المعروض</button>
 <button class="alt" onclick="printAll()">طباعة كل الأقسام</button>
 <small>للحفظ كملف: اختر "Save as PDF" في نافذة الطباعة.</small>
</div>
@GRIDS@
<script>
var selc=document.getElementById('selc'),selt=document.getElementById('selt');
function show(id){document.querySelectorAll('.grid').forEach(function(g){g.classList.remove('show')});
 if(id){var e=document.getElementById(id);if(e)e.classList.add('show');}}
selc.onchange=function(){selt.value='';show(this.value)};
selt.onchange=function(){selc.value='';show(this.value)};
function printAll(){document.body.classList.add('printall');window.print();
 document.body.classList.remove('printall');}
if(selc.options.length>1){selc.selectedIndex=1;show(selc.value);}
</script></body></html>"""

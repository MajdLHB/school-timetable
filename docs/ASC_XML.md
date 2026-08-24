# aSc TimeTables 2013 - integration notes

Everything here was read directly from the installed app, not from the internet.

App folder:
`C:\Users\Majd Lahbib\Desktop\Asus\desk\ASC TimeTables\`

## Facts established

- `roz.exe` (15.5 MB, 2012) is aSc TimeTables. `.roz` is its save file.
- **`.roz` is a proprietary binary format.** First bytes of `demos/Demo1.roz`:
  `67 00 00 00 ... 'Hronsk\xE1' ... '1996/97'` - length-prefixed binary records.
  It is NOT zip, NOT XML, NOT Access. **We will never write `.roz` directly.**
- The bridge is **XML import/export**, which this version fully supports.

## How to import (from the app's own readme)

`template/Import Samples/XML/readme.txt`:

> To import these files you have to create a blank document and use
> menu - File - Import - aSc Timetables XML.

## The schema

Read from `template/xmlexport/asctt2012.xml` (aSc's own export definition,
`displayname="aSc Timetables 2012 XML"`). Root is `<timetable>`, each table is
a child element whose `columns` attribute lists the legal attributes:

| element           | columns |
|-------------------|---------|
| `periods`         | `period,name,short,starttime,endtime` |
| `daysdefs`        | `id,days,name,short` |
| `weeksdefs`       | `id,weeks,name,short` |
| `termsdefs`       | `id,terms,name,short` |
| `subjects`        | `id,name,short` |
| `teachers`        | `id,name,short,gender,color,email,mobile` |
| `classrooms`      | `id,name,short,capacity` |
| `grades`          | `grade,name,short` |
| `classes`         | `id,name,short,classroomids,teacherid,grade` |
| `groups`          | `id,classid,name,entireclass,divisiontag,studentcount,studentids` |
| `students`        | `id,classid,name,email,mobile` |
| `studentsubjects` | `studentid,subjectid,seminargroup,importance,alternatefor` |
| `lessons`         | `id,subjectid,classids,groupids,teacherids,classroomids,periodspercard,periodsperweek,daysdefid,weeksdefid,termsdefid,seminargroup,capacity` |
| `cards`           | `lessonid,period,days,weeks,terms,classroomids` |

### The two that matter most

- **`lessons`** = *what must be taught*. `periodsperweek` is the hours count,
  `periodspercard` is the block size (1 = single hour, 2 = double hour).
- **`cards`** = *where it actually sits*. **This is the placement.**
  A simpler card form is also accepted (see below):
  `day,period,classids,subjectid,teacherids,classroomids`

So: **we can generate the complete, already-solved timetable**, not just the
input data. aSc receives it placed.

## Working sample (from `Import Samples/XML/`)

```xml
<timetable importtype="database" options="idprefix:MyApp">
   <teachers options="" columns="id,name,short">
      <teacher id="1" name="Bacova" short="Bc"/>
   </teachers>
   <classes options="" columns="id,name">
      <class id="1" name="5.A" short="5.A"/>
   </classes>
   <subjects options="" columns="id,name,short">
      <subject id="1" name="Mathematics" short="Ma"/>
   </subjects>
   <classrooms options="" columns="id,name,short">
      <classroom id="1" name="Room 106" short="106"/>
   </classrooms>
   <classsubjects options="" columns="classid,subjectid,periodsperweek,teacherid">
      <classsubject classid="1" subjectid="1" periodsperweek="5" teacherid="1"/>
   </classsubjects>
</timetable>
```

Note `options="idprefix:MyApp"` - our IDs get prefixed so they never collide
with aSc's internal ones. We will use `idprefix:SOLVER`.

## Printing

Arabic print designs already exist in `designs/` and will keep working, because
aSc is doing the printing, not us:
- `مطبوعة الجداول الرسمية - أستاذ`
- `جدول الأساتذة-نموذج رسمي`
- `نموذج  جداول تلاميذ`
- `نموذج للقاعات`
- `معهد الحبيب ثامر-بسيط`

## RISK - must be tested before we build anything big

This is a 2013 build. **We must prove the round-trip works before writing the
solver.** Test 1 (see `docs/OPEN_QUESTIONS.md`) is a 4-teacher toy XML: import
it, confirm aSc shows the lessons placed, print one page. If that works, the
whole plan is safe. If it fails, we fall back to CSV/clipboard import
(`template/Import Samples/Clipboard_Excel/`) and only automate data entry, with
the placement pasted per class.

Note: the folder also contains `Crack ASC TimeTables.exe`. I have not run it and
will not. It matters here only because a patched/limited build can restrict
import size - which is exactly what Test 1 checks for.

---

# ✅ TEST 1 RESULT - 2026-08-24 - VERIFIED ON THE REAL APP

All three test files were imported into `roz.exe` by the user. Outcome:

| file | result |
|---|---|
| `testA_basicdata.xml` | ✅ Teachers, classes, subjects, rooms all added |
| `testB1_placed_simple.xml` | ⚠️ Lessons **added to the lesson list but NOT placed in the grid** |
| `testB2_placed_lessonid.xml` | ✅ **Lessons added AND actually placed in the timetable grid** |

## THE DECISION - this is now settled, do not re-litigate

**We emit the `testB2` form.** Explicit `<lessons>` with our own `id`, then
`<cards>` referencing that id, with `days` as a **bitmask string**, not a number.

```xml
<lessons options="" columns="id,subjectid,classids,teacherids,classroomids,periodspercard,periodsperweek">
   <lesson id="L1" subjectid="MATH" classids="C01" teacherids="T01"
           classroomids="R01" periodspercard="1" periodsperweek="2"/>
</lessons>
<cards options="" columns="lessonid,period,days,classroomids">
   <card lessonid="L1" period="1" days="10000" classroomids="R01"/>
   <card lessonid="L1" period="1" days="01000" classroomids="R01"/>
</cards>
```

### `days` bitmask
One character per school day, `1` = this card is on that day.
`10000` = Monday, `01000` = Tuesday, `00100` = Wednesday, ...
**The string length must equal the number of school days.** If we run Monday to
Saturday the mask is 6 characters (`100000` = Monday), not 5.

### One card per occurrence
A lesson with `periodsperweek="2"` needs **two** `<card>` rows, one per day.
Do not put `days="11000"` on a single card unless it is genuinely the same
lesson repeating - emit one card per placed hour. That is what worked.

### Why B1 failed
The flat `day,period,classids,subjectid,teacherids` card form is accepted by the
parser but aSc cannot bind those cards to lesson records, so they land in the
lesson list unplaced. **Cards must reference a `lessonid`.**

## Import procedure - exact steps, confirmed by screenshots

1. `roz.exe` → **New** (blank document)
2. **File → Import → aSc Timetables XML** → choose the file
3. A dialog **"Synchronization with database - aSc Timetables XML"** appears,
   left pane listing every record with Action = **Add**. Press **OK**.
4. **A SECOND dialog appears** with the header **"Lesson grid"**, listing the
   lessons to add. Press **OK** again.
5. Done. Two OKs is correct and expected - one for basic data, one for lessons.

Reviewing the left pane before pressing OK is the safety check: `Add` on
everything for a fresh import. Anything saying `Delete` on a real file means
stop and cancel.

---

# ⚠️ BUG FOUND 2026-08-24 (second import test) - DAY MASK LENGTH

The user imported a full generated timetable. Result: **Monday and Friday had
lessons; Tuesday, Wednesday and Thursday were completely empty**, and a large
tray of unplaced cards sat at the bottom of the aSc window.

## Cause

We emitted **6-character** day masks (`100000` = Monday in a Mon-Sat week) into
an aSc project whose week was **not set to 6 days**. When the mask length does
not match the number of days in the aSc project, aSc does not raise an error -
it silently fails to place most cards.

**This is the dangerous failure mode of this whole integration: it fails
QUIETLY.** Nothing warns you. The timetable simply comes out full of holes.

## Rules that follow from this

1. **The aSc project must be configured for the same number of days as
   `config.json` BEFORE importing.** Do this first, in aSc, on a blank project.
2. `emit_asc.py` now also writes a `<daysdefs>` block declaring the day set, to
   give aSc the day count explicitly.
3. `verify.py` already checks that every mask length equals `len(cfg.days)`.
   That check passes on our side - the mismatch is between our file and the aSc
   PROJECT, which we cannot see from here. Only the import test catches it.

## Diagnostic files - run these to settle it

`test/daytest_6day.xml` and `test/daytest_5day.xml`.

Each contains ONE class, ONE teacher, and one lesson per day, named `Day1 Mon`,
`Day2 Tue`, ... Import into a blank project and look at where they land:

- **All six subjects on their matching days** -> masks are right, use 6-day.
- **Some days empty** -> the project day count does not match the mask length.
- **Subjects on the wrong days** -> aSc reads the mask in a different order,
  and `day_mask()` in emit_asc.py must be changed to match.

This costs two minutes and removes all guesswork.

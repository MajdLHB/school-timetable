# Open questions, reminders, and progress

The single live tracker. `RULES.md` is what is decided; this is what is not.

Answer in any order - but the **BLOCKING** ones stop real work, and Q1 and Q2
change which ministry rules apply at all.

---

# PROGRESS

## Done and verified

- [x] **aSc bridge proven** against the real `roz.exe`. Format: explicit
      `<lessons>` + `<cards>` referencing `lessonid`, `days` as a bitmask.
- [x] **The day-mask trap found and documented** - a mask whose length does not
      match the aSc project's day count makes aSc **silently** drop cards. That
      is what emptied Tue/Wed/Thu on the first real import.
- [x] **Encoding solved** - aSc labels its export `windows-1252` but writes
      Arabic in `windows-1256`. Reading as utf-8 silently DELETES Arabic names
      (101 names -> 0), which would make a privacy scan report a clean file
      that is not clean.
- [x] **Solver works end to end** at real scale. 10-minute run on a fake
      40-class school: valid, verifier ALL GREEN, 95% of teachers with a clean
      week, 2 one-hour days, 4 trapped pupil periods.
- [x] **Verification machinery**: independent `verify.py`; BREAK/RELAX tests
      proving each rule is wired up rather than merely written down; a coverage
      report for rules that exist only on paper. See `docs/VERIFICATION.md`.
- [x] **Crash safety** - `out/solution.json` written atomically as the search
      improves, `--continue` resumes, `out/archive/` keeps timestamped copies.
- [x] **Privacy firewall** - `data/` and `out/` never committed. It caught a
      real near-miss when a 101-teacher export was dropped in the project root.
- [x] **93 teachers imported** from the ministry list. National identity
      numbers deliberately NOT copied.
- [x] **H15 daylight cutoff** for Sport: stated, coded, verified, tested.
- [x] **Circular 51/2018 fully read** (all 13 pages), symbol notation decoded,
      curriculum transcribed to `rules/curriculum.json` and validated against
      last year's real timetable - see `docs/CIRCULAR_51_2018.md`.
- [x] **`rules/rules.pdf` fully read** (all 21 pages, 2026-08-24). It is the
      scanned original of the inspectorate recommendations already catalogued
      in `docs/MINISTRY_RULES.md`. Verified page by page; two transcription
      errors corrected (M-PH5 time window, M-PHI3/M-PHI8 swapped levels).
      Provenance: edunet.tn, captured 2003 - so circular 51/2018 wins conflicts.

## Not done
- [ ] **H9 block patterns** (`2+1+1`) - the biggest gap in the solver
- [ ] **Week A / Week B** fortnightly sessions
- [ ] **Group splitting**, and with it the pupil-hours vs teacher-hours problem
- [ ] **H14 option groups** pooled across classes
- [ ] Classes, Rooms, Curriculum sheets - all still empty
- [ ] Teacher `hours` and `day_off` - blank, not in the ministry list

---

# BLOCKING QUESTIONS

## Q1. Is معهد العالية a pilot institute (معهد نموذجي)?

The circular has a symbol - **boxed (4)** - meaning *حصّة أسبوعيّة بنظام الأفواج
تخصّ المعاهد النّموذجيّة*: a weekly group session **that applies only to pilot
institutes**. In the 2nd-year table it appears for Computer Science in the
Letters and Sciences streams.

**If the school is a pilot institute, some classes get group sessions that
otherwise do not exist** - changing hours, teacher workload and room needs.

## Q2. RESOLVED - there IS a lunch break

Periods **5 and 6 (12:00-14:00) are closed every day** in `config.json`,
matching circular I.3's required two-hour separation. That leaves 4 morning +
4 evening teaching periods - exactly the circular's "max 4 hours for a pupil in
one session".

*(I had recorded the opposite. Majd was twice pointing out that MY generated
timetable had no break, not describing the school.)*

Still to confirm: **is Saturday afternoon closed too?** Last year's file shows
Saturday at roughly half the lessons of other days, so `config.json` currently
closes Saturday afternoon as well. Guess, not fact.

## Q3. Which streams and levels does the school actually run?

High school, 1st to 4th year. Which of these exist here?

- 1st year جذع مشترك (common core)
- 2nd year: آداب / علوم / تكنولوجيا الإعلاميّة / اقتصاد / others?
- 3rd year: which streams?
- 4th year: which streams?
- شعبة الرّياضة - the circular devotes a whole table to the sport stream. Do we
  have it?

**Every per-level rule needs this**, and the circular's hour tables are
organised by exactly these streams.

## Q4. The 45 rooms - what are they?

Last year's file defines 45 classrooms and uses all 45. I need:

- how many ordinary rooms
- how many **Stad 1 / 2 / 3** (you said aSc models the stadium as rooms)
- labs: physics, natural sciences, technology (mechanics? electricity?)
- IT labs, and **how many computers in each** - a ministry rule caps pupils at
  twice the number of computers
- any music room, arts room, dedicated English room

## Q5. Group splitting - the real practice here

The circular formalises it; I need what actually happens:

- Which subjects split the class into groups at this school?
- **How many groups per class** - always 2, or sometimes 3?
- Class sizes - the rule says do not split at 24 pupils or fewer
- When a class splits, what does the other half do? Another subject with
  another teacher, or nothing?

## Q6. Week A / Week B - do you really run it?

Last year's file has **145 cards** marked Week A or Week B only, so it existed.
Which subjects use it now, and is it described to staff as A/B or some other
way?

---

# QUESTIONS ABOUT THE BUILDING

You offered these - and they matter more than they sound.

## Q7. How are the rooms physically arranged?

- Floors and buildings - are rooms numbered by floor?
- **How long does it take a class to walk from one end to the other?** If it is
  significant, back-to-back lessons in far-apart rooms have a real cost and the
  solver should avoid them.
- Are the specialised rooms **grouped together** or scattered? (The circular
  asks for technology rooms to be adjacent.)

## Q8. The stadium

- How far is it from the main building?
- Does getting there eat into the lesson? If it costs 10 minutes each way, PE
  placed next to another lesson is a problem.
- Are Stad 1/2/3 genuinely separate spaces, or one field divided by convention?
- What happens to PE when it rains?

## Q9. Rooms with restrictions

- Any room shared with another institution, or unavailable at certain times?
- Any room too small for a full class - half-group only?
- Any room that is effectively somebody's, because they keep materials there?
  (The music recommendation is exactly about this.)

---

# QUESTIONS ABOUT PEOPLE

## Q10. Teacher hours and days off

The ministry list has neither. For 93 teachers I need contracted weekly hours
and the day off, if any. Is there an existing document, or must it be typed?

## Q11. The training day (يوم التّكوين)

The circular says teachers must be free on their pedagogical training day, and
that this day does **not** count when balancing the week.

- Who has one, and which day?
- Is it the same day for everyone in a subject?

## Q12. Trainee teachers (المتربّصون)

The inspectorate text says 1st and 2nd year trainees must be free on
**Saturday**. Do we have trainees this year, and who?

## Q13. Teachers at two institutions

The circular asks for coordination between the two schools. Who works
elsewhere, and do we know their other timetable? Their blocked slots go in the
Unavailable sheet.

## Q14. The two vacancies

The ministry list has 2 numbered rows with no name. Not yet arrived, or posts
that will stay empty?

## Q15. Optional subjects (rule H14)

You described pupils choosing Spanish / German / Italian / Tashkilia, pooled
across classes.

- Which subjects exactly are options?
- Does every pupil take exactly one, or can they take none?
- How many classes typically pool into one option group?
- Must the pooled classes be the same level?
- **Is this the same thing as "a teacher teaching 3 portions of 3 classes"?**

---

# REMINDER LIST - things you said you would send

- [ ] **The compact-timetable exception list.** The ministry rule wins by
      default (hours spread across most days), but teachers who travel a long
      way keep a compact timetable. You said you would give the names later. A
      `compact` column will exist in the Teachers sheet, empty until then.
- [ ] More rules, as they come up.
- [x] **Friday evening for bac** - answered. It is a personal preference, and
      is recorded as S13 marked exactly that way. Applying it to **all bac
      streams** rather than bac maths alone is the defensible version; singling
      out one stream is the kind of thing staff and pupils notice.

---

# SMALLER QUESTIONS, WHENEVER

- **Q16.** Two subject names in the teacher list, `اقتصاد` and `تصرف`, were
  mapped as separate subjects (ECO and GEST). The circular's 2nd-year Economics
  table lists them separately too, so this looks right - please confirm.
- **Q17.** Are there fixed all-school slots - assembly, exams, ceremonies?
- **Q18.** Do devoirs de contrôle / de synthèse need reserved slots, or do they
  happen inside normal lessons?
- **Q19.** Two teachers who must never be scheduled at the same time, or must
  be (shared transport, a couple, one person covering two roles)?
- **Q20.** Any teacher with a medical or personal constraint that should be
  hard rather than a preference? **Only the constraint is needed - never the
  reason.** See `docs/PRIVACY.md`.
- **Q22. IMPORTANT.** You said a "3 hour" session here is really **1.5 hours
  per group** because the lab is small. The ministry notation means the
  opposite: `(3)` is **3 hours for EACH group**, so the teacher works 6. The
  sport-stream table proves the ministry reading - Biology at 1h whole + 2h
  group gives pupil 3 / teacher 5. So either this school deviates from the
  circular, or "3 hours" in your data means something else. **Which is it?**
  Every teacher workload number depends on the answer.
- **Q23.** How many groups does a class split into here - always 2? All the
  teacher-hour figures in `rules/curriculum.json` assume 2.
- **Q24.** Page 10/5 of the guide (3rd + 4th year **Letters**) has its top rows
  **cut off in the scan** - Arabic, French and English are missing for that
  stream. Can you send that page again, or tell me those three?
- **Q21.** Islamic Thought: the circular puts it in the morning, or 14:00-16:00
  if it must be in the evening. Apply that cutoff, same as Sport? One cell.
- **Q25. RESOLVED 2026-08-24 - period 5 stays CLOSED.** Majd: *"it shouldnt
  be open even if rare follow rules... last year due to time it was very hard
  to make the sceduel so we made exceptions"*. The 40 cards in period 5 last
  year were human exceptions under time pressure, not policy. The solver keeps
  periods 5-6 (12:00-14:00) hard-closed every day.

# Open questions, reminders, and progress

The single live tracker. `RULES.md` is what is decided; this is what is not.

**Majd's standing instruction (2026-08-24): anything he has not confirmed 100%
is marked UNSURE** - used for testing, never mistaken for fact, and re-asked
before the final version. This is a demo/test phase; the final version gets the
real data.

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
- [x] **`rules/rules.pdf` fully read** (all 21 pages, 2026-08-24), verified
      page by page against `docs/MINISTRY_RULES.md`; two transcription errors
      corrected. Circular 51/2018 wins conflicts (it is newer).
- [x] **H9 block patterns coded** - the solver places sessions (`2+1+1`), not
      loose hours. H18, H19, rescue mode, S15-S20 family all coded; selftest
      16/16.
- [x] **The 2026/27 pedagogical distribution extracted and cross-verified**
      (teachers' required hours, sections per stream, 41 classes) - see
      `data/DISTRIBUTION_REPORT.md` for the per-subject verification and flags.
- [x] **Training days written** for 77 teachers from the official delegation
      circular (see Q11, RESOLVED).
- [x] **The art (تشكيلية) 2026/27 sheet arrived and transcribed** - FLAG-7's
      provisional data replaced with the official row (16h/16h, verified).

## Not done
- [ ] **Week A / Week B** fortnightly sessions in the solver
- [ ] **Group splitting**, and with it the pupil-hours vs teacher-hours problem
- [ ] **H14 option groups** pooled across classes; **S20** aligned doubles
- [ ] Rooms and Curriculum sheets (being pre-filled from last year /
      distribution - Majd will verify)
- [ ] Teacher `day_off` - still blank for everyone (see Q10)
- [ ] The Sport distribution is **synthetic test data** (no 2026/27 sheet yet)

---

# ANSWERED 2026-08-24 (evening batch)

- **Q1. NOT a pilot institute.** Majd: "no its not a pilot institue". The
  boxed-④ group sessions do not apply anywhere. Closed.
- **Q2. Lunch break + Saturday afternoon both CONFIRMED.** Periods 5-6
  (12:00-14:00) closed every day; "no study on saturday afternoon" - the
  config's Saturday closure is now fact, not guess.
- **Q3. Streams CONFIRMED.** No sport stream. 1st year: common core. 2nd year:
  آداب / علوم / اقتصاد / إعلامية. 3rd year and bac: آداب / رياضيات / علوم
  (تجريبية) / إعلامية / تقنية / اقتصاد. Matches the 41-class structure read
  from the distribution sheets exactly.
- **Q11. Training days RESOLVED by the official circular** Majd dropped in
  `data/reference/SCAN_20260814_140843760.pdf` (Bizerte delegation,
  0000132-2151-07-2026): the pedagogical training day is fixed **per subject**
  for 2026-27. Secondary-level column, as written to the Teachers sheet:
  Thu = العربية، الرياضيات، التفكير الإسلامي، الاقتصاد ·
  Wed = الفرنسية، العلوم الفيزيائية، الفلسفة ·
  Tue = الإنقليزية، الألمانية، علوم الحياة والأرض، التاريخ والجغرافيا،
  التربية المدنية، التصرف ·
  Mon = الإسبانية، التربية التشكيلية · Sat = الإيطالية.
  **Left open inside it:** الإعلامية and التربية التكنولوجية/الهندسة send HALF
  the teachers Friday and half Saturday - the circular does not name the
  halves (noted per teacher, UNSURE). Sport is absent from the circular.
  Trainees (المتربصون والمدمجون دفعة 2025-2026) get separate days per subject -
  useless until Q12 says who they are.
- **Q14. Vacancies: "label them as new teachers until we know their name"**
  (Majd). The two nameless ministry-list rows carry NO data at all (no subject,
  no hours), so there is nothing to import; plausibly they are T094 /
  T095 who appear on the 2026/27 sheets but not the ministry list
  (UNSURE). Any future distribution row without a ministry match = new teacher.
- **Q16. CONFIRMED** - اقتصاد and تصرف are two separate subjects.
- **Q17. NO fixed all-school slots.** Closed.
- **Q18. Devoirs run INSIDE normal lessons**, usually the 2-hour sessions
  (example: Economics). New soft rule **S20**: same-level same-stream classes
  should get their doubles at the same time so a devoir runs everywhere at
  once - "try, if u couldnt get it its fine". SPEC, not yet coded.
- **Q19. Teacher pairings (must/must-not overlap): UNSURE by design** - "leave
  unsure until i am sure, im making a demo test". Final version will carry the
  real list.
- **Q20. Personal hard constraints: UNSURE for now.** One concrete note taken:
  **T043 (التفكير الإسلامي, T043) teaches only in classroom 5** -
  recorded in her Teachers row, marked unsure until confirmed.
- **Q22. RESOLVED: the ministry reading wins** - "what ministry says is
  usually right". `(3)` means 3 hours for EACH group; the teacher-hour figures
  in `rules/curriculum.json` stand. (FLAG-6's engineering 1.5h×2 convention is
  a separate question - see Q27 below.)
- **Q24. Letters 3rd/4th year Arabic/French/English: from LAST YEAR, kept
  UNSURE** exactly as Majd asked ("keep it as insure until official data
  comes"). Both the curriculum transcription and an independent re-extraction
  of last year's file give **5h / 5h / 5h** for both years. Replace with the
  official page when it arrives.
- **Q25. Period 5 stays CLOSED** (resolved earlier the same day - last year's
  40 uses were human exceptions under time pressure, not policy).
- **Q26. RESOLVED: yes** - H18 also forbids a Saturday day off with a Monday
  training day (three free days in a row through Sunday). Coded in the data
  check and verify.py, proven by a new selftest case (16/16).

---

# BLOCKING QUESTIONS

## Q10. Days off - what Majd sent is TRAINING days, not days off

The file that arrived is the delegation's **training-day** circular (see Q11) -
it fixes يوم التكوين per subject. The per-teacher **day off** (يوم الراحة) is a
different thing: H18 now constrains which days are even possible (never
adjacent to the training day, Sunday wrap included), but somebody still has to
pick each teacher's day off - or tell the solver to choose freely.

**Majd: if you meant this circular to BE the days-off answer, say so** - then
`day_off` stays empty and only the training day is blocked. Otherwise the
`day_off` column is still blank for all 93+ teachers.

## Q5. Group splitting - the real practice here

- Which subjects split the class into groups at this school?
- How many groups per class - always 2, or sometimes 3? (Q23: all teacher-hour
  figures assume 2.)
- Class sizes - the ministry says do not split at 24 pupils or fewer, and the
  `size` column is still empty for all 41 classes.
- When a class splits, what does the other half do?

## Q6. Week A / Week B - which subjects use it now?

Last year's file has 145 cards marked Week A or Week B only, so it existed.

## Q27 (was FLAG-6). Engineering hour model

Each هندسة teacher covers both classes of one ع تقنية year at 16h (8h per
class per discipline); the guide models mech+elec as 4 pupil-hours. Q22's
answer ("ministry is right") probably applies here too, but the engineering
sheets use their own convention - confirm before block patterns are written
for هندسة آلية/كهربائية. UNSURE.

---

# DATA STILL NEEDED (see docs/WHAT_I_NEED_FROM_YOU.md)

- **Class sizes** (`size` column) - needed for H16 splitting checks.
- **Rooms**: being pre-filled from last year for Majd to verify ("rooms
  usually same last year fill data in will see them and verify") - UNSURE
  until he checks. Zones/walking distances whenever (Q7-Q9).
- **Sport distribution 2026/27** - current data is synthetic round-robin
  (FLAG-8), for testing only.
- **Trainees (Q12)** - who they are; they must be free Saturday, and the
  training circular gives them extra days.
- **Second-school teachers (Q13)** - blocked slots. UNSURE/demo for now.
- **Compact-timetable list** - Majd: "will leave it for final version". The
  column exists, empty; everyone gets the ministry spread meanwhile.
- **English FLAG-1** - the documented guess ([name removed]'s section moved
  3ع إعلا → 3ع تج) stands until the corrected sheet.
- **French FLAG (T018 T018)** - on the ministry list, on no
  distribution sheet. Still unexplained.
- **IT ±1h (FLAG-2)** - T082 / T084 printed totals differ by
  one hour in opposite directions. Harmless for the grid; matters for pay.

---

# QUESTIONS ABOUT THE BUILDING (whenever)

## Q7. How are the rooms physically arranged?
Floors/buildings, walking time end to end, are specialised rooms grouped.

## Q8. The stadium
Distance, does travel eat into the lesson, are Stad 1/2/3 real separate
spaces, what happens to PE when it rains.

## Q9. Rooms with restrictions
Shared with another institution, too small for a full class, effectively
somebody's room (the music recommendation; see also Q20 - classroom 5).

---

# SMALLER QUESTIONS, WHENEVER

- **Q15 (H14 options).** Does every pupil take exactly one option or can they
  take none? How many classes pool into one option group? Must they be the
  same level? Is this "a teacher teaching 3 portions of 3 classes"?
  *(The art sheet now gives real 2026/27 section counts for التشكيلية - 8
  sections across 7 streams - which will pin part of this down.)*
- **Q21, retried in plain words** (the first wording was bad, Majd is right):
  The ministry text says Islamic Thought lessons should be **in the morning**;
  if they must be in the afternoon, then **finish by 16:00** (like Sport's
  daylight rule, but as a preference). Question: should I switch that on for
  التفكير الإسلامي؟ **yes / no** - one word. It costs one cell in the
  Subjects sheet (`avoid_after=8`).
- **Q23.** Groups per class - always 2? (assumed everywhere).

---

# REMINDER LIST

- [ ] **Compact-timetable exception list** - deferred to the final version
      (Majd, 2026-08-24). Ministry spread applies to everyone meanwhile.
- [ ] **Official page 10/5** (Letters 3rd/4th year) - replaces the Q24 unsure
      figures when it comes.
- [ ] **Sport 2026/27 distribution sheet** - replaces FLAG-8 synthetic data.
- [ ] **Real day_off decisions** (or "solver picks") - Q10.
- [x] **Friday evening for bac** - answered; recorded as S13, personal
      preference, applied to all bac streams.
- [x] **Art (تشكيلية) distribution** - arrived 2026-08-24, transcribed,
      verified 16h = 8×2h.
- [x] **Training days** - arrived 2026-08-24 (delegation circular), written to
      the Teachers sheet.

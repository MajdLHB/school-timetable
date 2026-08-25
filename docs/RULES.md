# The Rules

**This file is the single source of truth.** Every rule the solver enforces is
written here first, in plain language, before any code exists. If a rule is not
in this file, the solver does not know about it.

Read this file and correct it. Anything marked **[CONFIRM]** is my assumption,
not your rule - tell me if it is wrong.

Status legend: `SPEC` = written only | `CODED` = in solver | `VERIFIED` = checker proves it

---

## HARD constraints
Never violated. The solver is mathematically incapable of returning a timetable
that breaks any of these. If they cannot all be satisfied at once, the solver
reports **INFEASIBLE** and we find out which rule is impossible - it never
silently bends one.

| # | Rule | Status |
|---|------|--------|
| H1 | A teacher is never in two places in the same period. | VERIFIED |
| H2 | A class is never in two places in the same period. **Group-aware since 2026-08-24 (T43)**: a whole-class lesson clashes with everything of that class; group *g* clashes with group *g* and with the whole class; two DIFFERENT groups may run in parallel (the aSc split proven by test C1). **Week-aware (T42)**: a week-A and a week-B lesson may share a slot - they never meet. | VERIFIED |
| H3 | A room is never used by two lessons in the same period. | VERIFIED |
| H4 | Never more lessons at once than rooms exist. Measured last year: **45 rooms**, busiest period **47 lessons** - the extra fit because the stadium holds several classes (Stad 1/2/3). The solver counts per room TYPE, so this is automatic. | VERIFIED |
| H5 | Every class receives exactly the required weekly hours of every subject. | VERIFIED |
| H6 | A lesson only lands in a room of the right type (lab / IT / gym / normal). | VERIFIED |
| H7 | Each teacher's **day off** is fully empty - and so is their **training day** (`training_day` column; circular II.1: respect the pedagogical training days). **The day off is FLEXIBLE by default (Majd, 2026-08-24)**: a written day in `day_off` is fixed ("in data let me say when its fixed and which day"); `(none)` means no day off; **blank means the solver CHOOSES the day** - still exactly one fully free H18-legal day, but which one may change from run to run, and each run's choices are listed in the report. *Relaxable in rescue mode - see below.* | VERIFIED |
| H8 | A teacher is never scheduled in a period they declared unavailable. Never relaxed. | VERIFIED |
| H9 | **Block patterns.** A curriculum row's `blocks` pattern (e.g. `2+1+1`) is placed as exactly those sessions: each block is **consecutive periods on one day** (so it can never straddle the lunch break - those periods are closed), and **each block lands on its own day** - the ministry's meaning of "2+1+1 = three days". A **blank** pattern imposes nothing: single hours, spread by the soft rules. This unlocks the per-subject ministry patterns (M-AR6..10, M-PHI3/8, M-IT2...) as soon as the real curriculum sheet carries them. | VERIFIED |
| H10 | A teacher never exceeds their contracted weekly hours. | VERIFIED |
| H17 | **A teacher never teaches more than 6 hours in one day.** Circular 51/2018 II.2, stated again by the inspectorate text (M-T2). *Relaxable in rescue mode.* | VERIFIED |
| H19 | **24 hours between sessions of a `gap24` subject.** Circular III.2, the PE note: *ينبغي دائما احترام قاعدة الفصل بين حصّتي التربية البدنيّة بـ 24 ساعة*. On consecutive days the later session must not start earlier in the day than the first did; H9 already keeps sessions off the same day. Sport carries `gap24=yes` in the Subjects sheet. Needs a written block pattern. | VERIFIED |

| H18 | **The day off must not create two consecutive free days with the training day.** Source: the inspector's written note on the approved Arabic distribution sheet (21/08/2026): *"لا يسند للأستاذ يوما عطلة متتاليان باعتبار يوم التكوين (لا يمكن إسناد يوم الأربعاء و/أو يوم الجمعة)"* - do not give a teacher two consecutive rest days counting the training day; concretely, when the training day is Thursday, neither Wednesday nor Friday may be the day off. **Majd (2026-08-24): the inspector notes are to be followed, and this one applies to ALL teachers**, not only Arabic. General form: `day_off` must never be adjacent to `training_day`. Enforced as a data-check (like H10: it is a property of the data, no placement can change it), re-checked by verify.py, proven by selftest. **Q26 answered by Majd 2026-08-24: yes, the rule wraps around Sunday** - a Saturday day off with a Monday training day is also forbidden (three free days in a row through the Sunday rest day). Coded and selftested. | VERIFIED |
| H16 | **A small class is not split.** The ministry: *لا داعي إلى تقسيم التلاميذ إلى فوجين إذا لم يتجاوز عدد التلاميذ في القسم الواحد 24* - no need to split a class of 24 pupils or fewer. Majd: *"we were few to the point that we were treated as one group the whole class rather than 2 groups"*. **Whether a class splits is a property of the CLASS AND SUBJECT, not of the subject alone** - proved from last year's file, where 4رياضيات1 split for Natural Sciences and Physics but ran Computer Science whole-class. Carried by the `groups` column in the Curriculum sheet; default 1. Data-check warning when a small class is set to split; **full group placement is BUILT since 2026-08-24 (T43)** - `hours` are per group, the teacher teaches every group, the halves may run in parallel with other subjects' halves. | VERIFIED (T43) |
| H15 | **Daylight-only subjects.** Sport cannot run after **16:00** - the stadium has no lighting. With 10 periods of one hour from 08:00, 16:00 is the end of **period 8**, so Sport may occupy periods 1-8 and never 9 or 10. Stated by Majd 2026-08-24: "sport time window daylight meaning morning and max 14h to 16h". Generalised: any subject may carry a `latest_period` in the Subjects sheet. | VERIFIED |
| H14 | **Optional-subject groups cross class boundaries.** Pupils choose one option; pupils taking the same option are **pooled from several same-year classes** into one group. Groups sharing a class form a **BAND that runs simultaneously** - while options run, a pupil can only be in another option, so nobody misses a lesson. **CODED AND VERIFIED 2026-08-25** from Majd's five answers (below): Options sheet in the workbook (one row per option group), bands derived automatically, alignment + option-teacher binding + one-room-per-group all enforced, checked independently, selftested (2 BREAK/RELAX cases). The **aSc import format for multi-class option lessons is UNPROVEN** - `test/testC4_options.xml` probes it. | VERIFIED (aSc format pending C4) |

**H14 - Majd's answers, 2026-08-25 (the spec):**
- Options are ONLY: Spanish (ESP), German (ALL), Italian (ITA), Music (MUS), Art (TASH).
- Every pupil takes exactly ONE option.
- 1-4 classes pool into one group ("will fill the data later" - the Options sheet).
- Pooled classes must be the SAME year; streams may mix (3rd-year maths + letters together).
- While the option lesson runs, non-option pupils "can only have another option class so pupils dont miss out lessons" - hence the simultaneous band.

## RESCUE MODE - livable exceptions, stated by Majd 2026-08-24

Majd: *"u can tell the model if it get suck to make some livable realistic
exception that teachers and pupils can live with but in extreme condition...
or it gives after work report of what is done whats done but not by rules"*.

So: the solver first tries the strict rules. **Only if NO legal timetable
exists at all**, it retries with the two *livable* hard rules allowed to break
at enormous cost (10,000 per broken hour - far above any soft trade-off):

- **H7** - a teacher teaching on their day off / training day
- **H17** - a teacher's day running past 6 hours

**Never relaxed, ever:** clashes (H1-H3), room rules (H4/H6), hours (H5),
declared unavailability (H8), daylight (H15), the lunch break, closed period
5, and pinned lessons. Every exception taken is listed in `out/report.md`
("RULE EXCEPTIONS"), written to `out/exceptions.json`, and `verify.py` reports
the timetable as "GREEN WITH DECLARED EXCEPTIONS" - done, but not by rules,
exactly as asked. A later strict success deletes the exceptions file.

---

## SOFT constraints
Optimised, weighted, and **reported**. The solver maximises satisfaction and
then tells you in `out/report.md` exactly which ones it missed **and why**.

Weight = how much we care. Higher beats lower when they conflict. These numbers
are first guesses - **we will tune them together after seeing the first result.**

| # | Rule | Weight | Status |
|---|------|--------|--------|
| S1 | **No holes.** A teacher's day is one continuous run - no free hour trapped between two taught hours. | 100 | CODED |
| S2 | **No 1-hour days.** Never make a teacher travel to school to teach a single hour. Minimum 2h if present at all. *Answered by the PDFs: the minimum is 2 - circular I.2/II.2 ("minimum 2 hours in any morning or evening", for pupils AND teachers), and the inspectorate text repeats it twice. 2 is ministry policy, not a guess.* | 90 | CODED |
| S3 | **Hard subjects in the morning.** Maths, Physics, Chemistry etc. placed in early periods. | 70 | CODED |
| S4 | **No 3 hard subjects in a row** within one continuous session. *The ministry is stricter: inspectorate pupil-rule 8 says avoid **two or more consecutive** subjects of the same nature (literary/scientific/social) or stream-defining subjects (= M-P6). So the ministry's limit is "not even 2 of the same nature in a row" - our "hard subjects" framing is looser. Now CODED in the ministry's form: the `nature` column (literary/scientific/social) exists, and two DIFFERENT subjects of the same nature back to back are penalised - a double of one subject is a prescribed pattern and stays allowed.* | 80 | CODED |
| S5 | **Fair morning/evening balance** (circular II.4: alternation). Each teacher's morning and evening hours may differ by at most 2 before a penalty grows - nobody teaches only mornings or only evenings. | 60 | CODED |
| S6 | **Spread subjects across the week** (REWORKED with H9). Two parts: (a) sessions of one subject avoid **consecutive days** - circular III.2 says 2h/week subjects must not fall on consecutive days, and the inspectorate repeats it for English, History-Geo and Arabic; (b) for rows with **no** block pattern, piling several hours onto one day is penalised (the old behaviour). Rows WITH a pattern don't need (b) - H9 already forces one block per day. | 50 | CODED |
| S7 | **Compact days for classes.** Pupils get no free hour in the middle of their day either. | 85 | CODED |
| S8 | **Ministry spread** (REWRITTEN 2026-08-24, was "fewest days present"). Circular II.2: a teacher's hours are balanced across working days. Default: every taught hour beyond 4 on one day is penalised (H17 caps it at 6 outright). **Exception:** `compact=yes` in the Teachers sheet keeps the old packed week - for teachers with long journeys, the list Majd will supply. The old behaviour was the ministry conflict recorded below; the ministry now wins by default, exactly as Majd decided. | 40 | CODED |
| S9 | **Room stability.** A class stays in its home room where possible; less moving around. | 30 | SPEC |
| S14 | **Avoid the last period, 17:00-18:00.** *Majd: "try to avoid 17 to 18 as much as possible its late".* Applies to everyone, not only bac. Period 10 becomes a slot of last resort rather than a forbidden one - making it hard would cost too much capacity given classes average 42 hours. *Independently backed by the ministry: the inspectorate text tells Physics to avoid "from five to six" (M-PH5, corrected reading) - the same 17:00-18:00 hour.* | 55 | CODED |
| S13 | **No Friday evening for bac classes.** *Majd's own words: "me and my other colleague pupils dont want it... so its personal preference as a rule".* **This is a LOCAL preference, not a ministry rule** - the circular requires a free afternoon for bac in the first four days (Mon-Thu) and says nothing about Friday. Recorded as such deliberately, so nobody later mistakes it for policy. Uses `is_bac=yes` in the Classes sheet. | 30 | CODED |
| S12 | **Daylight subjects prefer the morning.** Majd said "morning and max 14h to 16h" - so 14:00-16:00 is the late acceptable window, not the target. Sport should land in the morning where possible and only use periods 7-8 when it must. | 45 | CODED |
| S10 | **Last-period fairness.** Nobody is stuck with the final period every single day: beyond two last-period days a week, each further one is penalised per teacher. | 35 | CODED |
| S19 | **Core subjects: three quarters of the hours in the morning** (circular III.2 - 1st year: Arabic, French, Maths; 2nd-4th: each stream's specific subjects). Rows flagged `core=yes` in the Curriculum sheet may sit in the evening for at most a quarter of their hours. | 65 | CODED |
| S15 | **A class never comes in for a single lone hour** in a morning or evening session (circular I.2 - the minimum-2 rule applies to pupils too). PE and optional subjects are exempt, as the circular itself says (`minmax_exempt=yes` in the Subjects sheet - Sport carries it). | 85 | CODED |
| S16 | **Subject-specific late-hour avoidance** - soft cousin of H15, via the `avoid_after` column in the Subjects sheet. Ministry: **Maths after 16:00** is avoided (M-MA3: "avoid the evening; if impossible, before 16:00"), **Physics avoids 17:00-18:00** (M-PH5). Maths=8, Physics=9. | 50 | CODED |
| S17 | **Bac classes get at least one free afternoon Mon-Thu** (circular I.6: ينبغي منح تلاميذ البكالوريا أمسية راحة). One evening of the first four days entirely free per bac class; penalty if none is. | 70 | CODED |
| S18 | **Never subject B straight after subject A** (`not_after` column in the Subjects sheet). The inspectorate, both 4th-year streams: never Philosophy in the period right after PE - so PHIL will carry `not_after=SPORT` in the real data. Generic: works for any pair. | 60 | CODED |
| S20 | **Align the 2-hour sessions of same-level, same-stream classes** so a devoir can run in all of them at once. Majd (2026-08-24, on Q18): devoirs happen **inside normal lessons**, usually the 2-hour sessions (his example: Economics), so classes of the same level studying the same subject should sit their double at the same time - *"try, if u couldnt get it its fine"*. Best-effort by his own words: a soft preference, never worth breaking real constraints for. | 40 | SPEC |
| S21 | **Shared transport: paired teachers come in on the same days.** Majd asked whether this is possible (2026-08-24) - it is: `travels_with` in the Teachers sheet names the partner (one side of the pair is enough), and each day where one is present and the other is not costs `travel_pair` points. The pairs themselves are still unknown (Q19: "leave unsure until I am sure") - the machinery is ready and waits for the names. | 70 | CODED |

---

## MEASURED from last year's real export (2026-08-24)

Not asked, measured. `python tools/analyze_reference.py` reproduces all of it.

| fact | value |
|---|---|
| teachers | **101** |
| classes | **41** |
| **classrooms** | **45** (not 20 - see below) |
| subjects | 24 |
| groups | 265 (41 whole-class + **224 real subdivisions**) |
| lessons / placed cards | 881 / **1682** |
| week | **Mon-Sat**, day mask **6 chars** on all 1682 cards |
| periods | **10 per day, 08:00-18:00, one hour each.** The grid defines no break, but usage shows one: **period 6 (13:00-14:00) has 0 cards, period 5 (12:00-13:00) only 40** vs ~220 for normal periods. The lunch break is real and visible in the data. |
| Saturday | half day (176 lessons vs ~300 on other days) |
| class load | min 32, median 43, max 53, **avg 42.2 h/week** |
| teacher load | min 8, median 17, max 23, **avg 16.7 h/week** |
| busiest period | **47 lessons at once** vs 45 rooms |
| alternating weeks | **145 of 1682 cards** are Week A or Week B only |
| co-teaching | **none** - 0 lessons with 2 teachers |
| multi-class lessons | 23 |

**The "20 physical classes" figure was wrong.** The real file defines 45
classrooms and uses all 45. That is why the room arithmetic looked impossible:
45 rooms x 6 days x 10 periods = 2700 room-slots for 1682 cards = 62% full.
Comfortable, not impossible.

The busiest period needs 47 rooms for 45 - because the stadium holds several
classes at once (Stad 1/2/3), exactly as described.

## Known about last year's timetable
- It is **not identical to this year**: dummy class-groups that were never used,
  groups added for nothing, fields never updated.
- **Some rules were deliberately broken** because it was too hard by hand.
- Treat it as a *reference for structure*, never as a source of truth.
- **The lunch break is real** (corrected 2026-08-24). Circular 51/2018 I.3
  requires a 2-hour separation between morning and evening; `config.json`
  closes periods 5-6 (12:00-14:00) daily. An earlier claim here that "no lunch
  break exists" was a misreading of Majd's remarks about a *generated*
  timetable. Note: last year 40 cards did sit in period 5 (12:00-13:00) -
  possibly the 5-hour mornings circular I.5 allows Mon-Thu. Whether period 5
  should stay hard-closed or be a rare 5th morning hour is an open question
  (see `docs/OPEN_QUESTIONS.md` Q25).

## Rules I suspect exist but you have not said yet

Tell me yes or no on each - each one is cheap to add now and expensive later.

- [ ] Are there teachers who work **part-time / specific days only**?
- [ ] Do any teachers teach at **another school** and need fixed free half-days?
- [ ] Are there subjects taught by **two teachers together** (co-teaching)?
- [ ] Are classes ever **split into groups** (e.g. half the class to the lab, half elsewhere)?
- [x] Is there a **fixed all-school slot** (assembly, sport, prayer, break)?
      **No** (Majd, 2026-08-24, Q17).
- [x] Do **exams / devoirs de contrôle** need reserved slots? **No - they run
      inside normal lessons**, usually the 2-hour sessions (Majd, 2026-08-24,
      Q18). Gave rise to soft rule S20 (align same-level doubles).
- [ ] Any teacher who must **not** be scheduled at the same time as another
      (shared spouse transport, same person covering two roles)?
      *Majd, Q19: "good point - leave unsure until I am sure"; this is a demo
      run, the final version will carry the real list.*
- [ ] Any **seniority** rules - senior staff get first pick of the good slots?

---

## Ministry recommendations

The Tunisian General Inspectorate publishes binding pedagogical
recommendations for building teacher timetables, per subject. Majd supplied
them 2026-08-24. They are catalogued and rated in **`docs/MINISTRY_RULES.md`**
- about 90 items - and none are coded yet.

Two findings from that catalogue that affect the rules below:

1. **S8 vs the ministry - RESOLVED 2026-08-24.** Our old S8 rewarded packing a
   teacher's hours into fewer days. The ministry says the opposite: *"توزيع
   الحصص على أغلب أيّام الأسبوع"* - spread over most days. **Majd decided the
   ministry wins by default**, with a per-teacher `compact=yes` exception for
   those with long journeys (names to come). S8 is rewritten and coded that
   way above.
2. Several ministry items are about **who teaches which classes**, not about
   when lessons happen. Our solver does not decide that - it reads `teacher_id`
   as input. Those are tagged [A] in the catalogue.

## Change log

Every change to a rule gets a line here, so no rule is ever silently lost.

| Date | Change |
|------|--------|
| 2026-08-24 | File created from the first conversation. All rules `SPEC`, nothing coded. |
| 2026-08-24 | Ministry recommendations catalogued and rated in `docs/MINISTRY_RULES.md`. Nothing coded from them yet. Recorded a direct conflict between our S8 and ministry rule M-T5. |
| 2026-08-24 | H15 (daylight cutoff for Sport) and S12 (prefer morning) stated by Majd, coded, verified, and covered by a BREAK/RELAX test. |
| 2026-08-24 | **Retracted H11, H12, H13, S11.** They were written up as numbered rules from remarks made in passing. Nothing had been decided. Moved to `docs/NOTES.md` as open questions. Nothing gets a rule number until it is stated deliberately and confirmed. |
| 2026-08-24 | **PDF verification pass** (Majd: "pdfs are source of truth"). All 21 pages of `rules/rules.pdf` read as images and checked against the catalogue; two errors fixed there (M-PH5 time window, M-PHI3/M-PHI8 swapped). In this file: removed the stale "no lunch break" claims (break confirmed by circular I.3, config, and last year's data - period 6 empty, period 5 nearly so); answered S2's [CONFIRM] (minimum is 2, ministry policy); annotated S4 with the ministry's stricter same-nature rule; added the ministry backing to S14. New Q25 raised on period 5. |
| 2026-08-24 | **Q25 answered by Majd: period 5 stays closed.** "it shouldnt be open even if rare follow rules" - last year's 40 uses were hand-made exceptions under time pressure, not policy. |
| 2026-08-24 | **Ministry rules coded.** New **H17** (max 6 teaching hours/day, circular II.2) - hard, verified, selftested. **H7 extended** to the training day (II.1; `training_day` column). **S8 rewritten** to the ministry spread with the `compact=yes` exception, as Majd decided. **S5 built** (II.4 alternation). New **S15** (class never a lone hour, I.2, PE/optional exempt via `minmax_exempt`), **S16** (`avoid_after`: Maths 16:00 M-MA3, Physics 17-18 M-PH5), **S17** (bac free afternoon Mon-Thu, I.6), **S13/S14 coded** (`is_bac` column). Statuses above updated to match reality: everything marked CODED/VERIFIED is running and tested; selftest 11/11, demo 580 lessons ALL GREEN. |
| 2026-08-24 | **H18 added** from the inspector's note on the approved Arabic distribution sheet; Majd instructed that inspector notes are binding and this one applies to all teachers. The 2026/27 pedagogical distribution (who teaches which stream, and each teacher's required hours) was extracted from the sheets in `data/reference/currect distirbution - can be changed/`, cross-verified against `rules/curriculum.json` hours and the 41-class structure, and written to `data/school.xlsx` (Teachers hours, Classes, Subjects, new Distribution sheet). Full verification log and open flags: `data/DISTRIBUTION_REPORT.md`. |
| 2026-08-24 | **H18 coded and proven** (inspector's rule, all teachers, as Majd instructed): day_off never adjacent to training_day. Data-check + verify.py + selftest. Q26 raised: does the rule wrap around Sunday? |
| 2026-08-24 | **RESCUE MODE built, stated by Majd** ("livable realistic exception... in extreme condition... after work report of what is done but not by rules"). Strict first, always; only if NO legal timetable exists, H7/H17 may break at cost 10,000/hour; every exception is listed in the report, `out/exceptions.json`, and verify.py's "GREEN WITH DECLARED EXCEPTIONS". Clashes, rooms, hours, H8, H15, the lunch break and locks are never relaxed. Proven end-to-end on a deliberately impossible school (one declared exception, minimal). |
| 2026-08-24 | **H9 CODED AND VERIFIED - the biggest gap is closed.** The solver now places SESSIONS, not hours: a `blocks` pattern like `2+1+1` becomes one double + two singles, each a run of consecutive periods on its own day; the lunch break can never be straddled (those periods are closed, so no legal start exists). Blank pattern = free single hours with soft spreading (S6 reworked: adjacent-days penalty per circular III.2, plus the old same-day pile-up penalty for pattern-less rows). Independent H9 check in verify.py compares placed runs against the declared pattern. Selftest 14/14 (two H9 BREAK/RELAX pairs); demo with 120 real doubles solved and ALL GREEN. Room assignment now keeps one room across a whole block. |
| 2026-08-24 | **H19 and S18 coded from the PDFs.** H19: 24 hours between sessions of a `gap24` subject (circular III.2's PE note) - hard, verified, selftested (15/15). S18: `not_after` pairs (inspectorate: never Philosophy straight after PE) - soft, weight 60, generic for any subject pair. Demo regression ALL GREEN. |
| 2026-08-24 | **S4/M-P6, S19 and S10 coded.** S4 in the ministry's exact form via the `nature` column (different same-nature subjects never back to back; doubles unaffected). S19: `core=yes` curriculum rows keep 3/4 of hours in the morning (III.2). S10: last-period fairness per teacher. Demo exercises all three (natures + core flags set); 15/15 selftests, verifier ALL GREEN. |
| 2026-08-24 | **Batch of answers from Majd (evening).** Not a pilot institute (Q1 - no boxed-④ group sessions anywhere). Q22 settled: **the ministry reading of group hours is right** ("what ministry says is usually right") - `rules/curriculum.json` teacher-hour figures stand. Streams confirmed (Q3): 1st common core; 2nd lettres/sciences/eco/info; 3rd+bac lettres/math/sciences/info/technique/eco; **no sport stream**. Saturday afternoon closed confirmed (config comment updated). Q16: اقتصاد and تصرف are two separate subjects, confirmed. Q17: no fixed all-school slots. Q18: devoirs inside lessons → new **S20** (SPEC). Q19/Q20: left "unsure" at Majd's request until the final version; noted meanwhile that the PISL teacher only teaches in classroom 5. **Q26: H18 wraps around Sunday - coded, verified, selftested (16/16).** |
| 2026-08-24 | **Training days arrived** - the official Bizerte delegation circular (0000132-2151-07-2026, `data/reference/SCAN_20260814_140843760.pdf`) fixes the pedagogical training day PER SUBJECT for 2026-27. Secondary-level column written to `Teachers.training_day` for 77 teachers (ARAB/MATH/PISL/ECO=Thu; FREN/PHYS/PHIL=Wed; ENGL/ALL/SVT/HIST/CIV/GEST=Tue; ESP/TASH=Mon; ITA=Sat). IT + TECH: the circular sends HALF the teachers Friday and half Saturday without naming them - noted per teacher, unsure. SPORT is absent from the circular - blank. Trainees have separate days (Sat/Fri per subject) - waiting on Q12 (who the trainees are). |
| 2026-08-24 | **The art (تشكيلية) 2026/27 sheet arrived** and replaced the provisional last-year row in the Distribution sheet (FLAG-7 half-closed): T032, 16h/16h, 8 sections × 2h across 3آداب/3ع-تج/3اق-ت/3ع-إعلا/4آداب/4اق-ت×2/4ع-إعلا - internally verified. |
| 2026-08-24 | **First real-school solves** (rescue mode: strict is infeasible for this data, so the new `--rescue` flag skips straight to the livable-exceptions build; every exception still costs 10,000/hour and is declared). Run 1 on the 437-row curriculum: 131 exceptions. Run 2 after the lab split (483 rows, PHYS_TP/SVT_TP): **111 exceptions, 330 versions in 300s**. Random balanced day offs assigned to all teachers per Majd ("day off is a random day"), H18-safe. The live progress line now shows, from the FIRST complete timetable on: exception hours + teacher-days + soft points per version (Majd asked to watch the number fall until Ctrl+C or OPTIMAL; Ctrl+C keeps the best). |
| 2026-08-24 | **S21 coded** (shared transport - Majd asked if it is possible; it is): new `travels_with` column in the Teachers sheet names the partner (one side of the pair is enough), the pair's day-presence is compared day by day at weight `travel_pair`=70. Data check validates the id. The real pairs are still unknown (Q19) - the machinery waits for the names. Selftest 16/16. |
| 2026-08-24 | **All human outputs now clean HTML**, per Majd: every solve writes `out/view.html` (printable per-class/per-teacher grids, A4 landscape, save-as-PDF), `out/teachers.html` (who teaches what, hours vs contract, unassigned lessons), and `out/report.html` (the stats) alongside `report.md` and the aSc `timetable.xml` - the XML stays the real table, HTML is the printable layer, exactly as Majd put it. |
| 2026-08-24 | **H7 reworked: the day off is the SOLVER'S CHOICE by default** (Majd: "day off isnt just random, u prechoose it flexible, u can change it along the way unless in data its fixed - and in data let me say when its fixed and which day"). The random pre-assigned day offs were deleted from the Teachers sheet. New semantics of `day_off`: written day = fixed hard; blank = solver picks one fully free H18-legal day (candidates never adjacent to the training day, Sunday wrap included), reported per run; `(none)` = no day off. Enforced in the model (strict: chosen day fully empty; rescue: breakable at 10,000/h, declared), verified independently (verify.py checks a fully free legal day EXISTS), selftest 17/17 (new BREAK/RELAX case; the old H7 case updated to "(none)"). Data check counts the flexible day as lost capacity. aSc export encoding left untouched at utf-8 - Majd confirmed Arabic imports correctly ("dont fix something working"). |
| 2026-08-24 | **T43 GROUP SPLITTING and T42 WEEK A/B are BUILT** - the whole machinery, end to end. Trigger: Majd ran both aSc probes; test C1 (groups) PASSED in the real aSc; test C2 (weeks) placed its week-A cards correctly once the project was set to 2 weeks (phantom unplaced copies remain - test C3 probes the fix; the card week masks are the proven part). New Curriculum semantics: `groups=N` = the row is taught once per group, `hours` are PER GROUP (teacher works NxHours); new `week` column: blank = every week, A/B = that week of the fortnight. Solver: clashes (H1/H2/H3/H4), H17 daily cap, H10 and every pupil/teacher comfort rule are per class-PART and per WEEK view; new S22 (M-SN4): the group sessions of one row prefer the same day, weight `tp_groups_same_day`=45. Emitter writes the proven `<groups>` + `<weeksdefs>`/week-mask forms. verify.py checks all of it independently (H5 now per group and per week). Selftest 20/20 with three new BREAK/RELAX cases; a mini school with split TP + fortnight rows solves and verifies ALL GREEN, and a deliberately tampered week card is caught. make_curriculum upgraded: real groups=2 TP rows, fortnightly hours restored as week rows balanced by class parity, `alt_whole1_group4` = whole-hour and group-hours on OPPOSITE weeks. |
| 2026-08-25 | **H14 CODED - the last hard rule.** Majd answered the five questions (recorded above). Options sheet added to the workbook (tools/options_sheet.py; empty until Majd fills the class lists). Bands auto-derived from shared classes; enforced: simultaneity across member classes, option teachers bound to band slots (their clashes/day off/6h cap/comfort all see it), one room per option group counted in the model and assigned concretely. Independent verify: per-class option hours, parallel-option clash semantics (options may overlap options, never normal lessons), room types. Selftest 23/23. Two-phase rescue added the same day (Majd: "least amount of exceptions... so i know its doable"): PHASE 1 minimises exceptions alone and can PROVE the minimum (0 = fully legal table exists), PHASE 2 locks that number and optimises comfort - proven live on the mini school ("PROVEN: a FULLY LEGAL timetable exists. Doable, 0 exceptions"). Also same day, from Majd's aSc feedback: theory<->TP auto not_same_day link, pupil day caps T26/T27, class_gap 150 (pupils' gaps outrank teachers'), S20 group_pair_swap, T45 zone proximity (inert until zones filled), T37/T41 coded, Weights sheet. aSc multi-class option lesson format pending test C4. |

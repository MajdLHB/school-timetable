# Tasks

The work plan. One line per task, in the order it should happen.

`DONE` `NEXT` `BLOCKED` `LATER` — and if a task is blocked, it says by what.

Related files: `docs/RULES.md` (what is decided) · `docs/OPEN_QUESTIONS.md`
(what is not) · `docs/WHAT_I_NEED_FROM_YOU.md` (data to collect) ·
`docs/HOW_IT_WORKS.md` (how the machine works).

---

## Phase 0 — foundations  ✅ all DONE

| id | task | status |
|---|---|---|
| T1 | Prove aSc will accept a generated timetable | DONE — `lessonid` + days bitmask |
| T2 | Find why cards vanished on the first real import | DONE — day-mask length must equal the aSc project's day count. **Fails silently.** |
| T3 | Read Arabic out of aSc exports | DONE — it is `cp1256`, mislabelled `windows-1252`. utf-8 **deletes** it |
| T4 | Working solver, real scale | DONE — 40 classes, 10 min, verifier all green |
| T5 | Independent verifier | DONE — `verify.py`, reads the XML off disk |
| T6 | Prove each rule is wired up, not just written | DONE — `selftest.py`, BREAK/RELAX pairs |
| T7 | Report rules that exist only on paper | DONE — `rule_coverage.py` |
| T8 | Crash safety and resume | DONE — `solution.json`, `--continue`, `out/archive/` |
| T9 | Privacy firewall | DONE — caught a real near-miss |
| T10 | Import the ministry teacher list | DONE — 93 teachers, national ID **not** copied |
| T11 | Read circular 51/2018 and decode its symbols | DONE — all 13 pages |
| T12 | Turn the curriculum tables into data | DONE — `rules/curriculum.json`, validated against last year |

## Phase 1 — the rest of the rules

| id | task | status |
|---|---|---|
| T13 | Read `rules/rules.pdf` — **20 of 21 pages still unread** | NEXT |
| T14 | Fold its per-subject rules into `docs/RULES.md` with ratings | after T13 |
| T15 | Re-scan guide page 10/5 — Letters Arabic/French/English top rows cut off | BLOCKED — Q24. Provisional values taken from last year |

## Phase 2 — prove the two hard aSc features

| id | task | status |
|---|---|---|
| T16 | Import `test/testC1_groups.xml` — split class, two groups in parallel | BLOCKED — needs you to run it |
| T17 | Import `test/testC2_weeks_AB.xml` — the ministry `△1/(4)` pattern | BLOCKED — needs you, and the aSc project set to 2 weeks + 6 days |
| T18 | Teach the emitter to write groups and weeks | BLOCKED by T16, T17 |

**Nothing gets built on these until they are proven by import.** The day-mask
bug fails silently, so "it looks right" is not evidence.

## Phase 3 — your data

| id | task | status |
|---|---|---|
| T19 | Classes: name, level, stream, size | BLOCKED — you. 41 class names already recovered from last year |
| T20 | Rooms: 45 of them — type, capacity, **where they are** | BLOCKED — you |
| T21 | Curriculum: per class and subject, from `rules/curriculum.json` | after T19 |
| T22 | Teacher hours and days off | BLOCKED — you |
| T23 | Who teaches what | BLOCKED — you |
| T24 | Training days, trainees, two-school teachers | BLOCKED — you |
| T25 | Compact-timetable exceptions | BLOCKED — you, list promised |

See `docs/WHAT_I_NEED_FROM_YOU.md`. **Send it in batches — do not wait for
everything.** Five classes is enough to start.

## Phase 4 — the cheap ministry constraints

Seventeen rules, all high value and low cost, most needing no new data.

| id | task | status |
|---|---|---|
| T26 | Max 6 h/day, min 2 h per half-day — **pupils and teachers** | LATER |
| T27 | Max 4 h for a pupil in one half-day | LATER |
| T28 | Spread each teacher across most days (replaces our S8) | LATER — with the T25 exceptions |
| T29 | Morning/evening alternation, first four days | LATER |
| T30 | Three quarters of core and stream subjects in the morning | LATER — replaces our cruder S3 |
| T31 | Bac: free afternoon in the first four days | LATER |
| T32 | PE sessions 24 hours apart | LATER |
| T33 | 2 h/week subjects never on consecutive days | LATER |
| T34 | Never Philosophy straight after PE | LATER |
| T35 | English never doubles; never two consecutive days | LATER |
| T36 | Maths before 16:00 — same machinery as H15 | LATER |
| T37 | History and Geography never the same day | LATER |
| T38 | Avoid 17:00–18:00 (S14) | LATER |
| T39 | No two separate sessions of one subject, same day, same class | LATER |

## Phase 5 — the machinery that unlocks many rules at once

| id | task | status |
|---|---|---|
| T40 | **H9 block patterns** — `2+1+1`, doubles kept together | LATER — biggest single gap |
| T41 | Doubles at the start of a half-day, never split by the break | after T40 |
| T42 | **Week A / Week B** | after T17 |
| T43 | **Group splitting**, with pupil ≠ teacher hours | after T16 |
| T44 | **H14 option groups** pooled across classes | after T43 |
| T45 | Room proximity — avoid long walks between consecutive lessons | after T20 |

## Phase 6 — finishing

| id | task | status |
|---|---|---|
| T46 | Tune the weights against real output, with you | LATER |
| T47 | Run ladder 30 s → 2 min → 10 min, verify each | LATER |
| T48 | Overnight run, 8–12 h | LATER |
| T49 | Import to aSc, print with your Arabic designs | LATER |

---

## Known debts

- `docs/MINISTRY_RULES.md` has ~90 rules catalogued and rated. **None coded.**
- `rule_coverage.py` currently flags **H9** and **H14** as written but not built.
- Weights are first guesses and have never been tuned against real output.
- The solver has never run on real data.

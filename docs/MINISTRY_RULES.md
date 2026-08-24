# Ministry pedagogical recommendations - rated catalogue

Source: *التفقدية العامة للتربية - توصيات بيداغوجية خاصة بإعداد موازنات الأساتذة*
(General Inspectorate of Education, Tunisia), supplied by Majd 2026-08-24.

**Provenance, established 2026-08-24:** the scanned `rules/rules.pdf` (21 pages)
is this same document. Its last page carries the capture footer: taken from
`www.edunet.tn/ressources/inspection/taousiat_pedag.htm` on **11-08-2003**. So
this text is from **around 2003** - fifteen years older than circular 51/2018.
**Where the two disagree, the 2018 circular wins.**

**Verified 2026-08-24:** every page of the scan was read image-by-image and
checked against this catalogue. The catalogue was found complete - all 13
subject sections and the three general sections match the scan. Two
transcription errors were found and corrected (marked ⚠ CORRECTED below):
M-PH5 (a misread time reference) and the M-PHI3/M-PHI8 level labels (swapped).

**Nothing here is coded yet.** This is a catalogue so we can choose an order of
work together. Each item gets two independent ratings.

| | POWER - how much it improves life | DIFFICULTY - how hard to build |
|---|---|---|
| 1 | barely noticed | a few lines, data already present |
| 2 | helps a few people | small constraint, data present |
| 3 | noticed by many, weekly | new constraint, small data addition |
| 4 | noticed by most, daily | real modelling work or new data |
| 5 | transforms the timetable | major modelling, or data we do not have |

**Best first work = high POWER, low DIFFICULTY.** Those are marked ⭐.

---

## ⚠️ First, a split that matters

The document covers **two different problems**, and we currently only solve one.

**A. توزيع المستويات - Pedagogical distribution (WHO teaches WHICH classes).**
Which teacher gets which levels and classes, based on competence, seniority,
and rotation. Our solver **does not decide this** - it reads `teacher_id` from
the Curriculum sheet as a given. Roughly half this document is about A.

**B. الموازنات - Timetabling (WHEN and WHERE).** That is what we built.

We could solve A later as a separate phase, and it would feed B. But it is a
different model with different data, and pretending otherwise would hide real
work. Everything below is tagged **[A]** or **[B]**.

Also note: rules in A depend on **teacher evaluation data** (الكفاءة البيداغوجية,
تقييم مردود المدرس). That is sensitive personal information about employees,
well beyond the timetable's needs. If we ever go near it, `docs/PRIVACY.md`
applies with full force - and my recommendation is that we do not store it.

---

## ⚠️ Second - a phrase that appears twice

The Islamic Thought section says the optional subject, if it must be in the
evening, should run **من الساعة 14 إلى الساعة 16** - exactly the "14h -> 16h"
you described for Sport.

You already confirmed you meant **Sport / daylight**, and H15 is built on that.
But the same window appears in the ministry text for **التفكير الإسلامي**.
**Do you want the 14:00-16:00 window applied to Islamic Thought as well?**
I am not assuming either way.

---

# GENERAL - pupils' timetables (موازنات التلاميذ)

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| ⭐ M-P1 | **No hollow hours** (الساعات الجوفاء) - no free period trapped inside a pupil's day | B | 5 | 1 | **already built** as S7 |
| ⭐ M-P2 | **Never a single lone hour** in a morning or evening session - pupils must not travel in for less than 2 hours | B | 5 | 2 | mirror of S2, which we built for teachers |
| ⭐ M-P3 | **Max 4 hours** for a pupil in one morning or one evening session | B | 4 | 2 | count per class per half-day |
| ⭐ M-P4 | **Max 6 hours per class per day** (Mon-Thu) - against exhaustion | B | 4 | 2 | your classes average **42 h/week**, so this bites hard |
| ⭐ M-P5 | **Subjects spread fairly across all week days** | B | 4 | 2 | partly built as S6 |
| M-P6 | **No two consecutive subjects of the same nature** (literary / scientific / social) or two stream-defining subjects | B | 4 | 3 | needs a `nature` column on Subjects. Stronger than our current S4 |
| M-P7 | **Balanced across morning and evening** for each class | B | 4 | 2 | |
| M-P8 | **One subject spread through the week** - not only at the start or end | B | 3 | 2 | |
| M-P9 | **Don't group the 1.5h / 2h subjects** - separate them (e.g. Civic Education) | B | 3 | 3 | needs fortnightly modelling |
| M-P10 | **Don't scatter one class across many rooms** | B | 3 | 3 | we have S9 room stability, unimplemented |
| M-P11 | **Specialised rooms used properly and continuously** | B | 3 | 2 | our room-type system already does most of this |
| M-P12 | **Free an evening for final-year classes** - not Friday or Saturday evening | B | 4 | 3 | needs a "final year" flag per class |
| M-P13 | **Distribute across morning/evening regardless of subject weight** | B | 2 | 1 | mostly a caution against hand-scheduling habits |
| M-P14 | **Organise fortnightly hours, group sessions and alternating sessions well** | B | 5 | 5 | this is the Week A / Week B + split-group work. **145 such cards existed last year** |

# GENERAL - teachers' timetables (موازنات الأساتذة)

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| ⭐ M-T1 | **Never a single lone hour** morning or evening | B | 5 | 1 | **already built** as S2 |
| ⭐ M-T2 | **Max 6 hours/day** counting morning + evening together | B | 4 | 1 | trivial to add |
| ⭐ M-T3 | **Balance morning and evening across teachers** - not some always morning, others always evening | B | 5 | 2 | our S5, specified but not built. **High value, cheap** |
| ⭐ M-T4 | **No two separate sessions of the same subject, same day, same class** | B | 4 | 2 | |
| ⭐ M-T5 | **Spread over most days of the week** | B | 4 | 1 | inverse of our S8; note S8 currently pushes the *other* way - see conflict below |
| M-T6 | **Respect the continuous-training day**, and Saturday for 1st/2nd-year trainees | B | 4 | 2 | needs a `trainee` flag + training day per teacher. Our `day_off` covers part |
| M-T7 | **Teacher wishes may be honoured, but never at pupils' expense** | B | 3 | 2 | a weighting principle: teacher preferences must weigh less than pupil rules |
| M-T8 | **Coordinate with the other institution** for teachers working at two schools | A+B | 4 | 3 | needs their external timetable as blocked slots - our `unavailable` sheet fits |

> **CONFLICT to resolve.** M-T5 (spread over most days) contradicts our current
> **S8 "fewest days present"** (weight 40), which rewards packing a teacher's
> hours into fewer days. The ministry wants the opposite. Ministry text should
> win unless you disagree - but this is your call, not mine.

# GENERAL - pedagogical distribution (التوزيع البيداغوجي)

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-A1 | **Max 2 levels per teacher** where possible | A | 4 | 4 | needs `level` per class |
| M-A2 | Assign levels using the teacher's **wish card**, scientific competence, pedagogical competence | A | 4 | 5 | needs evaluation data - **privacy-sensitive, see above** |
| M-A3 | **Balance experience** - don't concentrate the strong teachers on some classes | A | 4 | 5 | needs competence data |
| M-A4 | **Rotate levels every 2-3 years** | A | 3 | 5 | needs history from previous years |
| M-A5 | **Difficult classes to teachers able to recover them** | A | 4 | 5 | needs results data |
| M-A6 | **Final classes to the most experienced** | A | 4 | 4 | needs experience data |

---

# BY SUBJECT

## العربية - Arabic

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-AR1 | Min **2**, max **3** levels per teacher (across one or two schools) | A | 4 | 4 | |
| M-AR2 | Renew one of the two levels every 2-3 years (5 max for final classes) | A | 2 | 5 | needs history |
| M-AR3 | **Never** all final classes to one teacher - pair them | A | 4 | 4 | |
| M-AR4 | Non-literary 3rd-year classes not to one teacher - pair with literary | A | 3 | 4 | needs stream data |
| M-AR5 | Avoid a teacher having only one class of a level - prefer two | A | 3 | 4 | |
| **M-AR6** | **7th & 8th basic: 1 hour/day, separate, over 5 days** | B | 5 | 4 | exact per-level session pattern. Needs H9 blocks + level data |
| **M-AR7** | **9th basic & 3rd literary: 4 days = 3 separate + 1 double** | B | 5 | 4 | as above |
| **M-AR8** | **1st & 2nd secondary: 4 days = 1 double + 2 separate + 1 fortnightly** | B | 5 | 5 | needs blocks **and** Week A/B |
| **M-AR9** | **3rd non-literary: 2 days = 1 double + 1 separate** | B | 5 | 4 | |
| **M-AR10** | **4th literary: over 3 days** (better than the customary 2) | B | 4 | 3 | |
| M-AR11 | Balance a class's sessions between morning and evening | B | 4 | 2 | |
| ⭐ M-AR12 | **Doubles at the START of a session** (especially morning), never split by the break | B | 4 | 3 | needs H9 |
| M-AR13 | Doubles for a teacher's two parallel classes in the **same period**, so a unified test can be run | B | 4 | 4 | elegant and very specific |
| M-AR14 | Spread scarce sessions - never two consecutive days | B | 4 | 3 | |
| ⭐ M-AR15 | Teacher's daily load **3-4 hours, max 5** | B | 4 | 1 | trivial |

## العلوم الفيزيائية - Physical Sciences

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-PH1 | Levels distributed objectively | A | 3 | 4 | |
| M-PH2 | Prefer common-core + second-stage mix (1+3, 1+4, 2+3, 2+4) | A | 3 | 4 | |
| M-PH3 | Nobody "owns" a level, including final classes | A | 3 | 4 | |
| ⭐ M-PH4 | Spread across the week - not 2 or 3 consecutive days | B | 4 | 2 | |
| ⭐ M-PH5 | ⚠ CORRECTED: **avoid the 17:00-18:00 hour** for Physics | B | 3 | 1 | The Arabic is تجنّب برمجة حصّة من الخامسة إلى السادسة - "from five to six". First read as "period 5 into period 6", but the document uses clock times everywhere else (قبل الساعة الرابعة, من الساعة 14 إلى الساعة 16), and a 5th-to-6th-period session cannot exist here anyway (that is the lunch break). Reading it as **17:00-18:00** matches our S14 last-resort slot exactly. |
| M-PH6 | **TP may be in late hours** - morning or evening | B | 2 | 1 | a *relaxation*: TP is exempt from the morning preference |
| M-PH7 | TP rooms **reserved for TP only**, to protect equipment | B | 4 | 2 | our room types handle this once labs are declared |
| M-PH8 | Involve lab staff in room scheduling | - | 1 | - | organisational, not a solver rule |

## الرياضيات - Mathematics

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| ⭐ M-MA1 | Balanced across the week per class | B | 4 | 2 | |
| M-MA2 | **No double hours** for a class in 2nd stage of basic education | B | 4 | 3 | opposite of Arabic - patterns are per subject AND per level |
| ⭐ M-MA3 | **Avoid evening; if unavoidable, before 16:00** | B | 5 | 1 | same machinery as H15 - just `latest_period` on MATH |
| ⭐ M-MA4 | Teacher **max 5 h/day**, minimum **2 non-separated** hours | B | 4 | 2 | |
| M-MA5 | Max levels: **2** basic 2nd stage, **3** secondary in extremis | A | 4 | 4 | |
| M-MA6 | **Max 3 classes of the same level** per teacher | A | 3 | 4 | |
| M-MA7 | **A free session for same-level teachers to meet** | B | 4 | 4 | a shared free slot for a group of teachers - unusual and interesting |
| ⭐ M-MA8 | No two separate sessions the same day for one class | B | 4 | 2 | |

## التاريخ والجغرافيا - History & Geography

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| ⭐ M-HG1 | **Never History and Geography on the same day** for one class | B | 4 | 2 | needs the two treated as distinct subjects |
| M-HG2 | Alternate morning / evening for a class | B | 3 | 2 | |
| M-HG3 | Spread across the week; never two consecutive days | B | 4 | 2 | |
| M-HG4 | **Split the double hours** at every level EXCEPT final years | B | 4 | 3 | again the opposite of Arabic |
| M-HG5 | The weekly half-hour becomes **1 hour every 2 weeks (Week A / Week B)** | B | 5 | 5 | the core fortnightly mechanism |
| M-HG6 | Teach in rooms next to the History/Geo lab; avoid the teacher moving | B | 3 | 3 | |

## التربية الموسيقية - Music

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-MU1 | A large dedicated room (special board, instrument cabinet) | B | 3 | 1 | a room type |
| M-MU2 | If impossible, the teacher **must not move rooms all day** | B | 4 | 3 | teacher-stays-put constraint |
| M-MU3 | Electrical supply in the music room | - | 1 | - | facilities, not scheduling |
| M-MU4 | Teacher takes **similar levels** in one session; else at most 2 consecutive same-level | B | 3 | 4 | |

## الفلسفة - Philosophy

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-PHI1 | **3rd Letters:** the philosophy hour **mid-week** | B | 3 | 2 | the scan ties this rule to 3rd Letters specifically |
| M-PHI2 | Avoid evening sessions where possible | B | 3 | 1 | stated for 3rd Letters and 4th Letters; 4th scientific gets "alternate" instead |
| M-PHI3 | ⚠ CORRECTED: **4th scientific** (not 3rd literary): hours as **2/2**, never single hours | B | 4 | 3 | needs H9. The scan puts 2/2 under السنوات الرابعة الشعبة العلمية |
| M-PHI4 | The two sessions not on consecutive days | B | 3 | 2 | stated for 4th scientific |
| M-PHI5 | Alternate morning / evening | B | 3 | 2 | stated for 4th scientific |
| ⭐ M-PHI6 | **Never Philosophy straight after PE** | B | 4 | 2 | cheap, specific, and obviously right; stated for both 4th-year streams |
| M-PHI7 | Reserve an afternoon for regular tests | B | 3 | 3 | both 4th-year streams |
| M-PHI8 | ⚠ CORRECTED: **4th Letters** (not 4th scientific): pupils 2/2/2 (1-1), teacher 2/2/2/2 | B | 4 | 4 | the scan puts this under السنوات الرابعة شعبة الآداب |

## التربية التشكيلية - Plastic Arts

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-TP1 | Balanced across the week, except the training day | B | 3 | 2 | |
| ⭐ M-TP2 | Teacher **max 6 h/day** | B | 3 | 1 | |
| M-TP3 | Each teacher covers all three levels | A | 2 | 4 | |
| M-TP4 | Create an arts club to complete the quota | - | 1 | - | organisational |
| M-TP5 | Optional subject: ~12 pupils, **max 20** | B | 3 | 3 | ties into H14 option groups |
| M-TP6 | Normal hours; **Friday evening only if necessary** | B | 3 | 2 | |

## العلوم الطبيعية - Natural Sciences

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-SN1 | Max levels: **3** basic 2nd stage, **2** for 3rd/4th secondary, never above 3 | A | 4 | 4 | |
| M-SN2 | Final classes to capable teachers | A | 4 | 4 | |
| M-SN3 | **TP in the morning** for 4th and 3rd experimental science | B | 4 | 3 | |
| M-SN4 | Non-experimental streams: the two groups' TP **consecutive, same day** | B | 5 | 5 | **this is your "3 hours = 1.5h x 2 groups"** |
| ⭐ M-SN5 | **No group split if the class has 24 pupils or fewer** | B | 4 | 2 | uses the `size` column we already have |
| M-SN6 | Use specialised rooms rigorously | B | 3 | 1 | |
| M-SN7 | Balanced across the week except the training day | B | 3 | 2 | |

## الانقليزية - English

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| ⭐ M-EN1 | **Never two consecutive hours** for a class, at any level | B | 4 | 1 | very cheap - a "no doubles" flag on the subject |
| M-EN2 | Experienced teachers for 7th basic and 1st secondary | A | 3 | 4 | |
| ⭐ M-EN3 | Never two consecutive days | B | 4 | 2 | |
| M-EN4 | A dedicated English room every class visits **at least once a week** (listening) | B | 4 | 4 | "at least once weekly in room X" is a new shape of constraint |

## التقنية - Technology

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-TE1 | Two levels per teacher, **from the same stage** | A | 3 | 4 | |
| M-TE2 | Final classes to experienced teachers | A | 3 | 4 | |
| M-TE3 | Class split into **two equal groups** | B | 4 | 4 | |
| M-TE4 | The two groups in **two consecutive sessions** | B | 5 | 4 | same shape as M-SN4 |
| M-TE5 | Both groups to **one** teacher (1st/2nd year) | A | 3 | 3 | |
| M-TE6 | Prefer a **20 h** week for the teacher | A | 2 | 1 | a data value |
| ⭐ M-TE7 | **Max 4 h/day** for the teacher - the subject is demanding | B | 4 | 1 | |
| **M-TE8** | **Build the Technology timetables FIRST**, to get best use of rooms | B | 5 | 3 | see below |
| M-TE9 | Room at least **6 x 8 m**; a mechanics lab and an electricity lab | B | 3 | 1 | room types |
| M-TE10 | **Two teachers alternate** per specialised room with complementary timetables | B | 4 | 4 | |
| M-TE11 | Those rooms for Technology only | B | 4 | 1 | room types |
| M-TE12 | All technology rooms adjacent | - | 1 | - | building layout |
| M-TE13 | A coordinating teacher | - | 1 | - | organisational |

## التربية المدنية - Civic Education

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-CIV1 | Split the weekly 1.5 h into **one fixed + one fortnightly**, well separated | B | 5 | 5 | the fortnightly mechanism again |
| M-CIV2 | The fortnightly session **fixed for the teacher**, two different classes alternating on it | B | 4 | 5 | elegant: Week A class X, Week B class Y, same slot |
| ⭐ M-CIV3 | Never a lone 1-hour session morning or evening | B | 4 | 1 | same as M-T1 |
| ⭐ M-CIV4 | **Don't always give civic ed teachers the evening** - vary it | B | 4 | 2 | same as M-T3 |
| M-CIV5 | Max 6 h/day; respect training day and trainees' Saturday | B | 4 | 2 | |

## التربية والتفكير الإسلامي - Islamic Education & Thought

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-ISL1 | Optional "Thought" (4th lit) in the **morning**; if evening, **14:00-16:00** | B | 4 | 1 | **same machinery as H15** - see the question at the top |
| M-ISL2 | Separate weekly from fortnightly sessions at the same level | B | 3 | 4 | |
| M-ISL3 | Max 6 h/day; each half-day **at most 3 hours** where possible | B | 4 | 2 | |
| M-ISL4 | Never a single level per teacher - repetition breeds monotony | A | 3 | 4 | |
| M-ISL5 | Min 2, max 3 levels | A | 4 | 4 | |
| M-ISL6 | The 1.5 h system: fortnightly hour across classes, or weekly alternation 1/2 | B | 5 | 5 | |
| M-ISL7 | Final classes spread over more than one teacher | A | 3 | 4 | |

## الإعلامية - Computer Science

| id | rule | tag | POWER | DIFF | notes |
|---|---|---|---|---|---|
| M-IT1 | Pupils in the lab **at most twice the number of computers** | B | 4 | 2 | needs a computer count per lab |
| ⭐ M-IT2 | **Always 2-hour sessions** - never split into two single hours | B | 5 | 3 | needs H9 |
| ⭐ M-IT3 | Never 8 hours in one day for a teacher | B | 3 | 1 | |
| M-IT4 | One class's pupils to **one** teacher | A | 3 | 2 | |
| **M-IT5** | **Build the IT timetable from the start of the year - never by filling gaps** | B | 5 | 3 | see below |

---

# The scheduling-order rule (M-TE8 + M-IT5)

Both Technology and Computer Science say the same thing: **their timetables must
be built FIRST**, never by filling leftover gaps, because they are the ones tied
to scarce specialised rooms.

For a human doing this by hand, that is essential advice - order of work decides
the outcome. **For a constraint solver it is different**: CP-SAT places all
1,682 lessons *simultaneously*, so there is no "first" and no leftover gaps. The
scarce-room subjects are never squeezed into whatever is left, because nothing
is ever left over.

So this rule does not need implementing - **it is already satisfied by the
method**. Worth saying plainly, because it is one of the hardest parts of the
job by hand and it simply stops existing.

*(This may also be what you meant by "3 portions of 3 classes is the starting
point of the schedule and the hardest" - if so, that difficulty disappears. But
tell me if you meant something else.)*

---

# Recommended order of work

**Stage 1 - cheap and strong** (⭐ high power, difficulty 1-2). Roughly a dozen
constraints, most needing no new data:
M-T2, M-T3, M-T5, M-P2, M-P3, M-P4, M-MA3, M-MA4, M-AR15, M-PH5, M-PHI6,
M-EN1, M-EN3, M-TE7, M-IT3, M-SN5, M-HG1.

Resolve the **S8 vs M-T5 conflict** before starting.

**Stage 2 - the block patterns (H9).** Doubles, singles, "2 consecutive + 2
separate". Unlocks M-AR6..M-AR10, M-MA2, M-HG4, M-PHI3, M-IT2, M-AR12. This is
one piece of machinery that pays for many rules at once.

**Stage 3 - fortnightly Week A / Week B.** Unlocks M-P14, M-HG5, M-CIV1,
M-CIV2, M-ISL6, and part of M-AR8. Last year's file already used it: **145
cards**. The aSc format supports it - cards carry a `weeks` mask.

**Stage 4 - split groups.** M-SN4, M-TE3, M-TE4, plus H14 option groups. The
hardest, and where your "1.5h for two groups" really lives.

**Stage 5 - pedagogical distribution [A].** A separate model. Only worth
starting once B is in real use.

---

# Data we do not have yet

Nearly every [A] rule and many [B] rules need these:

- **level / grade per class** (7th, 8th, 9th basic; 1st-4th secondary)
- **stream** (آداب / علوم / تقنية ...) and a **final-year** flag
- **subject nature** (literary / scientific / social) for M-P6
- **continuous-training day** per teacher, and a **trainee** flag
- **pupils per class** - we have a `size` column, currently empty
- **computers per IT lab**
- **room sizes** for M-TE9
- teacher experience / evaluation - **[A] only, and privacy-sensitive**

The first two unlock the most and are the least sensitive. They belong in the
Classes sheet.

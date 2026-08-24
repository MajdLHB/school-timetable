# Privacy - non-negotiable

This project handles **real teachers' names, working hours, days off, and the
personal reasons behind their unavailability** ("collects his children at 3pm",
"teaches at another school"). That is personal data about real people who never
agreed to appear on the internet.

**If this project is ever published, none of that may go with it.**

## The rules

1. **`data/` and `out/` are never committed.** Enforced by `.gitignore`.
   Everything real lives there. Nothing real lives anywhere else.
2. **No real names in code, docs, commit messages, or issues.** When an example
   is needed, use `Prof Alpha`, `T01`, `Test 1A`.
3. **No PDFs, spreadsheets, or `.roz` files committed.** Blanket-blocked by
   extension, because those are how real data escapes by accident.
4. **The `reason` column is the most sensitive field in the whole project.**
   It contains private facts about people's lives. It exists only to make the
   report explainable to you. It must never appear in a published artefact.
5. **Before ever publishing, run the check** (`tools/check_privacy.py`) and read
   its output. If it is not clean, do not publish.

## Before you publish - the checklist

- [ ] `git status` shows no file under `data/` or `out/`
- [ ] `python tools/check_privacy.py` reports CLEAN
- [ ] `git log -p | grep` for a few real teacher surnames returns nothing
- [ ] The repository has never at any point contained real data
      (**git remembers deleted files forever** - if real data was ever
      committed, deleting it later does NOT remove it from history.
      In that case: start a brand new repository, do not try to clean the
      old one.)

## If you open-source this

Publish the **code**, the **rules**, and the **docs**. Those contain no personal
data and are the genuinely useful part for another school.

Never publish `data/`. Another school clones the code and fills in their own
people. That is the whole point - the code is general, the data is yours.

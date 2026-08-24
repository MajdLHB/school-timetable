"""Find rules that are written down but not actually checked anywhere.

RULES.md is the promise. verify.py is the proof. selftest.py is the proof that
the proof works. This script lines all three up and reports the gaps, so a rule
cannot quietly exist only as a sentence in a document.

    python tools/rule_coverage.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(HERE, "docs", "RULES.md")
VERIFY = os.path.join(HERE, "solver", "verify.py")
SOLVE = os.path.join(HERE, "solver", "solve.py")
SELFTEST = os.path.join(HERE, "tools", "selftest.py")


def read(p):
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return ""


def rules_from_doc(text):
    """Pull '| H7 | ... | STATUS |' table rows out of RULES.md."""
    found = {}
    for line in text.splitlines():
        m = re.match(r"\s*\|\s*(H\d+|S\d+)\s*\|(.+)\|\s*([A-Za-z ]*)\s*\|\s*$", line)
        if not m:
            continue
        rid, body, status = m.group(1), m.group(2), m.group(3).strip()
        cells = [c.strip() for c in body.split("|")]
        found[rid] = dict(text=cells[0][:70], status=status or "?")
    return found


def main():
    doc = read(RULES)
    if not doc:
        sys.exit("Cannot read docs/RULES.md")
    rules = rules_from_doc(doc)
    verify_src, solve_src, self_src = read(VERIFY), read(SOLVE), read(SELFTEST)

    hard = {k: v for k, v in rules.items() if k.startswith("H")}
    soft = {k: v for k, v in rules.items() if k.startswith("S")}

    print("")
    print("  %-5s %-46s %-8s %-7s %-6s" % ("rule", "what it says", "in solver",
                                           "checked", "tested"))
    print("  " + "-" * 82)

    gaps = []
    for rid in sorted(hard, key=lambda r: int(r[1:])):
        info = hard[rid]
        in_solve = bool(re.search(r"\b%s\b" % rid, solve_src))
        in_verify = bool(re.search(r'"%s"' % rid, verify_src))
        in_test = bool(re.search(r"\b%s\b" % rid, self_src))
        flag = "" if (in_verify and in_test) else "  <-- GAP"
        if flag:
            gaps.append(rid)
        print("  %-5s %-46s %-8s %-7s %-6s%s"
              % (rid, info["text"][:46],
                 "yes" if in_solve else "NO",
                 "yes" if in_verify else "NO",
                 "yes" if in_test else "NO", flag))

    print("")
    print("  SOFT rules are optimised, not enforced, so they are reported in")
    print("  out/report.md rather than checked. Listed for completeness:")
    for rid in sorted(soft, key=lambda r: int(r[1:])):
        in_report = bool(re.search(r'"?%s\b' % rid, solve_src))
        print("    %-5s %-50s %s" % (rid, soft[rid]["text"][:50],
                                     "in report" if in_report else "NOT REPORTED"))

    print("")
    if gaps:
        print("  %d HARD RULE(S) NOT FULLY COVERED: %s" % (len(gaps), ", ".join(gaps)))
        print("")
        print("  A rule with no check in verify.py is a promise nobody keeps.")
        print("  A rule with no case in selftest.py might be written but not")
        print("  wired up - and on 1,682 lessons you would never see it.")
        return 1
    print("  Every hard rule is checked by verify.py and proven by selftest.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

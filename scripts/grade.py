"""Grade Table 3 answers one at a time in the terminal. Saves after every answer, so you can stop and resume.

For each ungraded row it shows the question, what the right answer is (eval/quality_questions.json), and what the
system said, then asks:  c = correct   w = wrong   rc = refused_correctly   rw = refused_wrongly
                         s = skip for now   q = quit (progress is saved)
Run: python scripts/grade.py           (python scripts/grade.py --redo to change existing grades)
"""
import csv
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "results" / "quality_grading.csv"
KEYS = {"c": "correct", "w": "wrong", "rc": "refused_correctly", "rw": "refused_wrongly"}
redo = "--redo" in sys.argv

rows = list(csv.DictReader(open(PATH)))
cols = list(rows[0].keys())


def save():
    with open(PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(rows)


todo = [r for r in rows if redo or not r["answer_grade"]]
print(f"{len(todo)} to grade ({len(rows)} rows total)\n")
wrap = lambda s: "\n".join(textwrap.fill(line, 110, initial_indent="    ", subsequent_indent="    ")
                           for line in s.splitlines() if line.strip())
for i, r in enumerate(todo, 1):
    print("=" * 112)
    print(f"[{i}/{len(todo)}] {r['request_id']}   setting: {r['setting']}   outcome: {r['outcome']}"
          + (f"   current grade: {r['answer_grade']}" if r["answer_grade"] else ""))
    print(f"\n  QUESTION ({r['qid']}, answerable: {r['answerable']}):\n{wrap(r['question'])}")
    print(f"\n  EXPECTED:\n{wrap(r['expected'])}")
    print(f"\n  SYSTEM SAID:\n{wrap(r['answer'])}\n")
    while True:
        a = input("  grade [c / w / rc / rw / s / q]: ").strip().lower()
        if a in KEYS:
            r["answer_grade"] = KEYS[a]
            save()
            break
        if a == "s":
            break
        if a == "q":
            save(); sys.exit("saved; rerun to continue")
print("\nAll graded. Next: python scripts/build_results.py && python scripts/make_tables.py")

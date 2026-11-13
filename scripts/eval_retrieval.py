"""Check the production retriever against the retrieval test set. No Groq calls.

Expected (overnight experiment, pypdf 6.17): 280 chunks, hit@5 = 25/30,
misses A6, M9, D3, D5, X1.
Run: python scripts/eval_retrieval.py [--k 5]
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from relay.retrieval import Retriever  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=5)
    k = p.parse_args().k
    import pypdf
    r = Retriever()
    qs = json.load(open(ROOT / "eval" / "retrieval_questions.json"))["questions"]
    hits, misses = 0, []
    for q in qs:
        if not q["gold"]:
            continue
        top = [c for c, _ in r.search(q["q"], k=k)]
        found = [any(c.paper == paper and re.search(pat, re.sub(r"\s+", " ", c.text), re.I) for c in top)
                 for paper, pat in q["gold"]]
        ok = all(found) if q["need"] == "all" else any(found)
        hits += ok
        if not ok:
            misses.append(q["id"])
    print(f"pypdf {pypdf.__version__} | {len(r.chunks)} chunks | hit@{k} = {hits}/30 | missed: {', '.join(misses)}")


if __name__ == "__main__":
    main()

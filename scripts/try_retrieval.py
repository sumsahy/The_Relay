"""Play with retrieval. No API calls, so experiment freely.

Run:
  python scripts/try_retrieval.py "how does multi-head attention work"
  python scripts/try_retrieval.py "what is the latency of Moshi" --size 100 --k 3
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relay.retrieval import build  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--size", type=int, default=200, help="words per chunk")
    p.add_argument("--overlap", type=int, default=40)
    p.add_argument("--k", type=int, default=5, help="chunks to return")
    a = p.parse_args()

    r = build(size=a.size, overlap=a.overlap)
    print(f"{len(r.chunks)} chunks in the library (size={a.size}, overlap={a.overlap})\n")
    for chunk, score in r.search(a.query, k=a.k):
        print(f"{chunk.cite}  score={score:.2f}")
        print(f"  {chunk.text[:300]}...\n")


if __name__ == "__main__":
    main()

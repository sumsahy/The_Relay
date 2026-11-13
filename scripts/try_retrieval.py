"""Search the papers from the terminal. No Groq calls.

Run:
  python scripts/try_retrieval.py "what latency does Moshi achieve"
  python scripts/try_retrieval.py "how does multi-head attention work" --k 3
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relay.retrieval import Retriever  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--k", type=int, default=5, help="chunks to return")
    a = p.parse_args()

    r = Retriever()
    t0 = time.perf_counter()
    results = r.search(a.query, k=a.k)
    ms = (time.perf_counter() - t0) * 1000
    print(f"\n{len(r.chunks)} chunks | search took {ms:.0f} ms | "
          f"best embedding similarity {r.best_similarity(a.query):.3f}\n")
    for chunk, score in results:
        print(f"{chunk.cite}  {chunk.section}  (fused={score:.4f})")
        print(f"  {chunk.text[:300]}...\n")


if __name__ == "__main__":
    main()

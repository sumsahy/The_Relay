# Version history and decisions

What the system looks like at each version, what changed, and **who decided and why**.
Git commits hold the code; this file holds the reasoning.

`Decided by`: **Sumukh** = I reasoned and chose. **Claude default** = assistant chose, not yet reviewed by me.
**Overruled** = I changed an assistant suggestion (these feed "How I worked with the assistant").

---

## v0.2: retrieval experiment harness  (2026-11-13, overnight, run by Claude)

**What exists (main pipeline unchanged)**
- `experiments/retrieval_grid.py`: 48-config retrieval grid, no Groq calls, resumable with caches
- `experiments/analyze_retrieval.py`: regenerates every number in the report from the raw CSV
- `eval/retrieval_questions.json`: 36 retrieval test questions written by Claude (not the brief's 15)
- Section-heading detector (needed for paper + section citations)
- Report: `results/retrieval_report.md`

**Decisions in this version**
| Decision | Choice | Decided by | Status |
|---|---|---|---|
| Citation granularity | paper + section | Sumukh | final |
| Scope of overnight experiments | retrieval method + chunking | Sumukh | done |
| Run every combination, report one-change-at-a-time + interactions | full grid | Claude, explained to Sumukh | done |
| Embedding / re-rank models | bge-small-en-v1.5 / ms-marco-MiniLM-L-6 via fastembed (torch install too heavy here) | Claude default | not reviewed |
| Test questions for retrieval | written by Claude, 36 | Claude default | not reviewed |
| Chunking + retrieval | section chunks + hybrid (BM25 + embeddings), no re-ranker | Sumukh | **final** (21:00, 13 Nov) |
| Re-ranker, transcript fix, unanswerable pre-filter | under discussion | Sumukh | **pending** |

---

## v0.1: setup + naive retrieval  (commit 589ccda, 2026-11-13)

**What exists**
- Paper fetcher for the 3 exact arXiv versions
- PDF text extraction (pypdf), page by page
- Chunking: fixed word windows, page-bound
- BM25 search, citations as `[paper p.N]`
- `try_retrieval.py` to query from the terminal (no API calls)
- `.gitignore` keeps `.env` and keys out; Codespaces devcontainer

**Decisions in this version**
| Decision | Choice | Decided by | Status |
|---|---|---|---|
| Language | Python | Claude default | accepted |
| Where we work | GitHub repo + Codespaces | Sumukh | final |
| Repo visibility | Public, key only in Codespaces secret | Sumukh (Claude suggested private) | final |
| Queue tech | In-memory, no Redis | Claude default | accepted |
| PDF library | pypdf | Claude default | accepted |
| Retrieval method | BM25 only | Claude default | **under review** |
| Chunking | 200 words, 40 overlap, page-bound | Claude default | **under review** |
| Citation granularity | paper + page | Claude default | **under review** |
| Deep-dive topics | Claude cut my 6 down to 3 | Claude default | **under review** |
| Header/transcript noise fix | A / B / C / D | Sumukh | pending (see E02) |
| 429 principles | retry failed stage only, backoff + jitter, no retry when daily quota gone, never send unverified | Sumukh | principles agreed, numbers pending real measurements |

**Things I caught / pushed back on**
- Asked whether the 429 policy was actually final. It wasn't: Claude had logged it as "agreed". Corrected to principles only.
- Asked Claude to list every decision it had made without me. It had made 8, including cutting my deep-dive topics.

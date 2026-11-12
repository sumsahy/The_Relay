# Version history and decisions

What the system looks like at each version, what changed, and **who decided and why**.
Git commits hold the code; this file holds the reasoning.

`Decided by`: **Sumukh** = I reasoned and chose. **Claude default** = assistant chose, not yet reviewed by me.
**Overruled** = I changed an assistant suggestion (these feed "How I worked with the assistant").

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

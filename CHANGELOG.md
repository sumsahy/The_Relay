# Version history and decisions

What the system looks like at each version, what changed, and **who decided and why**.
Git commits hold the code; this file holds the reasoning.

`Decided by`: **Divyanshi** = I reasoned and chose. **Claude default** = assistant chose, not yet reviewed by me.
**Overruled** = I changed an assistant suggestion (these feed "How I worked with the assistant").

---

## Grading decisions  (2026-11-14 03:46)
| Decision | Choice | Decided by | Status |
|---|---|---|---|
| Q10 wrongly refused (stitched "..." quotes failed the quote check, E17) | **leave the system as is**, grade `refused_wrongly`, document the flaw | Divyanshi (Claude offered a fix + rerun) | final |

---

## v0.5: stand-in, queue, rate limiter, load scenarios  (2026-11-14, ~03:00)

**What exists**
- `standin/server.py`: Groq-shaped fake service. Limits = our account's (RPM, TPM with prompt+max_tokens reservation,
  RPD refilling 1 per 86.4 s, TPD), Groq-format 429s + headers, latency from `calibration.json`, slowdown per call in
  flight, 1% 500s, 0.5% hangs, 2% slow tail, streams pieces after hidden "thinking" time. Canned but valid answers.
- `standin/calibrate.py`: fits the latency model to every real Groq call we logged.
- `relay/service.py`: admission control (don't admit if expected wait > 3 min, P5), queue, workers, our own
  token-bucket rate limiter (calls wait *before* sending), adopts a changed provider limit from headers,
  drops requests whose person gave up, pre-filter when the queue builds or daily budget is low, refuses at the
  door once the daily limit is hit (P7).
- `scripts/load_test.py`: steady, burst, burst_naive (retry-storm demo), overload, halved, daily. Simulated patience.
- results.csv: the brief's 12 columns + outcome, queue_wait_ms, limiter_wait_ms, retry_ms, work_ms.

**First result (scale 10, same 96-request burst):** our design 49 answered + 6 pre-filtered, 0 rate-limited, 3 retries.
Naive (no limiter/queue, retries on) 29 answered, 67 rate-limited, **145 retries**: the retry-made-it-worse case.

| Decision | Choice | Decided by | Status |
|---|---|---|---|
| Stand-in capacity for load scenarios | 10x account limits (pending Divyanshi's answer) | Claude recommendation | **pending** |
| Patience model | lognormal, median 45 s | Claude default (least certain assumption) | not reviewed |
| Extra results.csv columns | outcome + waiting/working/retrying split | Claude default | not reviewed |
| Abandoned requests | dropped from queue; cancelled mid-work | Claude default | not reviewed |

---

## v0.4: cross-paper completeness, token budgets, retry policy, Table 3 runner  (2026-11-14, ~01:30)

| Decision | Choice | Decided by | Principle | Status |
|---|---|---|---|---|
| Cross-paper answer missing a paper (E13) | **enforce** a targeted second retrieval from that paper + draft only its part, once. If nothing verifies, say so explicitly | Divyanshi (overruled Claude's "message only" lean). Claude added: enforce the *attempt*, not a claim | P1, P7 | final |
| Draft max_tokens | 500 (700 for cross-paper). If a draft is cut off, retry that call once at 1,000: only that request pays | Divyanshi: 500 + "leeway for that request". Mechanism: Claude | P6, P9 | final |
| Log calls that hit max_tokens | yes (`hit_max_tokens` per request and per call) | Divyanshi | | final |
| Retry policy | per-minute 429: wait retry-after + up to 1 s jitter, max 2 retries per step, max 30 s total wait per request. Daily 429: never | Divyanshi (accepted Claude's proposal) | P5, P7 | final |
| Table 3 settings | w200/k5/bm25 (naive), section/k5/hybrid (chosen), section/k3/hybrid (cheaper) | Claude default | | **not reviewed** |
| Table 3 runner | paced by Groq's own token headers, resumable, stops cleanly at the daily limit | Claude default | P6 | not reviewed |

Tests: 13 offline cases pass, incl. both cross-paper outcomes, truncation leeway, retry cap.

---

## v0.3: the pipeline  (2026-11-14, ~00:30)

**What exists**
- `relay/pipeline.py`: classify (code) -> pre-filter (code, under load only) -> retrieve (tool) -> draft (LLM)
  -> verify quotes (code) -> verify support (LLM) -> drop failed claims / redraft once / refuse -> compose
- `relay/results_log.py`: one row per request in `results.csv` with the brief's exact columns, full detail in `results/raw/requests.jsonl`
- `scripts/ask.py`: one real question with progress steps and a timing breakdown
- `tests/test_pipeline_offline.py`: 8 scripted cases incl. 429s, all passing
- Groq client knows the stand-in URL, and tells per-minute from per-day 429s by Groq's error message

**Decisions in this version**
| Decision | Choice | Decided by | Principle | Status |
|---|---|---|---|---|
| Tensions T1-T4 resolutions | as written in PRINCIPLES.md | Divyanshi (confirmed Claude's proposals) | | final |
| Verification | both: code checks the exact quote, then LLM checks support | Divyanshi | P1 | final |
| LLM-verify only when idle | rejected | Divyanshi, Claude withdrew its lean | P8 | final |
| Classify | code (paper-name keywords), no LLM call | Claude default | P9 | **not reviewed**: LLM classify (query rewrite for A6, X1) still to test |
| Cross-paper questions | k=5 shared across named papers (at least 2 each) | Claude default | P1 | not reviewed |
| Failed claims | dropped, answer labelled "reduced"; if none survive, redraft once, then refuse | Claude default | P1, P4 | **not reviewed**: is this P4 "last resort"? |
| Quote check | letters and digits only (survives PDF spacing), quote at least 4 words | Claude default | P1 | not reviewed |
| Model | gpt-oss-20b, reasoning_effort=low, draft max_tokens 900, verify 400 | Claude default | P6 | not reviewed, to measure |
| Splitting steps across models | not done: brief forbids "tricks" to get around limits | Claude | | flagged |
| first_token_ms | time until the *verified* answer starts being delivered (progress messages logged separately) | Claude default | P1, P3 | not reviewed |
| Retry numbers | max_retries=0 until the limits probe | pending | | pending |

---

## Principles set  (2026-11-13, 23:30)
Divyanshi wrote down the user-experience principles **before** deciding the pipeline: see `PRINCIPLES.md` (P1 to P9).
From here on, decisions cite principles.

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
| Citation granularity | paper + section | Divyanshi | final |
| Scope of overnight experiments | retrieval method + chunking | Divyanshi | done |
| Run every combination, report one-change-at-a-time + interactions | full grid | Claude, explained to Divyanshi | done |
| Embedding / re-rank models | bge-small-en-v1.5 / ms-marco-MiniLM-L-6 via fastembed (torch install too heavy here) | Claude default | not reviewed |
| Test questions for retrieval | written by Claude, 36 | Claude default | not reviewed |
| Chunking + retrieval | section chunks + hybrid (BM25 + embeddings), no re-ranker | Divyanshi | **final** (21:00, 13 Nov) |
| Re-ranker | A: never in the live path | Divyanshi | final. Reasoning: section + hybrid already beats every re-ranked config (25 vs best re-ranked 24), and re-ranking adds ~1.4 s per question |
| Transcript fix | D: leave as is, document it. Rank 5 is good enough because embeddings compensate | Divyanshi | final |
| Unanswerable pre-filter (embedding score cutoff) | only when under load or low on budget | Divyanshi | final. Reasoning: normally the LLM can explain that a question isn't answerable from the 3 papers; under load the screen saves valuable tokens. Cutoff value to be set from real data |
| k under load | keep k=5, do NOT drop to 3 | Divyanshi (**overruled** Claude's k=3 suggestion) | final. Reasoning: keep answer quality unless it is heavily compromised; degrade elsewhere instead |

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
| Where we work | GitHub repo + Codespaces | Divyanshi | final |
| Repo visibility | Public, key only in Codespaces secret | Divyanshi (Claude suggested private) | final |
| Queue tech | In-memory, no Redis | Claude default | accepted |
| PDF library | pypdf | Claude default | accepted |
| Retrieval method | BM25 only | Claude default | **under review** |
| Chunking | 200 words, 40 overlap, page-bound | Claude default | **under review** |
| Citation granularity | paper + page | Claude default | **under review** |
| Deep-dive topics | Claude cut my 6 down to 3 | Claude default | **under review** |
| Header/transcript noise fix | A / B / C / D | Divyanshi | pending (see E02) |
| 429 principles | retry failed stage only, backoff + jitter, no retry when daily quota gone, never send unverified | Divyanshi | principles agreed, numbers pending real measurements |

**Things I caught / pushed back on**
- (v0.2) Claude suggested dropping to k=3 under load. I kept k=5 to protect answer quality.
- Asked whether the 429 policy was actually final. It wasn't: Claude had logged it as "agreed". Corrected to principles only.
- Asked Claude to list every decision it had made without me. It had made 8, including cutting my deep-dive topics.

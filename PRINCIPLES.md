# Principles: the experience we want to give the user

Written by Divyanshi, 2026-11-13, before deciding the pipeline. Every design decision in CHANGELOG.md should
point to a principle. If a decision turns out wrong, these say which way to correct it.

**The user:** an engineer asking questions about three research papers.

| # | Principle (Divyanshi's words) | What it means for the system |
|---|---|---|
| P1 | A wrong answer is worse than a slow one. | Never send an unverified or unsupported claim. When in doubt, refuse or wait. |
| P2 | Correctness > availability > speed = cost. | The order we give things up in when we can't have everything. |
| P3 | Show progress steps. | The user sees what is happening ("Searching papers... Checking citations...") instead of a blank wait. |
| P4 | Give a reduced answer, clearly labelled as such. | When we can't deliver the full answer, a labelled partial one beats nothing. |
| P5 | A 3-minute wait is alright. | Queueing is acceptable up to ~3 minutes; beyond that we turn requests away. |
| P6 | Ration the budget. | The daily token budget must last the whole day, not be spent on the first users. |
| P7 | Tell users why; give a time estimate only when we know it. | Honest reasons (busy, quota, couldn't verify). No made-up ETAs. |
| P8 | Same quality of answer under load, just a bit slower. | Load changes *when* you get the answer, not *how good* it is. |
| P9 | Keep looking for clever ways to be faster, if quality isn't affected much. | Speed-ups are welcome as long as they don't trade away P1 or P8. |

## Tensions found while writing these down (to resolve)

- **T1: P4 vs P8.** "Reduced answer" vs "same quality under load". Proposed resolution: a reduced answer is a
  *last resort* (budget nearly gone, or verification impossible), never the normal response to load. Load
  makes answers slower (P8); only scarcity makes them smaller (P4). Even a reduced answer must be verified (P1).
- **T2: the under-load pre-filter vs P8.** Under load, a borderline answerable question could be refused,
  while the same question would be answered when idle. That's a quality difference caused by load.
  Proposed resolution: set the cutoff conservatively, so it only catches clearly off-topic questions.
- **T3: P2 (availability above cost) vs P6 (ration the budget).** Rationing turns some users away now.
  Proposed resolution: rationing *is* availability, spread across the day: it protects the 9pm user.
- **T4: P5 (3 minutes is fine) vs capacity.** Real Groq handles roughly 1.5 to 3 questions a minute, so a 3-minute
  limit means a queue of only about 5 to 9 requests before we must turn people away. Many users also give up
  long before 3 minutes. The load tests should measure how many abandon.

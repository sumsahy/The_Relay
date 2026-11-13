# The Relay: write-up

*Draft for Sumukh's review. Every number comes from `results.csv` via `scripts/make_tables.py`
(output in `results/tables.md`). [YOU] marks the parts only Sumukh can write.*

## 1. What I built and why

A Python pipeline that answers questions about the three papers with **verified, cited claims, or an honest refusal**.
Before choosing the design, I wrote down nine user-experience principles (`PRINCIPLES.md`). The top one: **a wrong answer
is worse than a slow one**, followed by correctness > availability > speed = cost.

For each question the pipeline runs: classify (code: which papers are named) → retrieve (tool: section-based chunks,
hybrid BM25 + embedding search, k=5) → draft (LLM: short claims, each with a source passage and an exact quote, or
"not answerable") → verify quotes (code: is the quote really in that passage?) → verify support (LLM: does the passage
support the claim?) → branch: drop failed claims and label the answer "reduced"; if a named paper ends up with nothing
verified, go back to that paper once; if nothing survives, redraft once, then refuse. Around it sit our own token-bucket
rate limiter, a bounded queue with admission control, and progress messages instead of a blank wait.

**The decision that shaped it most: verify every claim twice (code and LLM) and never show unverified text.** It nearly
doubles the tokens per answer, rules out streaming the draft, and makes token budgets, not request counts, the
constraint on everything else.

## 2. The real service and my stand-in

**Table 1: Limits found in the real service (Groq free tier, openai/gpt-oss-20b)**

| Limit | Value found | How I found it | Confidence |
|---|---|---|---|
| Requests per minute | 30 | Probe: the 31st back-to-back request got a 429, "RPM: Limit 30, Used 30" | high |
| Tokens per minute | 8,000 | `x-ratelimit-limit-tokens` header; 429 body "TPM: Limit 8000"; console | high |
| Requests per day | 1,000 | `x-ratelimit-limit-requests` header; console | high |
| Tokens per day | 200,000 | Console only; never hit directly | medium |
| Requests in flight at once | no limit hit at 10 | Probe: 10 simultaneous requests all succeeded (399 to 1,458 ms) | low (only tested 10) |
| What it returns when a limit is hit | HTTP 429 + `retry-after` + a body naming the limit, e.g. "TPM: Limit 8000, Used 5257, **Requested 3496**. Please try again in 5.6s". It reserves **prompt + max_tokens**, not tokens actually used | 429 bodies from real runs (E12, E13) | high |
| Time until it recovers | Per-minute: continuous refill, `retry-after` 2 to 6 s, probe recovered after 2.9 s. Per-day requests refill gradually, one every 86.4 s, not at midnight | Probe; `x-ratelimit-reset-requests` = 86.4 s x requests used | high / medium |

**The stand-in** (`standin/server.py`) has Groq's endpoint, stream format, limits, 429 bodies and headers, including the
prompt + max_tokens reservation and gradual refills. Its latency is fitted (`standin/calibrate.py`) to **114 real Groq
calls**: first token p50 499 ms, p95 681 ms, plus 39 ms per 1K prompt tokens, about 1,370 tokens/s streaming, and
**+12.8% latency per extra call in flight** (from the 10-at-once probe). It also injects 1% server errors, 0.5% hangs
and 2% slow outliers. Load scenarios run it at **10x my account's limits** so each scenario has enough requests for
percentiles; that is still below Groq's paid tier (250K TPM, 1K RPM).

**Where it differs most:** (1) the in-flight slowdown is extrapolated from one probe of 10 tiny requests; (2) real Groq's
latency depends on other customers' traffic, which I can't see; (3) its answers are canned, so it says nothing about
answer quality: all quality numbers come from real Groq only.

## 3. Results

Real runs: `quality` (Table 3 questions, paced under the free-tier limits). All other rows: stand-in at 10x limits.
Percentiles are nearest-rank; with 27 to 121 requests per row, **p99 is close to the maximum**. First token = when the
*verified* answer starts reaching the person (we never stream unverified text), so it equals total time; the first
progress message appears within ~20 ms. Time includes queueing.

**Table 2a: Latency**

| Scenario | Real or stand-in | Requests sent | Duration (s) | Offered rate (per min) | First token p50 / p95 / p99 (ms) | Total time p50 / p95 / p99 (ms) |
|---|---|---|---|---|---|---|
| quality (steady, paced) | real | 27 | 603 | 2.7 | 1036 / 5425 / 9110 | 1036 / 5425 / 9110 |
| steady | stand-in | 32 | 174 | 11.1 | 1308 / 2347 / 2504 | 1308 / 2347 / 2504 |
| burst | stand-in | 96 | 131 | 104.5 | 13343 / 73154 / 76351 | 13343 / 73154 / 76351 |
| burst, naive (no limiter/queue) | stand-in | 96 | 17 | 577.6 | 4124 / 12429 / 12720 | 4124 / 12429 / 12720 |
| sustained overload | stand-in | 121 | 218 | 40.8 | 2443 / 45315 / 50989 | 2443 / 45315 / 50989 |
| per-minute limit halved | stand-in | 29 | 169 | 10.4 | 1354 / 3136 / 33450 | 1354 / 3136 / 33450 |
| daily budget exhausted | stand-in | 27 | 177 | 9.2 | 1212 / 1681 / 2148 | 1212 / 1681 / 2148 |

**Table 2b: Outcomes**

| Scenario | Succeeded % | Rate-limited % | Timed out or given up % | Retries per request | Peak queue length | Tokens per answer | Cost per 1,000 answers |
|---|---|---|---|---|---|---|---|
| quality (real) | 100.0 | 0.0 | 0.0 | 0.11 | 0 | 3133 | $0.44 (free tier: $0) |
| steady | 100.0 | 0.0 | 0.0 | 0.00 | 0 | 3134 | $0.29 |
| burst | 60.4 | 0.0 | 39.6 | 0.02 | 54 | 3278 | $0.33 |
| burst, naive | 33.3 | 66.7 | 0.0 | 1.46 | 1 | 3126 | $0.28 |
| sustained overload | 88.4 | 0.0 | 11.6 | 0.00 | 18 | 3301 | $0.32 |
| per-minute limit halved | 100.0 | 0.0 | 0.0 | 0.10 | 0 | 3219 | $0.29 |
| daily budget exhausted | 74.1 | 25.9 | 0.0 | 0.00 | 0 | 3129 | $0.29 |

Cost: Groq's paid price for gpt-oss-20b ($0.075 / $0.30 per 1M input / output tokens); the free tier costs $0.
"Sustained overload" was ~1.6x real capacity, not the 2.5x I designed: I sized it assuming 5K tokens per question,
and real questions used ~3.2K.

**Answer quality** (real Groq, my 15 questions, chosen setting): 53.3% correct and cited, 13.3% wrong, 26.7% correctly
refused, 13.3% wrongly refused. **Tokens per answer: 3,270** on average.

**A number I couldn't have guessed:** in the burst, 38 people gave up. **27 left while still queued and cost nothing;
the 11 who left mid-work wasted 17,030 tokens**, 9% of everything the burst spent, on answers nobody read.

## 4. Where the time goes

Slowest real request: `section-300-k5-Q05` ("how does quality filtering work?"), **9,110 ms = 1,797 ms working +
7,312 ms waiting to retry + 0 ms queued.** The draft call got a per-minute 429 ("Used 5796, Requested 2488, try again in
2.13s"), was retried after Groq's `retry-after` (3 s + jitter), and the verify call then got another ("Used 7893,
Requested 511"). **All of the delay was before the first token**, because nothing is shown until verification passes.
How I know: every call's timing, status and headers are in `results/raw/requests.jsonl`;
`python scripts/show_last.py k5-Q05` prints the split. The cause: my Table 3 runner paced per *question*, not per
*call*, so a question needing two drafts overran the token bucket.

## 5. When a limit is hit

**Per-minute limit:** our own limiter mirrors Groq's token buckets (including the prompt + max_tokens reservation), so
calls **wait before sending** instead of being sent and rejected. Who is **delayed**: everyone in the queue, in arrival
order. Who is **dropped**: anyone we expect to wait over ~3 minutes is refused at the door with an honest "at capacity,
try again in a few minutes", and anyone who gives up is removed before spending tokens. Who gets a **weaker answer**:
under load, a conservative pre-filter refuses clearly off-topic questions without spending a call; everyone else gets
the same answer quality, only slower (P8). When Groq changed the limit without telling us (the "halved" scenario), the
limiter read the new limit from the response headers and adapted: 29 of 29 answered.

**Per-day limit:** never retried (the daily limit refills one request every 86.4 s, so retrying is pointless). The
first daily 429 flips the service into "budget gone": every queued and new request gets the daily message immediately.
When the daily budget runs low, the pre-filter turns on to ration what's left (P6). In the "daily" scenario, 20
questions were answered, then 6 people got the daily message at the door and 1 request failed mid-answer.

## Retrieval: quality versus cost

| Setting (piece size, pieces fetched, re-rank) | Questions asked | Correct and cited % | Wrong % | Correctly refused % | Tokens per answer | First token p50 / p95 (ms) | Total time p50 / p95 (ms) |
|---|---|---|---|---|---|---|---|
| Section chunks (cap 300 words), k=5, hybrid, no re-rank: **chosen**, all questions | 15 | 53.3 | 13.3 | 26.7 | 3270 | 1156 / 9110 | 1156 / 9110 |
| Same, on the 6 shared questions | 6 | 33.3 | 33.3 | 33.3 | 2775 | 592 / 1204 | 592 / 1204 |
| 200-word chunks, k=5, BM25, no re-rank | 6 | 66.7 | 0.0 | 33.3 | 2061 | 593 / 1864 | 593 / 1864 |
| Section chunks, k=3, hybrid, no re-rank | 6 | 33.3 | 16.7 | 50.0 | 1926 | 579 / 1277 | 579 / 1277 |

(Wrongly refused: chosen 13.3% on all 15 / 16.7% on the shared 6; 200-word 0.0%; k=3 16.7%.)

I chose section chunks + hybrid from a no-quota retrieval experiment first (48 configurations, 30 test questions;
`results/retrieval_report.md`): it put the right passage in the top 5 for 25 of 30 questions vs 20 for 200-word BM25
(24 of 30 after the PDF library change in E15),
and section chunks never mislabel the section in a citation (24% of 200-word chunks span two sections). On real
answers, the naive setting scored higher on the 6 shared questions, but the gap is **two questions**, and both trace
to the same quote-check flaw (section 8), not to retrieval. I didn't change my choice on that evidence; I'd test it
on more questions first. **When the limit is close, I keep k=5** rather than drop to k=3: k=3 saves ~30% tokens, but in the retrieval
experiment it found the passage for 20 to 21 of 30 questions vs 25 to 26 at k=5 (on the 6 real answers the
difference didn't show). I save tokens elsewhere instead: admission control and the pre-filter.

## How this library will mislead a naive retriever

1. **Speaker labels in appendix transcripts.** "What latency does Moshi achieve?": with 100- or 200-word chunks, BM25
   ranked a *Three Musketeers* chat transcript first, because "MOSHI:" opens every line, while the answer in the
   abstract came 5th or lower. Stripping the running page headers didn't fix it; bigger (section) chunks did.
2. **Vocabulary mismatch.** "How does the Transformer cope with relationships between words that are far apart?" was
   missed by all 48 configurations: the paper says "long-range dependencies" and "path length".
3. **One paper hogs the results.** For the brief's own cross-paper question, the top 5 were all Dynamic Chunking; the
   Transformer evidence first appeared at rank 20. Fix built: share k across the named papers, and go back to a paper
   that ends up with no verified claim.

## 6. Retries

Policy: retry only the failed step (earlier steps are kept); on a per-minute 429, wait exactly Groq's `retry-after`
plus up to 1 s of random jitter; at most 2 retries per step and 30 s of waiting per request, then an honest "busy"
message; never retry a daily-limit 429. Timeouts and 5xx are retried with exponential backoff and jitter.

**When retrying made it worse:** the same 96-request burst, without our limiter and queue (everyone sent at once,
retries on), produced **140 retries and 64 rate-limited failures, and answered only 32**. Everyone got the same
`retry-after`, so the retries arrived together and hit the limit again. With the limiter and queue: **2 retries, 0
rate-limited, 52 answered**. Retries are a backstop; pacing is the fix.

## 7. What the person sees

At 3pm the daily budget is gone. A person who asks a question sees, immediately, with no queueing and no retrying:

> *"Today's model usage limit has been reached, so I can't answer right now. Nothing unverified was sent. Please try
> again later."*

No time estimate is given: the daily budget refills gradually (about one request every 86.4 s), so I can't promise
when *their* question will fit (P7). Anyone already mid-answer when the limit hits gets the same message rather than a
half-checked answer.

## 8. What I'm unsure about, what I left out, what I learned

**Least certain assumption: how strict the quote check should be.** It requires each quote to appear verbatim as one
continuous string. On real runs, **every** failure of my chosen setting (Q06 twice, Q10) came from the model shortening
a quote with "…": the facts were right, the check rejected them. If the check is too literal, the system refuses
correct answers (Q10) and the settings comparison measures quoting style instead of retrieval. If it's too loose, P1
breaks. I decided not to change it mid-evaluation, so the numbers above include the flaw.
Also uncertain: people's patience (I assumed a median of 45 s); the burst results depend on it.

**Deliberately not built:** (1) a re-ranker: it added ~1.4 s per question on CPU and no measured gain over hybrid;
(2) an LLM query-rewrite step: it might fix vocabulary mismatch, but costs a call and ~0.6 s for every question.
Also Redis: an in-memory queue was enough to measure what mattered.

**One thing that was new to me:** [YOU: in your own words. One option is the token bucket: Groq's limits aren't a
counter that resets each minute, but a bucket that refills continuously, and it reserves the *maximum* a call could
use, so asking for 900 max_tokens costs capacity even when the answer is 80 tokens.]

## Your feedback on Vaani

[YOU: final wording. Notes so far: what stood out: using emotion; real value of local languages and Hinglish for a
market like India; in my own teams, AI note-takers fail when meetings switch into Hinglish, which happens often
internally; getting this right could reduce the stigma people have against talking to AI.
Still needed: what confused you, and one thing you'd change.]

## How I worked with the assistant

Full history: `conversation/` (my planning chat with ChatGPT, then the Claude conversation that built this). [YOU: add
the Claude conversation export or share link.]

**Three prompts that mattered most:** [YOU: pick and edit. Suggestions:]
1. *"Let's first get our principles right, what kind of experience do we want to give our user"*: before choosing the
   pipeline. Every later decision cites a principle, and they settled verification, k under load and rationing.
2. *"Have we already taken any kind of decision?"*: made the assistant list the 8 decisions it had made silently;
   I reviewed each, and several changed.
3. *"Have you taken that into consideration after I said we are doing it tonight?"*: caught that its plan still
   assumed a second day of quota; the evaluation was redesigned to fit one day.

**One thing it got wrong that I caught:** [YOU. Suggestion: it planned an evaluation needing two days of Groq quota
after I'd said we were finishing in one night. I caught it from its own "you'll hit the daily limit, resume tomorrow"
instructions. Other real cases in `EXPERIMENTS.md`: E15 (a pinned library version broke PDF parsing on my Python
version), E16 (the load test silently ran without its stand-in).]

**One decision where I overruled it:** under load it proposed dropping from 5 retrieved passages to 3 to save tokens.
I kept 5: answer quality shouldn't change with load (P8). The retrieval experiment supports it (k=3 found the
right passage for 20 to 21 of 30 questions vs 25 to 26 at k=5). Also: it suggested only
*telling* the user when a compared paper was missing; I required a second, targeted retrieval instead.

**What's distinctly mine:** [YOU: e.g. the principles and their ranking; the 15 questions; the grading rules; every
final decision in `CHANGELOG.md`, with reasoning.] Grading rules I applied: true but incomplete answers count as correct
if the citation is right, unless a part the question explicitly asks for is missing (Q06); Q12's refusal counts as
correct because Moshi has nothing on boundary learning or compression; refusals of unanswerable questions are
"correctly refused", never "correct".

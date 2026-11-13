# The Relay: write-up

Every number below is computed from `results.csv` by `scripts/make_tables.py` (output: `results/tables.md`).
Experiments: `EXPERIMENTS.md`. Decisions and who made them: `CHANGELOG.md`. Principles: `PRINCIPLES.md`.

## 1. What I built and why

Before designing anything I wrote down nine principles for the user's experience (`PRINCIPLES.md`). The top two:
**a wrong answer is worse than a slow one**, and correctness > availability > speed = cost.

The pipeline (Python): classify (code: which papers are named) → retrieve (tool: section-based chunks, hybrid BM25 +
embedding search, k=5) → draft (LLM: short claims, each with a source passage and an exact quote, or "not
answerable") → verify quotes (code) → verify support (LLM) → branch: drop failed claims and label the answer
"reduced"; go back once to a named paper that has no verified claim; if nothing survives, redraft once, then refuse.
Around it: our own token-bucket rate limiter, a bounded queue with admission control, and progress messages.

**The decision that shaped it most: verify every claim twice and never show unverified text.** It roughly doubles the
tokens per answer, rules out streaming the draft, and makes tokens, not requests, the binding constraint.

## 2. The real service and my stand-in

**Table 1: Limits found in the real service (Groq free tier, openai/gpt-oss-20b)**

| Limit | Value found | How I found it | Confidence |
|---|---|---|---|
| Requests per minute | 30 | Probe: 31st back-to-back request got a 429, "RPM: Limit 30, Used 30" | high |
| Tokens per minute | 8,000 | `x-ratelimit-limit-tokens` header; 429 body "TPM: Limit 8000"; console | high |
| Requests per day | 1,000 | `x-ratelimit-limit-requests` header; console | high |
| Tokens per day | 200,000 | Console only; never hit directly | medium |
| Requests in flight at once | no limit hit at 10 | Probe: 10 simultaneous requests all succeeded (399 to 1,458 ms) | low |
| What it returns when a limit is hit | HTTP 429 + `retry-after` + a body naming the limit ("TPM: Limit 8000, Used 5257, Requested 3496. Please try again in 5.6s"). It reserves prompt + **max_tokens**, not tokens used | 429 bodies from real runs | high |
| Time until it recovers | Per-minute: continuous refill, retry-after 2 to 6 s (probe recovered in 2.9 s). Daily requests: one back every 86.4 s, not at midnight | Probe; `x-ratelimit-reset-requests` | high / medium |

**The stand-in** (`standin/server.py`) copies Groq's endpoint, streaming, limits, 429 bodies and headers, including
the max_tokens reservation and gradual refills. Its latency is fitted to **114 real calls** (first token p50 499 ms,
p95 681 ms; +39 ms per 1K prompt tokens; **+12.8% per extra call in flight**), with 1% errors, 0.5% hangs and 2% slow
outliers. Load runs use **10x my account's limits** so each scenario has enough requests for percentiles; that is
still below Groq's paid tier (250K TPM). **Where it differs most:** the in-flight slowdown is extrapolated from one
probe of 10 tiny requests; real latency depends on other customers' traffic; its answers are canned, so all answer
quality numbers come from real Groq.

## 3. Results

`quality` is real (my questions, paced under the free tier); everything else is the stand-in at 10x. Nearest-rank
percentiles; with 27 to 121 requests per row, p99 is close to the maximum. First token = when the *verified* answer
starts reaching the person, so it equals total time (a progress message appears within ~20 ms). Times include queueing.

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

Cost uses Groq's paid price for gpt-oss-20b ($0.075 / $0.30 per 1M input / output tokens). "Overload" turned out to be
~1.6x real capacity, not the 2.5x I designed, because questions used ~3.2K tokens, not the 5K I sized it for.

**Answer quality** (real, my 15 questions, chosen setting): 53.3% correct and cited, 13.3% wrong, 26.7% correctly
refused, 13.3% wrongly refused; **3,270 tokens per answer**. **A number I couldn't have guessed:** of the 38 people
who gave up during the burst, **27 left while still queued and cost nothing; the 11 who left mid-answer wasted 17,030
tokens**, 9% of the burst's spend, on answers nobody read.

## 4. Where the time goes

Slowest real request, `section-300-k5-Q05`: **9,110 ms = 1,797 ms working + 7,312 ms waiting to retry + 0 ms queued**,
all **before the first token** (nothing is shown until verification passes). The draft hit a per-minute 429 ("Used
5796, Requested 2488"), waited Groq's `retry-after` of 3 s plus jitter, then the verify call hit another ("Used 7893,
Requested 511"). I know this from the per-call timings, statuses and headers in `results/raw/requests.jsonl`
(`python scripts/show_last.py k5-Q05`). Cause: my evaluation runner paced per question, not per call.

## 5. When a limit is hit

**Per-minute:** our limiter mirrors Groq's buckets, so calls **wait before sending** instead of being rejected.
*Delayed:* everyone queued, in arrival order. *Dropped:* anyone we expect to wait over ~3 minutes (refused at the door,
honestly), and anyone who gives up (removed before spending tokens). *Weaker answer:* under load, a conservative
pre-filter refuses clearly off-topic questions without a model call; everyone else gets the same quality, only slower.
When the limit was halved without notice, the limiter read the new limit from Groq's headers: 29 of 29 answered.
**Per-day:** never retried. The first daily 429 switches the service to "budget gone" and every waiting or new request
gets the daily message at once; as the budget runs low, the pre-filter turns on to ration it. In that scenario 20 were
answered, 6 were told at the door, 1 failed mid-answer.

## Retrieval: quality versus cost

| Setting (piece size, pieces fetched, re-rank) | Questions asked | Correct and cited % | Wrong % | Correctly refused % | Tokens per answer | First token p50 / p95 (ms) | Total time p50 / p95 (ms) |
|---|---|---|---|---|---|---|---|
| Sections (cap 300 words), k=5, hybrid, no re-rank: **chosen**, all questions | 15 | 53.3 | 13.3 | 26.7 | 3270 | 1156 / 9110 | 1156 / 9110 |
| Same, on the 6 shared questions | 6 | 33.3 | 33.3 | 33.3 | 2775 | 592 / 1204 | 592 / 1204 |
| 200 words, k=5, BM25, no re-rank | 6 | 66.7 | 0.0 | 33.3 | 2061 | 593 / 1864 | 593 / 1864 |
| Sections (cap 300 words), k=3, hybrid, no re-rank | 6 | 33.3 | 16.7 | 50.0 | 1926 | 579 / 1277 | 579 / 1277 |

I chose the setting from a no-quota retrieval experiment (48 configurations, 30 test questions): it found the right
passage in the top 5 for 25 of 30 questions vs 20 for 200-word BM25, and section chunks never mislabel the section in a
citation (24% of 200-word chunks span two). On real answers the naive setting scored higher on the 6 shared questions,
but the gap is **two questions, and both trace to the quote-check flaw in section 8**, not to retrieval. **Near the
limit I keep k=5:** k=3 saves ~30% tokens but found the passage for only 20 to 21 of 30 in the experiment; I save
tokens through admission and the pre-filter instead.

## How this library will mislead a naive retriever

1. **Speaker labels in transcripts.** "What latency does Moshi achieve?": BM25 on 200-word chunks ranks a *Three
   Musketeers* chat transcript first, because "MOSHI:" opens every line; the answer in the abstract comes 5th or lower.
2. **Vocabulary mismatch.** "How does the Transformer cope with relationships between words that are far apart?":
   missed by all 48 configurations; the paper says "long-range dependencies" and "path length".
3. **One paper hogs the results.** The brief's own cross-paper question returns five Dynamic Chunking passages; the
   Transformer evidence first appears at rank 20. Fix built: share k across named papers.

## 6. Retries

Retry only the failed step; on a per-minute 429 wait Groq's `retry-after` plus up to 1 s of jitter; at most 2 retries
per step and 30 s per request, then an honest "busy"; never retry a daily-limit 429. **Retrying made it worse** in the
same 96-request burst without our limiter and queue: **140 retries, 64 rate-limited, only 32 answered**, because
everyone got the same `retry-after` and came back together. With the limiter and queue: 2 retries, 0 rate-limited,
52 answered. Retries are a backstop; pacing is the fix.

## 7. What the person sees

At 3pm the budget is gone. The person gets, immediately, with no queueing or retrying: *"Today's model usage limit has
been reached, so I can't answer right now. Nothing unverified was sent. Please try again later."* No time estimate:
the daily budget comes back gradually, so I can't honestly promise when their question will fit.

## 8. What I'm unsure about, what I left out, what I learned

**Least certain assumption: how strict the quote check should be.** It requires each quote to appear verbatim as one
string. **Every** failure of my chosen setting (Q06 twice, Q10) came from the model shortening a quote with "…": the
facts were right, the check rejected them. Too literal, and the system refuses correct answers and the settings
comparison measures quoting style; too loose, and wrong answers get through. I chose not to change it mid-evaluation,
so the numbers include the flaw. Also assumed: people's patience (median 45 s); the burst results depend on it.

**Deliberately not built:** a re-ranker (+1.4 s per question on CPU, no measured gain over hybrid); an LLM step that
rewrites questions into the papers' vocabulary (might fix mismatch, but costs a model call on every question).

**What I learned:** having a north-star vision for the product puts things in perspective, especially when trade-offs
get confusing. Laying out principles helps more than it constrains, as one might think. Here, "same answer quality
under load, just slower" settled two decisions I was stuck on: keeping 5 retrieved passages under load, and rejecting
a deeper check that would only run when the system was idle. Without the principle, both were coin flips.

## Your feedback on Vaani

What stood out: using emotion, and the real value of local languages for a market like India, Hinglish especially.
In my own teams I've seen AI note-takers fail when a meeting switches into Hinglish, which happens often, especially
internally. Getting this right could also reduce the stigma that makes many people dismiss talking to AI at all.
[YOU: what confused you, and one thing you would change.]

## How I worked with the assistant

Full, unedited history in `conversation/`: my planning chat with ChatGPT, then the Claude conversation that built this.

**The three prompts that mattered most.** (1) *"Let's first get our principles right, what kind of experience do we
want to give our user"*, before choosing the pipeline: every later decision cites a principle. (2) *"Have we already
taken any kind of decision?"*: the assistant listed 8 decisions it had made silently, and I reviewed each.
(3) *"Have you taken that into consideration after I said we are doing it tonight?"*: see below.

**What it got wrong, and how I caught it.** After I said we'd finish in one night, it still gave me an evaluation plan
that used more than a day's Groq quota and told me to "resume tomorrow". I caught it from its own instructions and
didn't run them; the evaluation was redesigned to fit one day's budget. (Other real errors are logged in
`EXPERIMENTS.md`, e.g. E16: its load test kept running when the stand-in failed to start, logging 100% errors.)

**Where I overruled it.** Under load it proposed dropping from 5 retrieved passages to 3 to save tokens; I kept 5,
because answer quality shouldn't change with load. For cross-paper questions with a missing side, it proposed only
telling the user; I required a second, targeted retrieval, because an incomplete answer to an explicit question isn't
good enough.

**What's distinctly mine:** the principles, and the habit of experimenting before building: measure, then decide,
instead of vibe coding. Also the 15 questions, the grading rules (true but incomplete counts as correct if the citation
is right, unless a part the question explicitly asks for is missing; refusals are only ever "correctly" or "wrongly"
refused), and every final call in `CHANGELOG.md`.

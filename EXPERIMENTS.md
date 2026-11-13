# Experiment log

Every experiment we run, in order, including the ones that failed or changed nothing.
Raw outputs live in `results/raw/` and are never overwritten or deleted.

**Template**
```
## EXX: short title  (date)
- Question: what we wanted to find out
- Hypothesis: what I expected, and why
- Setup: exact command, settings, commit hash
- Result: what actually happened (numbers, raw file path)
- Surprise: anything I didn't expect
- Conclusion / decision: what changes because of this (link to CHANGELOG entry)
```

---

## E01: BM25 sanity check on toy data  (2026-11-13)
- Question: does the retrieval code rank chunks at all?
- Hypothesis: a "moshi latency" query should rank the Moshi chunk first.
- Setup: two fake pages, every query word in exactly half the chunks. Run by Claude in its workspace.
- Result: all scores 0.0, ranking meaningless.
- Surprise: not a bug. BM25 gives zero weight to words that appear in half or more of the chunks.
  Rerun with skewed data (moshi on 1 of 6 pages): Moshi chunk ranked first, score 5.92.
- Conclusion: code is correct. Learned that common words carry almost no weight in BM25.

## E02: first real retrieval query  (2026-11-13)
- Question: does BM25 find the right passage for a simple factual question?
- Hypothesis: (not written down before running; do this next time)
- Setup: `python scripts/try_retrieval.py "what latency does Moshi achieve"`, size=200, overlap=40, k=5, commit 589ccda. 413 chunks.
- Result: top 5 = moshi p.63 (Three Musketeers transcript, 8.21), p.24 (MUSHRA audio eval, 8.19),
  p.62 (synthetic transcripts, 7.80), p.63 (Steinbeck transcript, 7.31), p.1 (title + authors, 6.85).
  The actual answer is in the abstract on p.1 and only appears 5th, with the wrong slice of the page.
- Surprise: the appendix chat transcripts beat the abstract for a factual question.
- Diagnosis: (1) running page header "Moshi: a speech-text foundation model..." puts "moshi" in every chunk,
  (2) "MOSHI:" speaker labels in appendix transcripts inflate term frequency, drowning out "latency".
- Conclusion: pending. Fix options A/B/C/D under discussion. Candidate example for
  "How this library misleads a naive retriever".

---

# Overnight retrieval experiments (2026-11-13)

Scope set by Sumukh: compare retrieval methods (BM25 / embeddings / re-ranking) and chunking options.
Citation format chosen by Sumukh: paper + section.
**Hypotheses below were written and committed BEFORE any of these runs** (check the commit timestamps).

Shared setup
- Test set: `eval/retrieval_questions.json`, 36 questions written by Claude (30 answerable, 6 unanswerable).
  Retrieval-only. Not the brief's 15 answer-quality questions, which Sumukh writes himself.
- "Hit@k" = a chunk containing the gold evidence (regex, checked to exist in the PDF text) is in the top k.
- No Groq calls. Measures whether the right passage *reaches* the model, not answer quality.
- Embedding model: BAAI/bge-small-en-v1.5 (local, ONNX via fastembed). Re-ranker: ms-marco-MiniLM-L-6-v2 cross-encoder (local).
  Neither uses Groq quota.

## E03: Does stripping running headers fix the Moshi problem?
- Hypothesis: yes for BM25 on header-trap questions (M1, M4, M5, M8): the paper title on every page is what
  inflates "moshi". Little effect on embeddings, which care less about one repeated word.
  Transcript question M11 should be unaffected.

## E04: Chunk size (100 / 200 / 400 words, page-bound) and section-based chunks
- Hypothesis: at the same k, bigger chunks find the answer more often (more text per slot) but cost
  proportionally more tokens. 200 words is the best hit-rate-per-token. Section chunks will be uneven and
  some sections are huge, so they need a size cap.

## E05: BM25 vs embeddings vs hybrid
- Hypothesis: BM25 wins on exact questions (numbers, names), embeddings win on paraphrase questions,
  hybrid (merged rankings) is best overall. Embeddings add noticeable latency per query.

## E06: Re-ranking on/off
- Hypothesis: re-ranking helps most at small k (k=3), where order matters most. At k=8 it matters less.
  Costs tens of ms per query on CPU.

## E07: k = 3 / 5 / 8
- Hypothesis: hit rate rises with k with diminishing returns; tokens rise linearly.

## E08: Can retrieval scores alone flag an unanswerable question?
- Hypothesis: only weakly. U6 ("latency of the Transformer in spoken dialogue") shares many words with
  real passages, so a score threshold will misfire. The refuse/answer branch will need the LLM.

## E09: Section detection for paper + section citations
- Hypothesis: a numbered-heading pattern ("3.2.1 Scaled Dot-Product Attention") recovers most headings in
  all three papers, but there will be false positives from table/figure text, and Moshi's appendix uses
  a different style ("Appendix A.").

## Results for E03 to E09 (run after the hypotheses above were committed)

Full report: `results/retrieval_report.md`. Tables: `results/retrieval_tables.md`. Raw: `results/raw/retrieval_grid_per_question.csv`.

- **E03 header stripping:** WRONG. No measurable effect (one question moved 5 -> 6). The Moshi latency miss is caused by
  appendix transcripts, and it is fixed by bigger chunks (400 words / section: rank 2 to 3), not by cleaning.
- **E04 chunk size:** PARTLY. 100 words clearly worse (BM25 14/30 vs 21/30). 400 no better than 200 at +80% tokens.
  Section chunks best (hybrid 25 to 26/30) at +40% tokens vs 200 words. 24% of 200-word chunks span two sections.
- **E05 method:** RIGHT. BM25 13/15 exact, 3/8 paraphrase. Embeddings 11/15 exact, 6/8 paraphrase.
  Switching BM25 -> embeddings: +7 / -6 questions. Hybrid hit@3 13 -> 21.
- **E06 re-ranking:** PARTLY. Helps (best hit@8 = 27), but costs ~1.4 s/question on 2 vCPU (68 ms x 20 pairs), not tens of ms.
- **E07 k:** RIGHT. 5 -> 8 = +60% tokens for +2 questions.
- **E08 unanswerable:** PARTLY WRONG. Embedding top-1 score separates 94% with one threshold (6 unanswerable only: overfit risk).
- **E09 section detection:** RIGHT after fixes: 3 false positives (numbered list items) and 1 miss (hyphen in "H-Net") fixed.
- **Surprise:** A6 ("relationships between words that are far apart") missed by all 48 configs: vocabulary mismatch.
- **Surprise:** cross-paper question X1: one paper fills the top 5; the second paper's evidence first appears at rank 20.
- **Measurement errors caught before publishing:** first report draft said the Moshi latency question fails in *all*
  BM25 configs (false: bigger chunks find it) and quoted section+hybrid as 26 (it is 25 clean / 26 raw). Both corrected
  after re-checking the raw CSV.
- **Conclusion:** no code change to the main pipeline yet. Decisions are Sumukh's (see end of the report).

## E10: first real Groq call + first Codespace run  (2026-11-13, run by Sumukh)
- Question: does the key work, and what do the response and rate-limit headers actually look like?
- Setup: `python scripts/hello_groq.py` (openai/gpt-oss-20b, max_tokens=200, prompt "Reply with exactly: hello relay").
- Result: ok, TTFT 601 ms, total 607 ms, prompt 77 tokens, completion **44** tokens for a 2-word answer.
  Headers: limit-requests 1000, remaining 999, reset-requests **1m26.4s**; limit-tokens 8000, remaining-tokens **7723**, reset-tokens 2.077s.
- Surprises / what they tell us:
  1. **44 completion tokens for "hello relay"**: about 40 are hidden reasoning tokens. gpt-oss "thinks" before answering,
     and those tokens are billed against our token limits. They also explain why TTFT (601 ms) is almost the whole call:
     the first *visible* token only arrives after the thinking.
  2. *(confirmed in E13)* **7723 remaining = 8000 - 277**, and 277 = 77 prompt + **200 max_tokens**, not 77 + 44 used.
     Hypothesis: Groq reserves prompt + max_tokens against the per-minute token limit up front. If true, a generous
     max_tokens costs us TPM capacity even when unused. Needs confirming with a second call at a different max_tokens.
  3. *(confirmed in E13)* **reset-requests 1m26.4s = 86,400 s / 1,000.** The daily request limit seems to refill gradually (one request
     every 86.4 s), not all at once at midnight. If true, "daily budget exhausted" recovers slowly, which changes how
     the system should behave in that scenario. Needs confirming.
  4. **reset-tokens 2.077s**: per-minute tokens also refill continuously (a "token bucket"), not in fixed minute windows.
- Also: the Codespace built **286 chunks, not 280**, with a different embedding cache file. Cause: pypdf 7.0.1 in the
  Codespace vs 6.17.0 where the experiments ran: different text extraction. The Moshi latency top 5 also differed.
- Conclusion: pinned `pypdf==6.17.0` so code and experiments use identical text. Added `scripts/eval_retrieval.py`
  to confirm the Codespace reproduces 25/30. Hypotheses 2 and 3 to be tested in the limits probe (Table 1).

## E11: Groq console limits for this account  (2026-11-13, screenshot by Sumukh)
- Raw: `results/raw/groq_console_limits_2026-11-13.png`
- gpt-oss-120b / gpt-oss-20b / qwen3.8-27b: 30 RPM, 1K RPD, 8K TPM, 200K TPD (matches Groq's docs page).
- allam-2-7b: 30 RPM, 7K RPD, 6K TPM, 500K TPD (much larger daily token budget, smaller model).
- Confirms the account-level numbers behind the pipeline token arithmetic. Tokens (per minute and per day) bind, not requests.

## E12: first three real pipeline runs  (2026-11-13 23:52, run by Sumukh)
- Setup: `scripts/ask.py`, gpt-oss-20b, reasoning_effort=low, draft max_tokens 900, verify 400, run back to back (~30 s).
- Q1 "What latency does Moshi achieve?": answered, 1 claim kept, 1,133 ms total. Tokens 3,187 in / 162 out.
  Draft call: 2,559 prompt tokens, TTFT 484 ms. Verify call: 628 prompt tokens.
- Q2 (the brief's cross-paper example): **reduced answer, 2 claims kept (both Transformer), 2 dropped**, 1,888 ms.
  Tokens 4,323 in / 554 out. The kept answer covers only one side of the comparison.
- Q3 "GPT-4 parameters": **HTTP 429 on the first call, after 93 ms.** Remaining tokens/min before it was ~1,538.
  User saw the "busy" message (max_retries is 0).
- Surprise: **three questions in ~30 seconds hit the per-minute token limit.** One impatient user can do this.
- Token accounting from the headers (8,000/min refills at ~133 tokens/s):
  remaining dropped by ~the *prompt* size when a call started, and by the *output* size after it finished.
  Q3's draft needed ~2,400 prompt tokens with ~2,800 left after refill, yet was refused. That fits
  "Groq checks prompt + max_tokens (900) before admitting", i.e. E10 hypothesis 2, but deducts what is actually used.
  **Still unconfirmed**: needs the 429 error body and a controlled probe (same prompt, different max_tokens).
- Bug found: `ask.py` crashed printing a failed step (KeyError 'ms'). Fixed.

## E13: why Q2 lost half its answer, and what the 429 said  (2026-11-14 00:03, `show_last.py`, no Groq calls)
- **Q2 dropped claims: the verifier was right.** Both Dynamic Chunking claims passed the quote check (the quotes are real)
  but the model then *inferred* "reduces path length / shortens the distance dependencies travel", which the passages
  never say. The LLM verifier rejected both as unsupported. This is P1 working: the draft model over-reached and got caught.
  Real gap: the retrieved Dynamic Chunking passages (intro, §1) don't discuss long-range dependencies at all.
  Side effect: the user got a "reduced" label but wasn't told that the *entire* Dynamic Chunking half is missing.
- **The 429 body confirms E10 hypothesis 2:** "Limit 8000, Used 5257, **Requested 3496**". The request was ~2,596 prompt
  tokens + **900 max_tokens** = 3,496. Groq reserves prompt + max_tokens against TPM before admitting a call.
  Our drafts actually produced 83 to 270 output tokens, so ~630+ tokens of every draft's reservation are wasted.
- **It also says when to retry:** `retry-after: 6` and "Please try again in 5.6475s". A single 6-second wait would have succeeded.
- **E10 hypothesis 3 confirmed:** reset-requests = 5m45.6s with 4 requests used = 4 x 86.4 s. The daily request limit
  refills one request every 86.4 s, continuously. It is not a midnight reset.

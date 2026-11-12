# Retrieval experiments: what worked, what it cost

Overnight run, 2026-11-13. Covers decision #2 (BM25 / embeddings / re-ranking) and #4 (chunking),
plus text cleaning, k, the section-citation choice, and spotting unanswerable questions.
All numbers come from `results/retrieval_tables.md`, which is generated from the raw file
`results/raw/retrieval_grid_per_question.csv` by `experiments/analyze_retrieval.py`.
**No Groq calls were made.** This measures whether the right passage *reaches* the model, not answer quality.

---

## TL;DR

1. **Section-based chunks + hybrid search (BM25 + embeddings, no re-ranker)** found the evidence for **25 to 26 of 30**
   questions in the top 5 (clean / raw text), the best result in the grid, in about 50 ms. The fixed 200-word baseline found 21.
2. **The re-ranker helps, but costs ~1.4 s per question on CPU**, before the first token, and that CPU time is
   shared by every concurrent request. Section + hybrid matched or beat every re-ranked config without it.
3. **BM25 and embeddings fail on different questions.** Switching from one to the other gained 7 questions and lost 6.
   That's why hybrid helps: the weaknesses barely overlap.
4. **Stripping the running headers did nothing measurable** (my hypothesis was wrong). The Moshi latency question
   is still lost because the appendix chat transcripts dominate, not because of the header.
5. **Your paper + section citation choice favours section chunks.** With 200-word windows, **24% of chunks span two
   sections**, so the section in the citation would be wrong for those. Section chunks are 0% by construction.

Lean (yours to decide): **section chunks, hybrid, k=5, no re-ranker by default**. See the open questions at the end.

---

## How it was tested (short)

- **36 test questions** I wrote (30 answerable, 6 unanswerable) in `eval/retrieval_questions.json`, tagged by type:
  exact facts (15), paraphrased in the asker's own words (8), Moshi header traps (4), transcript (1), cross-paper (2).
  These are retrieval tests only, not the brief's 15 answer-quality questions, which are yours to write.
- Each question has gold evidence: a phrase I confirmed exists in the PDF text. **Hit@5** = a chunk containing it
  is in the top 5. **MRR** = how high the first correct chunk ranks on average (1.0 = always first).
- Grid: raw vs cleaned text x 4 chunkings (100 / 200 / 400 words page-bound, section-based capped at 300) x
  3 retrievers (BM25, embeddings `bge-small-en-v1.5`, hybrid) x re-rank on/off (`ms-marco-MiniLM-L-6` cross-encoder,
  reorders the top 20) x k = 3/5/8. **48 configs, 1,728 rows.** All local, zero Groq quota.
- **Hypotheses were committed before the run** (commit `4bc61ef`), so the "surprises" below are real.

**How much to trust a difference:** 1 question = 3.3 points. Differences of 1 to 3 questions are within noise.
Only treat gaps of about 4+ questions, or patterns that repeat across configs, as real.

---

## Finding 1: retrieval method (decision #2)

| One change from baseline (raw, 200 words, BM25) | hit@3 | hit@5 | hit@8 | MRR | ms/question |
|---|---|---|---|---|---|
| Baseline: BM25 | 13 | 21 | 25 | 0.48 | 1 |
| Embeddings instead | 18 | 22 | 23 | 0.57 | 45 |
| Hybrid (both, merged) | 21 | 23 | 24 | 0.58 | 52 |
| BM25 + re-ranker | 19 | 24 | 27 | 0.58 | 1,361 |

- **BM25 is good at exact facts, bad at paraphrase**: 13/15 exact, only 3/8 paraphrased (clean, 200 words).
- **Embeddings are the reverse**: 6/8 paraphrased, 11/15 exact. They lost questions hinging on a specific number
  or name ("7 million hours", "Q = 8 codebooks", "ratio loss").
- **Hybrid** merges both rankings (reciprocal rank fusion), lifting hit@3 from 13 to 21. Biggest gain at small k,
  where order matters most.
- **Re-ranking** gives the best hit@8 (27) and fixes paraphrases, but see the cost below.

## Finding 2: the re-ranker's real cost

Measured: **68 ms per (question, chunk) pair x 20 candidates = ~1.4 s per question**, on a 2-vCPU machine
(Codespaces default is also 2 cores, so expect similar).

- That 1.4 s lands **before the first token**, so it hits the TTFT you'll report.
- It runs on **our CPU, not Groq's**. Under a burst, 20 concurrent requests all compete for the same 2 cores, so the
  re-ranker can become the bottleneck **even with Groq quota to spare**. That's a candidate load-test finding in itself.
- Section + hybrid **without** a re-ranker scored 26 at hit@5. No re-ranked config beat it.

## Finding 3: chunking (decision #4)

| Chunking (clean text, hybrid, k=5) | hit@5 | tokens of context | chunks spanning 2+ sections |
|---|---|---|---|
| 100 words | 18 | ~780 | 14% |
| 200 words | 22 | ~1,500 | 24% |
| 400 words | 21 | ~2,750 | 32% |
| Section-based (cap 300) | **25** | ~2,080 | **0%** |

- **100 words is clearly worse** with BM25 (14/30 raw vs 21 for 200). Chunks too small to hold both the question's
  words and the answer.
- **400 words costs ~80% more tokens than 200 for no gain.** Bigger chunks add text but also noise.
- **Section chunks win on quality and on citation correctness.** They follow the paper's own structure and never
  cross a section boundary.
- **Cost:** ~40% more tokens per answer than 200-word windows. Under the TPM limit, that means fewer answers per minute.

## Finding 4: cleaning headers didn't help (hypothesis E03 wrong)

- Stripping the repeated "Moshi: a speech-text foundation model..." line changed **one** question, and that one got
  slightly worse: M4 moved from rank 5 to 6. Noise.
- **"What latency does Moshi achieve?" still fails with BM25 on 100- and 200-word chunks**, cleaned or not
  (with 200 words the answer only moved from rank 12 to 9). The real cause is the **appendix chat transcripts**:
  "MOSHI:" before every line. **Bigger chunks fix it** (400-word and section chunks: rank 2 to 3), because the chunk
  holding "160ms" also holds the rest of the abstract's vocabulary. So chunk size mattered here, not header cleaning.
- Keep the cleaning anyway (cheap, cleaner citations), but **don't claim it fixes the Moshi problem**. Fixing the
  transcripts (option B or C from earlier) is the untested next step.

## Finding 5: k (pieces fetched)

For clean / 200 / hybrid: k=3 → 18 hits for ~910 tokens; k=5 → 22 for ~1,500; k=8 → 24 for ~2,430.
Going 5→8 costs 60% more tokens for 2 questions (noise level). **k=3 when near the limit, k=5 normally.**
This gives you a concrete "what we do with retrieval when the limit is close" lever for the write-up.

## Finding 6: spotting unanswerable questions (hypothesis E08 partly wrong)

The embedding similarity of the best chunk separated answerable from unanswerable questions better than I expected:
a single threshold sorted **94%** of the 36 correctly (BM25: 83%). The closest call was U6, "latency of the
Transformer in spoken dialogue", as predicted.

**Caveat: only 6 unanswerable questions**, so that threshold is overfit. Possible use: a free pre-filter that refuses
obvious misses before spending a Groq call. The LLM still has to make the final call.

## Finding 7: section detection for paper + section citations

Detected **24 / 36 / 46 headings** (Attention / Dynamic Chunking / Moshi), including lettered appendices.
I compared these against the actual headings in the text: **all real numbered headings were found**.
The first version had **3 false positives** (numbered list items like "1 How does our model behave...?") and
**1 miss** ("2 H-Net Architecture", because of the hyphen); both fixed. Full list: `results/raw/section_headings.txt`.
Text before the first heading on page 1 is labelled "front matter".

---

## New examples for "How this library misleads a naive retriever"

1. **Transcripts beat the abstract.** "What latency does Moshi achieve?": appendix transcripts outrank the answer on
   p.1 with small chunks. *(seen before; header stripping does not fix it, bigger chunks do)*
2. **Vocabulary mismatch.** "How does the Transformer cope with relationships between words that are far apart?":
   **missed by all 48 configs.** The paper says "long-range dependencies" and "path length", sharing no words with
   the question, and embeddings missed it too.
3. **One paper hogs the results.** The cross-paper question (Transformer vs Dynamic Chunking on long-range
   dependencies) put 5 Dynamic Chunking chunks on top. The Transformer evidence didn't appear until rank 20.
   A naive top-k never gives the model both sides. Fix idea: a per-paper quota when a question names two papers.

## Hypotheses vs results

| | Hypothesis (pre-registered) | Result |
|---|---|---|
| E03 | Stripping headers fixes the Moshi header traps for BM25 | **Wrong.** No measurable effect |
| E04 | Bigger chunks hit more often; 200 is best per token | **Partly.** 100 clearly worse, 400 no better than 200; section chunks beat both |
| E05 | BM25 wins exact, embeddings win paraphrase, hybrid best | **Right** |
| E06 | Re-ranking helps most at k=3, costs tens of ms | **Partly.** Helps at all k, but costs ~1.4 s, not tens of ms |
| E07 | Diminishing returns in k | **Right** |
| E08 | Scores can't flag unanswerable | **Partly wrong.** Embedding score did well, on a small sample |
| E09 | Heading regex finds most headings, some false positives | **Right**, after 2 fixes |

## Shortlist for Table 3 (to run later with real Groq answers)

| Setting | Why include it | Retrieval hit@5 | Context tokens@5 | Extra latency |
|---|---|---|---|---|
| A. 200 words, BM25, k=5 | Naive baseline, cheapest | 20 to 21 | ~1,500 | ~0 |
| B. Section, hybrid, k=5 | Best quality, correct section citations | 25 to 26 | ~2,080 | ~50 ms |
| C. Section, hybrid, k=3 | "Near the limit" mode | 20 to 21 (hit@3) | ~1,230 | ~50 ms |
| D. 200 words, hybrid + re-rank, k=5 | Tests whether re-ranking pays off in final answers | 23 | ~1,490 | ~1.4 s |

---

## Limitations (be ready to defend these)

- **I wrote the test questions after reading the papers.** Exact-fact questions reuse the paper's wording,
  which may favour BM25. The paraphrase questions deliberately avoid it. Your own 15 questions will be a fairer test.
- **30 answerable questions is small.** Differences under ~4 questions are noise.
- **One embedding model and one re-ranker.** Bigger ones might do better, but would be slower on CPU.
- **Gold = a phrase match.** A chunk can be useful without containing the exact phrase, so hit rates are slightly
  pessimistic, especially for small chunks where the phrase can be cut at a boundary.
- **Timings are from a 2-vCPU sandbox.** Re-measure on whatever machine runs the load tests.

## Decisions for you

1. **Chunking:** section chunks (better hits, correct citations, +40% tokens) or 200-word windows (cheaper, 24% wrong
   section labels)? Does the token cost worry you, given TPM?
2. **Re-ranker:** keep it out of the default path, keep it only for Table 3, or use it only when the system is idle?
3. **The transcripts:** test option B (drop appendix transcripts) or C (cap repeated words), or leave them as a
   documented failure?
4. **Embedding-score pre-filter for unanswerable questions:** worth building, given only 6 test cases?

## Reproduce

```bash
pip install fastembed
python experiments/retrieval_grid.py            # runs all 8 index configs (resumable; ~1 h on 2 vCPU)
python experiments/retrieval_grid.py merge
python experiments/analyze_retrieval.py         # regenerates results/retrieval_tables.md
```

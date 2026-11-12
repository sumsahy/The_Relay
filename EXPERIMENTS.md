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

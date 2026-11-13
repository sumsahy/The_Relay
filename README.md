# The Relay

> **Accounts used (disclosure, Divyanshi):** I used a friend's Claude Pro subscription, GitHub account and Codespace to build this, so the commits and the assistant conversation come from those accounts. All prompts, decisions, questions and grading are mine. The Groq account and API key used for every real run are my own.

A cited research-paper assistant that stays honest under load, built on Groq's free tier
plus a stand-in model service for loads the free tier can't take.

## Setup

```bash
pip install -r requirements.txt     # automatic in Codespaces
python scripts/fetch_papers.py      # downloads the 3 papers at the exact arXiv versions
```

Set `GROQ_API_KEY` as a Codespaces secret, or copy `.env.example` to `.env` locally.
Never commit the key.

## Step 1: retrieval (no API calls)

```bash
python scripts/try_retrieval.py "how does multi-head attention work"
python scripts/try_retrieval.py "what is Moshi's latency" --size 100 --k 3
```

## Step 2: production retrieval + first Groq call

```bash
git pull && pip install -r requirements.txt
python scripts/try_retrieval.py "what latency does Moshi achieve"   # section chunks + hybrid
python scripts/hello_groq.py                                          # 1 real Groq call (~50 tokens)
```

## Step 3: the pipeline (real Groq)

```bash
python tests/test_pipeline_offline.py                      # all paths with a fake model, free
python scripts/ask.py "What latency does Moshi achieve?"   # 2-4 real Groq calls, logged to results.csv
```

## Step 4: stand-in + load scenarios (no Groq quota)

```bash
python standin/calibrate.py          # fit the stand-in to your real Groq calls
python scripts/load_test.py          # all scenarios: steady, burst, burst_naive, overload, halved, daily
```

## Step 5: tables

```bash
python scripts/build_results.py      # merge real + stand-in rows, apply your grades
python scripts/make_tables.py        # -> results/tables.md (Tables 2a, 2b, 3)
```

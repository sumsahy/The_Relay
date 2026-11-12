# The Relay

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

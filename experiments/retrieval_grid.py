"""Overnight retrieval experiments (E03-E09). No Groq calls.

Grid: cleaning (raw/clean) x chunking (w100/w200/w400/section) x retriever
(bm25/dense/hybrid) x rerank (no/yes); k in {3,5,8} is derived from the ranking.

Writes:
  results/raw/retrieval_grid_per_question.csv  one row per config x question
  results/raw/retrieval_index_stats.csv        chunk counts, sizes, index build time
  results/raw/section_headings.txt             every heading the section detector found

Run: python experiments/retrieval_grid.py
"""
from __future__ import annotations

import csv
import hashlib
import pickle
import json
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pypdf import PdfReader
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "data" / "papers"
RAW = ROOT / "results" / "raw"
QUESTIONS = ROOT / "eval" / "retrieval_questions.json"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
CANDIDATES = 20          # how many chunks a re-ranker gets to reorder
KS = (3, 5, 8)
CACHE = ROOT / "results" / "cache"          # gitignored; speeds up reruns
PARTS = RAW / "grid_parts"
EMB_CACHE: dict = {}
RR_CACHE: dict = {}

# ---------------------------------------------------------------- text + sections

HEADING = re.compile(
    r"^(?:Appendix\s+)?([A-H]|\d{1,2})((?:\.\d{1,2}){0,3})\.?\s+([A-Z][A-Za-z\-][^=±%]{1,90})$"
)


def looks_like_heading(line: str, seen_references: bool) -> str | None:
    """Return a section label like '3.2.1 Scaled Dot-Product Attention' or None."""
    s = line.strip()
    if s in ("Abstract", "References"):
        return s
    m = HEADING.match(s)
    if not m:
        return None
    top, sub, title = m.group(1), m.group(2), m.group(3).strip()
    words = title.split()
    if title.endswith((".", "?")) or ". " in title:
        return None                     # numbered list items / sentences, not headings
    if len(words) > 12:
        return None
    letters = sum(ch.isalpha() for ch in title)
    if letters / max(1, len(title.replace(" ", ""))) < 0.8:
        return None                     # table rows, numbers ("5.0MosNet score")
    if top.isalpha() and not seen_references:
        return None                     # lettered appendices only after References
    if top.isdigit() and int(top) > 12:
        return None
    return f"{top}{sub} {title}"


@dataclass
class Word:
    text: str
    page: int
    section: str


@dataclass
class Chunk:
    paper: str
    page: int
    section: str
    text: str

    def cite(self) -> str:
        sec = self.section.split(" ")[0] if self.section else "?"
        return f"[{self.paper} §{sec} p.{self.page}]"


def page_lines(pdf: Path) -> list[list[str]]:
    reader = PdfReader(pdf)
    return [[l for l in (p.extract_text() or "").split("\n")] for p in reader.pages]


def repeated_lines(pages: list[list[str]]) -> set[str]:
    """Lines (digits stripped) that recur on >= 30% of pages: running headers/footers."""
    norm = lambda l: re.sub(r"[\d\s]+", " ", l).strip().lower()
    counts = Counter()
    for lines in pages:
        counts.update({norm(l) for l in lines if norm(l)})
    n = len(pages)
    return {k for k, c in counts.items() if n >= 5 and c >= 0.3 * n and len(k) > 3}


def word_stream(paper: str, pages: list[list[str]], clean: bool, headings_log: list) -> list[Word]:
    rep = repeated_lines(pages) if clean else set()
    norm = lambda l: re.sub(r"[\d\s]+", " ", l).strip().lower()
    section, seen_refs, words = "front matter", False, []
    for page_no, lines in enumerate(pages, start=1):
        for line in lines:
            if clean and (norm(line) in rep or re.fullmatch(r"\s*\d+\s*", line)):
                continue
            h = looks_like_heading(line, seen_refs)
            if h:
                section = h
                seen_refs = seen_refs or h == "References"
                if clean:  # log once
                    headings_log.append((paper, page_no, h))
            for w in line.split():
                words.append(Word(w, page_no, section))
    return words


def windows(paper: str, words: list[Word], size: int, overlap: int) -> list[Chunk]:
    """Page-bound fixed windows (same scheme as relay/retrieval.py)."""
    chunks, step = [], max(1, size - overlap)
    by_page: dict[int, list[Word]] = {}
    for w in words:
        by_page.setdefault(w.page, []).append(w)
    for page, ws in by_page.items():
        for start in range(0, len(ws), step):
            piece = ws[start:start + size]
            if len(piece) < 20 and start > 0:
                break
            chunks.append(Chunk(paper, page, piece[0].section, " ".join(w.text for w in piece)))
    return chunks


def section_chunks(paper: str, words: list[Word], cap: int = 300, overlap: int = 50) -> list[Chunk]:
    """Split at section boundaries (may cross pages); cap long sections into windows."""
    groups: list[list[Word]] = []
    for w in words:
        if not groups or groups[-1][0].section != w.section:
            groups.append([])
        groups[-1].append(w)
    chunks, step = [], cap - overlap
    for g in groups:
        for start in range(0, len(g), step):
            piece = g[start:start + cap]
            if len(piece) < 20 and start > 0:
                break
            chunks.append(Chunk(paper, piece[0].page, piece[0].section, " ".join(w.text for w in piece)))
    return chunks


CHUNKINGS = {
    "w100": lambda p, ws: windows(p, ws, 100, 20),
    "w200": lambda p, ws: windows(p, ws, 200, 40),
    "w400": lambda p, ws: windows(p, ws, 400, 80),
    "section": lambda p, ws: section_chunks(p, ws),
}

# ---------------------------------------------------------------- retrievers

def tok(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", t.lower())


class Index:
    def __init__(self, chunks: list[Chunk], embedder):
        self.chunks = chunks
        t0 = time.perf_counter()
        self.bm25 = BM25Okapi([tok(c.text) for c in chunks])
        self.bm25_build_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        keys = [hashlib.sha1(c.text.encode()).hexdigest() for c in chunks]
        todo = [(k, c.text) for k, c in zip(keys, chunks) if k not in EMB_CACHE]
        if todo:
            new = list(embedder.passage_embed([t for _, t in todo], batch_size=16))
            for (k, _), v in zip(todo, new):
                EMB_CACHE[k] = v
        vecs = np.array([EMB_CACHE[k] for k in keys])
        self.vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        # time per chunk measured only on freshly embedded chunks
        self.embed_ms_per_chunk = ((time.perf_counter() - t0) * 1000 / len(todo)) if todo else float("nan")
        self.embed_build_ms = self.embed_ms_per_chunk * len(chunks)
        self.embedder = embedder

    def bm25_rank(self, q):
        s = self.bm25.get_scores(tok(q))
        order = np.argsort(-s)
        return [(int(i), float(s[i])) for i in order]

    def dense_rank(self, q):
        v = np.array(list(self.embedder.query_embed([q])))[0]
        v = v / np.linalg.norm(v)
        s = self.vecs @ v
        order = np.argsort(-s)
        return [(int(i), float(s[i])) for i in order]

    def hybrid_rank(self, q, depth=50, k=60):
        """Reciprocal rank fusion: score = sum 1/(k + rank) over both rankings."""
        fused: dict[int, float] = {}
        for ranking in (self.bm25_rank(q)[:depth], self.dense_rank(q)[:depth]):
            for r, (i, _) in enumerate(ranking, start=1):
                fused[i] = fused.get(i, 0.0) + 1.0 / (k + r)
        return sorted(fused.items(), key=lambda x: -x[1])


def rerank(reranker, q, chunks, ranking):
    """Returns (new_ranking, ms_spent_on_uncached_pairs, n_uncached)."""
    cand = ranking[:CANDIDATES]
    keys = [(q, hashlib.sha1(chunks[i].text.encode()).hexdigest()) for i, _ in cand]
    todo = [(k, chunks[i].text) for k, (i, _) in zip(keys, cand) if k not in RR_CACHE]
    t0 = time.perf_counter()
    if todo:
        for (k, _), sc in zip(todo, reranker.rerank(q, [t for _, t in todo])):
            RR_CACHE[k] = float(sc)
    ms = (time.perf_counter() - t0) * 1000
    scores = [RR_CACHE[k] for k in keys]
    return sorted([(i, float(s)) for (i, _), s in zip(cand, scores)], key=lambda x: -x[1]), ms, len(todo)

# ---------------------------------------------------------------- evaluation

def relevant(chunk: Chunk, paper: str, pat: str) -> bool:
    return chunk.paper == paper and re.search(pat, re.sub(r"\s+", " ", chunk.text), re.I) is not None


def first_rank(q, ranking, chunks, depth=CANDIDATES) -> int | None:
    """1-based rank at which the question is satisfied, or None within depth."""
    top = [chunks[i] for i, _ in ranking[:depth]]
    ranks = []
    for paper, pat in q["gold"]:
        r = next((n for n, c in enumerate(top, 1) if relevant(c, paper, pat)), None)
        ranks.append(r)
    if q["need"] == "any":
        found = [r for r in ranks if r is not None]
        return min(found) if found else None
    return None if any(r is None for r in ranks) else max(ranks)


def load_caches():
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, d in (("emb.pkl", EMB_CACHE), ("rr.pkl", RR_CACHE)):
        if (CACHE / name).exists():
            d.update(pickle.load(open(CACHE / name, "rb")))


def save_caches():
    pickle.dump(EMB_CACHE, open(CACHE / "emb.pkl", "wb"))
    pickle.dump(RR_CACHE, open(CACHE / "rr.pkl", "wb"))


def run_config(clean: bool, chunking: str, embedder, reranker, questions, raw_pages):
    out = PARTS / f"{'clean' if clean else 'raw'}_{chunking}.csv"
    if out.exists():
        print(f"skip {out.name}", file=sys.stderr); return
    headings: list = []
    streams = {p: word_stream(p, pages, clean, headings) for p, pages in raw_pages.items()}
    chunks = [c for p, ws in streams.items() for c in CHUNKINGS[chunking](p, ws)]
    idx = Index(chunks, embedder)
    save_caches()
    lens = [len(c.text.split()) for c in chunks]
    stat = dict(clean=clean, chunking=chunking, n_chunks=len(chunks),
                words_mean=round(statistics.mean(lens), 1), words_max=max(lens),
                bm25_build_ms=round(idx.bm25_build_ms, 1),
                embed_ms_per_chunk=round(idx.embed_ms_per_chunk, 1))
    rows = []
    for retr in ("bm25", "dense", "hybrid"):
        for use_rr in (False, True):
            for q in questions:
                t0 = time.perf_counter()
                ranking = getattr(idx, f"{retr}_rank")(q["q"])
                t_retr = (time.perf_counter() - t0) * 1000
                rr_ms, rr_new = 0.0, 0
                if use_rr:
                    ranking, rr_ms, rr_new = rerank(reranker, q["q"], chunks, ranking)
                rank = first_rank(q, ranking, chunks) if q["gold"] else None
                row = dict(clean=clean, chunking=chunking, retriever=retr, rerank=use_rr,
                           qid=q["id"], qtype=q["type"], answerable=bool(q["gold"]),
                           first_rank=rank if rank is not None else "",
                           top1_score=round(ranking[0][1], 4),
                           retrieval_ms=round(t_retr, 2),
                           rerank_ms_uncached=round(rr_ms, 1), rerank_pairs_uncached=rr_new,
                           top1_section=chunks[ranking[0][0]].cite(),
                           top5=" ".join(chunks[i].cite() for i, _ in ranking[:5]))
                for k in KS:
                    row[f"hit@{k}"] = int(rank is not None and rank <= k) if q["gold"] else ""
                    row[f"tokens@{k}"] = sum(len(chunks[i].text) for i, _ in ranking[:k]) // 4
                rows.append(row)
            save_caches()
    PARTS.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with open(PARTS / f"stats_{out.name}", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(stat.keys()))
        w.writeheader(); w.writerow(stat)
    if clean and chunking == "w200":
        with open(RAW / "section_headings.txt", "w") as f:
            for paper, page, h in headings:
                f.write(f"{paper}\tp.{page}\t{h}\n")
    print(f"done {out.name}: {len(chunks)} chunks", file=sys.stderr)


def merge():
    parts = sorted(PARTS.glob("*.csv"))
    rows = [r for p in parts if not p.name.startswith("stats_") for r in csv.DictReader(open(p))]
    stats = [r for p in parts if p.name.startswith("stats_") for r in csv.DictReader(open(p))]
    for name, data in (("retrieval_grid_per_question.csv", rows), ("retrieval_index_stats.csv", stats)):
        with open(RAW / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader(); w.writerows(data)
    print(f"merged {len(rows)} rows from {len(stats)} configs", file=sys.stderr)


def main() -> None:
    """python experiments/retrieval_grid.py [raw|clean] [w100|w200|w400|section] | merge"""
    if sys.argv[1:] == ["merge"]:
        merge(); return
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    load_caches()
    questions = json.load(open(QUESTIONS))["questions"]
    embedder = TextEmbedding(EMBED_MODEL, threads=2)
    reranker = TextCrossEncoder(RERANK_MODEL, threads=2)
    raw_pages = {p.stem: page_lines(p) for p in sorted(PAPERS.glob("*.pdf"))}
    cleans = [a == "clean" for a in sys.argv[1:2]] or [False, True]
    chunkings = sys.argv[2:3] or list(CHUNKINGS)
    for clean in cleans:
        for ch in chunkings:
            run_config(clean, ch, embedder, reranker, questions, raw_pages)


if __name__ == "__main__":
    main()

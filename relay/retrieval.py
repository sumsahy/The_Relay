"""Retrieval: section chunks + hybrid search (BM25 + embeddings). Decided 2026-11-13, see CHANGELOG v0.2.

Pipeline at startup:
  PDF pages -> lines -> drop running headers -> detect section headings
  -> split at section boundaries (cap 300 words, 50 overlap) -> index with BM25 and embeddings.

At question time:
  BM25 ranking + embedding ranking -> merged with reciprocal rank fusion -> top k chunks.

Each chunk carries paper + section + page, so citations look like [moshi §3.4.4 p.16].
Embeddings are cached in data/index/ so restarts take seconds, not minutes.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pypdf import PdfReader
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = ROOT / "data" / "papers"
INDEX_DIR = ROOT / "data" / "index"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

SECTION_CAP, SECTION_OVERLAP = 300, 50
RRF_K, RRF_DEPTH = 60, 50

# ------------------------------------------------------------------ section detection

_HEADING = re.compile(
    r"^(?:Appendix\s+)?([A-H]|\d{1,2})((?:\.\d{1,2}){0,3})\.?\s+([A-Z][A-Za-z\-][^=±%]{1,90})$"
)


def _heading(line: str, seen_references: bool) -> str | None:
    s = line.strip()
    if s in ("Abstract", "References"):
        return s
    m = _HEADING.match(s)
    if not m:
        return None
    top, sub, title = m.group(1), m.group(2), m.group(3).strip()
    if title.endswith((".", "?")) or ". " in title or len(title.split()) > 12:
        return None
    if sum(c.isalpha() for c in title) / max(1, len(title.replace(" ", ""))) < 0.8:
        return None
    if top.isalpha() and not seen_references:
        return None
    if top.isdigit() and int(top) > 12:
        return None
    return f"{top}{sub} {title}"


def _norm(line: str) -> str:
    return re.sub(r"[\d\s]+", " ", line).strip().lower()


def _repeated_lines(pages: list[list[str]]) -> set[str]:
    """Running headers/footers: lines (digits ignored) on >= 30% of a paper's pages."""
    counts = Counter()
    for lines in pages:
        counts.update({_norm(l) for l in lines if _norm(l)})
    n = len(pages)
    return {k for k, c in counts.items() if n >= 5 and c >= 0.3 * n and len(k) > 3}


# ------------------------------------------------------------------ chunks

@dataclass
class Chunk:
    paper: str
    section: str     # e.g. "3.2.1 Scaled Dot-Product Attention"
    page: int        # page where the chunk starts
    text: str

    @property
    def section_id(self) -> str:
        return self.section.split(" ")[0]

    @property
    def cite(self) -> str:
        return f"[{self.paper} §{self.section_id} p.{self.page}]"


def build_chunks(paper_dir: Path = PAPER_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    pdfs = sorted(paper_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs in {paper_dir}. Run: python scripts/fetch_papers.py")
    for pdf in pdfs:
        pages = [(p.extract_text() or "").split("\n") for p in PdfReader(pdf).pages]
        drop = _repeated_lines(pages)
        words: list[tuple[str, int, str]] = []          # (word, page, section)
        section, seen_refs = "front matter", False
        for page_no, lines in enumerate(pages, start=1):
            for line in lines:
                if _norm(line) in drop or re.fullmatch(r"\s*\d+\s*", line):
                    continue
                h = _heading(line, seen_refs)
                if h:
                    section, seen_refs = h, seen_refs or h == "References"
                words += [(w, page_no, section) for w in line.split()]
        # group consecutive words by section, then cap long sections into windows
        start = 0
        while start < len(words):
            end = start
            while end < len(words) and words[end][2] == words[start][2]:
                end += 1
            group = words[start:end]
            for s in range(0, len(group), SECTION_CAP - SECTION_OVERLAP):
                piece = group[s:s + SECTION_CAP]
                if len(piece) < 20 and s > 0:
                    break
                chunks.append(Chunk(pdf.stem, piece[0][2], piece[0][1], " ".join(w for w, _, _ in piece)))
            start = end
    return chunks


# ------------------------------------------------------------------ search

def _tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class Retriever:
    def __init__(self, chunks: list[Chunk] | None = None):
        from fastembed import TextEmbedding

        self.chunks = chunks or build_chunks()
        self.bm25 = BM25Okapi([_tok(c.text) for c in self.chunks])
        self.embedder = TextEmbedding(EMBED_MODEL)
        self.vecs = self._load_or_embed()

    def _load_or_embed(self) -> np.ndarray:
        digest = hashlib.sha1("".join(c.text for c in self.chunks).encode()).hexdigest()[:12]
        path = INDEX_DIR / f"embeddings_{digest}.npy"
        if path.exists():
            return np.load(path)
        t0 = time.perf_counter()
        print(f"Embedding {len(self.chunks)} chunks (one-off, cached afterwards)...")
        vecs = np.array(list(self.embedder.passage_embed([c.text for c in self.chunks], batch_size=16)))
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        np.save(path, vecs)
        print(f"  done in {time.perf_counter() - t0:.0f}s -> {path.name}")
        return vecs

    def _dense_scores(self, query: str) -> np.ndarray:
        q = np.array(list(self.embedder.query_embed([query])))[0]
        return self.vecs @ (q / np.linalg.norm(q))

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        """Hybrid search. Returns top-k (chunk, fused score)."""
        bm25 = self.bm25.get_scores(_tok(query))
        dense = self._dense_scores(query)
        fused: dict[int, float] = {}
        for scores in (bm25, dense):
            for rank, i in enumerate(np.argsort(-scores)[:RRF_DEPTH], start=1):
                fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (RRF_K + rank)
        top = sorted(fused.items(), key=lambda x: -x[1])[:k]
        return [(self.chunks[i], s) for i, s in top]

    def best_similarity(self, query: str) -> float:
        """Embedding similarity of the closest chunk. Used by the under-load pre-filter."""
        return float(self._dense_scores(query).max())

"""Retrieval: split the papers into chunks and search them with BM25.

Concept in one paragraph:
  BM25 scores a chunk by how many query words it contains, giving more weight
  to rare words (e.g. "Moshi" beats "model") and less weight to very long
  chunks. No neural model, no API call, runs in milliseconds. That makes it
  cheap under load, which matters for this assignment.

Each chunk remembers which paper and page it came from, so every answer
can cite e.g. [attention p.5].
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from rank_bm25 import BM25Okapi

PAPER_DIR = Path(__file__).resolve().parent.parent / "data" / "papers"


@dataclass
class Chunk:
    paper: str
    page: int        # 1-based page number, used for citations
    idx: int         # chunk number within the whole library
    text: str

    @property
    def cite(self) -> str:
        return f"[{self.paper} p.{self.page}]"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def load_pages(paper_dir: Path = PAPER_DIR) -> list[tuple[str, int, str]]:
    """Return (paper, page_number, page_text) for every page of every paper."""
    pages = []
    for pdf in sorted(paper_dir.glob("*.pdf")):
        reader = PdfReader(pdf)
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                pages.append((pdf.stem, i, text))
    if not pages:
        raise FileNotFoundError(
            f"No PDFs in {paper_dir}. Run: python scripts/fetch_papers.py"
        )
    return pages


def chunk_pages(pages, size: int = 200, overlap: int = 40) -> list[Chunk]:
    """Split each page into windows of `size` words, overlapping by `overlap`.

    Chunks never cross a page boundary, so the page citation is always exact.
    size and overlap are experiment knobs (Table 3 in the brief).
    """
    step = max(1, size - overlap)
    chunks: list[Chunk] = []
    for paper, page_no, text in pages:
        words = text.split()
        for start in range(0, len(words), step):
            piece = words[start:start + size]
            if len(piece) < 20 and start > 0:   # skip tiny tail fragments
                break
            chunks.append(Chunk(paper, page_no, len(chunks), " ".join(piece)))
    return chunks


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks])

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [(self.chunks[i], float(scores[i])) for i in ranked[:k]]


def build(size: int = 200, overlap: int = 40) -> Retriever:
    return Retriever(chunk_pages(load_pages(), size=size, overlap=overlap))

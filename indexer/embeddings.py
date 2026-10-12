"""Latent Semantic Analysis embeddings, quantized to int8 for the browser.

TF-IDF (sublinear tf) + randomized SVD (Halko, Martinsson and Tropp, 2011) with numpy only.
Document vectors are ``X·V`` (= ``U·Σ``) L2-normalized; the browser projects a query with the
term vectors ``V`` and the same idf, so query and documents live in the same space.
See docs/algoritmo.md §3.2.
"""

from __future__ import annotations

import json
import math
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from analyzer.text import tokens
from pipeline.jsonio import write_bytes, write_json

DIMS = 64
MAX_TERMS = 5000
MIN_DF = 2
MAX_DF_RATIO = 0.5
SEED = 42
OVERSAMPLE = 10
POWER_ITERATIONS = 2
MAGIC = b"SKSE"
FORMAT_VERSION = 1

Matrix = NDArray[np.float64]


@dataclass(slots=True)
class LsaModel:
    ids: list[str]
    terms: list[str]
    idf: NDArray[np.float64]
    term_vectors: Matrix  # n_terms × k  (V)
    doc_vectors: Matrix  # n_docs × k, unit length

    @property
    def dims(self) -> int:
        return int(self.term_vectors.shape[1]) if self.term_vectors.ndim == 2 else 0

    def project(self, text: str) -> NDArray[np.float64]:
        """Unit vector of ``text`` in the latent space (zeros when no term is known)."""
        vector = np.zeros(self.dims)
        if not self.dims:
            return vector
        index = {t: i for i, t in enumerate(self.terms)}
        counts = Counter(t for t in tokens(text) if t in index)
        if not counts:
            return vector
        weights = np.zeros(len(self.terms))
        for term, count in counts.items():
            weights[index[term]] = (1 + math.log(count)) * self.idf[index[term]]
        weights /= np.linalg.norm(weights)
        vector = weights @ self.term_vectors
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def similarities(self, vector: NDArray[np.float64]) -> NDArray[np.float64]:
        if not self.dims or not vector.any():
            return np.zeros(len(self.ids))
        return self.doc_vectors @ vector


def _vocabulary(docs: list[list[str]]) -> tuple[list[str], NDArray[np.float64]]:
    n = len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    max_df = max(MIN_DF, int(MAX_DF_RATIO * n))
    eligible = [(t, c) for t, c in df.items() if MIN_DF <= c <= max_df]
    eligible.sort(key=lambda tc: (-tc[1], tc[0]))
    terms = sorted(t for t, _ in eligible[:MAX_TERMS])
    idf = np.array([math.log((n + 1) / (df[t] + 1)) + 1 for t in terms])
    return terms, idf


def _tfidf(docs: list[list[str]], terms: list[str], idf: NDArray[np.float64]) -> Matrix:
    index = {t: i for i, t in enumerate(terms)}
    matrix = np.zeros((len(docs), len(terms)))
    for row, doc in enumerate(docs):
        for term, count in Counter(t for t in doc if t in index).items():
            matrix[row, index[term]] = (1 + math.log(count)) * idf[index[term]]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def randomized_svd(matrix: Matrix, rank: int) -> tuple[Matrix, NDArray[np.float64], Matrix]:
    """Halko et al. (2011): random range finder + power iterations + small exact SVD."""
    rng = np.random.default_rng(SEED)
    sketch = min(matrix.shape[1], rank + OVERSAMPLE)
    omega = rng.standard_normal((matrix.shape[1], sketch))
    y = matrix @ omega
    q, _ = np.linalg.qr(y)
    for _ in range(POWER_ITERATIONS):
        z, _ = np.linalg.qr(matrix.T @ q)
        q, _ = np.linalg.qr(matrix @ z)
    b = q.T @ matrix
    u_b, s, vt = np.linalg.svd(b, full_matrices=False)
    u = q @ u_b
    return u[:, :rank], s[:rank], vt[:rank]


def build_lsa(documents: list[tuple[str, str]]) -> LsaModel:
    ids = [doc_id for doc_id, _ in documents]
    docs = [tokens(text) for _, text in documents]
    terms, idf = _vocabulary(docs)
    if len(docs) < 2 or len(terms) < 2:
        return LsaModel(ids, terms, idf, np.zeros((len(terms), 0)), np.zeros((len(ids), 0)))
    matrix = _tfidf(docs, terms, idf)
    rank = max(1, min(DIMS, len(docs) - 1, len(terms) - 1))
    _u, _s, vt = randomized_svd(matrix, rank)
    term_vectors = vt.T
    doc_vectors = matrix @ term_vectors
    norms = np.linalg.norm(doc_vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return LsaModel(ids, terms, idf, term_vectors, doc_vectors / norms)


def quantize_rows(matrix: Matrix) -> tuple[NDArray[np.int8], NDArray[np.float32]]:
    """Per-row scale so that the largest absolute value maps to ±127."""
    scale = np.max(np.abs(matrix), axis=1) / 127.0 if matrix.size else np.zeros(len(matrix))
    scale[scale == 0] = 1.0
    quantized = np.clip(np.round(matrix / scale[:, None]), -127, 127).astype(np.int8)
    return quantized, scale.astype(np.float32)


def encode(model: LsaModel) -> bytes:
    """Binary layout (little endian), read by web/src/search/embeddings.ts:

    magic "SKSE" · u16 version · u16 dims · u32 docs · u32 terms ·
    int8 doc vectors (docs×dims, unit vectors × 127) · padding to 4 bytes ·
    float32 term scales (terms) · int8 term vectors (terms×dims)
    """
    dims = model.dims
    docs = np.clip(np.round(model.doc_vectors * 127), -127, 127).astype(np.int8)
    term_q, term_scale = quantize_rows(model.term_vectors)
    header = MAGIC + struct.pack("<HHII", FORMAT_VERSION, dims, len(model.ids), len(model.terms))
    doc_bytes = docs.tobytes()
    padding = b"\0" * ((-len(doc_bytes)) % 4)
    return header + doc_bytes + padding + term_scale.astype("<f4").tobytes() + term_q.tobytes()


def decode(payload: bytes) -> tuple[int, NDArray[np.int8], NDArray[np.float32], NDArray[np.int8]]:
    """Inverse of ``encode`` (used by tests to check the browser format)."""
    if payload[:4] != MAGIC:
        raise ValueError("not an embeddings file")
    _version, dims, n_docs, n_terms = struct.unpack("<HHII", payload[4:16])
    offset = 16
    docs = np.frombuffer(payload, np.int8, n_docs * dims, offset).reshape(n_docs, dims)
    offset += n_docs * dims
    offset += (-offset) % 4
    scales = np.frombuffer(payload, "<f4", n_terms, offset)
    offset += n_terms * 4
    terms = np.frombuffer(payload, np.int8, n_terms * dims, offset).reshape(n_terms, dims)
    return dims, docs, scales, terms


def write(model: LsaModel, out_dir: Path) -> tuple[str, str]:
    """Write ``embeddings.bin`` and ``embeddings.json``; returns their content hashes."""
    import hashlib

    payload = encode(model)
    meta = {
        "schema_version": 1,
        "dims": model.dims,
        "ids": model.ids,
        "terms": model.terms,
        "idf": [round(float(v), 5) for v in model.idf],
    }
    meta_text = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    write_bytes(out_dir / "embeddings.bin", payload)
    write_json(out_dir / "embeddings.json", meta)
    return (
        hashlib.sha256(payload).hexdigest()[:12],
        hashlib.sha256(meta_text.encode("utf-8")).hexdigest()[:12],
    )

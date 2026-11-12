"""Reciprocal rank fusion of BM25 and precomputed BGE card vectors."""

import hashlib
import json
import os

from rate_truth.rag.bm25 import BM25
from rate_truth.settings import DATA


def texts(records):
    return [" ".join(f["text"] for f in r["card"]["facts"]) for r in records.values()]


def fingerprint(records):
    return hashlib.sha256(json.dumps(texts(records), ensure_ascii=False).encode()).hexdigest()


class Retriever:
    def __init__(self, records, encoder=None, directory=None):
        self.records, self.bm25 = records, BM25(records)
        self.mode = "bm25"
        self.encoder = encoder
        if os.environ.get("RATE_TRUTH_RETRIEVAL") == "bm25":
            return
        directory = directory or DATA / "index"
        try:
            import numpy as np

            metadata = json.loads((directory / "cards.json").read_text(encoding="utf-8"))
            if metadata["fingerprint"] != fingerprint(records):
                return
            self.ids = metadata["ids"]
            self.vectors = np.load(directory / "cards.npy", allow_pickle=False).astype("float32")
            if self.encoder is None:
                from rate_truth.rag.embed import query_embedding

                self.encoder = query_embedding
            self.encoder("hotel")  # Probe once; never claim hybrid when the encoder is missing.
            self.mode = "hybrid"
        except (ImportError, OSError, ValueError, RuntimeError):
            self.mode = "bm25"

    def search(self, query, limit=5):
        lexical = self.bm25.search(query, len(self.records))
        if self.mode == "bm25":
            return lexical[:limit]
        try:
            import numpy as np

            vector = np.asarray(self.encoder(query), dtype="float32")
            scores = self.vectors @ vector
            semantic = [self.ids[i] for i in np.argsort(-scores, kind="stable")]
        except (OSError, ValueError, RuntimeError):
            self.mode = "bm25"
            return lexical[:limit]
        fused = {}
        for ranking in ([r["hotel"]["id"] for r in lexical], semantic):
            for rank, identifier in enumerate(ranking, 1):
                fused[identifier] = fused.get(identifier, 0) + 1 / (60 + rank)
        return [
            {**self.records[key], "score": round(score, 6)}
            for key, score in sorted(fused.items(), key=lambda v: (-v[1], v[0]))[:limit]
        ]

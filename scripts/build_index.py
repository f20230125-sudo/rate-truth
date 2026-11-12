"""Precompute compact float16 card embeddings, using only the cached model."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from rate_truth.rag.cards import Cards
from rate_truth.rag.embed import MODEL, local_encoder
from rate_truth.rag.retrieve import fingerprint, texts
from rate_truth.settings import DATA
from rate_truth.supplier.catalog import Catalog


def main():
    records = Cards(Catalog()).records
    folder = DATA / "index"
    folder.mkdir(exist_ok=True)
    vectors = np.asarray(list(local_encoder().embed(texts(records), batch_size=8)), dtype="float16")
    np.save(folder / "cards.npy", vectors, allow_pickle=False)
    (folder / "cards.json").write_text(
        json.dumps(
            {
                "model": MODEL,
                "dimensions": 384,
                "dtype": "float16",
                "ids": list(records),
                "fingerprint": fingerprint(records),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Indexed {len(records)} cards; {vectors.nbytes} vector bytes")


if __name__ == "__main__":
    main()

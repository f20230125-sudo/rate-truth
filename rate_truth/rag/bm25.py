"""Small dependency-free BM25 index (k1=1.5, b=.75), rebuilt from local facts."""

import math
import re
from collections import Counter


def tokens(text):
    return re.findall(r"\w+", text.casefold())


class BM25:
    def __init__(self, records):
        self.records = records
        self.docs = {
            key: Counter(tokens(" ".join(f["text"] for f in record["card"]["facts"])))
            for key, record in records.items()
        }
        self.lengths = {key: sum(doc.values()) for key, doc in self.docs.items()}
        self.average = sum(self.lengths.values()) / max(1, len(self.docs))
        self.df = Counter(term for doc in self.docs.values() for term in doc)

    def search(self, query, limit=5):
        scores = []
        for key, doc in self.docs.items():
            score = 0.0
            for term in set(tokens(query)):
                tf = doc[term]
                if tf:
                    idf = math.log(
                        1 + (len(self.docs) - self.df[term] + 0.5) / (self.df[term] + 0.5)
                    )
                    score += (
                        idf
                        * tf
                        * 2.5
                        / (tf + 1.5 * (0.25 + 0.75 * self.lengths[key] / self.average))
                    )
            if score > 0:
                scores.append((score, key))
        return [
            {**self.records[key], "score": round(score, 6)}
            for score, key in sorted(scores, key=lambda v: (-v[0], v[1]))[:limit]
        ]

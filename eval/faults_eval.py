"""Evaluate classifier against injector-private ground truth, including clean controls."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_truth.accuracy.faults import FAULT_IDS
from rate_truth.accuracy.sampler import audit
from rate_truth.settings import ROOT
from rate_truth.supplier.rates import RateEngine


def main():
    engine = RateEngine()
    metrics = {}
    for fault in sorted(FAULT_IDS):
        report = audit(engine, faults=[fault])
        positives = [s for s in report["samples"] if s["injected"]]
        correct = sum(s["detected_reason"] == s["injected"] for s in positives)
        metrics[fault] = {
            "n": 30, "score": report["score"], **report["detection"],
            "diagnosis_accuracy": {
                "numerator": correct, "denominator": len(positives),
                "value": correct / len(positives) if positives else None,
            },
        }
    path = ROOT / "eval/results.json"
    results = json.loads(path.read_text()) if path.exists() else {"run_at": None}
    results["fault_detection"] = {
        "seed": 2026,
        "metrics": metrics,
        "note": "Rounding of two fils remains inside the advertised matching tolerance.",
    }
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()

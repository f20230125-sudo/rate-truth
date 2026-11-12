"""Render only the marked README results from eval/results.json."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- BEGIN EVAL RESULTS -->"
END = "<!-- END EVAL RESULTS -->"


def number(value):
    return "not measured" if value is None else f"{value:.4f}"


def render(results):
    lines = ["Measured results from [eval/results.json](eval/results.json). "
             "Zero-denominator metrics are not measured.", ""]
    for section, label in (("agent", "Live agent"),
                           ("agent_replay_smoke", "Offline replay smoke (not model quality)")):
        data = results.get(section, {})
        if not data.get("run_at"):
            lines += [f"**{label}: not run.** No live model quality result is claimed.", ""]
            continue
        lines += [f"**{label}** — model `{data['model']}`, mode `{data['mode']}`, "
                  f"n={data['n']}/{data['expected_n']}, run `{data['run_at']}`; "
                  f"complete: {str(data['complete']).lower()}.", "",
                  "| Metric | Numerator / denominator | Rate |", "| --- | ---: | ---: |"]
        for name, metric in data["metrics"].items():
            lines.append(f"| {name.replace('_', ' ')} | {metric['numerator']} / "
                         f"{metric['denominator']} | {number(metric['value'])} |")
        lines += ["", "Failing task IDs: " + (", ".join(data["failing_ids"]) or "none") + ".", ""]
        if "quota_error_count" in data:
            lines += [f"Quota errors (excluded from accuracy): {data['quota_error_count']}; IDs: "
                      + (", ".join(data["quota_error_ids"]) or "none") + ".", ""]
    retrieval = results.get("retrieval", {})
    if retrieval:
        lines += [f"**Retrieval** — {retrieval['n']} queries, macro averages.", "",
                  "| Metric | BM25 | Hybrid |", "| --- | ---: | ---: |"]
        for metric in ("hit_at_5", "precision_at_5", "r_precision", "ndcg_at_10"):
            lines.append(f"| {metric} | {number(retrieval.get('bm25_' + metric))} | "
                         f"{number(retrieval.get('hybrid_' + metric))} |")
        lines += [""]
    faults = results.get("fault_detection", {})
    if faults:
        lines += [f"**Injected-fault classifier** — seed {faults['seed']}; "
                  "synthetic corruption and clean controls, not production accuracy.", "",
                  "| Fault | Samples | TP / injected | Precision | Recall | Diagnosis |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for fault, metric in faults["metrics"].items():
            lines.append(f"| {fault} | {metric['n']} | {metric['true_positives']} / "
                         f"{metric['injected']} | {number(metric['precision'])} | "
                         f"{number(metric['recall'])} | "
                         f"{number(metric.get('diagnosis_accuracy', {}).get('value'))} |")
        lines += ["", faults.get("note", ""), ""]
    load = results.get("load", {})
    if load:
        lines += [f"**Local stateless HTTP load** — {load['calls_per_tool']} calls/tool, "
                  f"concurrency {load['concurrency']}, Python {load['python']}; "
                  f"run `{load['run_at']}`.", "", load["definition"], "",
                  "| Tool | p50 ms | p95 ms | Successes / calls | Errors |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for tool, metric in load["tools"].items():
            lines.append(f"| {tool} | {metric['p50_ms']:.3f} | {metric['p95_ms']:.3f} | "
                         f"{metric['successes']} / {metric['n']} | {metric['errors']} |")
        lines += [""]
    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "README.md"
    original = path.read_text(encoding="utf-8")
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError("README must contain exactly one pair of results markers")
    before, rest = original.split(START)
    _, after = rest.split(END)
    results = json.loads((ROOT / "eval/results.json").read_text(encoding="utf-8"))
    updated = before + START + "\n\n" + render(results) + "\n\n" + END + after
    if args.check:
        if updated != original:
            print("README results are stale; run python scripts/render_readme.py", file=sys.stderr)
            return 1
    else:
        path.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

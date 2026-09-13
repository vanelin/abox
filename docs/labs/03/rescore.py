#!/usr/bin/env python3
"""Recompute hit@1 / hit@3 from saved results without running any model.

Usage: uv run docs/labs/03/rescore.py [questions.json]

Reads every results-*.json next to this file, takes the saved top-3 per question,
and scores it against the labels in the given questions file (default: the
revision-2 labels in questions.json; pass questions.v1.json for the original).
Prints a table and, for the default labels, checks it against rescore-v2.json.
"""

import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def score(rows, labels):
    def hit(row, k):
        return bool(set(row["top3"][:k]) & set(labels[row["q"]]["relevant_ids"]))

    def count(rs, k):
        return f"{sum(hit(r, k) for r in rs)}/{len(rs)}"

    uk = [r for r in rows if r["lang"] == "uk"]
    return {"hit1": count(rows, 1), "hit3": count(rows, 3), "uk_hit3": count(uk, 3)}


def main():
    qfile = HERE / (sys.argv[1] if len(sys.argv) > 1 else "questions.json")
    labels = {q["id"]: q for q in json.load(open(qfile))["questions"]}
    rows = {}
    for f in sorted(glob.glob(str(HERE / "results-*.json"))):
        r = json.load(open(f))
        for dim, per_q in r["details"].items():
            rows[f"{r['model']}_{dim}"] = score(per_q, labels)
        rows.setdefault("lexical_baseline", score(r["baseline_details"], labels))

    print(f"labels: {qfile.name}")
    print(f"{'variant':18} {'hit@1':>6} {'hit@3':>6} {'uk@3':>5}")
    for k, v in rows.items():
        print(f"{k:18} {v['hit1']:>6} {v['hit3']:>6} {v['uk_hit3']:>5}")

    ref = HERE / "rescore-v2.json"
    if qfile.name == "questions.json" and ref.exists():
        saved = json.load(open(ref))["rows"]
        same = all(rows[k][m] == v[m] for k, v in saved.items() for m in ("hit1", "hit3", "uk_hit3"))
        print("matches rescore-v2.json:", same)
        sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()

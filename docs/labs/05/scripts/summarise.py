#!/usr/bin/env python3
"""Summarise an explicit evaluation campaign; never select the best answer.

  uv run docs/labs/05/scripts/summarise.py --review

The manifest pins raw reports by SHA256, in attempt order. Only failed attempts
may be retried. Repetitions stay separate. Judgements are an explicit review of
assertions, bound to a raw row hash; name mentions are only diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "docs/labs/05"
AGENTS = ("xray", "nomic", "official")
TYPES = ("lookup", "graph", "facet", "negative")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def row_digest(row: dict[str, Any]) -> str:
    return digest(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())


def failed(row: dict[str, Any]) -> bool:
    return bool(row.get("error") or row.get("trace_error") or not row.get("answer"))


def select_attempts(attempts: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    for row in attempts:
        key = (row["id"], row["repeat"])
        if key in selected and not failed(selected[key]):
            raise ValueError(f"Attempt after success for {key}; use a separate campaign/repetition")
        selected[key] = row
    return selected


def tokens(row: dict[str, Any]) -> int | None:
    usage = row.get("usage_events")
    if not usage:
        return None
    return sum(u.get("promptTokenCount", 0) + u.get("candidatesTokenCount", 0) for u in usage)


def graph_method(row: dict[str, Any], seed: str | None) -> str:
    calls = row.get("tool_calls") or []
    if any(c["name"] == "get_graph_impact" and c.get("response_received") for c in calls):
        return "impact"
    for call in calls:
        if call["name"] != "get_graph_node" or call["args"].get("qn", "").split("::")[-1] != seed:
            continue
        response = (call.get("response") or {}).get("output", "{}")
        try:
            node = json.loads(response)
        except (ValueError, TypeError):
            continue
        if node.get("references_by"):
            return "incoming_edges"
    return "other"


def load_campaign(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign = json.loads(path.read_text())
    questions_bytes = (ROOT / campaign["questions"]).read_bytes()
    if digest(questions_bytes) != campaign["questions_sha256"]:
        raise ValueError("Questions changed since campaign was reviewed")
    dataset = json.loads(questions_bytes)
    if digest((ROOT / dataset["corpus"]).read_bytes()) != dataset["corpus_sha256"]:
        raise ValueError("Frozen corpus changed")
    questions = {q["id"]: q for q in dataset["questions"]}
    if set(campaign["reports"]) != set(AGENTS):
        raise ValueError("Campaign must include all three agents")
    agents = {}
    contexts: set[str] = set()
    for agent, sources in campaign["reports"].items():
        attempts = []
        excluded = []
        previous_run = ""
        for source in sources:
            raw = (ROOT / source["path"]).read_bytes()
            if digest(raw) != source["sha256"]:
                raise ValueError(f"Raw report changed: {source['path']}")
            report = json.loads(raw)
            if report["corpus_sha256"] != dataset["corpus_sha256"]:
                raise ValueError("Report uses a different corpus")
            expected_agent = "retrieval-agent" + ("" if agent == "official" else f"-{agent}")
            if report["agent"] != expected_agent or report["run_id"] <= previous_run:
                raise ValueError("Wrong agent or reports not in chronological order")
            previous_run = report["run_id"]
            for row in report["rows"]:
                item = row | {"source": source["path"], "row_sha256": row_digest(row)}
                if row["id"] in source.get("exclude_ids", []):
                    excluded.append(item)
                    continue
                q = questions[row["id"]]
                if any(row[k] != q[k] for k in ("question", "gold", "type", "language")):
                    raise ValueError(f"Question/gold mismatch: {source['path']} {row['id']}")
                context = row.get("context_id")
                if context:
                    if context in contexts:
                        raise ValueError("Conversation reused between questions/attempts")
                    contexts.add(context)
                attempts.append(item)
        selected = select_attempts(attempts)
        expected = {(qid, rep) for qid in questions for rep in range(1, campaign["repeat"] + 1)}
        if set(selected) != expected:
            raise ValueError(f"Incomplete or unexpected campaign rows for {agent}: {expected ^ set(selected)}")
        agents[agent] = {"rows": list(selected.values()), "attempts": attempts, "excluded": excluded}
    return campaign, questions, agents


def load_judgements(path: Path, agents: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(path.read_text())
    valid = {r["row_sha256"] for a in agents.values() for r in a["rows"] if not failed(r)}
    if set(data["rows"]) - valid:
        raise ValueError("Stale judgement: its raw answer/trace is not selected in this campaign")
    for judgement in data["rows"].values():
        if type(judgement["correct"]) is not bool or not judgement["reason"]:
            raise ValueError("Judgements require an explicit verdict and rationale")
        if len(judgement["claimed_repos"]) != len(set(judgement["claimed_repos"])):
            raise ValueError("Duplicate claimed repository in judgement")
    for agent, group in agents.items():
        for row in group["rows"]:
            judgement = data["rows"].get(row["row_sha256"])
            if judgement is None:
                continue
            if judgement["agent"] != agent or any(judgement[k] != row[k] for k in ("id", "repeat", "source")):
                raise ValueError("Judgement attribution differs from its raw row")
            if judgement["correct"] and set(judgement["claimed_repos"]) != set(row["gold"]):
                raise ValueError("Correct verdict contradicts its claimed repository set")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=LAB / "evaluation/evaluation-campaign.json")
    parser.add_argument("--review", action="store_true", help="show every verdict and every unreviewed row")
    args = parser.parse_args()
    campaign, questions, agents = load_campaign(args.campaign)
    reviews = load_judgements(ROOT / campaign["judgements"], agents)
    print(f"Reviewer: {reviews['reviewer']}. {reviews['rubric']}")
    print(
        "\n| agent | type | correct / total | reviewed | claimed gold | mention exact (diagnostic) "
        "| impact / incoming edges | calls mean | tokens mean* |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    attempt_notes = []
    review_notes = []
    for agent, group in agents.items():
        for kind in TYPES:
            rows = [r for r in group["rows"] if r["type"] == kind]
            good = [r for r in rows if not failed(r)]
            judged = [(r, reviews["rows"][r["row_sha256"]]) for r in good if r["row_sha256"] in reviews["rows"]]
            correct = sum(j["correct"] for _, j in judged)
            found = sum(len(set(r["gold"]) & set(j["claimed_repos"])) for r, j in judged)
            gold = sum(len(r["gold"]) for r, _ in judged)
            methods = [graph_method(r, questions[r["id"]].get("seed")) for r in good]
            usage = [tokens(r) for r in good]
            token_mean = (
                f"{statistics.mean(u for u in usage if u is not None):.0f}"
                if usage and None not in usage
                else "unknown"
            )
            calls = f"{statistics.mean(len(r['tool_calls']) for r in good):.1f}" if good else "-"
            mentions = sum(r["mention_check"]["exact_mentions"] for r in good)
            accuracy = (
                f"{correct}/{len(rows)}" if len(judged) == len(rows) else f"incomplete ({correct} verified correct)"
            )
            print(
                f"| {agent} | {kind} | {accuracy} | {len(judged)}/{len(rows)} | "
                f"{f'{found}/{gold}' if gold else 'n/a'} | {mentions}/{len(rows)} | "
                f"{methods.count('impact')}/{methods.count('incoming_edges')} | {calls} | {token_mean} |"
            )
        all_attempts = group["attempts"] + group["excluded"]
        usage = [tokens(r) for r in all_attempts]
        attempt_notes.append(
            f"{agent}: {len(all_attempts)} total attempts, {sum(failed(r) for r in all_attempts)} failed attempts, "
            f"{len(group['excluded'])} excluded old-question attempts; "
            f"recorded tokens ≥{sum(u for u in usage if u is not None)}, "
            f"unknown usage for {usage.count(None)} attempts."
        )
        if args.review:
            for row in sorted(group["rows"], key=lambda r: (r["id"], r["repeat"])):
                verdict = reviews["rows"].get(row["row_sha256"])
                status = "ERROR" if failed(row) else (str(verdict["correct"]) if verdict else "UNREVIEWED")
                review_notes.append(
                    f"{agent} {row['id']} repeat={row['repeat']}: {status}; "
                    f"{verdict['reason'] if verdict else row.get('error')}; source={row['source']}"
                )
    print("\n" + "\n\n".join(attempt_notes))
    if review_notes:
        print("\n" + "\n".join(review_notes))
    print(
        "\n*Token means cover selected successful answers only; totals include failed and excluded attempts. "
        "Tokens are reported usage, not billing. One sample per question is not a significance test. "
        "Prompts, embeddings and available data/tools differ: this compares configured agents."
    )


if __name__ == "__main__":
    main()

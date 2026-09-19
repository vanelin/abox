#!/usr/bin/env python3
"""Lab 5: ask the real kagent agent over A2A and retain its tool trace.

  kubectl -n kagent port-forward svc/kagent-controller 8083:8083
  uv run docs/labs/05/scripts/agentic.py ask xray --ids l02,g01,n02
  uv run docs/labs/05/scripts/agentic.py ask xray
  uv run docs/labs/05/scripts/agentic.py ask xray --repeat 3

Only question text goes to the agent: no gold, seed, filter or evaluator note.
Each question/repetition starts a new conversation. Shared memory is NOT reset:
recall can see existing notes and any remember/forget calls are recorded.

Reports have unique filenames under .local/lab05/ and are checkpointed after
each question. --output selects a new file; existing reports are never replaced.
Fill correct, grounded, handled_conflict and note by hand. mention_check only
compares repository names mentioned in prose; negations, citations and unknown
invented names require human judgement. It never sets correct automatically.

Tool calls/arguments/responses and token usage come from kagent session events,
not from the agent's description of what it did. Raw A2A and session responses
are retained. Missing traces are errors, never silently reported as zero calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "docs/labs/05"
AGENTS = {"xray": "retrieval-agent-xray", "nomic": "retrieval-agent-nomic", "official": "retrieval-agent"}
TERMINAL = {"completed", "failed", "canceled", "rejected", "input-required", "auth-required"}


def rpc(url: str, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    response = requests.post(
        url, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, timeout=timeout
    )
    response.raise_for_status()
    body = response.json()
    if body.get("id") != request_id:
        raise ValueError("A2A response ID does not match request")
    if "error" in body:
        raise RuntimeError(f"A2A {method}: {body['error']}")
    if not isinstance(body.get("result"), dict):
        raise ValueError("A2A response has no result object")
    return body


def send(url: str, question: str, timeout: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    message = {
        "kind": "message",
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": question}],
    }
    responses = [rpc(url, "message/send", {"message": message, "configuration": {"blocking": True}}, timeout)]
    while True:
        result = responses[-1]["result"]
        if result.get("kind") == "message" or result.get("status", {}).get("state") in TERMINAL:
            return responses
        if result.get("kind") != "task" or not result.get("id"):
            raise ValueError("Unrecognized A2A result")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # Preserve the task/context IDs; the caller records its incomplete status.
            return responses
        time.sleep(min(1, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return responses
        responses.append(rpc(url, "tasks/get", {"id": result["id"]}, remaining))


def answer_text(result: dict[str, Any]) -> str:
    def text(message: dict[str, Any]) -> str:
        return "\n".join(p["text"] for p in message.get("parts", []) if p.get("kind") == "text").strip()

    if result.get("kind") == "message":
        return text(result)
    answer = "\n".join(filter(None, (text(a) for a in result.get("artifacts", []))))
    if answer:
        return answer
    status_message = result.get("status", {}).get("message", {})
    if status_message.get("role") == "agent" and text(status_message):
        return text(status_message)
    for message in reversed(result.get("history", [])):
        if message.get("role") == "agent" and text(message):
            return text(message)
    return ""


def parse_trace(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        raise ValueError("Session has no events; tool trace is unavailable")
    calls = []
    responses = {}
    usage = []
    seen = set()
    for event in events:
        if event["id"] in seen:
            continue
        seen.add(event["id"])
        data = json.loads(event["data"]) if isinstance(event["data"], str) else event["data"]
        if data.get("UsageMetadata"):
            usage.append({"event_id": event["id"], **data["UsageMetadata"]})
        for part in (data.get("Content") or {}).get("parts", []):
            if "functionCall" in part:
                call = part["functionCall"]
                calls.append(
                    {
                        "id": call["id"],
                        "name": call["name"],
                        "args": call.get("args", {}),
                        "event_id": event["id"],
                        "timestamp": event.get("created_at"),
                    }
                )
            if "functionResponse" in part:
                response = part["functionResponse"]
                responses[response["id"]] = response.get("response")
    for call in calls:
        call["response_received"] = call["id"] in responses
        call["response"] = responses.get(call["id"])
    return {"tool_calls": calls, "usage_events": usage}


def mention_check(answer: str, repos: list[str], gold: list[str], ordered: bool) -> dict[str, Any]:
    matches = []
    for name in repos:
        # "vanelin's profile" names the owner, not the repository called vanelin.
        match = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-]|['’]s\b)", answer)
        if match:
            matches.append((match.start(), name))
    names = [name for _, name in sorted(matches)]
    return {
        "mentioned": names,
        "missing": sorted(set(gold) - set(names)),
        "extra": sorted(set(names) - set(gold)),
        "exact_mentions": names == gold if ordered else set(names) == set(gold),
        "requires_human_review": True,
    }


def save(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def ask(args: argparse.Namespace) -> int:
    question_bytes = (LAB / "data/questions.json").read_bytes()
    dataset = json.loads(question_bytes)
    corpus_bytes = (ROOT / dataset["corpus"]).read_bytes()
    if hashlib.sha256(corpus_bytes).hexdigest() != dataset["corpus_sha256"]:
        raise ValueError("Frozen corpus SHA256 differs from questions.json")
    questions = dataset["questions"]
    if args.ids:
        wanted = set(args.ids.split(","))
        unknown = wanted - {q["id"] for q in questions}
        if unknown:
            raise ValueError(f"Unknown question IDs: {sorted(unknown)}")
        questions = [q for q in questions if q["id"] in wanted]
    repos = [e["name"] for e in json.loads(corpus_bytes)["entries"] if e["kind"] == "Repo"]
    agent = AGENTS[args.toolset]
    url = f"{args.url.rstrip('/')}/api/a2a/kagent/{agent}"
    card_response = requests.get(url + "/.well-known/agent-card.json", timeout=15)
    card_response.raise_for_status()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    out = args.output or ROOT / f".local/lab05/agentic-{args.toolset}-{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "run_id": run_id,
        "agent": agent,
        "agent_card": card_response.json(),
        "url": url,
        "corpus_sha256": dataset["corpus_sha256"],
        "questions_sha256": hashlib.sha256(question_bytes).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "method": "Fresh context per question/repetition; only question text sent; shared memory not reset. "
        "Gold and mention checks are evaluator-only. Token usage is reported by kagent, not billing data.",
        "selected_ids": [q["id"] for q in questions],
        "repeat": args.repeat,
        "rows": [],
    }
    with out.open("x") as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    errors = 0
    contexts: set[str] = set()
    for repetition in range(1, args.repeat + 1):
        for q in questions:
            row: dict[str, Any] = {
                "id": q["id"],
                "repeat": repetition,
                "type": q["type"],
                "language": q["language"],
                "question": q["question"],
                "gold": q["gold"],
                "answer": "",
                "error": None,
                "tool_calls": None,
                "trace_error": None,
                "correct": None,
                "grounded": None,
                "handled_conflict": None,
                "note": "",
            }
            started = time.perf_counter()
            try:
                row["a2a_responses"] = send(url, q["question"], args.timeout)
                result = row["a2a_responses"][-1]["result"]
                row["task_id"] = result.get("id")
                row["context_id"] = result.get("contextId")
                row["state"] = result.get("status", {}).get("state", "message")
                row["answer"] = answer_text(result)
                if row["state"] not in ("completed", "message") or not row["answer"]:
                    row["error"] = f"Incomplete or empty answer (state={row['state']})"
                if not row["context_id"] or row["context_id"] in contexts:
                    raise ValueError("Missing or reused contextId; conversation isolation not verified")
                contexts.add(row["context_id"])
                row["answer_seconds"] = round(time.perf_counter() - started, 3)
                try:
                    response = requests.get(
                        f"{args.url.rstrip('/')}/api/sessions/{quote(row['context_id'], safe='')}",
                        params={"order": "asc"},
                        timeout=30,
                    )
                    response.raise_for_status()
                    row["session_response"] = response.json()
                    row.update(parse_trace(row["session_response"]["data"]["events"]))
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    row["trace_error"] = str(exc)
                row["mention_check"] = mention_check(row["answer"], repos, q["gold"], "order" in q.get("args", {}))
            except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError) as exc:
                # Do not retry an uncertain POST: it may already have incurred LLM/tool calls.
                row["error"] = str(exc)
            row["seconds"] = round(time.perf_counter() - started, 3)
            failed = bool(row["error"] or row["trace_error"])
            errors += int(failed)
            report["rows"].append(row)
            save(out, report)
            print(f"{q['id']} run={repetition} {row['seconds']}s {'ERROR' if failed else 'recorded'}", file=sys.stderr)
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["errors"] = errors
    save(out, report)
    print(f"{len(report['rows'])} answers, {errors} errors: {out}; judge the null fields by hand")
    return int(errors > 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["ask"])
    parser.add_argument("toolset", choices=sorted(AGENTS))
    parser.add_argument("--url", default="http://127.0.0.1:8083")
    parser.add_argument("--ids", help="comma-separated question IDs; defaults to all 29")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180, help="seconds per answer")
    parser.add_argument("--output", type=Path, help="new report path; must not exist")
    args = parser.parse_args()
    if args.repeat < 1 or args.timeout < 1:
        parser.error("--repeat and --timeout must be positive")
    return ask(args)


if __name__ == "__main__":
    sys.exit(main())

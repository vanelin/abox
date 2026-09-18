#!/usr/bin/env python3
"""Lab 4: drive the retrieval agents through kagent's A2A endpoint.

The agentic pass is the same conversation the kagent UI would have -- same
Agent, prompt, model and tools -- sent over the A2A JSON-RPC API instead of
typed by hand. Nothing is bypassed: every store, find and Cypher call is the
agent's own decision. The script only replaces the clicking, so three agents
x (37 objects + 10 questions) is repeatable.

  kubectl -n kagent port-forward svc/kagent-controller 8083:8083

  uv run docs/labs/04/agentic.py ingest official        # one message per object, 27 objects
  uv run docs/labs/04/agentic.py ingest official --retry   # only the objects that failed last time
  uv run docs/labs/04/agentic.py ask official           # one conversation per question
  uv run docs/labs/04/agentic.py ask official --ids q02,q06

`ingest` sends one message per object -- "Ingest Agent helm-agent in
namespace kagent" -- because a single "ingest all Agents" message made the
model stop after one or two objects and rationalise why; per-object
messages keep the loop out of the model. `ask` sends each of the ten
lab 3 questions in its own conversation and writes the answers to
.local/lab04/agentic-<toolset>.json with `correct` left null, to be judged
by hand (docs/labs/04/README.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[3]
LAB3 = ROOT / "docs" / "labs" / "03"
OUT_DIR = ROOT / ".local" / "lab04"

AGENTS = {"official": "retrieval-agent", "nomic": "retrieval-agent-nomic", "qwen": "retrieval-agent-qwen"}

# What the agents ingest: the declared objects of this release, by kubectl
# plural type. Namespace "" means all namespaces (the agent lists with -A).
# (plural, namespace or "" for all, kind, name filter or None). The chart's
# five other agents are skipped: 7KB of system prompt each, relayed through
# two models, and nothing in the questions needs them.
OBJECTS: list[tuple[str, str, str, set[str] | None]] = [
    (
        "agents.kagent.dev",
        "kagent",
        "Agent",
        {"k8s-agent", "retrieval-agent", "retrieval-agent-nomic", "retrieval-agent-qwen"},
    ),
    ("modelconfigs.kagent.dev", "kagent", "ModelConfig", None),
    ("mcpservers.kagent.dev", "kagent", "MCPServer", None),
    ("helmreleases.helm.toolkit.fluxcd.io", "", "HelmRelease", None),
    ("ocirepositories.source.toolkit.fluxcd.io", "flux-system", "OCIRepository", {"releases"}),
    ("kustomizations.kustomize.toolkit.fluxcd.io", "flux-system", "Kustomization", None),
]


def send(base: str, agent: str, text: str, context_id: str | None, timeout: int) -> tuple[str, str]:
    """message/send; returns (answer text, contextId)."""
    msg: dict[str, Any] = {
        "role": "user",
        "kind": "message",
        "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}],
    }
    if context_id:
        msg["contextId"] = context_id
    body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "message/send", "params": {"message": msg}}
    r = requests.post(f"{base}/api/a2a/kagent/{agent}", json=body, timeout=timeout)
    r.raise_for_status()
    res = r.json()
    if "error" in res:
        raise RuntimeError(f"{agent}: {res['error']}")
    task = res["result"]
    texts = [p["text"] for a in task.get("artifacts", []) for p in a.get("parts", []) if p.get("kind") == "text"]
    if not texts:
        texts = [
            p["text"]
            for m in task.get("history", [])
            if m.get("role") == "agent"
            for p in m.get("parts", [])
            if p.get("kind") == "text"
        ]
    return "\n".join(texts).strip(), task.get("contextId", "")


def list_names(plural: str, namespace: str) -> list[tuple[str, str]]:
    import subprocess

    jp = "jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name}{'\\n'}{end}"
    cmd = ["kubectl", "get", plural, "-o", jp]
    cmd += ["-n", namespace] if namespace else ["-A"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    pairs = []
    for line in out.splitlines():
        if line.strip():
            ns, name = line.split("/", 1)
            pairs.append((ns, name))
    return pairs


def ingest(args: argparse.Namespace) -> int:
    agent = AGENTS[args.toolset]
    out = OUT_DIR / f"agentic-ingest-{args.toolset}.json"
    done: dict[tuple[str, str], dict[str, Any]] = {}
    if args.retry and out.exists():
        for o in json.loads(out.read_text())["objects"]:
            if o["ok"] and o["answer"]:
                done[(o["kind"], o["name"])] = o
    log = list(done.values())
    t_all = time.perf_counter()
    for plural, ns, kind, only in OBJECTS:
        for obj_ns, name in list_names(plural, ns):
            if only and name not in only:
                continue
            if (kind, name) in done:
                continue
            text = (
                f"Ingest one object: {kind} {name} in namespace {obj_ns} "
                f"(kubectl type {plural}). Create its vector and its graph node and edges. "
                f"One store call. Reply with one line: stored or failed, and why."
            )
            t0 = time.perf_counter()
            try:
                answer, _ = send(args.url, agent, text, None, args.timeout)
                head = answer.lower().lstrip()[:200]
                ok = bool(answer) and (head.startswith("stored") or "failed" not in head)
            except Exception as e:  # noqa: BLE001 - record and continue, the run is the measurement
                answer, ok = f"error: {e}", False
            dt = round(time.perf_counter() - t0, 1)
            log.append(
                {"kind": kind, "name": name, "namespace": obj_ns, "ok": ok, "seconds": dt, "answer": answer[:500]}
            )
            print(f"{'ok ' if ok else 'ERR'} {dt:6.1f}s {kind}/{name}: {answer[:100]!r}", file=sys.stderr)
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"agent": agent, "objects": log}, indent=1))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {"agent": agent, "seconds": round(time.perf_counter() - t_all, 1), "objects": log}
    out.write_text(json.dumps(summary, indent=1))
    print(f"{sum(o['ok'] for o in log)}/{len(log)} ok, written {out}")
    return 0


def ask(args: argparse.Namespace) -> int:
    agent = AGENTS[args.toolset]
    questions = json.loads((LAB3 / "questions.json").read_text())["questions"]
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    out_path = OUT_DIR / f"agentic-{args.toolset}.json"
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        try:
            answer, ctx = send(args.url, agent, q["question"], None, args.timeout)
        except Exception as e:  # noqa: BLE001
            answer, ctx = f"error: {e}", ""
        dt = round(time.perf_counter() - t0, 1)
        rows.append(
            {
                "id": q["id"],
                "language": q["language"],
                "question": q["question"],
                "relevant_ids": q["relevant_ids"],
                "context_id": ctx,
                "seconds": dt,
                "answer": answer,
                "answered_from_ids": [],
                "correct": None,
                "tool_calls": None,
                "note": "",
            }
        )
        print(f"{q['id']} {dt:6.1f}s {answer[:120]!r}", file=sys.stderr)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"written {out_path}; judge correct / answered_from_ids / tool_calls by hand")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["ingest", "ask"])
    p.add_argument("toolset", choices=sorted(AGENTS))
    p.add_argument("--url", default="http://127.0.0.1:8083", help="kagent controller (port-forward 8083)")
    p.add_argument("--timeout", type=int, default=600, help="seconds per message")
    p.add_argument("--ids", help="ask: comma-separated question ids, e.g. q02,q06 (default all ten)")
    p.add_argument("--retry", action="store_true", help="ingest: skip objects already ok in the previous run's file")
    args = p.parse_args()
    return ingest(args) if args.command == "ingest" else ask(args)


if __name__ == "__main__":
    sys.exit(main())

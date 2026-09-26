"""Lab 7 runs A, B, C through kagent's A2A endpoint, the same messages the UI sends.

Run from the repo root: uv run docs/labs/07/scripts/runs.py
Needs: kubectl -n kagent port-forward svc/kagent-controller 8083:8083
Writes: .local/lab07/runs.json (agent, message, answer, context, start/end UTC).
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docs" / "labs" / "04"))
from agentic import send  # noqa: E402  # pyright: ignore[reportMissingImports]

BASE = "http://127.0.0.1:8083"
OUT = ROOT / ".local" / "lab07" / "runs.json"

INGEST = [
    ("Agent", "helm-agent", "agents.kagent.dev"),
    ("Agent", "k8s-agent", "agents.kagent.dev"),
    ("ModelConfig", "default-model-config", "modelconfigs.kagent.dev"),
]
QUESTIONS = ["Which agents use the model config default-model-config?", "Which model does k8s-agent use?"]
SESSION = [
    "Which repositories use Terraform?",
    "Which of them also use Kubernetes?",
    "Remember that I plan to archive the oldest of them.",
]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run(log: list, run_id: str, agent: str, text: str, context: str | None = None) -> str:
    start = now()
    try:
        answer, ctx = send(BASE, agent, text, context, 600)
    except Exception as e:  # recorded, the run goes on
        answer, ctx = f"ERROR: {e}", context or ""
    log.append({"run": run_id, "agent": agent, "message": text, "answer": answer,
                "context": ctx, "start": start, "end": now()})
    OUT.write_text(json.dumps(log, indent=2))
    print(f"{run_id} {agent}: {answer[:100]!r}", flush=True)
    return ctx


def main() -> None:
    log: list = []
    for agent in ("retrieval-agent", "retrieval-agent-nomic"):
        for kind, name, plural in INGEST:
            run(log, "A-ingest", agent,
                f"Ingest one object: {kind} {name} in namespace kagent (kubectl type {plural}). "
                "Create its vector and its graph node and edges. Reply with one line: stored or failed, and why.")
        for q in QUESTIONS:
            run(log, "A-question", agent, q)  # no context: a new chat per question
    ctx = None
    for q in SESSION:
        ctx = run(log, "B-session", "retrieval-agent-xray", q, ctx)
    run(log, "C-failure", "k8s-agent", "Get the YAML of agent does-not-exist in namespace kagent.")


if __name__ == "__main__":
    main()

# Lab 4: agentic retrieval, two Qdrant MCP toolsets

[ADR-0003](../../adr/0003-agentic-retrieval.md) compares the official Qdrant MCP server with the course's Go `qdrant-mcp` on the same corpus, under the same agent prompt and model. This folder holds the script for the tool-level pass; the agentic pass is judged by hand. Run commands from the repository root.

## Toolsets

| Toolset | Server | MCPServer | Embedding model | Dims | Collection | Tools |
|---|---|---|---|---:|---|---|
| `official` | qdrant/mcp-server-qdrant 0.8.1, run with uvx | `qdrant-mcp-official` | sentence-transformers/all-MiniLM-L6-v2 (fastembed, in-pod ONNX) | 384 | `abox-minilm` | `qdrant-store` / `qdrant-find` |
| `nomic` | ours, [mcp/qdrant-mcp](../../../mcp/qdrant-mcp) | `qdrant-mcp` | nomic-embed-text-v1.5 over llama.cpp | 768 | `abox-nomic` | `vector_store` / `vector_find` |

Both are declared in [releases/mcp-servers.yaml](../../../releases/mcp-servers.yaml). The two vector spaces are different, so each toolset keeps its own collection; a vector written by one is meaningless to the other. The two agents in [releases/agent-retrieval.yaml](../../../releases/agent-retrieval.yaml) — `retrieval-agent` (official) and `retrieval-agent-nomic` — share one system prompt and `default-model-config`, so only the toolset differs.

## Prerequisites

A cluster running this branch's release (`make push`, then `flux get all -A` Ready and `kubectl -n kagent get mcpserver`), `uv sync`, and three port-forwards. kmcp serves each MCPServer as `<name>.kagent:3000`, streamable HTTP at `/mcp`:

```bash
kubectl -n kagent port-forward svc/qdrant-mcp-official 3001:3000
kubectl -n kagent port-forward svc/qdrant-mcp 3002:3000
kubectl -n qdrant port-forward svc/qdrant 6333:6333
```

The official server downloads its ONNX model from HuggingFace on first start, so give the pod a minute and the kind nodes egress (`make fix-egress`).

## Score a toolset

```bash
uv run docs/labs/04/eval.py official --reset --qdrant http://127.0.0.1:6333 --ingest
uv run docs/labs/04/eval.py nomic --reset --qdrant http://127.0.0.1:6333 --ingest
uv run docs/labs/04/eval.py official --ingest
uv run docs/labs/04/eval.py official
```

The first form is the clean run: drop the collection through Qdrant's REST API, store all 144 chunks, then search. Use it whenever the corpus may already be in there — neither server deduplicates, every store call mints a new point, so a second `--ingest` (third form) leaves a duplicated corpus behind. The last form only searches what is already stored. `--url http://127.0.0.1:8000/mcp/` points the script at a server outside the cluster.

The script stores each [frozen lab 3 chunk](../03/chunks.jsonl) once with `{id, path, kind, start, end}` as metadata and asks each of the [ten labelled questions](../03/questions.json) once, so the measurement isolates the toolset — tool contract, embedding model, collection — from the model driving the agent.

## What the output means

Results are printed and written to gitignored `.local/lab04/results-<toolset>.json`.

| Field | Meaning |
|---|---|
| `hit@1` / `hit@3` | Questions whose labelled answer is the first result / among the first three |
| `uk_hit@3` | `hit@3` over the three Ukrainian questions only |
| `ingest_seconds` | Wall clock for storing all 144 chunks through the store tool; `null` without `--ingest` |
| `find_p50_s` / `find_max_s` | Per-question find latency over ten calls, port-forward included |
| `unparsed_results` | Questions that returned nothing the script could parse; must be `0` or the scores are meaningless |

Ten questions decide nothing on their own; read the per-question top-3 next to the scores.

## Agentic pass

The script calls the tools directly. The agentic pass asks the same ten questions to each Agent and judges the answer, which is what the lab is actually about: the model chooses the query, may search again, and may answer from the wrong hit.

Ingest first — ask the agent to ingest, it delegates to `k8s-agent` for the manifests — then ask each question in the kagent UI, in the question's own language, one conversation per question. `kagent invoke --agent retrieval-agent --task "<question>"` should do the same from a shell; that CLI form is unverified here.

Record one judgement per question by hand in `.local/lab04/agentic-<toolset>.json`:

```json
[
  {
    "id": "q02",
    "answered_from_ids": ["releases/kagent.yaml:16-90"],
    "correct": true,
    "tool_calls": 1,
    "note": "cited the postRenderer block; one qdrant-find call"
  }
]
```

`answered_from_ids` are the chunk ids the agent cited, mapped from the metadata it quotes; `correct` is the hit@1 equivalent — the answer is right and came from a labelled chunk; `tool_calls` counts store/find calls in that conversation. Judging is manual and subjective, so note why.

```bash
uv run ruff check docs/labs/04
uv run ruff format --check docs/labs/04
uv run pyright
```

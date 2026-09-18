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

Three agents, one prompt, one ModelConfig (`openai-gpt-5-4-mini`, [releases/model-configs.yaml](../../../releases/model-configs.yaml)): `retrieval-agent` (official), `retrieval-agent-nomic`, `retrieval-agent-qwen`. All three also carry `neo4j-mcp` with an identical Graph section, so the graph is a constant, not a variable. Ingest is delegated to `k8s-agent` -- our own, in [releases/agent-retrieval.yaml](../../../releases/agent-retrieval.yaml), replacing the chart's: the chart's prompt summarises tool output into prose and never returned a manifest; ours relays raw output verbatim and has only read tools plus labels, annotations and a connectivity check.

[agentic.py](agentic.py) drives the agents over kagent's A2A endpoint -- the same conversation the UI has, without the clicking:

```bash
kubectl -n kagent port-forward svc/kagent-controller 8083:8083

uv run docs/labs/04/agentic.py ingest official   # one message per object, 38 objects
uv run docs/labs/04/agentic.py ask official      # one conversation per question
```

`ingest` sends one message per declared object of this release (Agents, ModelConfigs, MCPServers, HelmReleases, OCIRepositories, Kustomizations) and records each reply in `.local/lab04/agentic-ingest-<toolset>.json`. One message per object, not one "ingest all Agents": given the list, the model stopped after one or two objects and rationalised why -- the loop belongs outside the model. Before an ingest, empty that toolset's collection and the graph, and create the collection with the schema its server expects: the official server writes a named vector, `fast-all-minilm-l6-v2`, and fails with 400 on a collection created without it; the Go server writes the default unnamed vector.

```bash
curl -s -X DELETE localhost:6333/collections/abox-minilm
curl -s -X PUT localhost:6333/collections/abox-minilm -H 'Content-Type: application/json' \
  -d '{"vectors":{"fast-all-minilm-l6-v2":{"size":384,"distance":"Cosine"}}}'
curl -s -X PUT localhost:6333/collections/abox-nomic -H 'Content-Type: application/json' -d '{"vectors":{"size":768,"distance":"Cosine"}}'
curl -s -X PUT localhost:6333/collections/abox-qwen256 -H 'Content-Type: application/json' -d '{"vectors":{"size":256,"distance":"Cosine"}}'
kubectl -n neo4j exec neo4j-0 -- cypher-shell -u neo4j -p abox-neo4j "MATCH (n) DETACH DELETE n"
```

Audit what landed rather than what the agent reported -- the report and the store disagreed more than once:

```bash
curl -s localhost:6333/collections/abox-minilm/points/scroll -H 'Content-Type: application/json' \
  -d '{"limit":100,"with_payload":true,"with_vector":false}' | jq -r '.result.points[].payload | (.metadata // .) | "\(.kind)/\(.name)"' | sort | uniq -c
kubectl -n neo4j exec neo4j-0 -- cypher-shell -u neo4j -p abox-neo4j "MATCH (a)-[r]->(b) RETURN type(r), a.name, b.kind+'/'+b.name"
```

`ask` writes `.local/lab04/agentic-<toolset>.json` with the answer per question and the judgement fields empty. Fill them by hand:

```json
[
  {
    "id": "q02",
    "answer": "...",
    "answered_from_ids": ["releases/kagent.yaml:16-90"],
    "correct": true,
    "tool_calls": 1,
    "note": "cited the postRenderer block; one qdrant-find call"
  }
]
```

`answered_from_ids` are the chunk ids the agent cited, mapped from the metadata it quotes; `correct` is the hit@1 equivalent -- the answer is right and came from a labelled chunk; `tool_calls` counts store/find calls in that conversation (read them in the kagent UI, the conversation is listed under the agent). Judging is manual and subjective, so note why. Three of the ten questions ask about Makefile, setup.sh and fix-egress.sh, which are not cluster objects and cannot be in an agent-ingested store; "nothing relevant stored" is the right answer there and is judged as such, not as a miss.

```bash
uv run ruff check docs/labs/04
uv run ruff format --check docs/labs/04
uv run pyright
```

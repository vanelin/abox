# Lab 4: agentic retrieval, three Qdrant MCP toolsets

Runbook for [ADR-0003](../../adr/0003-agentic-retrieval.md), which holds the results and the decision. [eval.py](eval.py) scores a toolset directly (tool level); [agentic.py](agentic.py) drives the agents (agentic level). Run commands from the repository root.

## Toolsets

| Toolset | MCPServer | Agent | Embedding | Dims | Collection | Tools |
|---|---|---|---|---:|---|---|
| `official` | `qdrant-mcp-official` (mcp-server-qdrant 0.8.1, uvx) | `retrieval-agent` | all-MiniLM-L6-v2, fastembed in the pod | 384 | `abox-minilm` | `qdrant-store` / `qdrant-find` |
| `nomic` | `qdrant-mcp` ([ours](../../../mcp/qdrant-mcp), 0.5.0) | `retrieval-agent-nomic` | nomic-embed-text-v1.5 over llama.cpp | 768 | `abox-nomic` | `vector_store` / `vector_find` |
| `qwen` | `qdrant-mcp-qwen` (same image) | `retrieval-agent-qwen` | Qwen3-Embedding-0.6B Q8_0 over llama.cpp, 256 of 1024 | 256 | `abox-qwen256` | same |

Declared in [releases/mcp-servers.yaml](../../../releases/mcp-servers.yaml), [agent-retrieval.yaml](../../../releases/agent-retrieval.yaml), [model-configs.yaml](../../../releases/model-configs.yaml) and [llama-cpp-qwen.yaml](../../../releases/llama-cpp-qwen.yaml). The three agents share one prompt, one ModelConfig (`gpt-5.4-mini`) and the same `neo4j-mcp` graph section, so only the vector toolset differs. Vector spaces are not interchangeable: one collection per toolset.

Ingest is delegated to `k8s-agent` — ours, not the chart's (disabled in [kagent.yaml](../../../releases/kagent.yaml)): the chart's hardcoded prompt summarises tool output and never returned a manifest. Ours relays raw output verbatim, runs on `gpt-5.4-nano`, and has read tools plus labels, annotations and a connectivity check.

## Cold start

`make run` brings the cluster up and calls `make secrets`, which creates Secret `kagent-openai` from `OPENAI_API_KEY` in the environment (a Codespaces Secret on Codespaces); the key never touches a file. Two things to check on a fresh cluster:

```bash
kubectl -n kagent get agent | grep -E "retrieval|k8s-agent"    # all Accepted=True
```

- `Accepted=False … Agent "k8s-agent" not found`: the retrieval agents compiled in the gap between Helm removing the chart's agent and Flux creating ours, and the controller does not requeue them — `kubectl -n kagent rollout restart deploy/kagent-controller`.
- Agents read the key at pod start. After `make secrets` on a running cluster: `kubectl -n kagent rollout restart deploy/k8s-agent deploy/retrieval-agent deploy/retrieval-agent-nomic deploy/retrieval-agent-qwen`.

Port-forwards (kmcp serves each MCPServer at `<name>.kagent:3000/mcp`):

```bash
kubectl -n kagent port-forward svc/qdrant-mcp-official 3001:3000 &
kubectl -n kagent port-forward svc/qdrant-mcp 3002:3000 &
kubectl -n kagent port-forward svc/qdrant-mcp-qwen 3003:3000 &
kubectl -n qdrant port-forward svc/qdrant 6333:6333 &
kubectl -n kagent port-forward svc/kagent-controller 8083:8083 &   # A2A, for agentic.py
kubectl -n kagent port-forward svc/kagent-ui 8080:8080 &
```

The official server pulls its ONNX model from HuggingFace on first start: give it a minute and the kind nodes egress (`make fix-egress`).

## Tool level

```bash
uv run docs/labs/04/eval.py official --reset --qdrant http://127.0.0.1:6333 --ingest
uv run docs/labs/04/eval.py nomic    --reset --qdrant http://127.0.0.1:6333 --ingest
uv run docs/labs/04/eval.py qwen     --reset --qdrant http://127.0.0.1:6333 --ingest   # ~4.5 min
uv run docs/labs/04/eval.py official            # search only
```

`--reset` drops the collection first. Use it whenever the corpus may already be there: no server deduplicates, every store mints a new point. `--url` points at a server outside the cluster. The script stores each [frozen lab 3 chunk](../03/chunks.jsonl) once with `{id, path, kind, start, end}` and asks each of the [ten labelled questions](../03/questions.json) once, so the score isolates the toolset from the model driving an agent.

Results go to gitignored `.local/lab04/results-<toolset>.json`:

| Field | Meaning |
|---|---|
| `hit@1` / `hit@3` | Labelled answer first / in the top three |
| `uk_hit@3` | `hit@3` over the three Ukrainian questions |
| `ingest_seconds` | Wall clock for 144 store calls; `null` without `--ingest` |
| `find_p50_s` / `find_max_s` | Find latency, port-forward included |
| `unparsed_results` | Must be `0`, or the scores are meaningless |

Ten questions decide nothing on their own; read the per-question top-3 next to the scores.

## Agentic level

The model chooses the query, may search again, and may answer from the wrong hit — which is what the lab is about. `agentic.py` sends the same conversations the UI would, over kagent's A2A endpoint; every store, find and Cypher call is still the agent's decision.

**1. Prepare memory.** Empty the collections and the graph, and create each collection with the schema its server expects — the official server writes a *named* vector and fails with 400 without it:

```bash
for c in abox-minilm abox-nomic abox-qwen256; do curl -s -X DELETE localhost:6333/collections/$c; done
curl -s -X PUT localhost:6333/collections/abox-minilm -H 'Content-Type: application/json' \
  -d '{"vectors":{"fast-all-minilm-l6-v2":{"size":384,"distance":"Cosine"}}}'
curl -s -X PUT localhost:6333/collections/abox-nomic   -H 'Content-Type: application/json' -d '{"vectors":{"size":768,"distance":"Cosine"}}'
curl -s -X PUT localhost:6333/collections/abox-qwen256 -H 'Content-Type: application/json' -d '{"vectors":{"size":256,"distance":"Cosine"}}'
kubectl -n neo4j exec neo4j-0 -- cypher-shell -u neo4j -p abox-neo4j "MATCH (n) DETACH DELETE n"
```

Creating them up front also avoids a race: an agent issues store calls in parallel, and the official server answers all but one with `409 Collection already exists`.

**2. Ingest.** One message per object, 27 declared objects of this release (4 Agents, ModelConfigs, MCPServers, HelmReleases, the `releases` OCIRepository, Kustomizations); ~40 s each. The three toolsets can run in parallel; run `--retry` one at a time, since the delegate's 200k TPM limit is what fails a parallel run:

```bash
uv run docs/labs/04/agentic.py ingest official          # also: nomic, qwen
uv run docs/labs/04/agentic.py ingest official --retry  # only what failed; repeat until 27/27
```

Replies are recorded in `.local/lab04/agentic-ingest-<toolset>.json`. One message per object, not "ingest all Agents": given a list, the model stopped after one or two objects and rationalised why. Do not change an agent or MCPServer during a run — the rollout kills the in-flight message.

**3. Audit.** The report and the store disagreed more than once (invented objects, a manifest stored under a neighbour's name, a store that succeeded while the agent saw a timeout). Check what landed:

```bash
curl -s localhost:6333/collections/abox-minilm/points/scroll -H 'Content-Type: application/json' \
  -d '{"limit":300,"with_payload":true,"with_vector":false}' \
  | jq -r '.result.points[].payload | (.metadata // .) | "\(.kind)/\(.name)"' | sort | uniq -c
kubectl -n neo4j exec neo4j-0 -- cypher-shell -u neo4j -p abox-neo4j \
  "MATCH (a)-[r]->(b) RETURN type(r), a.kind+'/'+a.name, b.kind+'/'+b.name ORDER BY 1,2"
```

Expect 27 distinct objects per collection (the Go server adds points for chunks; duplicates share `kind/name` but differ in `doc`), and edges equal to the cluster's `dependsOn`, `chartRef` / `sourceRef`, `modelConfig` and `tools`.

**4. Ask and judge.**

```bash
uv run docs/labs/04/agentic.py ask official --ids q02,q06   # or all ten without --ids
```

One conversation per question; answers land in `.local/lab04/agentic-<toolset>.json` with the judgement fields empty. Fill by hand: `correct` (right, and from a relevant object), `answered_from_ids`, `tool_calls` (find calls, visible in the kagent UI), `note` (why). q02 and q06 are the two questions answerable from cluster objects; the three about Makefile, setup.sh and fix-egress.sh cannot be in an agent-ingested store, and "nothing relevant stored" is the right answer there.

The same check by hand in the UI (http://localhost:8080), a new conversation per question: `Why does kagent need a postRenderer?`, `Звідки Flux отримує маніфести застосунків?`, and for the graph `What does the kagent HelmRelease depend on, and where is its chart sourced from?` Expect two find calls per question, and `read-cypher` for the last.

## Settings that exist because an agent broke the default

| Setting | Where | Why |
|---|---|---|
| `timeout: 120s` / `300s` | MCPServer `qdrant-mcp`, `qdrant-mcp-qwen` | kmcp's client default is 30 s; one 1500-token chunk is ~35 s in Qwen on this CPU |
| `EMBEDDING_MAX_INPUT_CHARS: 3500` | both Go servers | the default 7000 characters of YAML overflow a 2048-token slot |
| `EMBEDDINGS_TIMEOUT_SECONDS: 300` | `qdrant-mcp-qwen` | parallel stores queue behind each other |
| `--cache-ram 0`, `--parallel 2`, `--ubatch-size 512`, 2Gi | `llama-cpp-qwen` | llama.cpp `server-b10920` keeps an 8 GiB RAM prompt cache by default, a linear leak under embedding traffic; parallel stores filled two full micro-batches |
| no `providers.openAI.apiKey` | `kagent.yaml` | with it the chart renders Secret `kagent-openai` and every Helm upgrade overwrites the real key |
| no `{` `}` in a system prompt | `agent-retrieval.yaml` | kagent treats the prompt as a Go template |

## Checks

```bash
uv run ruff check docs/labs/04 && uv run ruff format --check docs/labs/04 && uv run pyright
```

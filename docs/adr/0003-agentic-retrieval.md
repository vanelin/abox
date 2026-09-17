# ADR-0003: Agentic Retrieval toolset for the retrieval agent

- Status: Proposed — tool-level results measured locally for both toolsets, agentic pass and cluster run pending.
- Date: 2026-09-17.
- Model decision: [ADR-0001](0001-embedding-model.md). Serving: [ADR-0002](0002-embedding-deployment.md).

## Problem

Lab 4 turns retrieval into an agent capability: an agent indexes cluster manifests and answers questions from what it indexed. Two MCP toolsets can back it — the official qdrant/mcp-server-qdrant with `all-MiniLM-L6-v2`, and the course's default `qdrant-mcp` with nomic-embed-text-v1.5. This decision picks one for the retrieval agent, measured on the same data, under the same agent prompt and the same model, so the toolset is the only variable.

Both are deployed side by side in [releases/mcp-servers.yaml](../../releases/mcp-servers.yaml), each with its own agent in [releases/agent-retrieval.yaml](../../releases/agent-retrieval.yaml).

## Options

| Option | Embedding path | Dims | Tool contract | Benefit | Cost |
|---|---|---:|---|---|---|
| Official mcp-server-qdrant 0.8.1 | fastembed ONNX inside the MCP pod | 384 | `qdrant-store` / `qdrant-find`, upstream names and descriptions, both overridable by env | Upstream-maintained, no embedding service to run, smaller vectors | Model downloaded from HuggingFace on first start; a CPU embedding run in the agent's pod; requests 256Mi and limits 1Gi, and only small models fit — the f32 nomic ONNX did not |
| Our Go qdrant-mcp | any OpenAI-compatible `/v1/embeddings` route | 768 | `vector_store` / `vector_find`, ours | Shares the cluster's embedding endpoint, so agent memory lands in the vector space the gateway serves; pod stays small (32Mi request, 256Mi limit) | One more dependency: a llama.cpp (or llm-d) Deployment must be up, and repointing it is a re-embed, not a copy |

Run with uvx, because upstream publishes a PyPI package and no image; the version is pinned in the args. Both write to Qdrant, never to the same collection — `abox-minilm` (384) and `abox-nomic` (768) are different vector spaces.

## Method

Two passes, because an agent's answer confounds the toolset with the model driving it.

- **Tool level.** [docs/labs/04/eval.py](../labs/04/eval.py) calls the store and find tools directly over kmcp's streamable HTTP endpoint: each of the [144 frozen lab 3 chunks](../labs/03/chunks.jsonl) is stored once with `{id, path, kind, start, end}` in its metadata, each of the [ten labelled questions](../labs/03/questions.json) is searched once, and hit@1 / hit@3 / Ukrainian hit@3 come from the returned ids. Same inputs as ADR-0001, so the numbers sit next to it.
- **Agentic level.** The same ten questions asked to `retrieval-agent` and `retrieval-agent-nomic` through kagent, judged by hand into `.local/lab04/agentic-<toolset>.json`: did the answer come from a labelled chunk, and how many tool calls did it take. See the [lab bundle](../labs/04/README.md).

Limits to read the results with. Ten questions support a preliminary choice for this repository, not a ranking; three of them are Ukrainian, so the Ukrainian column moves in thirds. `all-MiniLM-L6-v2` is an English model, which makes the Ukrainian questions a known weakness rather than a surprise — ADR-0001 already measured every candidate below 3/3 there. The agentic pass is a manual judgement of a non-deterministic system and is not a benchmark.

## Results

| Toolset | Model | Dims | Ingest s | hit@1 | hit@3 | uk hit@3 | find p50 |
|---|---|---:|---:|---:|---:|---:|---:|
| official | all-MiniLM-L6-v2 (fastembed) | 384 | 4.0 | 2/10 | 5/10 | 1/3 | 0.023 s |
| nomic | nomic-embed-text-v1.5 (llama.cpp) | 768 | 14.1 | 5/10 | 7/10 | 1/3 | 0.051 s |

Per question, `1` = the labelled chunk came back first, `3` = it was in the top three only, `–` = miss.

| Question | Lang | official | nomic |
|---|---|:---:|:---:|
| q01 | en | – | – |
| q02 | en | – | 3 |
| q03 | uk | – | – |
| q04 | en | – | 1 |
| q05 | en | 3 | 1 |
| q06 | uk | – | – |
| q07 | en | 3 | 1 |
| q08 | en | 1 | 1 |
| q09 | uk | 1 | 1 |
| q10 | en | 3 | 3 |

Both rows are local runs over the same 144 chunks and ten questions through the same script, so they compare directly; neither is the in-cluster path. The official row used a local mcp-server-qdrant process against a local Qdrant whose `abox-minilm` held the corpus as 384-dimensional `fast-all-minilm-l6-v2` vectors, ingest timed separately on an empty collection. The nomic row used the Go server built from [mcp/qdrant-mcp](../../mcp/qdrant-mcp) (`go build ./cmd/server`, run with `-http`) with `EMBEDDINGS_BASE_URL` pointing at llama.cpp in Docker (`ghcr.io/ggml-org/llama.cpp:server`, arm64) serving the lab 3 pinned nomic-embed-text-v1.5 Q8_0 GGUF with the cluster Deployment's arguments (`--embeddings --ctx-size 16384 --ubatch-size 2048 --parallel 8`), against Qdrant 1.19.1 in Docker, collection `abox-nomic`, 768 dimensions. All ten questions parsed on both (`unparsed_results: 0`), and both latencies are loopback, without the kmcp and port-forward hops.

One difference from the cluster: `llama-cpp-embeddings` serves the f16 GGUF and this run used Q8_0, so the in-cluster numbers may differ slightly. The tool path is identical — same `search_document:` / `search_query:` prefixes, same chunking, same payload.

The nomic numbers equal ADR-0001's Nomic 768 row exactly — 5/10, 7/10, 1/3 — which is what should happen: the Go tool applies the same `search_document:` / `search_query:` prefixes and searches the full 768-dimensional vector, so it reproduces that measurement through a different code path. Read it as a consistency check of the tool path, not as new retrieval evidence.

**Preliminary reading.** On this corpus nomic through the Go tool leads MiniLM through the official tool by three questions at hit@1 and two at hit@3. Ukrainian is equal and weak for both at 1/3. The official server's advantage is operational, not retrieval quality: no embedding Deployment to keep up, roughly twice as fast to find on loopback and 3.5x faster to ingest.

| Agent | Answered from a labelled chunk | Tool calls (median) |
|---|---:|---:|
| retrieval-agent | pending | pending |
| retrieval-agent-nomic | pending | pending |

## Decision

Pending results. The tool-level comparison is done; both toolsets and both agents stay deployed until the agentic pass and the in-cluster run exist.

## Consequences

- Whichever toolset wins, the other's `MCPServer` and `Agent` are removed from `releases/` and its collection is dropped; keeping both costs a pod and a duplicate copy of the corpus.
- Choosing the official server makes the MCP pod the embedding runtime and ties the agent to what fits in its memory limit; choosing ours keeps the agent dependent on the embeddings Deployment being up, and on the route decided in [ADR-0002](0002-embedding-deployment.md).
- The two collections never merge. Switching the agent from one toolset to the other is a full re-ingest, not a copy — same reason a changed `EMBEDDINGS_BASE_URL` is.
- The prompt stays shared between the two agents. Any change to retrieval behaviour must be made in both, or the comparison stops being about the toolset.

## Sources

- [qdrant/mcp-server-qdrant](https://github.com/qdrant/mcp-server-qdrant): tool names, `fastembed` as the only embedding provider, the `TOOL_*_DESCRIPTION` and `COLLECTION_NAME` environment contract.
- [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2): 384 dimensions, English training data.
- [nomic-ai/nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5): 768 dimensions, English-focused, as recorded in ADR-0001.
- [kagent-dev/kmcp](https://github.com/kagent-dev/kmcp): how an `MCPServer` becomes a Service and how stdio servers are adapted to streamable HTTP.
- Checked 2026-09-17.

# ADR-0003: Agentic Retrieval toolset for the retrieval agent

- Status: Accepted — Go `qdrant-mcp` on Qwen3-Embedding-0.6B, 256 dimensions. Preliminary: ten questions at tool level, two per agent.
- Date: 2026-09-18.
- Model decision: [ADR-0001](0001-embedding-model.md). Serving: [ADR-0002](0002-embedding-deployment.md).

## Problem

Lab 4 turns retrieval into an agent capability: an agent indexes cluster manifests and answers questions from what it indexed. This decision picks the MCP toolset behind it, measured on the same data, prompt and model, so the toolset is the only variable.

Three toolsets are deployed side by side in [releases/mcp-servers.yaml](../../releases/mcp-servers.yaml), each with its own agent in [releases/agent-retrieval.yaml](../../releases/agent-retrieval.yaml). The lab asks for the first two; the third was added because neither carries the model ADR-0001 chose. Official against nomic varies tool and model together; nomic against Qwen varies the model alone.

## Options

| Toolset | Server and embedding path | Dims | Tools | Benefit | Cost |
|---|---|---:|---|---|---|
| `official` | qdrant/mcp-server-qdrant 0.8.1 run with uvx; fastembed `all-MiniLM-L6-v2` ONNX inside the MCP pod | 384 | `qdrant-store` / `qdrant-find` | Upstream-maintained, no embedding service, fastest ingest | One vector per stored text and a 256-token model window; model pulled from HuggingFace on first start; only small models fit the pod |
| `nomic` | our Go `qdrant-mcp`; nomic-embed-text-v1.5 f16 over llama.cpp | 768 | `vector_store` / `vector_find` | Chunks long texts; shares the cluster's embedding endpoint; 32Mi pod | Needs the llama.cpp Deployment up; English-focused |
| `qwen` | same Go server 0.5.0; Qwen3-Embedding-0.6B Q8_0 over its own llama.cpp, truncated to 256 of 1024 and L2-normalized in the tool (`EMBEDDINGS_DIMS`) | 256 | same | ADR-0001's winner end to end: multilingual, a third of nomic's vector storage | ~1.4Gi resident against ~150Mi, ~45 tokens/s on this CPU, ingest 4x slower |

Each toolset has its own collection (`abox-minilm`, `abox-nomic`, `abox-qwen256`); the vector spaces are not interchangeable.

## Method

Two passes, because an agent's answer confounds the toolset with the model driving it.

- **Tool level.** [eval.py](../labs/04/eval.py) calls store and find directly over kmcp: the [144 frozen lab 3 chunks](../labs/03/chunks.jsonl) stored once, the [ten labelled questions](../labs/03/questions.json) searched once, hit@1 / hit@3 from the returned ids. Same inputs as ADR-0001.
- **Agentic level.** Three agents, one prompt, one ModelConfig (`gpt-5.4-mini`), each ingest the same 27 declared cluster objects by delegating to `k8s-agent`, writing a vector per object and a node plus declared edges into one shared neo4j graph. [agentic.py](../labs/04/agentic.py) sends the conversations over kagent's A2A endpoint, one message per object. Memory is audited against the cluster, not the agents' reports; then q02 (English) and q06 (Ukrainian) are asked to each agent and judged by hand. Details in the [lab bundle](../labs/04/README.md).

Limits. Ten questions, three of them Ukrainian, support a choice for this repository, not a ranking. The agentic pass is two questions per agent, one run each, judged by the author, after three prompt rounds every agent received identically. Agents ingest live manifests, not the lab 3 corpus, so the two passes describe different stores, and the three questions about Makefile and scripts cannot be answered agentically at all.

## Results

### Tool level, in the cluster

| Toolset | Ingest s | hit@1 | hit@3 | uk hit@3 | find p50 |
|---|---:|---:|---:|---:|---:|
| official | 30.9 | 2/10 | 5/10 | 1/3 | 0.201 s |
| nomic | 64.8 | 5/10 | 7/10 | 1/3 | 0.104 s |
| qwen | 265.4 | 7/10 | 9/10 | 2/3 | 0.204 s |

`1` = labelled chunk first, `3` = in the top three, `–` = miss.

| | q01 | q02 | q03 uk | q04 | q05 | q06 uk | q07 | q08 | q09 uk | q10 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| official | – | – | – | – | 3 | – | 3 | 1 | 1 | 3 |
| nomic | – | 3 | – | 1 | 1 | – | 1 | 1 | 1 | 3 |
| qwen | 3 | 1 | 1 | 1 | 1 | – | 1 | 1 | 1 | 3 |

nomic and Qwen equal their ADR-0001 rows exactly, through a different code path: the Go tool applies each model's prefixes and, for Qwen, truncates and normalizes in `embed()`, so store and find share one space. That is a consistency check of the tool path, and it makes the Qwen row ADR-0001's winner rather than a lookalike. An earlier local run gave the same hits question for question; f16 against Q8_0 for nomic moved no ranking. Latency is the path, not the search: official went from 0.023 s on loopback to 0.201 s through kmcp's stdio adapter and in-pod ONNX.

### Agentic level

| Agent | Objects stored | Points | Invented | q02 en | q06 uk | find calls |
|---|---:|---:|---:|:-:|:-:|---:|
| retrieval-agent (official) | 27 / 27 | 27 | 0 | correct | correct | 2 |
| retrieval-agent-nomic | 27 / 27 | 31 | 0 | correct | correct | 2 |
| retrieval-agent-qwen | 27 / 27 | 30 | 0 | correct | correct | 2 |

Extra points are the Go server's chunks. The shared graph holds 41 nodes; `SOURCED_FROM` (15) and `DEPENDS_ON` (4) are identical to the cluster's `chartRef` / `sourceRef` / `dependsOn`, and `USES_MODEL` (4) and `USES_TOOL` (10) match the Agents' manifests. Reaching that state took a first pass of 20, 20 and 23 objects, a `--retry` pass, and a cleanup the agents did not do: three duplicate documents (store succeeded, agent saw a timeout), five junk or duplicate nodes, and `USES_*` edges two agents wrote only when asked for the graph alone.

q02 separates the toolsets. Only Qwen answered it from the question alone; the prompt had to change twice before the other two did:

| Prompt round | official, nomic on q02 | qwen | q06, all |
|---|---|---|---|
| 1. one find, a reworded one allowed | wrong hit (`Agent/k8s-agent`); official speculated, nomic offered to search | correct | correct |
| 2. search again if the key term is missing | said nothing relevant, did not search again | correct | correct |
| 3. always two finds: the question, then kind + name + key term | correct | correct | correct |

The official server stores a manifest as one vector and MiniLM reads its first 256 tokens; `postRenderers` sits deep in the kagent HelmRelease, so the question matched Agent manifests that say "kagent" often, while "HelmRelease kagent postRenderers" matches the top of the right one. nomic chunks and still ranked the Agent first. The Ukrainian q06 was answered by all three from round 1: "Flux" and the word for manifests overlap enough with English YAML. At tool level q06 missed everywhere, because its labelled answer is a prose section competing with its neighbours.

### What only the agentic pass showed

- **The report is not the store.** gpt-4.1-mini stored one concatenated text per resource type, invented `Agent/agent1` and `HelmRepository/agentgateway-repo`, and reported a 409 as "duplicate keys". Memory is audited with a Qdrant scroll and a Cypher `MATCH`.
- **An LLM delegate summarises.** The chart's k8s-agent answers in a fixed "Response Format" hardcoded in the chart and never returned a manifest; it is replaced by our own with a raw mode. Even that one once answered from an earlier turn without a tool call — `releases-crds` for `releases` — which is now a rule in its prompt.
- **The loop belongs outside the model.** Given a list, gpt-5.4-mini stopped after one or two objects and rationalised why; one message per object reached 27 of 27.
- **Defaults bite under an agent**: kmcp's 30 s client timeout, llama.cpp's 8 GiB RAM prompt cache, a 7000-character chunk over a 2048-token slot, a 200k TPM limit under three parallel ingests, the official server's named vector. Fixes and reasons are in the release YAML comments and the [lab bundle](../labs/04/README.md).
- **Cost.** ~40 s per object through two models, against 31–265 s for all 144 chunks at tool level: roughly twenty times a scripted ingest.

## Decision

Use the Go `qdrant-mcp` on **Qwen3-Embedding-0.6B at 256 dimensions** (`qdrant-mcp-qwen`, collection `abox-qwen256`). It leads hit@1 by two questions over nomic and five over MiniLM, is the only one above 1/3 on Ukrainian, and the only agent to answer q02 without the keyword second query. It is ADR-0001's configuration, reproduced exactly through the MCP path.

The official server stays the cheapest to operate and fits English, keyword-like questions over short texts. Its limits here are structural, not tuning: one vector per text and a 256-token window hide anything deep in a manifest.

All three toolsets and agents stay deployed on this branch as the lab's comparison; collapsing to the chosen one is the follow-up when this leaves the lab.

## Consequences

- The agent depends on `llama-cpp-qwen`: ~1.4Gi resident and an ingest four times slower than nomic's. Limits are measured in [releases/llama-cpp-qwen.yaml](../../releases/llama-cpp-qwen.yaml).
- Collections never merge; switching toolsets, `EMBEDDINGS_BASE_URL` or `EMBEDDINGS_DIMS` is a full re-ingest.
- Prompt, graph section and ModelConfig stay shared by the three agents, or the comparison stops being about the toolset.
- Retrieval is two find calls per question by policy. It made the weaker models usable and does not replace chunking in the official server.
- Ingest is driven from outside the model, one message per object, and audited. An unaudited agentic ingest is not trusted.
- `k8s-agent` is ours, on `gpt-5.4-nano`; the chart's is disabled in [releases/kagent.yaml](../../releases/kagent.yaml). On a cold cluster the retrieval agents can stay `Accepted=False` until the kagent controller is restarted.
- The graph is a constant across agents, so this ADR says nothing about Graph RAG. Dependency questions belong there — "what breaks if kagent-crds goes" is `DEPENDS_ON` edges, not an embedding — and tool-level q06, which every vector model missed, is that kind of question.
- A fairer benchmark needs questions written against the ingested manifests, several labelled answers each, repeated runs with variance, a judge who is not the author, and one harness for both passes.

## Sources

- [qdrant/mcp-server-qdrant](https://github.com/qdrant/mcp-server-qdrant): tool names, `fastembed` as the only provider, the environment contract.
- [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2): 384 dimensions, 256-token window, English.
- [nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) and [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B): prefixes, pooling and MRL as recorded in ADR-0001.
- [kagent-dev/kmcp](https://github.com/kagent-dev/kmcp): how an `MCPServer` becomes a Service, stdio adapted to streamable HTTP, `spec.timeout`.
- kagent 0.10.1 chart: `charts/k8s-agent/templates/agent.yaml` (hardcoded prompt), `templates/modelconfig-secret.yaml` (Secret rendered when `providers.*.apiKey` is set).
- Checked 2026-09-18.

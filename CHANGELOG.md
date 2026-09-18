# Changelog

## [Unreleased]

### Added

- Accepted [ADR-0003](docs/adr/0003-agentic-retrieval.md): the Go `qdrant-mcp` on Qwen3-Embedding-0.6B at 256 dimensions for the retrieval agent, measured in the cluster on three toolsets (tool level) and three agents (two questions each, memory audited against the cluster).
- Added a third toolset reproducing ADR-0001's winner: `llama-cpp-qwen` (Qwen3-Embedding-0.6B Q8_0 baked into [images/qwen-embed](images/qwen-embed), `--pooling last`, `--cache-ram 0`, 2 slots, 2Gi measured), MCPServer `qdrant-mcp-qwen` and agent `retrieval-agent-qwen`. `qdrant-mcp` 0.5.0 gains `EMBEDDINGS_DIMS`: truncate then L2-normalize in `embed()`, so store and find share one space.
- Wired `neo4j-mcp` into all three retrieval agents with one shared Graph section (MERGE a node per object and only declared edges), and replaced the chart's `k8s-agent` with our own: raw mode that relays tool output verbatim, read tools plus labels, annotations and a connectivity check, on `gpt-5.4-nano`. The retrieval agents run on `gpt-5.4-mini`; both ModelConfigs are in [releases/model-configs.yaml](releases/model-configs.yaml).
- Added [docs/labs/04/agentic.py](docs/labs/04/agentic.py): drives ingest (one A2A message per object, `--retry`) and questions (`ask --ids`) through kagent, so the agentic pass is repeatable.
- Added `make secrets` ([scripts/secrets.sh](scripts/secrets.sh), called by `make run`): creates Secret `kagent-openai` from `OPENAI_API_KEY` in the environment. The key never touches a file.

- Added the official Qdrant MCP server as a second toolset: MCPServer `qdrant-mcp-official` (mcp-server-qdrant 0.8.1 run with uvx, fastembed `all-MiniLM-L6-v2`, 384 dimensions, collection `abox-minilm`) next to the Go `qdrant-mcp` (nomic, 768 dimensions, `abox-nomic`). The two vector spaces never share a collection.
- Added two retrieval agents with one shared system prompt and `default-model-config` — `retrieval-agent` on the official tools, `retrieval-agent-nomic` on ours — so a comparison measures the toolset, not the prompt. Both delegate to `k8s-agent` for ingest only; neo4j stays deployed but unwired.
- Added the [lab 4 bundle](docs/labs/04/README.md): a scoring script that drives either toolset through kmcp's HTTP endpoint on the frozen lab 3 corpus and questions, and proposed [ADR-0003](docs/adr/0003-agentic-retrieval.md) for the toolset choice. Both tool-level runs (local) are recorded there.
- Added the `mcp` Python dependency in [pyproject.toml](pyproject.toml) for the lab 4 client.
- Added external llama-server evaluation via `eval.py --endpoint`; remote identity and memory are recorded as unknown and verified separately. Updated deployment plans with measured-resource caveats, Recreate rollouts and Flux-aware shutdown.

- Proposed [ADR-0002](docs/adr/0002-embedding-deployment.md): serve the model in the cluster as one shared Deployment + Service (Qwen, `strategy: Recreate`, starting envelope memory 2Gi/3Gi and CPU 1/2 to be measured then reduced, paused the Flux way when idle), Nomic as the lighter fallback, sidecar documented for a single real consumer, llm-d deferred to an environment that meets its 64 CPU / 64 GB profile. Nothing deployed.
- `eval.py` gained `--endpoint` to score an already running server (for the in-cluster check) and distinct-question latency p50/p95 next to the repeated-query number.
- Added agent ToDo lists: [local run](docs/labs/03-local-embeddings.md) (verified on this Codespace) and [cluster: Deployment, sidecar, llm-d](docs/labs/03-cluster-embeddings.md) (plan only).
- Accepted [ADR-0001](docs/adr/0001-embedding-model.md): Qwen3-Embedding-0.6B Q8_0 at 256 dimensions for local repository retrieval.
- Added the [lab 3 bundle](docs/labs/03/README.md): evaluation and rescoring scripts, 144 frozen chunks, both label revisions and the latest three runs.
- Added `make llama`, `make models` and `make clean-llama` for the local runtime and weights, separate from `make run`.
- Added uv-managed Python dependencies, Ruff and Pyright in [pyproject.toml](pyproject.toml), with a lockfile, Python version file and ignored caches.

### Fixed

- The kagent chart no longer renders Secret `kagent-openai`: `providers.openAI.apiKey: OPENAI_API_KEY` in [releases/kagent.yaml](releases/kagent.yaml) made every Helm upgrade overwrite the hand-made key with that placeholder, and agents then failed with 401.
- `MCPServer.spec.timeout` for the two Go servers (120s, 300s for Qwen) instead of kmcp's 30s default, `EMBEDDING_MAX_INPUT_CHARS=3500` and a 300s embed timeout for Qwen: large manifests timed out or overflowed the 2048-token slot during an agent's ingest.

### Verified

- Scored three toolsets in the cluster on 2026-09-17 on the frozen lab 3 corpus (144 chunks, 10 questions): official / MiniLM hit@1 2/10, hit@3 5/10, uk 1/3; nomic 5/10, 7/10, 1/3; Qwen 256 7/10, 9/10, 2/3 -- nomic and Qwen equal their ADR-0001 rows exactly. On 2026-09-18 each agent ingested the same 27 cluster objects (27/27 after one retry pass, no invented objects; `SOURCED_FROM` 15/15 and `DEPENDS_ON` 4/4 identical to the cluster) and answered q02 (en) and q06 (uk) correctly with two find calls each. See [ADR-0003](docs/adr/0003-agentic-retrieval.md).
- Scored both Qdrant MCP toolsets locally on 2026-09-17 on the frozen lab 3 corpus (144 chunks, 10 questions): official / all-MiniLM-L6-v2 hit@1 2/10, hit@3 5/10; Go qdrant-mcp / nomic-embed-text-v1.5 hit@1 5/10, hit@3 7/10; Ukrainian 1/3 for both. See [ADR-0003](docs/adr/0003-agentic-retrieval.md).
- Evaluated three models on 2026-09-13 using 144 chunks and ten questions (7 EN / 3 UA) in a 4 CPU / 16 GB Codespace; two threads, one slot, batches of eight, context 2048.
- Verified llama.cpp tag `v0.4.0` (binary `0.4.0-dev`, commit `5266f24`) and all three model SHA256 values against [Makefile pins](Makefile); hashes are saved in the [run files](docs/labs/03/README.md).
- Corrected one missing answer for q04; [v2 rescoring](docs/labs/03/rescore-v2.json) and subsequent full runs produced the same scores. Both label revisions are retained.

| Model | Dimensions | hit@1 | hit@3 | UA hit@3 |
|---|---:|---:|---:|---:|
| Nomic | 768 | 5/10 | 7/10 | 1/3 |
| Nomic | 256 | 3/10 | 7/10 | 1/3 |
| Nomic | 128 | 2/10 | 6/10 | 1/3 |
| EmbeddingGemma | 768 | 6/10 | 7/10 | 1/3 |
| EmbeddingGemma | 256 | 5/10 | 6/10 | 1/3 |
| EmbeddingGemma | 128 | 2/10 | 6/10 | 1/3 |
| Qwen3-Embedding-0.6B | 1024 | 6/10 | 8/10 | 2/3 |
| Qwen3-Embedding-0.6B | 256 | 7/10 | 9/10 | 2/3 |
| Qwen3-Embedding-0.6B | 128 | 6/10 | 9/10 | 2/3 |
| Lexical baseline | — | 3/10 | 5/10 | 1/3 |

- Latest embedding times / sampled RSS: Nomic 59.9 s / 305 MB; Gemma 69.4 s / 1239 MB; Qwen 256.8 s / 1741 MB. These exclude Qdrant indexing time and do not measure peak RAM.
- All inputs fit 2048 tokens; maximum chunk/query counts were Nomic 720/40, Gemma 818/26 and Qwen 724/49, including prompts and special tokens. See [measurements and limitations](docs/adr/0001-embedding-model.md#resources-and-tokenization).
- Qdrant top-3 text matched in-memory search in all 90 comparisons. Four ID comparisons differed because of duplicate Namespace chunks; hit metrics were unchanged.
- Qwen 256 remains the local choice at 7/10 hit@1 and 9/10 hit@3. The small question set, q06 Ukrainian miss and cached repeated-query timing limit the conclusions; deployment remains separate work.

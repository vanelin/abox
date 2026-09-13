# Changelog

## [Unreleased]

### Added

- Added external llama-server evaluation via `eval.py --endpoint`; remote identity and memory are recorded as unknown and verified separately. Updated deployment plans with measured-resource caveats, Recreate rollouts and Flux-aware shutdown.

- Proposed [ADR-0002](docs/adr/0002-embedding-deployment.md): serve the model in the cluster as one shared Deployment + Service (Qwen, `strategy: Recreate`, starting envelope memory 2Gi/3Gi and CPU 1/2 to be measured then reduced, paused the Flux way when idle), Nomic as the lighter fallback, sidecar documented for a single real consumer, llm-d deferred to an environment that meets its 64 CPU / 64 GB profile. Nothing deployed.
- `eval.py` gained `--endpoint` to score an already running server (for the in-cluster check) and distinct-question latency p50/p95 next to the repeated-query number.
- Added agent ToDo lists: [local run](docs/labs/03-local-embeddings.md) (verified on this Codespace) and [cluster: Deployment, sidecar, llm-d](docs/labs/03-cluster-embeddings.md) (plan only).
- Accepted [ADR-0001](docs/adr/0001-embedding-model.md): Qwen3-Embedding-0.6B Q8_0 at 256 dimensions for local repository retrieval.
- Added the [lab 3 bundle](docs/labs/03/README.md): evaluation and rescoring scripts, 144 frozen chunks, both label revisions and the latest three runs.
- Added `make llama`, `make models` and `make clean-llama` for the local runtime and weights, separate from `make run`.
- Added uv-managed Python dependencies, Ruff and Pyright in [pyproject.toml](pyproject.toml), with a lockfile, Python version file and ignored caches.

### Verified

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

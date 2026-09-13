# Changelog

## [Unreleased]

### Added

- Accepted [ADR-0001](docs/adr/0001-embedding-model.md): Qwen3-Embedding-0.6B Q8_0 with 256-dimensional embeddings for local code and documentation retrieval.
- Added `make llama` to build the pinned CPU runtime, `make models` to download revision-pinned GGUF weights with SHA256 checks, and `make clean-llama` to remove `.local/llama.cpp` and `.local/models`; these targets are separate from `make run`.

### Verified

- Lab 3 evaluation completed on 2026-09-13 in a 4 CPU / 16 GB Codespace, using 144 chunks, seven English questions and three Ukrainian questions; models ran sequentially with two CPU threads, one server slot, context 2048 and client batches of eight.
- llama.cpp checkout tag `v0.4.0` matched the pin; the evaluated binary reported `0.4.0-dev (build 1, commit 5266f24)`, built with GNU 13.3.0 for Linux x86_64.
- Nomic Q8_0 SHA256 matched the Makefile pin: `3e24342164b3d94991ba9692fdc0dd08e3fd7362e0aacc396a9a5c54a544c3b7`.
- EmbeddingGemma Q8_0 SHA256 matched the Makefile pin: `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63`.
- Qwen3-Embedding-0.6B Q8_0 SHA256 matched the Makefile pin: `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`.
- Corrected q04 labels to accept the explanatory comment in `releases/agentgateway.yaml:5-18`; rescored saved top-3 for all nine variants without rerunning embeddings. Original results and v1 labels were preserved; the ADR includes both tables.
- Corrected v2 retrieval scores follow; the lexical baseline was unchanged.

| Model | Dimensions | hit@1 | hit@3 | UA hit@3 |
|---|---|---|---|---|
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

- Measured corpus embedding time, server RSS after embedding (not peak), and median latency over ten repetitions of one warmed query:

| Model | Corpus embedding time | RSS after embedding | Repeated-query p50 |
|---|---|---|---|
| Nomic | 61.0 s | 305 MB | 68.7 ms |
| EmbeddingGemma | 62.6 s | 1239 MB | 109.7 ms |
| Qwen3-Embedding-0.6B | 254.6 s | 1741 MB | 48.0 ms |

- Qwen's 254.6 seconds measure corpus embedding generation, not total Qdrant indexing; its 48 ms repeated-query p50 is not latency for a new query and may reflect caching.
- Qdrant ordered top-3 matched in-memory search for 10/10 questions in each of all nine collections; all models passed the 2048-token input check and expected vector-dimension checks.
- Qwen 256 achieved 7/10 hit@1, 9/10 hit@3 and 2/3 Ukrainian hit@3; q06 remains an open Ukrainian retrieval weakness. Ten questions support a preliminary local choice, not a general ranking or guarantee that truncation preserves quality.
- Evidence and scripts remain in gitignored `.local/lab03/`, including `rescore-v2.json` and the original per-run JSON files; this commit documents results but does not include the full reproduction bundle. Deployment ADR and lab runbooks remain separate follow-up work.

# Changelog

## [Unreleased]

### Added

- Accepted [ADR-0001](docs/adr/0001-embedding-model.md): Qwen3-Embedding-0.6B Q8_0 with 256-dimensional embeddings for local code and documentation retrieval.
- Added `pyproject.toml` with uv-managed dev tools (ruff, pyright) as the single source of Python lint and type rules; `.venv/` and caches are gitignored.
- Added `make llama` to build the pinned CPU runtime, `make models` to download revision-pinned GGUF weights with SHA256 checks, and `make clean-llama` to remove `.local/llama.cpp` and `.local/models`; these targets are separate from `make run`.

### Verified

- Lab 3 evaluation completed on 2026-09-13 in a 4 CPU / 16 GB Codespace, using a set of 144 chunks, seven English questions and three Ukrainian questions; models ran sequentially with two CPU threads, one server slot, context 2048 and client batches of eight.
- llama.cpp checkout tag `v0.4.0` matched the pin; the evaluated binary reported `0.4.0-dev (build 1, commit 5266f24)`, built with GNU 13.3.0 for Linux x86_64.
- Nomic Q8_0 SHA256 matched the Makefile pin: `3e24342164b3d94991ba9692fdc0dd08e3fd7362e0aacc396a9a5c54a544c3b7`.
- EmbeddingGemma Q8_0 SHA256 matched the Makefile pin: `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63`.
- Qwen3-Embedding-0.6B Q8_0 SHA256 matched the Makefile pin: `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`.
- Corrected q04 labels to accept the explanatory comment in `releases/agentgateway.yaml:5-18`; rescored saved top-3 for all nine variants without rerunning embeddings. Initial result files remain in gitignored `.local/lab03/`; the bundle contains the latest v2-labelled runs. Both label revisions are preserved and the ADR includes both score tables.
- Latest runs reproduced all nine corrected v2 retrieval scores below; the lexical baseline was unchanged.

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

- Measured embedding time for all chunks, server RSS after embedding (not peak), and median latency over ten repetitions of one warmed query:

| Model | Embedding time, all chunks (run 1 / run 2) | RSS after embedding | Repeated-query p50 (run 1 / run 2) | Longest chunk, tokens | Longest query, tokens |
|---|---|---|---|---|---|
| Nomic | 61.0 s / 59.9 s | 305 MB | 68.7 ms / 67.7 ms | 720 | 40 |
| EmbeddingGemma | 62.6 s / 69.4 s | 1239 MB | 109.7 ms / 93.3 ms | 818 | 26 |
| Qwen3-Embedding-0.6B | 254.6 s / 256.8 s | 1741 MB | 48.0 ms / 31.4 ms | 724 | 49 |

The second full run reproduced all nine corrected hit@1/hit@3 scores and the same sampled RSS; timings changed. The repeated-query p50 (Qwen 48.0 ms then 31.4 ms) is not a measurement of new-query latency. Token maxima cover the same 144 chunks and ten questions, including each model's prompts and special tokens (`add_special=true`, `parse_special=true`). They show context usage against the common 2048-token limit, not tokenizer quality or speed. Maxima alone cannot establish the total token count or work per chunk, and the instruction-only token count was not recorded. Per-language counts, total/median/p95 token counts and tokenization time were not saved.

- Qwen's roughly 255 seconds measure embedding generation for all chunks, not total Qdrant indexing; its repeated-query p50 (48 ms, then 31 ms on the second run) is not latency for a new query and may reflect caching.
- In the latest runs, ordered top-3 IDs agreed with in-memory search on 9/10 questions for Nomic 768, Gemma 256/128 and Qwen 1024, and on 10/10 for the other five variants. Every differing ID refers to an identical Namespace chunk: Nomic q04 and Gemma q02 swap duplicate chunks, while Qwen full q02 substitutes a duplicate at position 3. Top-3 text is identical in all 90 comparisons, and hit@1/hit@3 are unchanged. Raw similarity scores were not saved. This verifies agreement by retrieved content, not label correctness or the entire embedding pipeline.
- All models passed the 2048-token input check and expected vector-dimension checks.
- Qwen 256 achieved 7/10 hit@1, 9/10 hit@3 and 2/3 Ukrainian hit@3; q06 remains an open Ukrainian retrieval weakness. Ten questions support a preliminary local choice, not a general ranking or guarantee that truncation preserves quality.
- Evidence and scripts are in `docs/labs/03/`: the frozen set of 144 chunks, both label revisions, `eval.py`, `chunk.py`, the three per-run JSON files and `rescore-v2.json`; see its README for how to re-score or rerun. Deployment ADR and lab runbooks remain separate follow-up work.

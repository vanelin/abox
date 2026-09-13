# ADR-0001: Choosing an embedding model for abox

- Status: Accepted — Qwen3-Embedding-0.6B Q8_0, 256 dimensions.
- Date: 2026-09-13.

An ADR (Architecture Decision Record) explains the problem, the options, and why we choose one. This record covers model selection; deployment comes later.

## Problem

We want an agent to find the code and documentation needed to answer questions such as “Why does kagent need a postRenderer?” The repository contains Markdown, YAML, OpenTofu HCL, and shell scripts. Questions may be Ukrainian or English.

We will evaluate search by meaning using embeddings. An embedding is a list of numbers representing a text fragment. Qdrant stores these vectors and finds fragments close to the question's vector. The agent can then use the retrieved text to answer: this is the retrieval step of RAG (Retrieval-Augmented Generation). Ordinary text search remains a useful comparison for exact names.

## Requirements

- Find relevant source blocks, including English content for Ukrainian questions.
- Run locally on CPU in our 4 CPU / 16 GB Codespace, shared with KinD.
- Support MRL (Matryoshka Representation Learning). MRL enables useful shorter vectors. We will compare full-size, 256- and 128-dimensional embeddings to measure the quality/storage tradeoff on our repository. Published research motivates testing stronger truncation but does not establish a universal threshold. Shortening output vectors does not reduce model weights.
- Have available GGUF weights (the model format used by llama.cpp) and licence terms suitable for our use.

This comparison covers three local models. Cloud APIs are outside its scope. Measured runtime memory and speed are recorded below. The last disk check found 7.7 GB free on 2026-09-13; check again before downloading.

## Options

Published properties, checked on 2026-09-13:

| Model | Languages | Full vector → MRL options | Input limit | Q8_0 weights | Licence |
|---|---|---|---|---|---|
| Nomic Embed Text v1.5 | English-focused | 768 → 64–768 | 8192 tokens | 146 MB | Apache-2.0 |
| Qwen3-Embedding-0.6B | 100+ | 1024 → 32–1024 | 32k tokens | 639 MB | Apache-2.0 |
| EmbeddingGemma-300M | 100+ | 768 → 512/256/128 | 2048 tokens | 334 MB | Gemma terms |

Q8_0 is an 8-bit weight format that reduces the model file size. File size is not total runtime memory. Tokens are the units into which a model splits text; the input limit is not a recommendation to embed whole files. We use a 2048-token context for all models in this test; longer Nomic contexts in this GGUF build have not been tested.

- **Nomic:** smallest weights here. Can it retrieve English source blocks from Ukrainian questions well enough?
- **Qwen:** multilingual and designed for text and code retrieval. Does better retrieval, if observed, justify its resource use and CPU latency?
- **EmbeddingGemma:** compact and multilingual. Are its results good on our configuration files? Its licence terms need review before adoption.

Sources: [Nomic model](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) / [GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF), [Qwen model](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) / [GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF), [EmbeddingGemma model](https://huggingface.co/google/embeddinggemma-300m) / [GGUF](https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF), [Nomic's MRL explanation](https://www.nomic.ai/news/nomic-embed-matryoshka), [To MRL or not to MRL (arXiv 2605.16608)](https://arxiv.org/html/2605.16608), [Sentence Transformers on Matryoshka](https://sbert.net/examples/sentence_transformer/training/matryoshka/README.html).

Further reading: [Awesome Search — Embeddings](https://frutik.github.io/awesome-search/Concepts/Embeddings), an introductory overview of embeddings, dense/sparse search, MRL, and vector compression. Model specifications above are based on the primary sources.

## Decision

Choose Qwen3-Embedding-0.6B Q8_0 at 256 dimensions for local repository retrieval, based on the experiment below. This decision applies to this repository as tested and can be revisited with broader evaluation.

## Test after discussion

The following was the agreed test plan; the Result section records what was measured and its limitations.

1. **Prepare the same input.** Freeze a repository commit and list the files included. Split them into meaningful chunks: Markdown sections, HCL blocks, YAML resources, or shell functions. Save each chunk's path and line numbers. Keep chunks within every model's input limit, including prompt text.
2. **Define success first.** Write about ten real questions in Ukrainian and English. Label the relevant blocks before searching; several blocks may be correct. Agree on acceptable quality loss at 256 and 128 dimensions before results.
3. **Run one model at a time.** Pin weights and runtime versions. Verify that llama.cpp returns embeddings, then index full-size, 256- and 128-dimensional vectors into separate Qdrant collections and search each directly; two-stage search with a full-vector rescore is a later option. Follow each model's input prompts and normalization procedure. For Nomic, the reference MRL procedure includes LayerNorm before truncation and L2 normalization; check what the runtime already does. Compare with simple keyword search on identifier questions.
4. **Record useful results.** Count questions with a relevant block at rank 1 (hit@1) and within the first 3 (hit@3). Show language/type groups as counts, such as “2 of 3”, and inspect failures. Record median query time after warm-up (p50), process memory in RAM (RSS), and total indexing time.
5. **Decide together.** Choose the model and dimension offering acceptable retrieval quality and resource use. If none meets the criteria, revisit the choice. Mark this ADR Accepted only after agreement, and put measured results in CHANGELOG.md.

## Result

Accepted on 2026-09-13: **Qwen3-Embedding-0.6B Q8_0 at 256 dimensions**, using llama.cpp `--pooling last --embd-normalize -1`. Embed documents without a prefix. For queries, use the exact template below, with a newline before `Query:`; replace `<question>` with the question text.

```text
Instruct: Given a question about a Kubernetes/OpenTofu repository, retrieve the file section that answers it
Query: <question>
```

Take the first 256 coordinates of each raw 1024-dimensional document/query vector, then L2-normalize and search with cosine similarity. In this comparison, Nomic used LayerNorm before truncation and L2 normalization, including at full dimension; Gemma used truncation then L2. All models used a 2048-token context, two CPU threads for both generation and batch processing, one server slot, and client batches of eight chunks.

The chunk set contained 144 chunks and ten labelled questions (seven English, three Ukrainian). The latest runs use corrected labels v2 and reproduce the previous corrected retrieval scores; hit@k counts questions with any accepted block in the first k results.

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

Qwen 256 had the highest hit@1 (7/10) and tied Qwen 128 for the highest hit@3 (9/10). We choose 256 to retain its better first-result ranking. It uses one quarter of the raw vector storage of Qwen full, at the same numeric precision. Nomic was lighter and faster at embedding all chunks, but retrieved fewer labelled answers. Qwen's measured resource use was practical for a sequential run in this Codespace.

| Model | Embedding time, all chunks (run 1 / run 2) | RSS after embedding | Repeated-query p50 (run 1 / run 2) | Longest chunk, tokens | Longest query, tokens |
|---|---|---|---|---|---|
| Nomic | 61.0 s / 59.9 s | 305 MB | 68.7 ms / 67.7 ms | 720 | 40 |
| EmbeddingGemma | 62.6 s / 69.4 s | 1239 MB | 109.7 ms / 93.3 ms | 818 | 26 |
| Qwen3-Embedding-0.6B | 254.6 s / 256.8 s | 1741 MB | 48.0 ms / 31.4 ms | 724 | 49 |

The second full run reproduced all nine corrected hit@1/hit@3 scores and the same sampled RSS; timings changed. The repeated-query p50 (Qwen 48.0 ms then 31.4 ms) is not a measurement of new-query latency. Token maxima cover the same 144 chunks and ten questions, including each model's prompts and special tokens (`add_special=true`, `parse_special=true`). They show context usage against the common 2048-token limit, not tokenizer quality or speed. Maxima alone cannot establish the total token count or work per chunk, and the instruction-only token count was not recorded. Per-language counts, total/median/p95 token counts and tokenization time were not saved.

These are preliminary results on ten questions, not evidence of a universal model ranking or guaranteed lossless truncation. Question q06 (“Звідки Flux отримує маніфести застосунків?”) remained a miss at Qwen 256 and is an open weakness for Ukrainian retrieval. Qwen's approximately 255 seconds measure embedding generation for all chunks, not total Qdrant indexing. RSS was sampled after embedding, not measured as peak memory. The repeated-query p50 (48 ms, then 31 ms on the second run) comes from ten repetitions of one warmed query and may benefit from caching; it does not measure latency for a new query or establish a pooling-related speed advantage.

In the latest runs, ordered top-3 IDs agreed with in-memory search on 9/10 questions for Nomic 768, Gemma 256/128 and Qwen 1024, and on 10/10 for the other five variants. Every differing ID refers to an identical Namespace chunk: Nomic q04 and Gemma q02 swap duplicate chunks, while Qwen full q02 substitutes a duplicate at position 3. Top-3 text is identical in all 90 comparisons, and hit@1/hit@3 are unchanged. Raw similarity scores were not saved. This verifies agreement by retrieved content, not label correctness or the entire embedding pipeline. Language metrics are recorded; chunk-type breakdowns and a separate held-out evaluation were not performed.

### Label correction

After inspecting failures, we added `releases/agentgateway.yaml:5-18` as an alternative correct answer for q04: its comment explains why the chart is held at v2.2.1. Only this label changed. We rescored all nine variants and the baseline from their saved top-3 without rerunning models or changing the chunk set. This raised Qwen's hit@1 too; Ukrainian scores and the baseline were unchanged. For q01, the expected RSIP block remains correct: the default release version does not configure newest-semver selection.

Initial results with v1 labels, for comparison (also reproduced by rescoring the latest saved top-3 with v1):

| Model | Dimensions | hit@1 | hit@3 | UA hit@3 |
|---|---|---|---|---|
| Nomic | 768 | 4/10 | 6/10 | 1/3 |
| Nomic | 256 | 2/10 | 6/10 | 1/3 |
| Nomic | 128 | 2/10 | 5/10 | 1/3 |
| EmbeddingGemma | 768 | 5/10 | 6/10 | 1/3 |
| EmbeddingGemma | 256 | 4/10 | 5/10 | 1/3 |
| EmbeddingGemma | 128 | 2/10 | 5/10 | 1/3 |
| Qwen3-Embedding-0.6B | 1024 | 5/10 | 8/10 | 2/3 |
| Qwen3-Embedding-0.6B | 256 | 6/10 | 9/10 | 2/3 |
| Qwen3-Embedding-0.6B | 128 | 5/10 | 9/10 | 2/3 |
| Lexical baseline | — | 3/10 | 5/10 | 1/3 |

Evidence is stored in `docs/labs/03/`: the frozen chunk set (`chunks.jsonl`, SHA256 `ddea3b90df9aa4025e0448c1e90c610a99b18b70e3ad8ca0c14f060b1e2c9257`), labels v1 and v2, `rescore-v2.json`, the latest per-run result files (`results-gemma-b64b502449fa.json`, `results-nomic-086a6a22fa49.json`, `results-qwen-8ec9dffbfc33.json`), and the `chunk.py`, `eval.py` and `rescore.py` scripts. The chunk set captures the working tree at preparation time; later edits to this ADR, CHANGELOG and Makefile are not in it, so regenerating from a newer commit gives a different set.

The initial per-run JSON files remain in gitignored `.local/lab03/`; they were replaced in this bundle by the latest runs.

## Consequences

At the same numeric precision, 256 values take one third of the raw vector storage of 768 and one quarter of 1024; 128 takes one sixth and one eighth. Total Qdrant size also includes text, payload and the index. Shorter vectors do not shrink the model or guarantee unchanged quality. Changing the model requires re-embedding all chunks and queries consistently.

Model selection is accepted for this lab. Kubernetes deployment and agent memory management remain later tasks.

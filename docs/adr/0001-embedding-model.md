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

Choose Qwen3-Embedding-0.6B Q8_0 at 256 dimensions for local repository retrieval, based on the experiment below. This decision applies to our lab corpus and can be revisited with broader evaluation.

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

The corpus contained 144 chunks and ten labelled questions (seven English, three Ukrainian). Results below use corrected labels v2; hit@k counts questions with any accepted block in the first k results.

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

Qwen 256 had the highest hit@1 (7/10) and tied Qwen 128 for the highest hit@3 (9/10). We choose 256 to retain its better first-result ranking. It uses one quarter of the raw vector storage of Qwen full, at the same numeric precision. Nomic was lighter and faster at embedding the corpus, but retrieved fewer labelled answers. Qwen's measured resource use was practical for a sequential run in this Codespace.

| Model | Corpus embedding time | RSS after embedding | Repeated-query p50 |
|---|---|---|---|
| Nomic | 61.0 s | 305 MB | 68.7 ms |
| EmbeddingGemma | 62.6 s | 1239 MB | 109.7 ms |
| Qwen3-Embedding-0.6B | 254.6 s | 1741 MB | 48.0 ms |

These are preliminary results on ten questions, not evidence of a universal model ranking or guaranteed lossless truncation. Question q06 (“Звідки Flux отримує маніфести застосунків?”) remained a miss at Qwen 256 and is an open weakness for Ukrainian retrieval. Qwen's approximately 255 seconds measure corpus embedding generation, not total Qdrant indexing. RSS was sampled after embedding, not measured as peak memory. The 48 ms p50 comes from ten repetitions of one warmed query and may benefit from caching; it does not measure latency for a new query or establish a pooling-related speed advantage.

Qdrant returned the same ordered top-3 as in-memory cosine search for all ten questions in all nine model/dimension collections. This verifies search agreement, not the correctness of labels or the entire embedding pipeline. Language metrics are recorded; chunk-type breakdowns and a separate held-out evaluation were not performed.

### Label correction

After inspecting failures, we added `releases/agentgateway.yaml:5-18` as an alternative correct answer for q04: its comment explains why the chart is held at v2.2.1. Only this label changed. We rescored all nine variants and the baseline from their saved top-3 without rerunning models or changing the corpus. This raised Qwen's hit@1 too; Ukrainian scores and the baseline were unchanged. For q01, the expected RSIP block remains correct: the default release version does not configure newest-semver selection.

Original results with v1 labels, for comparison:

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

Local evidence is stored in gitignored `.local/lab03/`: `questions.v1.json`, corrected `questions.json`, `rescore-v2.json`, and `results-nomic-7bd17b03d9d7.json`, `results-gemma-5acf01fd57aa.json`, `results-qwen-efaf7a1db4f9.json`. Corpus SHA256: `ddea3b90df9aa4025e0448c1e90c610a99b18b70e3ad8ca0c14f060b1e2c9257`. The corpus captures the working tree at preparation time; later ADR edits are not included. The eval/chunking scripts, corpus and raw results are not committed, so this repository records the decision and measurements but does not contain the complete reproduction bundle.

## Consequences

At the same numeric precision, 256 values take one third of the raw vector storage of 768 and one quarter of 1024; 128 takes one sixth and one eighth. Total Qdrant size also includes text, payload and the index. Shorter vectors do not shrink the model or guarantee unchanged quality. Changing the model requires re-embedding the corpus and queries consistently.

Model selection is accepted for this lab. Kubernetes deployment and agent memory management remain later tasks.

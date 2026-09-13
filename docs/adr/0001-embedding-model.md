# ADR-0001: Choosing an embedding model for abox

- Status: Proposed — three candidates; no model selected.
- Date: 2026-09-13.

An ADR (Architecture Decision Record) explains the problem, the options, and why we choose one. This proposal covers model selection; deployment comes later.

## Problem

We want an agent to find the code and documentation needed to answer questions such as “Why does kagent need a postRenderer?” The repository contains Markdown, YAML, OpenTofu HCL, and shell scripts. Questions may be Ukrainian or English.

We will evaluate search by meaning using embeddings. An embedding is a list of numbers representing a text fragment. Qdrant stores these vectors and finds fragments close to the question's vector. The agent can then use the retrieved text to answer: this is the retrieval step of RAG (Retrieval-Augmented Generation). Ordinary text search remains a useful comparison for exact names.

## Requirements

- Find relevant source blocks, including English content for Ukrainian questions.
- Run locally on CPU in our 4 CPU / 16 GB Codespace, shared with KinD.
- Support MRL (Matryoshka Representation Learning). MRL enables useful shorter vectors. We will compare full-size, 256- and 128-dimensional embeddings to measure the quality/storage tradeoff on our repository. Published research motivates testing stronger truncation but does not establish a universal threshold. Shortening output vectors does not reduce model weights.
- Have available GGUF weights (the model format used by llama.cpp) and licence terms suitable for our use.

This comparison covers three local models. Cloud APIs are outside its scope. Runtime memory and speed are unknown until measured. The last disk check found 7.7 GB free on 2026-09-13; check again before downloading.

## Options

Published properties, checked on 2026-09-13:

| Model | Languages | Full vector → MRL options | Input limit | Q8_0 weights | Licence |
|---|---|---|---|---|---|
| Nomic Embed Text v1.5 | English-focused | 768 → 64–768 | 8192 tokens | 146 MB | Apache-2.0 |
| Qwen3-Embedding-0.6B | 100+ | 1024 → 32–1024 | 32k tokens | 639 MB | Apache-2.0 |
| EmbeddingGemma-300M | 100+ | 768 → 512/256/128 | 2048 tokens | 334 MB | Gemma terms |

Q8_0 is an 8-bit weight format that reduces the model file size. File size is not total runtime memory. Tokens are the units into which a model splits text; the input limit is not a recommendation to embed whole files.

- **Nomic:** smallest weights here. Can it retrieve English source blocks from Ukrainian questions well enough?
- **Qwen:** multilingual and designed for text and code retrieval. Does better retrieval, if observed, justify its resource use and CPU latency?
- **EmbeddingGemma:** compact and multilingual. Are its results good on our configuration files? Its licence terms need review before adoption.

Sources: [Nomic model](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) / [GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF), [Qwen model](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) / [GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF), [EmbeddingGemma model](https://huggingface.co/google/embeddinggemma-300m) / [GGUF](https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF), [Nomic's MRL explanation](https://www.nomic.ai/news/nomic-embed-matryoshka), [To MRL or not to MRL (arXiv 2605.16608)](https://arxiv.org/html/2605.16608), [Sentence Transformers on Matryoshka](https://sbert.net/examples/sentence_transformer/training/matryoshka/README.html).

Further reading: [Awesome Search — Embeddings](https://frutik.github.io/awesome-search/Concepts/Embeddings), an introductory overview of embeddings, dense/sparse search, MRL, and vector compression. Model specifications above are based on the primary sources.

## Proposed decision

Keep these three candidates and choose after a small test on abox. Start with Nomic to check the local setup because its weights are smallest; this is not an assumption that it retrieves best. Published benchmarks do not establish a winner for our repository.

## Test after discussion

1. **Prepare the same input.** Freeze a repository commit and list the files included. Split them into meaningful chunks: Markdown sections, HCL blocks, YAML resources, or shell functions. Save each chunk's path and line numbers. Keep chunks within every model's input limit, including prompt text.
2. **Define success first.** Write about ten real questions in Ukrainian and English. Label the relevant blocks before searching; several blocks may be correct. Agree on acceptable quality loss at 256 and 128 dimensions before results.
3. **Run one model at a time.** Pin weights and runtime versions. Verify that llama.cpp returns embeddings, then index full-size, 256- and 128-dimensional vectors into separate Qdrant collections and search each directly; two-stage search with a full-vector rescore is a later option. Follow each model's input prompts and normalization procedure. For Nomic, the reference MRL procedure includes LayerNorm before truncation and L2 normalization; check what the runtime already does. Compare with simple keyword search on identifier questions.
4. **Record useful results.** Count questions with a relevant block at rank 1 (hit@1) and within the first 3 (hit@3). Show language/type groups as counts, such as “2 of 3”, and inspect failures. Record median query time after warm-up (p50), process memory in RAM (RSS), and total indexing time.
5. **Decide together.** Choose the model and dimension offering acceptable retrieval quality and resource use. If none meets the criteria, revisit the choice. Mark this ADR Accepted only after agreement, and put measured results in CHANGELOG.md.

## Consequences

At the same numeric precision, 256 values take one third of the raw vector storage of 768 and one quarter of 1024; 128 takes one sixth and one eighth. Total Qdrant size also includes text, payload and the index. Shorter vectors do not shrink the model or guarantee unchanged quality. Changing the model requires re-embedding the corpus and queries consistently.

This is a proposal, not a completed experiment. Kubernetes deployment and agent memory management remain later tasks.

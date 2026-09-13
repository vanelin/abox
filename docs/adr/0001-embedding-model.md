# ADR-0001: Choosing an embedding model for abox

- Status: Accepted — Qwen3-Embedding-0.6B Q8_0, 256 dimensions.
- Date: 2026-09-13.

An ADR (Architecture Decision Record) records a choice and its reasons. This decision covers local retrieval; deployment comes later.

## Problem and requirements

An agent needs to find relevant Markdown, YAML, OpenTofu and shell blocks in abox for English and Ukrainian questions. Embeddings represent text as vectors; retrieving nearby vectors supplies context for RAG (Retrieval-Augmented Generation).

The model must run on CPU in our 4 CPU / 16 GB Codespace alongside KinD, have GGUF weights usable by llama.cpp, and support MRL (Matryoshka Representation Learning) for shorter vectors. We compare three local models; cloud APIs are outside this experiment.

## Options

Published properties checked on 2026-09-13. Q8_0 means 8-bit weights; file size is not runtime RAM.

| Model | Languages | Full vector → MRL options | Input limit | Q8_0 weights | Licence |
|---|---|---|---|---|---|
| Nomic Embed Text v1.5 | English-focused | 768 → 64–768 | 8192 tokens | 146 MB | Apache-2.0 |
| Qwen3-Embedding-0.6B | 100+ | 1024 → 32–1024 | 32k tokens | 639 MB | Apache-2.0 |
| EmbeddingGemma-300M | 100+ | 768 → 512/256/128 | 2048 tokens | 334 MB | Gemma terms |

Sources: [Nomic model](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) / [GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF), [Qwen model](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) / [GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF), [EmbeddingGemma model](https://huggingface.co/google/embeddinggemma-300m) / [GGUF](https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF), [Nomic's MRL explanation](https://www.nomic.ai/news/nomic-embed-matryoshka), [To MRL or not to MRL (arXiv 2605.16608)](https://arxiv.org/html/2605.16608), [Sentence Transformers on Matryoshka](https://sbert.net/examples/sentence_transformer/training/matryoshka/README.html).

## Decision

Use **Qwen3-Embedding-0.6B Q8_0, 256 dimensions**. It achieved the best first-result accuracy in our test and uses one quarter of the raw vector storage of its full 1024-dimensional output. Nomic uses less RAM and embeds the chunks faster, but finds fewer labelled answers.

Run llama.cpp with `--pooling last --embd-normalize -1`. Embed documents without a prefix; use this exact query template:

```text
Instruct: Given a question about a Kubernetes/OpenTofu repository, retrieve the file section that answers it
Query: <question>
```

Keep the first 256 coordinates, then L2-normalize documents and queries and search by cosine similarity. Shorter vectors reduce vector storage, not model size; changing the model requires re-embedding the data.

## Test

- **Input:** [144 frozen chunks](../labs/03/chunks.jsonl) and [10 labelled questions](../labs/03/questions.json), seven English and three Ukrainian. Regenerating chunks from a newer commit changes the input.
- **Setup:** llama.cpp tag `v0.4.0` (binary reports `0.4.0-dev`, commit `5266f24`), SHA256-checked models from [Makefile](../../Makefile), two CPU threads, one server slot, batches of eight, context 2048. Longer Nomic contexts in this GGUF build were not tested.
- **Comparison:** full / 256 / 128 dimensions and a lexical baseline. Nomic uses LayerNorm → truncate → L2, including at full size; Gemma and Qwen use truncate → L2. Each model uses its own prompts and tokenizer.
- **Method:** [eval.py](../labs/03/eval.py) runs embedding generation and Qdrant checks; [rescore.py](../labs/03/rescore.py) recalculates metrics without models. Follow the [run instructions](../labs/03/README.md) to repeat either step.

## Results

**hit@1** counts questions with a correct block first; **hit@3** counts those with a correct block among the first three. Both runs produced the same corrected scores below; [rescore-v2.json](../labs/03/rescore-v2.json) records them.

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

Qwen 128 ties 256 on hit@3, but 256 places the correct block first more often. Ten questions support a preliminary choice for this repository, not a general ranking. Qwen 256 still misses q06, “Звідки Flux отримує маніфести застосунків?”; Ukrainian retrieval needs further evaluation.

### Resources and tokenization

Latest runs: [Nomic](../labs/03/results-nomic-086a6a22fa49.json), [Gemma](../labs/03/results-gemma-b64b502449fa.json), [Qwen](../labs/03/results-qwen-8ec9dffbfc33.json).

| Model | Embed all chunks | RSS | Warm query p50 | Max chunk tokens | Max query tokens |
|---|---:|---:|---:|---:|---:|
| Nomic | 59.9 s | 305 MB | 67.7 ms | 720 | 40 |
| EmbeddingGemma | 69.4 s | 1239 MB | 93.3 ms | 818 | 26 |
| Qwen3-Embedding-0.6B | 256.8 s | 1741 MB | 31.4 ms | 724 | 49 |

Embedding time excludes Qdrant indexing; RSS is a sample after embedding, not peak memory. Query p50 measures ten repetitions of one warmed query and may benefit from caching; it is not new-query latency. For example, Qwen's p50 changed from 48.0 to 31.4 ms between runs.

Token maxima include model prompts and special tokens (`add_special=true`, `parse_special=true`). All inputs fit the 2048-token limit. These counts show context usage, not tokenizer quality or speed; token totals, distributions by language and tokenization time were not measured.

### Validation and label correction

Qdrant and in-memory search returned identical top-3 text in all 90 comparisons. Ordered IDs matched on 9/10 questions for Nomic 768, Gemma 256/128 and Qwen 1024, and 10/10 for the other variants. Differences involve duplicate Namespace chunks and do not change hit metrics; they do not establish correctness of the whole pipeline.

After reviewing q04, we added `releases/agentgateway.yaml:5-18` as a correct answer because its comment explains the version pin. [Labels v1](../labs/03/questions.v1.json) and [v2](../labs/03/questions.json) are preserved. Rescoring saved top-3 corrected the initial metrics; later full runs reproduced them. Only this label changed; Ukrainian scores and the baseline were unchanged.

<details>
<summary>Scores with the original v1 labels</summary>

| Model | Dimensions | hit@1 | hit@3 | UA hit@3 |
|---|---:|---:|---:|---:|
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

</details>

The [lab bundle](../labs/03/README.md) contains the frozen inputs, scripts and latest raw results. Initial raw runs remain in gitignored `.local/lab03/`. Separate held-out evaluation, Kubernetes deployment and agent memory integration remain future work.

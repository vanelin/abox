# Lab 3: evaluation scripts and evidence

[ADR-0001](../../adr/0001-embedding-model.md) selects Qwen3-Embedding-0.6B Q8_0 at 256 dimensions. This folder contains the inputs, scripts and latest saved runs behind that decision. Run commands from the repository root.

## Files

| File | Purpose |
|---|---|
| [chunks.jsonl](chunks.jsonl) | Frozen 144 chunks from `5ad7024` plus the Makefile targets; regenerating from a newer checkout changes the input |
| [questions.json](questions.json) / [questions.v1.json](questions.v1.json) | Corrected v2 labels / original labels; only q04 gained an alternative correct answer |
| [eval.py](eval.py) | Evaluate full / 256 / 128 dimensions, compare keyword search, optionally check Qdrant |
| [rescore.py](rescore.py) / [rescore-v2.json](rescore-v2.json) | Recalculate metrics from saved top-3 / expected v2 scores |
| `results-*.json` | Latest run per model: hashes, settings, top-3, timings and token counts |
| [chunk.py](chunk.py) | Generate chunks from tracked files into `.local/lab03/chunks.jsonl`; does not replace the frozen input |

## Recalculate scores without models

```bash
uv sync
uv run docs/labs/03/rescore.py
uv run docs/labs/03/rescore.py questions.v1.json
```

The first command after setup must report `matches rescore-v2.json: True`. The v1 command scores the latest top-3 using the original labels.

## Run a model locally

After `make llama` and `make models`, leave port 8081 free:

```bash
uv run docs/labs/03/eval.py qwen
```

Use `nomic` or `gemma` for the other candidates. The script checks the frozen input hash and local model SHA256, then starts and stops its own server. Add `--qdrant http://127.0.0.1:6333` only with Qdrant reachable; this creates new collections without deleting existing ones. Results and logs go to gitignored `.local/lab03/`.

## Test an existing server

Only after the server is running and reachable, for example through a cluster port-forward:

```bash
uv run docs/labs/03/eval.py qwen --endpoint http://127.0.0.1:8082
```

The endpoint must provide `/health`, `/tokenize` and raw `/v1/embeddings` (`--embd-normalize -1`). The script does not start or stop it; remote model hash, runtime version and RSS remain unknown. Verify those and the pooling settings separately. `--ctx-size 1024` checks inputs for an already configured 1024-token server; it does not reconfigure it. The local baseline remains 2048.

## Interpret and check

Both saved runs reproduced the corrected retrieval scores. Compare hit metrics and retrieved text: duplicate Namespace chunks can produce different IDs without changing the answer. Timings vary; the current script measures repeated-query p50 and distinct-query p50/p95 on a warm server. Neither guarantees uncached latency, and older results may lack the distinct-query fields. Initial raw runs remain in `.local/lab03/`.

```bash
uv run ruff check docs/labs/03
uv run ruff format --check docs/labs/03
uv run pyright
```

More detail: [local checklist](../03-local-embeddings.md), [cluster plan](../03-cluster-embeddings.md).

# Lab 3 evidence: embedding model evaluation

Scripts and data behind the Result section of [ADR-0001](../../adr/0001-embedding-model.md). Everything here is enough to re-score the saved runs or to repeat the experiment.

| File | What |
|---|---|
| `chunk.py` | Splits the tracked files into chunks; writes `.local/lab03/chunks.jsonl` |
| `chunks.jsonl` | The frozen chunk set used in the test: 144 chunks from commit `5ad7024` plus the Makefile targets, SHA256 `ddea3b90…`. Regenerating from a later HEAD gives a different set |
| `questions.json` | Ten labelled questions, label revision 2 (q04 gained one alternative answer after the run) |
| `questions.v1.json` | Labels as frozen before the initial runs |
| `eval.py` | Starts `llama-server`, embeds the chunks and questions, scores hit@1/hit@3 at full, 256 and 128 dimensions, optionally cross-checks through Qdrant |
| `results-*.json` | One file per model run (second, reproducing run): settings, hashes, per-question top-3, timings, token counts |
| `rescore.py` | Recomputes hit@1/hit@3 from the saved top-3 against any label file; no models needed |
| `rescore-v2.json` | Scores recomputed from the saved top-3 with revision-2 labels; the table in ADR-0001 and CHANGELOG comes from here |

Re-score the saved runs without models (about a second):

```bash
uv sync
uv run docs/labs/03/rescore.py                     # revision-2 labels, checks against rescore-v2.json
uv run docs/labs/03/rescore.py questions.v1.json   # original labels
```

Reproduce a run (needs `make llama` and `make models` first; the user's port-forward to Qdrant is optional):

```bash
uv sync
uv run docs/labs/03/eval.py qwen --qdrant http://127.0.0.1:6333
```

`eval.py` refuses to run if `chunks.jsonl` does not match the SHA256 recorded in `questions.json`, or if a model file does not match its Makefile pin. Results and server logs go to gitignored `.local/lab03/`.

Lint and types: `uv run ruff check docs/labs/03` and `uv run pyright`.

The latest runs reproduce the initial corrected retrieval scores; timings differ. Initial raw results remain in gitignored `.local/lab03/`. The v1 command applies the original labels to the latest top-3. Qdrant ID ordering differs in four comparisons involving duplicate Namespace chunks; retrieved text and hit metrics agree.

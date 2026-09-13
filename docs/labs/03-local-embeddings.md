# Lab 3: local embedding checklist

Status: local evaluations completed on 2026-09-13. This checklist covers setup, verification and optional cleanup. Model: [ADR-0001](../adr/0001-embedding-model.md); cluster plan: [ADR-0002](../adr/0002-embedding-deployment.md); evidence: [lab bundle](03/README.md). Run commands from the repository root.

## 1. Prepare

Check `df -h /workspaces`, `free -h` and `kubectl top nodes`; KinD shares the host. The three model files total about 1.1 GB; leave space for the build and outputs.

```bash
make llama
make models
uv sync
```

Makefile pins llama.cpp `v0.4.0`, model revisions and SHA256 values. Builds are incremental; verified downloads are reused. Generated files stay in `.local/`.

## 2. Check Qwen manually

In one terminal:

```bash
.local/llama.cpp/build/bin/llama-server -m .local/models/Qwen3-Embedding-0.6B-Q8_0.gguf --embedding --pooling last --embd-normalize -1 --host 127.0.0.1 --port 8081 --ctx-size 2048 --parallel 1 --threads 2 --threads-batch 2 --batch-size 2048 --ubatch-size 2048
```

After the server is listening, use another terminal:

```bash
curl -fsS http://127.0.0.1:8081/health
curl -fsS http://127.0.0.1:8081/v1/embeddings -H 'Content-Type: application/json' -d '{"input":["Kubernetes runs containers."]}' | jq -e '.data[0].embedding | length == 1024'
```

Expect a healthy server and 1024 raw values. Clients apply the ADR-0001 query template, truncate to 256 and L2-normalize; documents have no prefix. Stop this manual server with Ctrl+C before the local eval, which starts its own process.

## 3. Evaluate

```bash
uv run docs/labs/03/eval.py qwen
uv run docs/labs/03/rescore.py
```

The eval uses frozen inputs and saves a new result in `.local/lab03/`; compare hit metrics and retrieved text with ADR-0001. Rescore uses saved bundle results without inference and must print `matches rescore-v2.json: True`. Timings and duplicate-ID ordering may vary.

Use `nomic` or `gemma` to repeat the other candidates. Nomic requires mean pooling, `search_document: ` / `search_query: ` prefixes and LayerNorm → truncate → L2; eval applies these automatically. It returns 768 raw dimensions and uses less memory, with lower measured retrieval accuracy.

For an existing server, use `--endpoint http://127.0.0.1:8082`; the script does not start or stop it and cannot attest its model hash, runtime or RSS. See [endpoint requirements](03/README.md#test-an-existing-server). Optionally add `--qdrant http://127.0.0.1:6333` with a live port-forward; this writes new collections to Qdrant.

## 4. Finish

Eval stops only the server it started. Stop a manual server with Ctrl+C in its owning terminal; avoid broad `pkill`. Keep builds, weights and evidence for reuse. `make clean-llama` removes both the build and models and is optional, not a routine completion step. Do not delete cluster resources or Qdrant collections without an explicit request.

Done when: the API and retrieval checks pass and results are recorded. Cluster deployment remains a separate task.

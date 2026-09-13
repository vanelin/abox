# Lab 3: cluster deployment checklist

Status: plan; nothing deployed. Follow [ADR-0002](../adr/0002-embedding-deployment.md) for architecture and resources, and [ADR-0001](../adr/0001-embedding-model.md) for prompts and vector processing. Image publication, OCI release and deployment require explicit user approval; `make push` creates a release. Do not delete existing resources.

## A. Shared Qwen service

1. Check host RAM/disk and cluster load; KinD nodes share one host. Stop any local model run before testing the cluster copy.
2. Select an inspected, version-pinned chart and digest-pinned llama.cpp image. Add Namespace `embeddings` and HelmRelease in `releases/embeddings.yaml`, registered in `releases/kustomization.yaml`; the chart must render one Deployment with `Recreate` and a ClusterIP Service on 8081. No component-specific CRDs are needed.
3. Apply the ADR-0002 baseline: CPU request/limit 1/2, memory 2Gi/3Gi, complete runtime arguments, SHA256-verified download into disk-backed `emptyDir`, read-only model mount and startup/readiness probes. Start liveness conservatively; verify image permissions and writable paths.
4. Render with `kubectl kustomize releases/`; validate with client dry-run. Obtain approval before publishing or applying anything. Delivery remains OCI/Flux.
5. After authorised delivery, check Flux Kustomizations and HelmRelease Ready, Deployment available and Pod Ready. Record image digest, runtime version, model SHA256 and actual flags; the external eval cannot attest them.
6. Run the Service check below, then test from an in-cluster client as well. Compare hit@1/hit@3 and top-3 text with the saved results; identical Namespace chunks may have different IDs.
7. Measure embedding time, container peak memory where available, CPU throttling, OOM/restarts and host impact. `kubectl top pod` is a sample, not a peak measurement. Separate distinct-query p50/p95 from repeated-query timing; neither guarantees an uncached request.
8. If needed, test context/batch/ubatch 1024 separately, using the same frozen inputs and `--ctx-size 1024` in external eval. Recheck token limits and quality. Do not change pooling, prompts or normalization.
9. When finished, deliver zero replicas through chart values and the authorised OCI workflow. Do not suspend shared Flux reconciliation. Scaling to zero discards `emptyDir`, so the next Pod downloads weights again.

In one terminal after deployment:

```bash
kubectl -n embeddings port-forward svc/embeddings 8082:8081
```

In another:

```bash
curl -fsS http://127.0.0.1:8082/health
uv run docs/labs/03/eval.py qwen --endpoint http://127.0.0.1:8082
```

Add `--qdrant http://127.0.0.1:6333` if Qdrant is also forwarded. The server must return raw vectors; eval verifies 1024 dimensions and applies the 256-dimensional retrieval contract.

Done when: Flux manages a healthy service, retrieval quality is reproduced, resource impact is recorded and the pause procedure is verified. Record results in CHANGELOG; do not mark untested steps complete.

## B. Sidecar — only with a real consumer

- Choose a client that actually calls embeddings and Qdrant; do not attach a model to kagent or Qdrant without integration.
- Reuse A's pinned image, download and model contract. Run the model as a native sidecar (`initContainers`, `restartPolicy: Always`), listening on `127.0.0.1:8081`; no Service is needed.
- Gate client startup with a sidecar startup probe. For a loopback-only listener, use an exec probe calling localhost with a tool available in the image; default HTTP probes target the Pod IP.
- Budget model plus client, verify retrieval from inside the Pod and test a client restart. Measure before adding replicas.

Done when: the client retrieves through its sidecar and Qdrant, with Flux ownership and resource measurements recorded.

## C. llm-d — separate environment

- Find a supported environment; the documented CPU profile needs a minimum of 64 CPU cores / 64 GB per replica on 4th Gen Xeon or equivalent ([accelerators.md](https://github.com/llm-d/llm-d/blob/main/docs/getting-started/accelerators.md#cpu-inferencing)). This Codespace has 4 shared vCPU and `avx2` only; a below-profile run on vLLM's `avx2` path is possible but unsupported and must not be reported as a validated llm-d deployment. Pin llm-d, backend image, model revision/format and Gateway API/CRDs.
- Verify the backend directly: Qwen embedding support, pooling, normalization and `/v1/embeddings`. GGUF support in llama.cpp does not establish support in another backend.
- Verify the actual llm-d gateway/scheduler path and check CRD/GatewayClass conflicts before integration. A proxy or simulator is not proof of scheduled inference; embedding does not automatically benefit from generation-style prefill/decode splitting.
- Adapt the evaluation adapter if the backend lacks llama-server's `/tokenize` or raw-vector API; preserve model-specific processing. Record unsupported paths and errors instead of claiming success.
- After authorised deployment, test real inference, retrieval and resource use; document the outcome.

Done when: real embeddings pass through the verified llm-d path and preserve the retrieval contract. Until an environment is available, the deliverable is this plan, not a deployment.

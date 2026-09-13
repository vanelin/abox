# ADR-0002: Serving embeddings in the cluster

- Status: Proposed — no cluster deployment yet.
- Date: 2026-09-13.
- Model decision: [ADR-0001](0001-embedding-model.md).

## Problem and evidence

Future clients in KinD need a shared embedding endpoint; their `localhost` is not the Codespace host. The 4 CPU / 16 GB host is shared by all three KinD nodes, so node capacities must not be added. The last host check showed 8.5 GiB available RAM and 6 GB free disk; check again before deployment.

Measured locally at 256 dimensions, using the same 144 chunks and ten questions:

| Model | RSS after embedding | Embed all chunks | hit@1 | hit@3 |
|---|---:|---:|---:|---:|
| Qwen3-Embedding-0.6B Q8_0 | 1741 MB | 255–257 s | 7/10 | 9/10 |
| Nomic Embed v1.5 Q8_0 | 305 MB | 60–61 s | 3/10 | 7/10 |
| EmbeddingGemma-300M Q8_0 | 1239 MB | 63–69 s | 5/10 | 6/10 |

RSS is a process sample, not peak container memory. Node CPU-limit overcommit does not show actual usage or determine OOM order.

## Options

| Option | Benefit | Cost / decision |
|---|---|---|
| Shared Deployment + Service | One model process for multiple clients | Recommended; independent lifecycle, one network hop |
| Sidecar in the client Pod | Localhost access and shared lifecycle | Model process duplicated per client Pod; no embedding consumer exists yet |
| llm-d | Separate inference routing and scaling | Deferred; documented CPU profile needs 64 CPU / 64 GB per replica, and the embedding path is unverified |

The llm-d profile requirements are not Qwen's requirements. This Codespace can test a single llama-server without llm-d.

The 64 CPU / 64 GB figure is llm-d's supported CPU profile ("Each replica requires a minimum of 64 CPU cores and 64GB RAM", 4th Gen Xeon or equivalent), not a technical floor. The vLLM CPU backend underneath documents no core minimum and runs on `avx2` in "limited features" mode, with `avx512f` recommended. So a hand-sized llm-d with a 0.6B model could probably be made to start on less, but outside support. We do not attempt it here: this VM exposes 4 vCPU shared with three KinD nodes and `avx2` only (AMD EPYC 9V74 as presented, no AVX-512 flags), and llm-d's scheduling features target generative decoding, which an embedding request does not have.

## Proposed deployment

Use one Qwen Q8_0 replica in namespace `embeddings`, exposed as `embeddings.embeddings.svc:8081`. Set `strategy: Recreate` to avoid overlapping model Pods during rollout; brief downtime is acceptable. Deliver a Namespace and HelmRelease through `releases/` and OCI/Flux, following [CODEBASE.md](../../CODEBASE.md). A suitable chart still needs selection and pinning.

| Resource | Request | Limit |
|---|---:|---:|
| CPU | 1 | 2 |
| Memory | 2Gi | 3Gi |

This is a starting test budget, not a measured requirement. It gives Burstable QoS; Guaranteed requires matching CPU and memory requests/limits for all applicable containers. Measure container peaks, throttling and host impact before adjusting it; avoid simultaneous local inference.

Use a digest-pinned image reproducing llama.cpp `v0.4.0` and these baseline arguments, plus the model path:

```text
--embedding --pooling last --embd-normalize -1 --ctx-size 2048 --parallel 1 --threads 2 --threads-batch 2 --batch-size 2048 --ubatch-size 2048 --host 0.0.0.0 --port 8081
```

Clients apply the exact [ADR-0001 query template](0001-embedding-model.md#decision), keep the first 256 coordinates and L2-normalize. Documents have no prefix. The server returns raw 1024-dimensional vectors.

An initContainer downloads the revision-pinned GGUF from [Makefile](../../Makefile), checks SHA256 and writes to disk-backed `emptyDir`; the runtime mounts it read-only. Do not use `medium: Memory`. Removing the Pod loses the cache and triggers another download; consider a PVC only if repeated starts justify it. Budget image and model storage against the remaining disk.

Use `/health` startup and readiness probes; allow five minutes for server startup after the download, and tune liveness to tolerate CPU work. Use a non-root container and read-only root filesystem with required writable mounts. ClusterIP is not access control: reachable Pods may call the API. Add an HTTPRoute only when an external client needs one.

For a lasting pause, deliver zero replicas through chart values and the authorised OCI workflow. Suspending HelmRelease alone does not stop Pods; manual scaling may be corrected by the owner. Do not suspend the shared `releases` Kustomization to pause one model.

## Fallback and tuning

Fallback to Nomic if Qwen harms the stack or embedding time matters more than first-result accuracy. Change the pinned model URL/hash, use mean pooling, `search_document: ` / `search_query: ` prefixes and LayerNorm → truncate → L2. Start with memory request 512Mi / limit 1Gi, then measure. Switching models requires re-embedding stored data. Gemma is not the fallback: it used more memory than Nomic with lower hit@3 in this test.

After baseline validation, optionally test context/batch/ubatch 1024 with the same inputs; the longest Qwen input was 724 tokens. Compare memory, speed and retrieval before adoption. This profile is untested for future longer inputs. Keep Q8_0, pooling and prompts unchanged; stronger quantization is a separate quality experiment.

## Validation and deferred options

Follow the [cluster checklist](../labs/03-cluster-embeddings.md). Compare retrieval through the Service, measure distinct-query latency separately from repeated-query timing, and record resource impact. Duplicate chunk IDs may differ when their text is identical.

Sidecar requires a real client, a readiness-gated native sidecar and a combined client/model budget. llm-d requires another environment, verified backend weights/API and an actual scheduler path. Qwen has a decoder-based backbone, but embedding inference has no autoregressive output-decode stage; generation-oriented disaggregation is not automatically useful.

No publication, rollout or resource deletion is authorised by this document. Keep Proposed until the cluster test and decision review are complete.

## Sources

- [Kubernetes resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) and [QoS](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/): requests, limits and memory behavior.
- [Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#strategy), [sidecars](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/) and [emptyDir](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir): rollout, startup and storage lifecycle.
- [Flux HelmRelease](https://fluxcd.io/flux/components/helm/helmreleases/): suspension and drift detection.
- [llama.cpp v0.4.0](https://github.com/ggml-org/llama.cpp/blob/v0.4.0/tools/server/README.md), [Qwen GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF) and [llm-d CPU profile](https://github.com/llm-d/llm-d/blob/main/docs/getting-started/accelerators.md#cpu-inferencing): runtime contracts and requirements.
- [vLLM CPU installation](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/): `avx512f` recommended, `avx2` limited; no documented core minimum. Checked 2026-09-13.

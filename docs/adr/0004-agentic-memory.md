# ADR-0004: Memory for retrieval agents

- Status: Proposed
- Date: 2026-09-19
- Related: [retrieval toolsets](0003-agentic-retrieval.md), [embedding model](0001-embedding-model.md), [embedding deployment](0002-embedding-deployment.md)

## Context

Lab 5 explores how agents retrieve facts, follow relationships and retain user notes. The [frozen GitHub-profile corpus](../labs/05/data/vanelin.catalog.json) contains 135 nodes and 219 edges, including repositories, README sections and manually assigned topics.

We evaluated xray-memory with nomic/256, Qdrant with nomic/768, and the official Qdrant MCP server with MiniLM/384. All received the same 135 texts; xray additionally received graph edges and attributes.

## Decision

Use **xray-memory for structured corpus queries and agent notes**; retain **Qdrant for free-text retrieval**. Keep corpus facts and user notes separate, attribute notes to the user and report conflicts explicitly. A note must not silently replace a corpus fact.

The [xray agent](../../releases/agent-memory.yaml) uses graph traversal for relationships, attribute filters for exact selection and vector search for semantic lookup. This is the intended policy; the evaluation shows that the agent does not always follow it.

Lab 5 keeps Qwen components outside the active bundle to reduce memory use. This changes the deployment described in ADR-0003 without re-evaluating its Qwen recommendation.

## Evidence

The [evaluation review](../labs/05/evaluation-review.md) records 29 questions per agent: 17 lookup, six graph, four facet and two negative. Tool tests call memory directly; agent tests send only the question through A2A and capture tool traces. Codex judged 87 selected answers. There were 25 retries after HTTP 429 errors and six reruns after clarifying two questions.

### Tool retrieval

| Path | Hit@1 | Recall@5 | MRR@5 |
|---|---:|---:|---:|
| xray, no kind filter | 0.824 | 0.941 | 0.850 |
| xray, `kind=Repo` | 0.765 | 0.941 | 0.843 |
| Qdrant + nomic | 0.882 | 1.000 | 0.926 |

With supplied seeds and filters, xray answered 6/6 graph and 4/4 facet questions. The tested Qdrant MCP tools do not expose equivalent graph or attribute operations; this does not describe Qdrant's full capabilities.

A separate exact-cosine check on the same vectors gave Hit@1 15/17 at both 256 and 768 dimensions, with Recall@5 0.941 and 1.000 respectively (`.local/lab05/results-dimensions.json`). This limited check does not explain xray's full ranking difference.

### Agent answers

| Agent | Lookup | Graph | Facet | Negative | Total |
|---|---:|---:|---:|---:|---:|
| xray | 16/17 | 4/6 | 3/4 | 2/2 | 25/29 |
| Qdrant + nomic | 17/17 | 2/6 | 0/4 | 2/2 | 21/29 |
| Official + MiniLM | 16/17 | 0/6 | 0/4 | 2/2 | 18/29 |

xray followed relationships in only two of six graph questions: one traversal and one incoming-edge read. Its four failed answers were:

- **g01:** treated 27 search candidates as evidence of more Terraform repositories.
- **g02:** offered to verify Helm candidates later instead of answering.
- **f02:** used creation year instead of last-push year, missing dotfiles.
- **l13:** gave contradictory counts of Django repositories.

All recorded `recall` calls returned no notes, and no memory writes occurred. This campaign does not validate note retention, expiry, conflict handling or resistance to poisoning.

### Token usage

Tokens are prompt plus completion tokens summed across all recorded LLM calls. The mean covers the 29 selected answers per agent, including negative questions and incorrect answers; it excludes failed and superseded attempts. Campaign totals include those attempts and retries, but exclude early smoke tests.

| Agent | Mean tokens / selected answer | All attempts | Recorded tokens, all attempts | Attempts missing usage |
|---|---:|---:|---:|---:|
| xray | 15,369 | 41 | 530,062 | 0 |
| Qdrant + nomic | 7,648 | 39 | ≥264,756 | 1 |
| Official + MiniLM | 6,181 | 38 | ≥205,749 | 1 |

Means are rounded to whole tokens. Totals marked ≥ are lower bounds because missing usage is unknown, not zero. These are reported tokens, not billed cost; prompts and tool workflows differ between agents.

## Consequences

- Use `references` edges for tool, language and topic membership, `depth=1` for direct neighbours, and `map=vanelin` on corpus searches. Keep notes in the separate session map.
- [CI](../../.github/workflows/xray-memory-maps-image.yaml) builds encrypted maps; the tag hashes catalogs **and summaries**. The [release](../../releases/xray-memory.yaml) pins that tag. Seeding preserves existing files, so updating a populated PVC requires explicit map replacement while preserving session notes.
- A PVC preserves notes across pod restarts, but cluster/storage loss can erase them. Durable memory needs a separate recovery plan.
- The snapshot identity is stored with SOPS; Flux receives its decryption key from the environment or local SOPS key file. Provider API keys come from the environment via [secrets.sh](../../scripts/secrets.sh). Snapshot encryption protects stored data, not the MCP interface or answer correctness.
- xray consumed more tokens in this configuration, which requires recall and full node reads. Run evaluations sequentially to reduce rate-limit contention.

## Limits and follow-up

This is a small development set with one selected answer per question and assistant judgements. Prompts, embeddings and available information differ; the Qdrant agents retain prompts designed for Kubernetes manifests. This prompt mismatch limits the comparison. Current manifests reference the same ModelConfig, but historical reports lack configuration snapshots.

Before broader use, test the complete note lifecycle and poisoning scenarios, review ambiguous judgements with a person, and repeat evaluation with recorded configurations and held-out questions. Status remains Proposed pending acceptance of the architecture; human review of answers is a separate evidence check.

Raw reports are pinned by the [campaign manifest](../labs/05/evaluation/evaluation-campaign.json); per-answer reasons are in [judgements](../labs/05/evaluation/agentic-judgements.json).

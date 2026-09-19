# Lab 5: Evaluation Review

**2026-09-19 · 135 documents · 29 questions × 3 agents**

This compares configured agents on a frozen corpus. Codex reviewed all 87 selected answers; these are assistant judgements, not human adjudication.

## Corrections

- The [campaign manifest](evaluation/evaluation-campaign.json) pins reports by SHA256 and attempt order. Only failed attempts may be retried; repetitions remain separate. Failures stay in attempt and token totals.
- [Judgements](evaluation/agentic-judgements.json) are bound to answer/trace hashes. Correctness requires a complete answer without material contradictions. Rejected alternatives and quoted names are not positive answers.
- `g02` and `g03` now ask about detected Tools membership: Helm usage does not imply shipping a chart, and kbot mentions ArgoCD without a detected edge. Both questions were rerun for every agent; gold lists and prompts were unchanged. Old versions remain in cost totals but are excluded from accuracy.
- Graph traversal and reading incoming edges are counted separately. Official ingestion now skips existing documents and rejects changed or duplicate data.

## Agent results

| Agent | Lookup | Graph | Facet | Negative | Total |
|---|---:|---:|---:|---:|---:|
| xray | 16/17 | 4/6 | 3/4 | 2/2 | 25/29 |
| Qdrant + nomic | 17/17 | 2/6 | 0/4 | 2/2 | 21/29 |
| Official + MiniLM | 16/17 | 0/6 | 0/4 | 2/2 | 18/29 |

Key failures:

- **xray g01:** names all five Terraform repositories, then incorrectly claims more exist because search returned 27 candidates.
- **xray g02:** offers to verify candidates later instead of answering.
- **xray l13:** contradicts itself about the number of Django repositories.
- **xray f02:** filters `created=2026` instead of last-push `year=2026`, missing dotfiles.
- **Official g06:** mentions kbot but explicitly declines to classify it as Go; the old mention counter incorrectly credited it.

For six graph questions, xray used `get_graph_impact` once and read incoming edges once. All recorded `recall` calls returned no notes; traces contain no writes. Negative answers correctly reject the premise, but top-k retrieval alone does not prove absence across the entire corpus.

## Tool results

Both retrieval evaluations were rerun with corpus checks. Official ingestion verified 135 documents and added none.

| Retrieval path | Hit@1 | Recall@5 | MRR@5 |
|---|---:|---:|---:|
| xray, no kind filter | 0.824 | 0.941 | 0.850 |
| xray, kind=Repo | 0.765 | 0.941 | 0.843 |
| Qdrant + nomic | 0.882 | 1.000 | 0.926 |

With oracle arguments, xray answered 6/6 graph and 4/4 facet questions. Warm median lookup latency was 5 / 4 / 153 ms respectively, including MCP, embedding and caching differences. Qdrant completed with exit code 0 but logged `Session termination failed: 202` during cleanup.

## Limits

- xray has additional edges and attributes; Qdrant lacks curated GitOps membership edges. Equal texts do not provide equal information or tool capabilities.
- Prompts differ. Embeddings are nomic/256, nomic/768 and MiniLM/384. Token costs reflect the entire agent configuration.
- Current agents reference `openai-gpt-5-4-mini`; historical reports lack prompt/model snapshots, so configuration stability cannot be established retroactively.
- This is a development set with one selected answer per question, not evidence of statistical superiority. Review covers substantive answers, not every ancillary claim.
- `fork=false` does not prove authorship; `year` records the latest push, not push history.

## Attempts and reproduction

118 attempts: 87 initial, 25 retries after confirmed HTTP 429 errors, and six reruns of clarified questions. Early smoke tests are excluded.

| Agent | Attempts | 429 failures | Recorded tokens | Attempts missing usage |
|---|---:|---:|---:|---:|
| xray | 41 | 10 | 530062 | 0 |
| nomic | 39 | 8 | 264756 | 1 |
| official | 38 | 7 | 205749 | 1 |

Token totals include failed and excluded attempts. They are reported usage, not billing data; missing usage is unknown, not zero.

```bash
uv run docs/labs/05/scripts/summarise.py --review
```

Keep the pinned raw reports in `.local/lab05/` to reproduce the summary. New runs need their own campaign manifest and judgements. See [README](README.md) for test and evaluation commands.

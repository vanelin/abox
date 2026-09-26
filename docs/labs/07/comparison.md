# Phoenix vs MLflow: lab results

One test batch on 2026-09-26, using [scripts/runs.py](scripts/runs.py) to send messages through kagent's A2A endpoint. Both backends receive traces from the demo collector with the same `gen_ai_normalizer`; Phoenix also has an input/output adapter. This compares our configured integrations.

## Tests

| Scenario | Agent | Test |
|---|---|---|
| Retrieval and delegation | `retrieval-agent`, `retrieval-agent-nomic` | Ingest three objects per agent, then ask two questions in fresh chats |
| Conversation and memory | `retrieval-agent-xray` | Three turns in one chat, including a memory write |
| Tool failure | `k8s-agent` | Request an object that does not exist |

## Data delivery

Both backends contained 15 traces from 14 messages, including one extra three-span trace without a model call. Token totals matched in 14 of 15 traces.

In `10f4b77f…`, MLflow lacked two `k8s-agent` spans accounting for 6,387 tokens. The bridge collector restarted five times in 23 minutes; delivery loss during a restart is a suspected cause, not a proven one. A CPU request and longer probe timeouts were added. Sustained delivery after that change was not measured in this batch.

## Practical comparison

| Task | Phoenix | MLflow |
|---|---|---|
| Follow an agent run | Span tree with agent, model and tool types | Span tree and graph view |
| Inspect a tool call | Arguments and results on the span | Arguments and results on the span |
| Check token usage | Per call, trace and session | Trace totals and estimated cost; sessions grouped by the same ID |
| Find the failed call (`b63171f7…`) | Tool span marked ERROR | Tool span marked ERROR, while the trace state remained OK |
| Read conversation summaries | HTTP root limits the summary | Session inputs and outputs were empty; content was available in model spans |
| Observed memory use | 449 MiB + 51 MiB for PostgreSQL | 1,888–1,940 MiB for MLflow, excluding the bridge collector |

Both supported inspecting these runs. Phoenix used less memory in this deployment. These observations do not establish a general winner: evaluation workflows, prompt management and datasets were not tested, and the memory readings are samples rather than peak measurements.

## What we learned

- **Long conversations increased input tokens.** The first two xray turns used 16,779 and 32,648 input tokens; the memory-write turn used 27,240. Chat history and tool output contribute to the context sent to the model.
- **Delegation was visible in both backends.** Calls to `k8s-agent` appeared inside the caller's trace. The first ingests took 157–199 seconds, mostly in the delegate.
- **“Stored” did not mean the whole task was completed.** The first ingest by each retrieval agent (`1f2ad1f4…`, `10f4b77f…`) stored a vector without a recorded `write-cypher` call. The next four included graph writes. Checking the tool sequence exposed the missing step.
- **A successful trace can contain a failed tool.** Inspect child spans as well as the overall status; an HTTP success does not establish that the agent's task succeeded.
- **Instrumentation affects the summary.** The HTTP root span lacked the question and answer. These were available in model spans, but not consistently in trace and session summaries.

## Limits

One batch, small workload, different storage configurations and one incomplete trace. The shop's replay traces were explored separately and do not measure live LLM cost or latency. Jaeger was disabled, so this is a two-backend comparison, not a three-way comparison with the lab 6 setup.

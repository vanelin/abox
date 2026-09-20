# Lab 6: Agent results

Recorded on 2026-09-20 with kagent 0.10.1, Go ADK and the demo's OpenTelemetry Collector. These are individual observations, not a benchmark. [Overview](README.md) · [Demo results](demo.md)

## Retrieval-agent traces

Both agents received: “Which repositories use Terraform?” The Qdrant run was recorded before that workload was removed from the final bundle.

| Measurement | Qdrant agent, empty store | xray agent |
|---|---:|---:|
| Spans | 10 | 16 |
| Model calls | 3 | 3 |
| Tool calls | 2, both errors | 6, in parallel batches |
| Input / output tokens | Not recorded here | 16,478 / 403 |
| Controller request duration | 11.7 s | 26.5 s |

Evidence: Qdrant `c90c74cc50089c9cc0c8081f43864e14`; xray `c0df86cc8345cbce758cfdea334b02b6`.

The traces showed the agent loop, model name, token usage and tool arguments/results. Input tokens grew **2,905 → 5,914 → 7,659** as conversation history and tool output accumulated. Tool calls ran in parallel even though the UI listed them sequentially.

Two problems were visible in the trace:

- The Qdrant UI reported two successful calls, but both tool spans contained `no text content in tool response`.
- The xray agent used search instead of graph traversal and returned four of five Terraform repositories, missing `abox`. It also mistook a hint about the corpus size for a match count.

Instrumentation was incomplete: xray's agent work ended at 5.2 s, while the controller request lasted 26.5 s. The trace did not explain that gap.

## Can an agent investigate an incident?

With `paymentFailure=50%`, `observability-agent` used Grafana MCP to investigate checkout errors.

| Attempt | Result | Trace |
|---|---|---|
| No metric hints | Searched metric names, delegated to the tool-less `promql-agent`, then asked for more information; no metric query ran | `bd06d26e04beaa38fd3e16d0bae366d7` |
| Metric and labels supplied | Ran four queries; three were empty, and the remaining result was misinterpreted | `136e28688d7b9f33ae775462d9eeb2ad` |

The error signal was a label on `traces_span_metrics_calls_total`, not a metric with “error” in its name. The agent invented a `namespace` filter, then treated per-second rates as percentages:

| Service | Reported by agent | Recalculated from the returned rates |
|---|---:|---:|
| checkout | 1.67% | 0.0167 / 0.158 ≈ 10.6% |
| payment | 0.42% | 0.0042 / 0.0042 = 100% |

The agent blamed checkout instead of payment. The first, inconclusive attempt used about **43,000 input tokens**. Tool access and a plausible answer did not establish correctness; query labels, units and the time window needed manual review.

Grafana MCP also required `--allowed-hosts` for its Kubernetes hostname. Its floating image tag remains a reproducibility limitation.

## Jaeger and Phoenix

Agents export once to the Collector. Jaeger receives traces across the system; a separate pipeline sends filtered kagent traces to Phoenix and excludes controller API polling.

| | Jaeger | Phoenix |
|---|---|---|
| Main use in this lab | Service timing, failures and tool execution | Agent calls, token usage, prompts and responses |
| Storage | In memory, up to 25,000 traces | Postgres |
| Message content | Raw span attributes | Input/output fields populated by a Collector transform |

Trace `02ad36e78c5ef7eafefe7e6f5e2ecc8d` had 16 spans in both backends. After mapping `gcp.vertex.agent.*` to OpenInference input/output attributes, trace `b81baf8515bc8075b80db57df77f106d` displayed content on 15 model/tool spans. Root-level input/output remained empty.

The mapping depends on this instrumentation version. Prompts, answers, tool output and user identifiers are present in traces. Phoenix authentication is disabled for this lab; all forwarded interfaces must remain private.

## LLM gateway

`agentgateway-llm` served `gemini-3.5-flash-lite` through Google's OpenAI-compatible endpoint, using a key mounted from a Kubernetes Secret. A request without a client API key returned **HTTP 200** and `gateway ok`. Gateway access logs included status, duration, model and token counts; no Collector export was configured for this gateway.

The native Gemini adapter returned 401 with the same credential. Direct Google requests and the OpenAI-compatible adapter worked; the exact cause was not established.

Attaching the UI to the traffic gateway fixed browser access but also exposed configuration endpoints on that port. This was reverted in the final manifest: the admin UI remains on port 15000, separate from the LLM API. The browser Playground is therefore not a verified final access path.

Configuration is stored on a PVC. The ConfigMap only seeds an empty volume; updating it does not replace configuration saved through the admin API.

## Agent logs

With `otel.logging` enabled, 15 records for one question reached OpenSearch with trace and span IDs (`7fa8b55f5a6e8111e5bffe5616810150`). However, their bodies contained `<elided>` and `@timestamp` was the Unix epoch; only `observedTimestamp` was populated. Trace-ID lookup worked, while ordinary time-range searches missed these records. Full message content remained in spans.

## Resource limits

During extended testing, Prometheus restarted 25 times, with OOM kills at its 400 MiB limit; OpenSearch restarted 23 times. Host load reached 40 on four CPUs, with 177 MB free. Dashboard gaps and Collector export errors were the visible symptoms. OpenSearch restarts lost stored logs, limiting later verification.

Prometheus and OpenSearch limits were raised, OpenSearch received a longer startup allowance, and unused workloads from earlier labs were removed. **Sustained stability after these changes was not verified.** One OpenSearch exit with code 143 remained unexplained.

## Conclusions

- Traces exposed reasoning and tool-use mistakes hidden by plausible answers.
- Token usage grew with repeated context and tool output.
- Missing or broken telemetry also affected the investigation tools themselves.
- Go/Python runtime comparison and dedicated agent dashboards were not completed.

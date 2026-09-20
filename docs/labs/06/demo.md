# Lab 6: Demo results

Recorded on 2026-09-20 with OpenTelemetry Demo 3.0.0 (chart 0.41.2), running on a 4 CPU / 16 GB Codespace with three KinD nodes. [Overview](README.md) · [Agent results](observations.md)

## Deployment

| Host metric | Before deployment | After 14 HelmReleases became Ready |
|---|---:|---:|
| Memory used | 3.3 GiB | 12.1 GiB |
| Memory available | 12.4 GiB | 3.9 GiB |
| Load average | — | 25 / 15 / 11 |

Three releases timed out during the initial installation. After checking pods and events, `flux reconcile helmrelease <name> --reset` allowed them to recover. No OOM kills were observed at this stage; later resource failures are covered in [agent results](observations.md#resource-limits).

Two setup issues required changes:

- **xray-memory:** chart 0.6.3 referenced an image that returned 404 during the check. Chart 0.6.0 was retained.
- **Load generation:** the running demo used k6, so the upstream Locust UI configuration did not work. Traffic was controlled through `loadGeneratorTraffic` and `loadGeneratorVUs` in flagd.

KinD nodes share the host's resources. Scheduler capacity and container requests were insufficient to assess headroom; host memory, load and actual pod usage also mattered.

## Baseline: one order

Trace `14152593b94ca3460a30873af81e5852`: **51 spans, 11 services, 51 ms**.

The frontend span lasted 50.5 ms but spent less than 1 ms on its own work. Its duration mostly reflected downstream calls. Checkout steps ran sequentially: prepare items, payment, shipping, empty cart, email, then publish the order.

Kafka consumers used separate traces linked to the producer with `FOLLOWS_FROM`. The checkout trace alone did not cover subsequent accounting or fraud-detection work.

## Three fault experiments

### 1. Payment errors

With `paymentFailure` set to 50% and five configured virtual users, span-derived metrics showed:

| Service | Requests/s | Error rate | p95 |
|---|---:|---:|---:|
| payment | 0.08 | 57.2% | 38 ms |
| checkout | 0.08 | 44.4% | 155 ms |
| frontend | 7.79 | 1.1% | 99 ms |

A high payment failure rate barely changed the frontend's aggregate error rate. The trace identified payment as the source; upstream error spans showed propagation of that failure.

In a separate sample of 95 payment spans, all 11 failures belonged to gold customers. The `demo.user_context.loyalty_level` attribute exposed this distinction; the aggregate metrics did not. The matching OpenSearch record had severity `warn` and a trace ID, so an error-only log filter would miss it.

Evidence: `e877c8923e64cb85bba693a80999e6d9`.

### 2. Slow shipping

With `intlShippingSlowdown=5sec`, a manual international order took **5385 ms**. Of that, **5016 ms** was in `shipping POST /ship-order`; the trace contained no error spans.

The trace located the delay but did not explain the affected customer group: shipping spans had no country attribute. Metrics reported high latency, but a small sample made percentile estimates unreliable.

Evidence: `fa221393e490c4d6c775293efe381921`.

**Limitation:** `paymentFailure` was still enabled during this experiment. The shipping trace is useful evidence, but this was not an isolated fault test; aggregate error rates were excluded.

### 3. Unreachable payment service

| Observation | Payment answered with an error | Payment was unreachable |
|---|---|---|
| Payment server span | Present, with error | Absent |
| Deepest error | Payment | Checkout's payment client span |
| Message | Invalid token | `name resolver error: produced zero addresses` |
| Failed call duration | About 5 ms | About 6 ms |

When payment was unreachable, checkout reported the failure while payment disappeared from the metric result. Missing telemetry was distinct from zero errors. The error message identified name resolution as the failed layer.

Evidence: `6641614504af09cc15d7454fba8aa31e`.

The planned `failedReadinessProbe` experiment was replaced: the deployed cart had no readiness probe to observe the injected failure.

## Takeaways and open questions

- Metrics locate the affected operation; traces follow the failure; correlated logs add detail.
- Parent duration includes downstream work. Compare child spans and self time before blaming a service.
- Low traffic and newly created metric series can make short-window error rates misleading.
- Which business attributes should shipping record without exposing personal data?
- How should alerts detect missing service telemetry and failures after Kafka processing?

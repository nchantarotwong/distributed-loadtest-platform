# Production-Grade Distributed Load Testing Platform

## Design Goals

- Eliminate false confidence in load tests
- Enable deterministic performance runs
- Separate workload modeling from transport
- Support horizontal generator scaling
- Remain portable across container runtimes

## Failure Modes in Load Testing

Some failures make tests unrealistic.
Others make them dangerously misleading.

The worst load tests are not the naive ones, 
they are the ones that produce false confidence.

### Tests that silently invalidate results

- Coordinated omission
  - Latency pauses hide inside the load generator, dramatically understating tail latency.
- Load generator bottlenecks
  - The test saturates the generator before the system, producing false capacity signals.
- Percentile blindness (averages hide pain)
  - Averages look healthy while P95/P99 users experience unacceptable latency.
- Missing saturation signals
  - Without CPU, memory, queue depth, and connection pressure, you cannot identify the real bottleneck.

### Tests that model the wrong reality

- Testing only happy-path endpoints
- Unrealistic ramp patterns

## Prerequisites

A container runtime with Compose support is required.

Tested with:
- Docker Compose V2 (primary)
- Podman + podman-compose (compatible)

The stack is runtime-agnostic and intentionally avoids engine-specific features.

## Quickstart

Run the stack (master + workers):

```bash
docker compose up --build --scale locust-worker=2
```

Podman users can replace docker compose with podman-compose.

### Access the UIs

- Locust: http://localhost:8089
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090

### Validate the Stack

1. Access the Locust UI.
2. Target host should default to http://demo-target:8000 (included demo API) or set BASE_URL to your API.
3. Start a small run (example):
   - Users: 50
   - Spawn rate: 5
   - Duration: 1m

Confirm that workers register with the master before initiating larger runs.

### Artifacts

Artifacts are intended to support regression detection and capacity comparison across runs.
- CSV and run metadata are written to ./artifacts/ (mounted volume).

### Notes

- This mode is the fastest feedback loop for iteration and CI smoke runs.
- Distributed mode is enabled even locally (master/worker).

---

## Profiles

Profiles provide deterministic, repeatable headless runs suitable for CI and capacity validation.

Run them by setting env vars inline (examples below), or by sourcing the provided `.env.*` files.

Smoke:
```bash
TEST_PROFILE=smoke LOCUST_USERS=10 LOCUST_SPAWN_RATE=2 LOCUST_DURATION=30s docker compose --profile runner up --build locust-runner
```

Baseline:
```bash
TEST_PROFILE=baseline LOCUST_USERS=50 LOCUST_SPAWN_RATE=5 LOCUST_DURATION=5m docker compose --profile runner up --build locust-runner
```

Spike:
```bash
TEST_PROFILE=spike LOCUST_USERS=200 LOCUST_SPAWN_RATE=50 LOCUST_DURATION=60s docker compose --profile runner up --build locust-runner
```

Using the checked-in env files:

```bash
set -a && source .env.smoke && set +a
docker compose --profile runner up --build locust-runner
```

Artifacts will appear in ./artifacts/ as CSV.

---

## Scaling the Load Generator

To increase load generator capacity on your machine:
```bash
docker compose up --build --scale locust-worker=8
```

### What scales

- locust-worker containers scale horizontally
- The Locust master coordinates workers automatically

### How to tell if the load generator is the bottleneck

- Grafana dashboard: worker CPU pegged, RPS stops increasing, latency behavior looks "flat weird"
- Locust UI: increasing users does not increase throughput proportionally

### Recommended practice

- Begin below expected capacity and ramp gradually.
- Watch p95/p99 latency and error rate as you increase load.
- If the load generator saturates first, add workers (or move to Kubernetes later).

---

## Interpreting Results

Focus on signals, not single metrics.

### Warning signs

- Rising p95/p99 latency while throughput plateaus
- Error rate increasing with load
- CPU saturation without proportional RPS gain
- Queue depth or connection pressure climbing

### Healthy scaling typically shows

- Throughput increasing proportionally with users
- Stable tail latency
- Controlled error rates

Always validate that the load generator is not the bottleneck before drawing conclusions.

---

## Protocol adapters (HTTP today, gRPC later)

Scenarios are written against a small client interface:
- HTTP adapter: src/platform/clients/http.py (implemented)
- gRPC adapter: src/platform/clients/grpc.py (stub, planned)

To add gRPC later, implement the same interface and switch via CLIENT=grpc (no scenario rewrite).

"""
Locust workload modeling a read-heavy service with occasional CPU pressure.

Intended to demonstrate distributed load generation patterns rather than
synthetic hello-world traffic.

Profiles are selected via TEST_PROFILE to enable repeatable, headless runs.
"""

import os
import random
import re
from locust import between, events, HttpUser, tag, task


PROFILES = {
    "smoke":   {"users": 10,  "spawn_rate": 2,  "duration_s": 30},
    "baseline": {"users": 50,  "spawn_rate": 5,  "duration_s": 300},
    "spike":   {"users": 200, "spawn_rate": 50, "duration_s": 60},
}


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def parse_duration_s(value: str) -> int | None:
    """
    Parse a Locust-style duration ("30s", "5m", "1h30m") into seconds.

    Returns None if the string can't be parsed so the caller can skip the
    duration check rather than raise on an unexpected format.
    """
    matches = re.findall(r"(\d+)\s*([smh])", value.strip().lower())
    if not matches:
        return None
    unit_s = {"s": 1, "m": 60, "h": 3600}
    return sum(int(n) * unit_s[u] for n, u in matches)


def get_profile() -> dict:
    name = os.getenv("TEST_PROFILE", "smoke").strip().lower()
    if name not in PROFILES:
        name = "smoke"

    return {"name": name, **PROFILES[name]}


@events.init.add_listener
def validate_profile(environment, **_kwargs):
    profile = get_profile()

    users = int(os.getenv("LOCUST_USERS", profile["users"]))
    spawn = int(os.getenv("LOCUST_SPAWN_RATE", profile["spawn_rate"]))

    # Duration is optional and only compared when it parses to a known format.
    duration_env = os.getenv("LOCUST_DURATION")
    duration_s = parse_duration_s(duration_env) if duration_env else None
    duration_mismatch = duration_s is not None and duration_s != profile["duration_s"]

    if users != profile["users"] or spawn != profile["spawn_rate"] or duration_mismatch:
        failure_str = "\nLOCUST_* values do not match TEST_PROFILE defaults.\n" +\
            f"TEST_PROFILE={profile['name']} expects users={profile['users']} "\
            f"spawn_rate={profile['spawn_rate']} duration_s={profile['duration_s']}\n" +\
            f"but got LOCUST_USERS={users} LOCUST_SPAWN_RATE={spawn} "\
            f"LOCUST_DURATION={duration_env}\n"

        if env_bool("STRICT_PROFILES") or env_bool("CI"):
            raise RuntimeError(failure_str)
        else:
            print(f"\nWARNING: {failure_str}")


QUANTILES = (0.5, 0.95, 0.99)


def _render_metrics(environment) -> str:
    """
    Render Locust runner stats as Prometheus text exposition format.

    Percentiles come straight from Locust's own stats engine, so p50/p95/p99
    reflect real tail latency instead of the always-zero value the external
    locust_exporter reports. No third-party deps required: the stock locust
    image is enough because we format the exposition text by hand.

    Two flavours of percentile are exposed:
    - scope "current" (locust_response_time_current_ms): sliding window,
      matching the live UI charts.
    - scope "total" (locust_response_time_total_ms): cumulative over the whole
      run, the headline number for capacity decisions.
    """
    stats = environment.runner.stats
    total = stats.total
    out = []

    def emit(name, mtype, help_text, samples):
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} {mtype}")
        for labels, value in samples:
            label_str = f"{{{labels}}}" if labels else ""
            out.append(f"{name}{label_str} {value}")

    emit("locust_users", "gauge", "Simulated users currently running",
         [("", environment.runner.user_count)])
    emit("locust_requests_total", "gauge", "Total completed requests",
         [("", total.num_requests)])
    emit("locust_failures_total", "gauge", "Total failed requests",
         [("", total.num_failures)])
    emit("locust_rps", "gauge", "Current aggregate requests per second",
         [("", total.current_rps)])
    emit("locust_fail_per_sec", "gauge", "Current aggregate failures per second",
         [("", total.current_fail_per_sec)])
    emit("locust_fail_ratio", "gauge", "Aggregate failure ratio (0-1)",
         [("", total.fail_ratio)])

    # Response-time percentiles: the whole point of this platform.
    emit("locust_response_time_current_ms", "gauge",
         "Sliding-window response time percentile (ms)",
         [(f'quantile="{q}"', total.get_current_response_time_percentile(q) or 0)
          for q in QUANTILES])
    emit("locust_response_time_total_ms", "gauge",
         "Cumulative response time percentile over the run (ms)",
         [(f'quantile="{q}"', total.get_response_time_percentile(q) or 0)
          for q in QUANTILES])
    emit("locust_response_time_avg_ms", "gauge", "Average response time (ms)",
         [("", total.avg_response_time)])
    emit("locust_response_time_max_ms", "gauge", "Max response time (ms)",
         [("", total.max_response_time)])

    # Per-endpoint breakdown. Cardinality stays bounded because get_item groups
    # its 1000 ids under a single name (see DemoUser.get_item).
    endpoints = [e for e in stats.entries.values()]
    emit("locust_endpoint_rps", "gauge", "Current requests per second per endpoint",
         [(f'method="{e.method}",name="{e.name}"', e.current_rps) for e in endpoints])
    emit("locust_endpoint_p95_ms", "gauge", "Sliding-window p95 latency per endpoint (ms)",
         [(f'method="{e.method}",name="{e.name}"',
           e.get_current_response_time_percentile(0.95) or 0) for e in endpoints])

    return "\n".join(out) + "\n"


@events.init.add_listener
def register_metrics_endpoint(environment, **_kwargs):
    """Expose /metrics on the Locust master web UI for Prometheus to scrape."""
    if environment.web_ui is None:
        return  # workers and headless runs have no web UI

    from flask import Response

    @environment.web_ui.app.route("/metrics")
    def prometheus_metrics():
        return Response(_render_metrics(environment), mimetype="text/plain")


@events.test_start.add_listener
def announce_profile(environment, **_kwargs):
    profile = get_profile()

    print(
        f"\n=== Locust Profile ==================================\n"
        f"Profile:      {profile['name']}\n"
        f"Users:        {profile['users']}\n"
        f"Spawn rate:   {profile['spawn_rate']}\n"
        f"Duration (s): {profile['duration_s']}\n"
        f"=====================================================\n"
    )


class DemoUser(HttpUser):
    """
    Models a realistic read-heavy workload against demo-target.

    Traffic mix:
    - list_items (fanout): 60%
    - get_item (lookup): 30%
    - compute (CPU): 10%
    """
    wait_time = between(0.5, 2.5)

    @task(6)
    @tag("read")
    def list_items(self):
        limit = random.choice([10, 25, 50])
        self.client.get(f"/items?limit={limit}")

    @task(3)
    @tag("read")
    def get_item(self):
        item_id = random.randint(1, 1000)
        # Group all ids under one name so Prometheus series stay bounded
        # instead of exploding to ~1000 per-id entries.
        self.client.get(f"/items/{item_id}", name="/items/:id")

    @task(1)
    @tag("compute")
    def compute(self):
        self.client.get("/compute")

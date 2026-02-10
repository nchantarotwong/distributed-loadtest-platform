"""
Locust workload modeling a read-heavy service with occasional CPU pressure.

Intended to demonstrate distributed load generation patterns rather than
synthetic hello-world traffic.

Profiles are selected via TEST_PROFILE to enable repeatable, headless runs.
"""

import os
import random
from locust import HttpUser, task, between


PROFILES = {
    "smoke":   {"users": 10,  "spawn_rate": 2,  "duration_s": 30},
    "baseline": {"users": 50,  "spawn_rate": 5,  "duration_s": 300},
    "spike":   {"users": 200, "spawn_rate": 50, "duration_s": 60},
}


def get_profile() -> dict:
    name = os.getenv("TEST_PROFILE", "smoke").strip().lower()
    if name not in PROFILES:
        name = "smoke"

    return {"name": name, **PROFILES[name]}


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
    def list_items(self):
        limit = random.choice([10, 25, 50])
        self.client.get(f"/items?limit={limit}")

    @task(3)
    def get_item(self):
        item_id = random.randint(1, 1000)
        self.client.get(f"/items/{item_id}")

    @task(1)
    def compute(self):
        self.client.get("/compute")

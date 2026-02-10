"""
Locust workload modeling a read-heavy service with occasional CPU pressure.

Intended to demonstrate distributed load generation patterns rather than
synthetic hello-world traffic.

Profiles are selected via TEST_PROFILE to enable repeatable, headless runs.
"""

import os
import random
from locust import between, events, HttpUser, tag, task


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


@events.init.add_listener
def validate_profile(environment, **_kwargs):
    profile = get_profile()

    users = int(os.getenv("LOCUST_USERS", profile["users"]))
    spawn = int(os.getenv("LOCUST_SPAWN_RATE", profile["spawn_rate"]))

    if users != profile["users"] or spawn != profile["spawn_rate"]:
        print(
            "\nWARNING: LOCUST_* values do not match TEST_PROFILE defaults.\n"
            f"TEST_PROFILE={profile['name']} expects users={profile['users']} spawn_rate={profile['spawn_rate']}\n"
            f"but got LOCUST_USERS={users} LOCUST_SPAWN_RATE={spawn}\n"
        )


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
        self.client.get(f"/items/{item_id}")

    @task(1)
    @tag("compute")
    def compute(self):
        self.client.get("/compute")

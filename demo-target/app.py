"""
Deterministic FastAPI service used as a controllable load target for the
distributed load testing platform.

The service intentionally supports latency injection, tail behavior,
error simulation, and optional authentication to model realistic
production failure modes.
"""
import asyncio
import hashlib
import os
import random
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="demo-target", version="0.1.0")


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


REQUIRE_AUTH = _env_bool("REQUIRE_AUTH", False)
AUTH_BEARER_TOKEN = os.getenv("AUTH_BEARER_TOKEN", "devtoken")

BASE_LATENCY_MS = _env_int("BASE_LATENCY_MS", 5)
JITTER_LATENCY_MS = _env_int("JITTER_LATENCY_MS", 15)

# Tail latency injection for some requests.
TAIL_PROB = _env_float("TAIL_PROB", 0.02)  # 2%
TAIL_MIN_MS = _env_int("TAIL_MIN_MS", 200)
TAIL_MAX_MS = _env_int("TAIL_MAX_MS", 600)

# Error injection (independent probabilities, keep small).
ERROR_429_PROB = _env_float("ERROR_429_PROB", 0.005)  # 0.5%
ERROR_500_PROB = _env_float("ERROR_500_PROB", 0.002)  # 0.2%

# CPU burn configuration for /compute
CPU_ITERATIONS = _env_int("CPU_ITERATIONS", 40_000)


def _sleep_ms(ms: int) -> None:
    if ms <= 0:
        return
    time.sleep(ms / 1000.0)


def _latency_budget_ms() -> int:
    # Baseline + jitter, with occasional tail amplification.
    total = BASE_LATENCY_MS + random.randint(0, max(0, JITTER_LATENCY_MS))
    if random.random() < TAIL_PROB:
        total += random.randint(TAIL_MIN_MS, TAIL_MAX_MS)
    return total


async def _maybe_inject_latency_async() -> None:
    # MUST be awaited, not slept. This runs in the request middleware on the
    # event loop; a blocking time.sleep() here would serialize every in-flight
    # request and fabricate tail latency that has nothing to do with the
    # configured model -- the exact "test that silently invalidates results"
    # this platform exists to avoid. asyncio.sleep yields the loop so requests
    # actually run concurrently.
    ms = _latency_budget_ms()
    if ms > 0:
        await asyncio.sleep(ms / 1000.0)


def _maybe_inject_errors() -> None:
    # Inject occasional 429/500 to model rate limiting and transient faults.
    if random.random() < ERROR_429_PROB:
        raise HTTPException(status_code=429, detail="rate limited (injected)")
    if random.random() < ERROR_500_PROB:
        raise HTTPException(status_code=500, detail="server error (injected)")


def _auth_check(authorization: str | None) -> None:
    if not REQUIRE_AUTH:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != AUTH_BEARER_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    """Central failure and latency injection layer for workload realism."""
    # Do not interfere with orchestration/metrics endpoints.
    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    await _maybe_inject_latency_async()
    try:
        _maybe_inject_errors()
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    return await call_next(request)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe for container orchestration."""
    return {"ok": True}


@app.get("/config")
def config() -> dict[str, Any]:
    """Exposes active runtime configuration for test verification."""
    return {
        "require_auth": REQUIRE_AUTH,
        "base_latency_ms": BASE_LATENCY_MS,
        "jitter_latency_ms": JITTER_LATENCY_MS,
        "tail_prob": TAIL_PROB,
        "tail_min_ms": TAIL_MIN_MS,
        "tail_max_ms": TAIL_MAX_MS,
        "error_429_prob": ERROR_429_PROB,
        "error_500_prob": ERROR_500_PROB,
        "cpu_iterations": CPU_ITERATIONS,
    }


@app.get("/items")
def list_items(
    limit: int = 25,
    offset: int = 0,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Paginated read endpoint modeling fanout under load."""
    _auth_check(authorization)

    limit = max(1, min(limit, 200))
    offset = max(0, min(offset, 10_000))

    items = [{"id": offset + i, "name": f"item-{offset + i}"} for i in range(limit)]
    return {"limit": limit, "offset": offset, "items": items}


@app.get("/items/{item_id}")
def get_item(
    item_id: int,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Item lookup endpoint with small, variable I/O latency."""
    _auth_check(authorization)

    if item_id < 0:
        raise HTTPException(status_code=400, detail="item_id must be >= 0")

    # Add a tiny "DB lookup" feel (still fast).
    _sleep_ms(random.randint(1, 8))

    return {"id": item_id, "name": f"item-{item_id}", "value": "demo"}


@app.get("/compute")
def compute(
    seed: str = "x",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """CPU-bound endpoint used to simulate compute pressure under load."""
    _auth_check(authorization)

    # CPU work to let you observe saturation behavior under load.
    # Intentionally deterministic-ish per seed.
    data = seed.encode("utf-8")
    h = data
    for _ in range(max(1, CPU_ITERATIONS)):
        h = hashlib.sha256(h).digest()

    # Return a short digest so results are stable.
    return {"seed": seed, "digest": h[:8].hex()}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

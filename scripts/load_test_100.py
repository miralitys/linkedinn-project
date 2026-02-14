#!/usr/bin/env python3
"""Simple async load test for LFAS (100 active users baseline)."""

import argparse
import asyncio
import os
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv


AUTH_ENDPOINTS = [
    "/people?limit=20&offset=0",
    "/posts?limit=20&offset=0",
    "/reddit/posts?limit=20&offset=0",
    "/news?limit=20&offset=0",
]

PUBLIC_ENDPOINTS = [
    "/",
    "/login",
]


@dataclass
class Stats:
    total: int = 0
    ok: int = 0
    error: int = 0
    status_counts: Counter = field(default_factory=Counter)
    latencies_ms: List[float] = field(default_factory=list)
    endpoint_latencies: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    endpoint_totals: Counter = field(default_factory=Counter)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def add(self, endpoint: str, status_code: int, latency_ms: float) -> None:
        async with self.lock:
            self.total += 1
            self.status_counts[status_code] += 1
            self.latencies_ms.append(latency_ms)
            self.endpoint_latencies[endpoint].append(latency_ms)
            self.endpoint_totals[endpoint] += 1
            if 200 <= status_code < 400:
                self.ok += 1
            else:
                self.error += 1


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    idx = max(0, min(len(values) - 1, int(round((pct / 100.0) * (len(values) - 1)))))
    sorted_vals = sorted(values)
    return sorted_vals[idx]


async def login(base_url: str, email: str, password: str, timeout_sec: float) -> Dict[str, str]:
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout_sec, follow_redirects=False) as client:
        resp = await client.post(
            "/login",
            data={"email": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code not in (302, 303):
            raise RuntimeError(f"Login failed: HTTP {resp.status_code}")
        cookies = dict(client.cookies)
        if not cookies:
            raise RuntimeError("Login failed: no session cookie received")
        return cookies


async def worker(
    worker_id: int,
    base_url: str,
    timeout_sec: float,
    think_ms: int,
    endpoints: List[str],
    stats: Stats,
    end_ts: float,
    cookies: Optional[Dict[str, str]] = None,
) -> None:
    rnd = random.Random(worker_id + int(time.time()))
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout_sec,
        cookies=cookies,
        follow_redirects=False,
    ) as client:
        while time.perf_counter() < end_ts:
            endpoint = rnd.choice(endpoints)
            started = time.perf_counter()
            status = 0
            try:
                resp = await client.get(endpoint)
                status = resp.status_code
            except Exception:
                status = 0
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            await stats.add(endpoint, status, elapsed_ms)
            if think_ms > 0:
                await asyncio.sleep(rnd.uniform(0, think_ms / 1000.0))


async def run_test(
    base_url: str,
    vus: int,
    duration_sec: int,
    timeout_sec: float,
    think_ms: int,
    public_only: bool,
) -> int:
    stats = Stats()
    cookies = None
    endpoints = PUBLIC_ENDPOINTS

    if not public_only:
        email = os.getenv("LOADTEST_EMAIL") or os.getenv("AUTH_ADMIN_EMAIL")
        password = os.getenv("LOADTEST_PASSWORD") or os.getenv("AUTH_ADMIN_PASSWORD")
        if email and password:
            try:
                cookies = await login(base_url, email, password, timeout_sec)
                endpoints = AUTH_ENDPOINTS
                print(f"Auth mode: ON ({email})")
            except Exception as e:
                print(f"Auth mode failed, fallback to public endpoints: {e}")
        else:
            print("Auth credentials are not set, fallback to public endpoints.")

    start_ts = time.perf_counter()
    end_ts = start_ts + duration_sec
    tasks = [
        asyncio.create_task(
            worker(
                worker_id=i,
                base_url=base_url,
                timeout_sec=timeout_sec,
                think_ms=think_ms,
                endpoints=endpoints,
                stats=stats,
                end_ts=end_ts,
                cookies=cookies,
            )
        )
        for i in range(vus)
    ]
    await asyncio.gather(*tasks)
    real_duration = max(0.001, time.perf_counter() - start_ts)

    if stats.total == 0:
        print("No requests executed.")
        return 2

    success_rate = (stats.ok / stats.total) * 100.0
    rps = stats.total / real_duration
    p50 = percentile(stats.latencies_ms, 50)
    p95 = percentile(stats.latencies_ms, 95)
    p99 = percentile(stats.latencies_ms, 99)

    print("\n=== Load Test Summary ===")
    print(f"Base URL: {base_url}")
    print(f"Duration: {real_duration:.1f}s")
    print(f"Virtual users: {vus}")
    print(f"Total requests: {stats.total}")
    print(f"Success rate: {success_rate:.2f}%")
    print(f"RPS: {rps:.2f}")
    print(f"Latency p50: {p50:.1f} ms")
    print(f"Latency p95: {p95:.1f} ms")
    print(f"Latency p99: {p99:.1f} ms")
    print(f"Status counts: {dict(stats.status_counts)}")

    print("\nPer-endpoint:")
    for endpoint in sorted(stats.endpoint_totals.keys()):
        lats = stats.endpoint_latencies.get(endpoint, [])
        print(
            f"  {endpoint} -> requests={stats.endpoint_totals[endpoint]}, "
            f"p95={percentile(lats, 95):.1f} ms"
        )

    # Basic pass/fail gate for quick checks.
    if success_rate < 99.0 or p95 > 1500:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LFAS load test (100 active users baseline).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--vus", type=int, default=100)
    parser.add_argument("--duration-sec", type=int, default=60)
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument("--think-ms", type=int, default=50)
    parser.add_argument("--public-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    return asyncio.run(
        run_test(
            base_url=args.base_url,
            vus=args.vus,
            duration_sec=args.duration_sec,
            timeout_sec=args.timeout_sec,
            think_ms=args.think_ms,
            public_only=args.public_only,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

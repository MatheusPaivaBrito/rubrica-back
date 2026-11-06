import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import logging
import math
import random
import time

import httpx
from prometheus_client import Counter

from observability_api.infrastructure.settings import settings
from observability_api.modules.platform_publish.contract import ContractError, DEADLINE, INTERVAL, configured, encode, headers, matches_scope, snapshot
from observability_api.modules.platform_publish.transport import Result, exchange

logger = logging.getLogger(__name__)
ATTEMPTS = Counter("rubrica_platform_publish_attempts_total", "Tentativas agregadas de publicacao remota.")
SUCCEEDED = Counter("rubrica_platform_publish_succeeded_total", "Publicacoes aceitas pela plataforma.")
DROPPED = Counter("rubrica_platform_publish_dropped_total", "Pendencias descartadas, substituidas ou expiradas.")
FILTERED = Counter("rubrica_platform_publish_filtered_families_total", "Familias incompativeis filtradas integralmente.")
FAILED = Counter("rubrica_platform_publish_failed_total", "Falhas agregadas de transporte ou contrato.")


@dataclass
class Pending:
    body: bytes
    deadline: float
    next_attempt: float


def elapsed_clock():
    # Linux MONOTONIC pauses during suspend; PC resume must not revive old data.
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()


def retry_after(value, server_date=None):
    if not value:
        return 0
    try:
        number = float(value)
        return max(0, number) if math.isfinite(number) else 0
    except ValueError:
        try:
            reference = parsedate_to_datetime(server_date) if server_date else datetime.now(UTC)
            return max(0, (parsedate_to_datetime(value)-reference).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


class Publisher:
    def __init__(self, config, *, clock=elapsed_clock, jitter=random.uniform):
        self.config, self.clock, self.jitter = config, clock, jitter
        self.pending, self.failures, self.retry_at = {}, {}, {}
        self.inflight = None
        self.paused = set()
        self.blocked_until = 0
        self.scope_valid_until = 0
        self.requests = deque()
        self.changed = asyncio.Event()

    def offer(self, kind, payload):
        if kind not in {"heartbeat", "metrics"}:
            raise ContractError("publication_kind_invalid")
        if kind in self.paused:
            DROPPED.inc()
            return
        previous = self.pending.get(kind)
        if previous is not None and previous is not self.inflight:
            DROPPED.inc()
        now = self.clock()
        self.pending[kind] = Pending(encode(payload), now+DEADLINE, max(now, self.retry_at.get(kind, 0)))
        self.changed.set()

    def discard(self, kind, item):
        if self.pending.get(kind) is item:
            del self.pending[kind]
        DROPPED.inc()

    async def attempt_once(self, client):
        if self.inflight is not None:
            return False
        now = self.clock()
        for kind, item in list(self.pending.items()):
            if item.deadline <= now:
                self.discard(kind, item)
        if self.blocked_until > now:
            return False
        while self.requests and self.requests[0] <= now-60:
            self.requests.popleft()
        if len(self.requests) >= 30:
            self.blocked_until = self.requests[0]+60
            return False
        ready = [(item.next_attempt, kind, item) for kind, item in self.pending.items() if item.next_attempt <= now]
        if not ready:
            return False
        _, kind, item = min(ready)
        self.inflight = item
        self.requests.append(now)
        ATTEMPTS.inc()
        checking_scope = self.scope_valid_until <= now
        try:
            async with asyncio.timeout(min(10, item.deadline-now)):
                result = await exchange(client, "GET" if checking_scope else "POST",
                    f"{self.config.PLATFORM_URL.rstrip('/') + '/ingest/v1'}/{'status' if checking_scope else kind}",
                    headers(self.config), body=None if checking_scope else item.body, limit=65536)
        except TimeoutError:
            result = Result(None, "timeout")
        finally:
            self.inflight = None
        if checking_scope and result.reason == "ok" and result.code == 200:
            if matches_scope(result.payload, self.config):
                self.scope_valid_until = self.clock()+INTERVAL
                self.failures[kind], self.retry_at[kind] = 0, 0
                return True
            result = Result(403, "ingest_scope_denied")
        if result.reason == "ok" and result.code and 200 <= result.code < 300:
            SUCCEEDED.inc()
            self.failures[kind], self.retry_at[kind] = 0, 0
            if self.pending.get(kind) is item:
                del self.pending[kind]
            return True
        FAILED.inc()
        terminal = result.reason in {"access_denied", "invalid_response", "response_limit"} or (
            result.code is not None and 400 <= result.code < 500 and result.code not in {408, 429})
        if terminal:
            affected = {"heartbeat", "metrics"} if result.reason == "access_denied" or result.code in {401, 403} else {kind}
            self.paused.update(affected)
            for lane in affected:
                if lane in self.pending:
                    self.discard(lane, self.pending[lane])
            logger.warning("Platform publisher paused; code=%s count=%d", result.code, len(affected))
            return True
        failures = min(6, self.failures.get(kind, 0)+1)
        self.failures[kind] = failures
        delay = self.jitter(1, min(30, 2**(failures-1)))
        if result.code == 429:
            delay = max(delay, retry_after(result.retry_after, result.server_date))
            self.blocked_until = self.clock()+delay
        self.retry_at[kind] = self.clock()+delay
        current = self.pending.get(kind)
        if current is not None:
            current.next_attempt = self.retry_at[kind]
        if current is not item:
            DROPPED.inc()
        return True

    async def capture_once(self, local):
        healthy = False
        try:
            async with asyncio.timeout(5):
                health = await local.get("http://127.0.0.1:8000/health")
                ready = await local.get("http://127.0.0.1:8000/ready")
                healthy = (health.status_code == ready.status_code == 200 and health.json().get("status") == "ok"
                    and ready.json().get("status") == "ready" and ready.json().get("dependencies", {}).get("database", {}).get("status") == "ok")
        except (httpx.HTTPError, TimeoutError, ValueError, AttributeError):
            pass
        self.offer("heartbeat", {"service": self.config.PLATFORM_SERVICE, "healthy": healthy})
        if "metrics" in self.paused:
            return
        try:
            async with asyncio.timeout(5):
                async with local.stream("GET", "http://127.0.0.1:8000/metrics") as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2*1024*1024:
                            raise ContractError("local_metrics_limit")
                payload, filtered = snapshot(body.decode(), self.config)
                FILTERED.inc(filtered)
                self.offer("metrics", payload)
        except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError):
            FAILED.inc()
            DROPPED.inc()
            logger.warning("Platform metrics snapshot unavailable", extra={"count": 1})

    async def produce(self, local):
        while True:
            started = self.clock()
            await self.capture_once(local)
            await asyncio.sleep(max(.1, INTERVAL-(self.clock()-started)))

    async def run(self):
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, verify=True, trust_env=False, limits=limits) as remote:
            async with httpx.AsyncClient(timeout=2, follow_redirects=False, trust_env=False) as local:
                producer = asyncio.create_task(self.produce(local))
                try:
                    while True:
                        if producer.done():
                            producer.result()
                        self.changed.clear()
                        if await self.attempt_once(remote):
                            continue
                        now = self.clock()
                        future = [max(self.blocked_until, item.next_attempt) for item in self.pending.values()]
                        future += [item.deadline for item in self.pending.values()]
                        wait = max(.05, min(5, min(future)-now)) if future else 5
                        try:
                            await asyncio.wait_for(self.changed.wait(), timeout=wait)
                        except TimeoutError:
                            pass
                finally:
                    producer.cancel()
                    with suppress(asyncio.CancelledError):
                        await producer
                    DROPPED.inc(len(self.pending))
                    self.pending.clear()


async def supervise(publisher):
    try:
        await publisher.run()
    except asyncio.CancelledError:
        raise
    except Exception:
        FAILED.inc()
        logger.warning("Platform publisher stopped safely", extra={"count": 1})


@asynccontextmanager
async def lifespan(app):
    task = None
    if settings.PLATFORM_PUBLISH_ENABLED:
        if configured(settings):
            app.state.platform_publisher = Publisher(settings)
            task = asyncio.create_task(supervise(app.state.platform_publisher))
        else:
            logger.warning("Platform publisher disabled; configuration incomplete", extra={"count": 1})
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

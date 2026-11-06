import asyncio
import json

from fastapi import FastAPI
import httpx
import pytest

from observability_api.infrastructure.settings import ObservabilitySettings, PLATFORM_SECRET_FIELDS
from observability_api.modules.platform_publish import publisher
from observability_api.modules.platform_publish.contract import ContractError, configured, snapshot
from observability_api.modules.platform_publish.ensure import ensure, fixed_query
from observability_api.modules.platform_publish.transport import exchange


@pytest.fixture
def config(tmp_path):
    values = {"ENVIRONMENT": "staging", "PLATFORM_URL": "https://grafana.7f3a9c2e8b.stream"}
    for index, name in enumerate(PLATFORM_SECRET_FIELDS):
        path = tmp_path/name.lower()
        path.write_text(f"private-{index}-"+"x"*40)
        path.chmod(0o600)
        values[name+"_FILE"] = str(path)
    return ObservabilitySettings(_env_file=None, **values)


class Clock:
    value = 0
    def __call__(self):
        return self.value


def run(coro):
    return asyncio.run(coro)


def ready_publisher(config, **kwargs):
    # Queue/retry tests begin after admission; separate tests cover scope reads.
    result = publisher.Publisher(config, **kwargs)
    result.scope_valid_until = float("inf")
    return result


def test_optional_invalid_platform_secret_never_prevents_settings_or_health(config, tmp_path):
    path = tmp_path/"public"
    path.write_text("must-not-be-readable-by-others")
    path.chmod(0o644)
    broken = ObservabilitySettings(_env_file=None, ENVIRONMENT="staging", PLATFORM_TOKEN_FILE=str(path))
    assert broken.PLATFORM_TOKEN is None and broken.PLATFORM_TOKEN is None
    assert not configured(broken)
    assert config.PLATFORM_TOKEN not in repr(config)
    assert config.PLATFORM_TOKEN not in config.model_dump_json()
    assert not ObservabilitySettings(_env_file=None).PLATFORM_PUBLISH_ENABLED


@pytest.mark.parametrize("change", [{"ENVIRONMENT": "development"}, {"PLATFORM_ENVIRONMENT": "production"},
    {"PLATFORM_PROJECT": "other"}, {"PLATFORM_SERVICE": "core_api"}, {"PLATFORM_URL": "http://grafana.7f3a9c2e8b.stream"},
    {"PLATFORM_URL": "https://grafana.7f3a9c2e8b.stream?token=x"},
    {"PLATFORM_URL": "https://attacker.example/ingest/v1"}, {"PLATFORM_TOKEN_FILE": None}])
def test_publication_refuses_wrong_scope_insecure_origin_and_environment(config, change):
    assert not configured(config.model_copy(update=change))


def test_snapshot_preserves_counter_and_histogram_and_drops_entire_incompatible_family(config):
    text = '''# TYPE rubrica_http_requests counter
rubrica_http_requests_total{service="observability_api",method="GET",route="/health",status_class="2xx"} 7
rubrica_http_requests_created{service="observability_api",method="GET",route="/health",status_class="2xx"} 1
# TYPE rubrica_duration_seconds histogram
rubrica_duration_seconds_bucket{le="0.1"} 1
rubrica_duration_seconds_bucket{le="+Inf"} 3
rubrica_duration_seconds_sum 5
rubrica_duration_seconds_count 3
# TYPE rubrica_bad gauge
rubrica_bad{route="/health"} 1
rubrica_bad{route="/private/customer"} 2
python_gc_objects_collected_total 50
'''
    payload, filtered = snapshot(text, config)
    assert filtered == 1
    assert [s["name"] for s in payload["samples"]] == ["rubrica_http_requests_total", "rubrica_duration_seconds_bucket",
        "rubrica_duration_seconds_bucket", "rubrica_duration_seconds_sum", "rubrica_duration_seconds_count"]
    assert payload["samples"][0]["value"] == 7
    assert all(set(s) == {"name", "value", "labels"} for s in payload["samples"])


@pytest.mark.parametrize("text", ['rubrica_metric{project="other"} 1', 'rubrica_metric NaN',
    'rubrica_metric +Inf', 'rubrica_metric{user_id="private"} 2', 'rubrica_metric 1\nrubrica_metric 2',
    '\n'.join(f'rubrica_metric_{n} 1' for n in range(1001))])
def test_invalid_or_oversized_snapshots_are_never_sent_partially(config, text):
    with pytest.raises(ContractError):
        snapshot(text, config)


def test_normalized_size_limit_includes_server_imposed_labels(config):
    text = '\n'.join('rubrica_'+str(n)+'x'*110+' 1' for n in range(600))
    with pytest.raises(ContractError):
        snapshot(text, config)


def test_exactly_one_pending_snapshot_replaces_previous_values(config):
    clock = Clock()
    worker = ready_publisher(config, clock=clock)
    for value in range(100):
        worker.offer("metrics", {"samples": [value]})
    assert len(worker.pending) == 1
    assert json.loads(worker.pending["metrics"].body)["samples"] == [99]
    worker.offer("heartbeat", {"healthy": True})
    assert len(worker.pending) == 2


def test_authentication_failure_pauses_both_lanes_until_recreation(config, caplog):
    async def exercise():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(401)
        worker = ready_publisher(config, clock=Clock())
        worker.offer("heartbeat", {"healthy": True})
        worker.offer("metrics", {"samples": [1]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await worker.attempt_once(client)
            for _ in range(3):
                worker.offer("metrics", {"samples": [2]})
                assert not await worker.attempt_once(client)
        assert len(calls) == 1 and worker.paused == {"heartbeat", "metrics"}
    run(exercise())
    assert config.PLATFORM_TOKEN not in caplog.text


@pytest.mark.parametrize("code", [413, 415, 422])
def test_permanent_payload_error_does_not_loop_and_heartbeat_stays_independent(config, code):
    async def exercise():
        worker = ready_publisher(config, clock=Clock())
        worker.offer("metrics", {"samples": [1]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(code))) as client:
            await worker.attempt_once(client)
        assert worker.paused == {"metrics"}
        worker.offer("heartbeat", {"healthy": False})
        assert "heartbeat" in worker.pending
    run(exercise())


def test_429_respects_retry_after_for_new_snapshots_and_both_lanes(config):
    async def exercise():
        clock = Clock()
        worker = ready_publisher(config, clock=clock, jitter=lambda low, high: high)
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "60"}) if len(calls) == 1 else httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            worker.offer("metrics", {"value": 1})
            await worker.attempt_once(client)
            clock.value = 30
            worker.offer("metrics", {"value": 2})
            worker.offer("heartbeat", {"healthy": True})
            assert not await worker.attempt_once(client)
            clock.value = 60
            assert await worker.attempt_once(client)
            assert len(calls) == 2
    run(exercise())


def test_retry_deadline_drops_pending_and_recovery_sends_only_the_latest_snapshot(config):
    async def exercise():
        clock = Clock()
        worker = ready_publisher(config, clock=clock, jitter=lambda low, high: high)
        worker.offer("metrics", {"value": 1})
        def timeout(_):
            raise httpx.ReadTimeout("secret-must-not-appear")
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            await worker.attempt_once(client)
            assert worker.pending["metrics"].next_attempt == 1
            clock.value = 90
            assert not await worker.attempt_once(client) and not worker.pending
        worker.offer("metrics", {"value": 3})
        bodies = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (bodies.append(json.loads(request.content)) or httpx.Response(200, json={})))) as client:
            await worker.attempt_once(client)
        assert bodies == [{"value": 3}]
    run(exercise())


def test_single_inflight_and_pending_new_snapshot_are_not_lost_on_old_ack(config):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        bodies = []
        async def handler(request):
            bodies.append(json.loads(request.content))
            entered.set()
            await release.wait()
            return httpx.Response(200, json={})
        worker = ready_publisher(config, clock=Clock())
        worker.offer("metrics", {"value": 1})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            old = asyncio.create_task(worker.attempt_once(client))
            await entered.wait()
            worker.offer("metrics", {"value": 2})
            worker.offer("metrics", {"value": 3})
            assert not await worker.attempt_once(client)
            release.set()
            await old
            assert "metrics" in worker.pending
            await worker.attempt_once(client)
        assert bodies == [{"value": 1}, {"value": 3}]
    run(exercise())


def test_local_readiness_and_metrics_capture_never_query_the_platform(config):
    async def exercise():
        seen = []
        def handler(request):
            seen.append(request.url.path)
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/ready":
                return httpx.Response(200, json={"status": "degraded", "dependencies": {"database": {"status": "unavailable"}}})
            return httpx.Response(200, text='rubrica_business_metrics_collection_success{service="observability_api"} 0\n')
        worker = ready_publisher(config)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await worker.capture_once(client)
        assert json.loads(worker.pending["heartbeat"].body) == {"service": "observability_api", "healthy": False}
        assert seen == ["/health", "/ready", "/metrics"]
    run(exercise())


def test_per_process_request_budget_cannot_exceed_thirty_requests_a_minute(config):
    async def exercise():
        worker = ready_publisher(config, clock=Clock())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))) as client:
            for _ in range(30):
                worker.offer("heartbeat", {"healthy": True})
                assert await worker.attempt_once(client)
            worker.offer("heartbeat", {"healthy": True})
            assert not await worker.attempt_once(client)
    run(exercise())


def status(now):
    return {"project": "rubrica", "environment": "staging", "services": ["observability_api"], "authorized": True,
        "contract_version": 2, "metric_prefix": "rubrica_", "checks": dict.fromkeys(["configured", "reachable", "authenticated", "authorized", "operational"], True), "receiving": True, "query_reachable": True, "available": True, "operational": True, "last_seen": now-5, "server_time": now,
        "metrics": {"observability_api": {"last_received": now-5, "last_collected": now-5, "samples": 1, "fresh": True}}}


def vector(value, timestamp, scope="staging"):
    return {"status": "success", "project": "rubrica", "environment": "staging", "data": {"resultType": "vector", "result": [
        {"metric": {"__name__": "rubrica_business_metrics_collection_success", "project": "rubrica", "environment": scope,
        "service": "observability_api"}, "value": [timestamp, str(value)]}]}}


def test_ensure_uses_only_read_operations_and_proves_fresh_metric_with_server_clock(config):
    async def exercise():
        seen = []
        now = 1900000000  # Deliberately unrelated to the PC clock.
        def handler(request):
            seen.append((request.method, request.url.path))
            if request.method == "GET":
                assert request.headers["authorization"] == "Bearer "+config.PLATFORM_TOKEN
                return httpx.Response(200, json=status(now))
            assert json.loads(request.content) == fixed_query()
            assert request.headers["authorization"] == "Bearer "+config.PLATFORM_TOKEN
            return httpx.Response(200, json=vector(1, now-15))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await ensure(config, client=client)
        assert all(result[k] for k in ["configured", "reachable", "authenticated", "authorized", "operational"])
        assert seen == [("GET", "/ingest/v1/status"), ("POST", "/ingest/v1/query")]
        assert config.PLATFORM_TOKEN not in json.dumps(result)
    run(exercise())


@pytest.mark.parametrize("scenario", ["empty", "stale", "wrong_scope", "zero", "datasource_denied", "wrong_ingest", "revoked"])
def test_ensure_never_accepts_empty_stale_foreign_or_denied_data(config, scenario):
    async def exercise():
        now = 1900000000
        def handler(request):
            if request.method == "GET":
                data = status(now)
                if scenario == "wrong_ingest":
                    data["environment"] = "production"
                if scenario == "revoked":
                    return httpx.Response(401)
                return httpx.Response(200, json=data)
            if scenario == "datasource_denied":
                return httpx.Response(403, json={})
            result = vector(0 if scenario == "zero" else 1, now-200 if scenario == "stale" else now-15,
                            "production" if scenario == "wrong_scope" else "staging")
            if scenario == "empty":
                result["data"]["result"] = []
            return httpx.Response(200, json=result)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await ensure(config, client=client)
        assert not result["operational"]
    run(exercise())


@pytest.mark.parametrize("code,headers,reason", [(302, {"location": "https://login.cloudflareaccess.com"}, "access_denied"),
    (403, {"content-type": "text/html"}, "access_denied"), (401, {}, "credential_denied"), (403, {}, "scope_denied")])
def test_machine_auth_never_follows_browser_login_or_confuses_query_denial(config, code, headers, reason):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(code, headers=headers)), follow_redirects=False) as client:
            result = await exchange(client, "POST", config.PLATFORM_URL+"/api/ds/query", {}, query=True)
        assert result.reason == reason
    run(exercise())


def test_publisher_failure_does_not_escape_application_lifespan(monkeypatch, caplog):
    async def exercise():
        async def broken(_):
            raise RuntimeError("secret-exception-body")
        monkeypatch.setattr(publisher.settings, "PLATFORM_PUBLISH_ENABLED", True)
        monkeypatch.setattr(publisher, "configured", lambda _: True)
        monkeypatch.setattr(publisher.Publisher, "run", broken)
        async with publisher.lifespan(FastAPI()):
            await asyncio.sleep(.01)
    run(exercise())
    assert "secret-exception-body" not in caplog.text


def test_retry_after_http_date_uses_server_date():
    assert publisher.retry_after("Wed, 01 Jan 2031 00:01:00 GMT", "Wed, 01 Jan 2031 00:00:00 GMT") == 60
    assert publisher.retry_after("invalid") == publisher.retry_after("NaN") == 0


def test_pause_from_missing_secrets_never_blocks_health_or_readiness(monkeypatch):
    from observability_api.bootstrap.app import create_app
    from observability_api.bootstrap import health
    async def exercise():
        monkeypatch.setattr(publisher.settings, "PLATFORM_PUBLISH_ENABLED", True)
        monkeypatch.setattr(publisher.settings, "PLATFORM_TOKEN_FILE", None)
        monkeypatch.setattr(health, "_database_status", lambda: {"status": "ok"})
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
                assert (await client.get("/health")).json()["status"] == "ok"
                assert (await client.get("/ready")).json()["status"] == "ready"
    run(exercise())




def test_transport_response_body_is_bounded(config):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x"*100))) as client:
            result = await exchange(client, "GET", config.PLATFORM_URL+"/status", {}, limit=50)
            assert result.reason == "response_limit" and result.payload is None
    run(exercise())


def test_post_payload_is_json_with_content_length_and_both_auth_layers(config):
    async def exercise():
        def handler(request):
            assert request.headers["content-type"] == "application/json"
            assert "transfer-encoding" not in request.headers
            assert int(request.headers["content-length"]) == len(request.content)
            assert request.headers["Authorization"] == "Bearer "+config.PLATFORM_TOKEN
            body = json.loads(request.content)
            assert set(body) == {"service", "samples"}
            assert set(body["samples"][0]) == {"name", "labels", "value"}
            return httpx.Response(200, json={})
        worker = ready_publisher(config)
        payload, _ = snapshot('rubrica_business_metrics_collection_success 1\n', config)
        worker.offer("metrics", payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await worker.attempt_once(client)
    run(exercise())


def test_server_stale_status_overrides_a_recent_looking_grafana_response(config):
    async def exercise():
        now = 1900000000
        def handler(request):
            if request.method == "GET":
                value = status(now)
                value["last_seen"] = now-120
                return httpx.Response(200, json=value)
            return httpx.Response(200, json=vector(1, now))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert not (await ensure(config, client=client))["operational"]
    run(exercise())


def test_malformed_status_cannot_echo_server_strings_into_evidence(config):
    async def exercise():
        body = status(1900000000)
        body["metrics"]["observability_api"]["samples"] = "secret-from-untrusted-response"
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
            report = await ensure(config, client=client)
        assert not report["operational"] and "secret-from-untrusted" not in json.dumps(report)
    run(exercise())


def test_total_timeout_also_bounds_a_slow_stream(monkeypatch, config):
    from observability_api.modules.platform_publish import transport
    timeout = asyncio.timeout
    budgets = []
    def bounded(budget):
        budgets.append(budget)
        return timeout(.01)
    monkeypatch.setattr(transport.asyncio, "timeout", bounded)
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            await asyncio.sleep(1)
            yield b"}"
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Slow()))) as client:
            assert (await exchange(client, "GET", config.PLATFORM_URL+"/status", {})).reason == "timeout"
    run(exercise())
    assert budgets == [10]


def test_unknown_queue_lane_is_rejected_so_the_queue_stays_bounded(config):
    with pytest.raises(ContractError):
        ready_publisher(config).offer("arbitrary-customer-id", {})


def test_default_elapsed_clock_counts_suspend_time_on_linux(monkeypatch):
    monkeypatch.setattr(publisher.time, "CLOCK_BOOTTIME", 7, raising=False)
    monkeypatch.setattr(publisher.time, "clock_gettime", lambda identity: 500 if identity == 7 else 0)
    assert publisher.elapsed_clock() == 500


@pytest.mark.parametrize("scope", ["production", "foreign_project", "revoked"])
def test_wrong_credential_scope_is_refused_before_any_heartbeat_or_snapshot(config, scope):
    async def exercise():
        calls = []
        def handler(request):
            calls.append(request.method)
            assert request.method == "GET" and request.url.path == "/ingest/v1/status"
            response = status(1900000000)
            if scope == "production":
                response["environment"] = "production"
            elif scope == "foreign_project":
                response["project"] = "another"
            else:
                return httpx.Response(401)
            return httpx.Response(200, json=response)
        worker = publisher.Publisher(config, clock=Clock())
        worker.offer("heartbeat", {"service": "observability_api", "healthy": True})
        worker.offer("metrics", {"samples": [1]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await worker.attempt_once(client)
            assert not await worker.attempt_once(client)
        assert calls == ["GET"] and worker.paused == {"heartbeat", "metrics"}
    run(exercise())


def test_registered_pending_scope_can_publish_and_scope_is_rechecked_each_cycle(config):
    async def exercise():
        clock, calls = Clock(), []
        def handler(request):
            calls.append(request.method)
            response = status(1900000000)
            response["available"] = response["operational"] = False
            response["last_seen"] = 0
            return httpx.Response(200, json=response if request.method == "GET" else {})
        worker = publisher.Publisher(config, clock=clock)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            worker.offer("heartbeat", {"healthy": True})
            await worker.attempt_once(client)
            await worker.attempt_once(client)
            clock.value = 30
            worker.offer("heartbeat", {"healthy": True})
            await worker.attempt_once(client)
            await worker.attempt_once(client)
        assert calls == ["GET", "POST", "GET", "POST"]
    run(exercise())


@pytest.mark.parametrize("case", ["ok", "scope_accepted", "invalid_key_accepted", "missing"])
def test_live_validation_is_read_only_and_does_not_accept_broken_security(config, case):
    from observability_api.modules.platform_publish.validation import validate
    async def exercise():
        paths = []
        def handler(request):
            paths.append(request.url.path)
            assert request.url.path in {"/ingest/v1/status", "/ingest/v1/query"}
            if request.url.path.endswith("/status"):
                if request.headers.get("authorization") != "Bearer "+config.PLATFORM_TOKEN:
                    return httpx.Response(200 if case == "invalid_key_accepted" else 401, json={})
                return httpx.Response(200, json=status(1900000000))
            body = json.loads(request.content)
            if body != fixed_query(config):
                return httpx.Response(200 if case == "scope_accepted" else 422, json={})
            return httpx.Response(200, json=vector(1, 1899999990))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await validate(config.model_copy(update={"PLATFORM_TOKEN_FILE": None}) if case == "missing" else config, client=client)
        assert result["operational"] is (case == "ok")
        if case == "missing":
            assert not paths
    run(exercise())


@pytest.mark.parametrize("field", ["contract_version", "query_reachable", "receiving", "last_collected"])
def test_ensure_requires_v2_and_collection_receipt_not_only_http_200(config, field):
    async def exercise():
        payload = status(1900000000)
        if field == "last_collected":
            payload["metrics"]["observability_api"][field] = 1899999000
        else:
            payload[field] = 1 if field == "contract_version" else False
        def handler(request):
            return httpx.Response(200, json=payload if request.method == "GET" else vector(1, 1900000000))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert not (await ensure(config, client=client))["operational"]
    run(exercise())

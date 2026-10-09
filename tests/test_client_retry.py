"""Retry rules: 429 honors Retry-After; create POSTs are never replayed; GETs are retried."""

from datetime import UTC, datetime

import httpx2
import pytest

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError


class Script:
    """A MockTransport handler that plays a list of responses/exceptions in order."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        step = self.steps[min(len(self.requests), len(self.steps)) - 1]
        if isinstance(step, type) and issubclass(step, Exception):
            raise step("boom", request=request)
        return step


def ok():
    return httpx2.Response(200, json={"ok": True})


def status(code, **headers):
    return httpx2.Response(
        code, json={"error": {"message": "nope", "type": "t", "code": code}}, headers=headers
    )


@pytest.fixture
def slept():
    return []


@pytest.fixture
def build(make_settings, slept):
    def factory(script, now=None, **settings):
        async def fake_sleep(seconds):
            slept.append(seconds)

        return PerplexityClient(
            make_settings(**settings),
            transport=httpx2.MockTransport(script),
            sleep=fake_sleep,
            jitter=lambda: 0.5,
            clock=(lambda: now) if now else (lambda: datetime.now(UTC)),
        )

    return factory


# --- 429 ---------------------------------------------------------------------------------


async def test_retry_after_seconds_is_honored(build, slept):
    script = Script(status(429, **{"Retry-After": "2"}), ok())
    assert await build(script).request_json("GET", "/v1/models") == {"ok": True}
    assert slept == [2]
    assert len(script.requests) == 2


async def test_retry_after_http_date_is_honored(build, slept):
    now = datetime(2026, 10, 21, 7, 28, 0, tzinfo=UTC)
    script = Script(status(429, **{"Retry-After": "Wed, 21 Oct 2026 07:28:05 GMT"}), ok())
    await build(script, now=now).request_json("GET", "/v1/models")
    assert slept == [5]


async def test_retry_after_date_in_the_past_waits_zero(build, slept):
    now = datetime(2026, 10, 21, 7, 28, 0, tzinfo=UTC)
    script = Script(status(429, **{"Retry-After": "Wed, 21 Oct 2026 07:00:00 GMT"}), ok())
    await build(script, now=now).request_json("GET", "/v1/models")
    assert slept == [0]


async def test_retry_after_over_cap_raises_without_sleeping(build, slept):
    script = Script(status(429, **{"Retry-After": "600"}), ok())
    with pytest.raises(PerplexityError) as info:
        await build(script).request_json("GET", "/v1/models")
    assert info.value.category == "rate_limited"
    assert info.value.status == 429
    assert slept == []
    assert len(script.requests) == 1


async def test_cap_follows_the_setting(build, slept):
    script = Script(status(429, **{"Retry-After": "60"}), ok())
    await build(script, max_retry_wait=100).request_json("GET", "/v1/models")
    assert slept == [60]


async def test_attempts_exhausted_raises_rate_limited(build, slept):
    script = Script(status(429))
    with pytest.raises(PerplexityError) as info:
        await build(script).request_json("GET", "/v1/models")
    assert info.value.category == "rate_limited"
    assert len(script.requests) == 3
    assert len(slept) == 2  # no sleep after the last attempt


async def test_backoff_without_retry_after_grows_with_jitter(build, slept):
    script = Script(status(429))
    with pytest.raises(PerplexityError):
        await build(script, max_attempts=4).request_json("GET", "/v1/models")
    assert len(slept) == 3
    assert slept[0] < slept[1] < slept[2]
    assert all(0 < s <= 30 for s in slept)


async def test_backoff_never_exceeds_the_cap(build, slept):
    script = Script(status(429))
    with pytest.raises(PerplexityError):
        await build(script, max_attempts=8, max_retry_wait=3).request_json("GET", "/x")
    assert max(slept) <= 3


async def test_unparseable_retry_after_falls_back_to_backoff(build, slept):
    script = Script(status(429, **{"Retry-After": "soon"}), ok())
    await build(script).request_json("GET", "/v1/models")
    assert len(slept) == 1
    assert slept[0] > 0


async def test_max_attempts_one_never_retries(build, slept):
    script = Script(status(429), ok())
    with pytest.raises(PerplexityError):
        await build(script, max_attempts=1).request_json("GET", "/v1/models")
    assert len(script.requests) == 1


# --- create POSTs ------------------------------------------------------------------------


async def test_post_5xx_is_not_replayed(build, slept):
    script = Script(status(503), ok())
    with pytest.raises(PerplexityError) as info:
        await build(script).request_json("POST", "/v1/agent", json={})
    assert info.value.category == "upstream_failure"
    assert len(script.requests) == 1
    assert slept == []


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413, 500, 502])
async def test_post_other_statuses_are_not_replayed(build, code):
    script = Script(status(code), ok())
    with pytest.raises(PerplexityError):
        await build(script).request_json("POST", "/v1/agent", json={})
    assert len(script.requests) == 1


async def test_post_read_timeout_is_not_replayed(build):
    script = Script(httpx2.ReadTimeout, ok())
    with pytest.raises(PerplexityError) as info:
        await build(script).request_json("POST", "/v1/agent", json={})
    assert info.value.category == "network_timeout"
    assert len(script.requests) == 1


async def test_post_write_timeout_and_read_error_are_not_replayed(build):
    for exc in (httpx2.WriteTimeout, httpx2.ReadError, httpx2.RemoteProtocolError):
        script = Script(exc, ok())
        with pytest.raises(PerplexityError):
            await build(script).request_json("POST", "/v1/agent", json={})
        assert len(script.requests) == 1, exc


async def test_post_429_then_200_returns_after_two_requests(build, slept):
    script = Script(status(429, **{"Retry-After": "2"}), ok())
    assert await build(script).request_json("POST", "/v1/agent", json={}) == {"ok": True}
    assert len(script.requests) == 2
    assert slept == [2]


async def test_post_connect_failure_then_success(build):
    script = Script(httpx2.ConnectError, ok())
    assert await build(script).request_json("POST", "/v1/agent", json={}) == {"ok": True}
    assert len(script.requests) == 2


async def test_post_connect_timeout_then_success(build):
    script = Script(httpx2.ConnectTimeout, ok())
    assert await build(script).request_json("POST", "/v1/agent", json={}) == {"ok": True}
    assert len(script.requests) == 2


async def test_post_connect_failure_exhausts_attempts(build):
    script = Script(httpx2.ConnectError)
    with pytest.raises(PerplexityError) as info:
        await build(script).request_json("POST", "/v1/agent", json={})
    assert info.value.category == "upstream_failure"
    assert len(script.requests) == 3


# --- GETs --------------------------------------------------------------------------------


async def test_get_5xx_then_200(build, slept):
    script = Script(status(503), ok())
    assert await build(script).request_json("GET", "/v1/models") == {"ok": True}
    assert len(script.requests) == 2
    assert len(slept) == 1


async def test_get_5xx_exhausted_raises_upstream_failure(build):
    script = Script(status(502))
    with pytest.raises(PerplexityError) as info:
        await build(script).request_json("GET", "/v1/models")
    assert info.value.category == "upstream_failure"
    assert len(script.requests) == 3


async def test_get_read_timeout_then_200(build):
    script = Script(httpx2.ReadTimeout, ok())
    assert await build(script).request_json("GET", "/v1/models") == {"ok": True}
    assert len(script.requests) == 2


async def test_get_connect_failure_then_200(build):
    script = Script(httpx2.ConnectError, ok())
    assert await build(script).request_json("GET", "/v1/models") == {"ok": True}


async def test_get_timeout_exhausted_raises_network_timeout(build):
    script = Script(httpx2.ReadTimeout)
    with pytest.raises(PerplexityError) as info:
        await build(script).request_json("GET", "/v1/models")
    assert info.value.category == "network_timeout"
    assert len(script.requests) == 3


@pytest.mark.parametrize("code", [400, 401, 403, 404])
async def test_get_client_errors_are_not_retried(build, code):
    script = Script(status(code), ok())
    with pytest.raises(PerplexityError):
        await build(script).request_json("GET", "/v1/models")
    assert len(script.requests) == 1

"""Upstream text is redacted; each upstream call leaves one diagnostic record, no bodies."""

import logging

import httpx2
import pytest

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError

KEY = "test-dummy-api-key"
TOKEN = "pplx-" + "Qq7_" * 10


def build(settings, handler):
    async def no_sleep(_):
        return None

    return PerplexityClient(settings, transport=httpx2.MockTransport(handler), sleep=no_sleep)


def record_text(record: logging.LogRecord) -> str:
    """Every string a handler could render from the record, message and extras alike."""
    parts = [record.getMessage()]
    parts += [str(v) for k, v in record.__dict__.items() if k not in ("args", "msg")]
    return "\n".join(parts)


@pytest.fixture
def client_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="mcp_perplexity_pro")
    return caplog


async def test_401_echoing_the_key_yields_clean_error_and_log(make_settings, client_logs):
    body = {"error": {"message": f"Invalid key {KEY} / {TOKEN}", "type": "invalid_api_key"}}
    client = build(make_settings(), lambda r: httpx2.Response(401, json=body))
    with pytest.raises(PerplexityError) as info:
        await client.request_json("GET", "/v1/models")
    err = info.value
    assert err.category == "authentication"
    for secret in (KEY, TOKEN):
        assert secret not in str(err)
        assert secret not in (err.api_type or "")
        assert secret not in repr(err.args)
        assert secret not in client_logs.text
        assert all(secret not in record_text(r) for r in client_logs.records)
    assert "[redacted]" in str(err)


async def test_echoed_key_in_api_type_is_redacted(make_settings):
    body = {"error": {"message": "m", "type": f"bad_{KEY}"}}
    client = build(make_settings(), lambda r: httpx2.Response(401, json=body))
    with pytest.raises(PerplexityError) as info:
        await client.request_json("GET", "/v1/models")
    assert KEY not in str(info.value)
    assert KEY not in (info.value.api_type or "")


async def test_one_record_per_call_with_the_listed_fields(make_settings, client_logs):
    def handler(request):
        return httpx2.Response(200, json={"ok": 1}, headers={"x-request-id": "req-123"})

    client = build(make_settings(), handler)
    await client.request_json("GET", "/v1/models")
    records = [r for r in client_logs.records if r.name == "mcp_perplexity_pro.client"]
    assert len(records) == 1
    rec = records[0]
    assert rec.http_method == "GET"
    assert rec.http_path == "/v1/models"
    assert rec.http_status == 200
    assert rec.request_id == "req-123"
    assert rec.attempt == 1
    assert rec.elapsed_ms >= 0
    text = rec.getMessage()
    for expected in ("GET", "/v1/models", "200", "req-123"):
        assert expected in text


async def test_record_without_request_id_or_response(make_settings, client_logs):
    def handler(request):
        raise httpx2.ReadTimeout("slow", request=request)

    client = build(make_settings(max_attempts=1), handler)
    with pytest.raises(PerplexityError):
        await client.request_json("GET", "/v1/models")
    rec = next(r for r in client_logs.records if r.name == "mcp_perplexity_pro.client")
    assert rec.http_status is None
    assert rec.request_id is None


async def test_each_retry_attempt_is_logged_with_its_number(make_settings, client_logs):
    responses = iter([httpx2.Response(503, json={}), httpx2.Response(200, json={})])
    client = build(make_settings(), lambda r: next(responses))
    await client.request_json("GET", "/v1/models")
    records = [r for r in client_logs.records if r.name == "mcp_perplexity_pro.client"]
    assert [r.attempt for r in records] == [1, 2]
    assert [r.http_status for r in records] == [503, 200]


async def test_log_has_no_request_body_credentials_or_response_body(make_settings, client_logs):
    prompt = "TOP-SECRET-PROMPT-TEXT"
    answer = "SECRET-ANSWER-TEXT"

    def handler(request):
        return httpx2.Response(200, json={"output": answer})

    client = build(make_settings(), handler)
    await client.request_json("POST", "/v1/agent", json={"input": prompt})
    assert client_logs.records
    for rec in client_logs.records:
        text = record_text(rec)
        assert prompt not in text
        assert answer not in text
        assert KEY not in text
        assert "Bearer" not in text
        assert "TOP-SECRET" not in text

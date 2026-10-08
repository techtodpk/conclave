import asyncio

import httpx
import pytest

from conclave.client import REASONING_ALLOWANCE, ModelError, OpenRouterClient
from conclave.config import Member
from conclave.http import new_client
from conftest import KEY, answer, failure

SONNET = Member("anthropic/claude-sonnet-5.5")
MESSAGES = [{"role": "user", "content": "hello"}]


def _complete(member=SONNET, max_tokens=500):
    async def go():
        async with new_client() as http:
            return await OpenRouterClient(http, KEY).complete(member, MESSAGES, max_tokens)

    return asyncio.run(go())


def test_success_returns_text_tokens_and_cost(openrouter):
    openrouter.reply(SONNET.model, answer("  The answer.  ", cost=0.0123))

    done = _complete()

    assert done.text == "The answer."
    assert (done.prompt_tokens, done.completion_tokens) == (300, 200)
    assert done.cost_usd == pytest.approx(0.0123)
    assert done.seconds >= 0


def test_request_carries_the_model_limit_and_key(openrouter):
    _complete(max_tokens=777)

    body = openrouter.chat_requests[0]
    assert body["model"] == SONNET.model
    assert body["max_tokens"] == 777 + REASONING_ALLOWANCE
    assert body["reasoning"] == {"effort": "low"}
    assert body["messages"] == MESSAGES
    assert body["usage"] == {"include": True}
    assert openrouter.auth_headers == [f"Bearer {KEY}"]


def test_missing_cost_is_none_not_zero(openrouter):
    openrouter.reply(SONNET.model, answer(cost=None))

    assert _complete().cost_usd is None


def test_rate_limit_is_retried_then_succeeds(openrouter):
    openrouter.reply(SONNET.model, failure(429), failure(503), answer("Third time lucky."))

    assert _complete().text == "Third time lucky."
    assert len(openrouter.chat_requests) == 3


def test_gives_up_after_three_attempts(openrouter):
    openrouter.reply(SONNET.model, failure(429, "slow down"))

    with pytest.raises(ModelError) as raised:
        _complete()

    assert raised.value.status == 429
    assert "Rate limited" in str(raised.value)
    assert "slow down" in str(raised.value)
    assert len(openrouter.chat_requests) == 3


@pytest.mark.parametrize(
    ("status", "phrase"),
    [(401, "rejected the API key"), (402, "lack of credit"), (404, "does not know this model")],
)
def test_clear_message_and_no_retry_for_caller_errors(openrouter, status, phrase):
    openrouter.reply(SONNET.model, failure(status))

    with pytest.raises(ModelError, match=phrase):
        _complete()

    assert len(openrouter.chat_requests) == 1


def test_error_messages_never_contain_the_key(openrouter):
    openrouter.reply(SONNET.model, failure(401, "bad key"))

    with pytest.raises(ModelError) as raised:
        _complete()

    assert KEY not in str(raised.value)


def test_provider_error_inside_a_200_reply(openrouter):
    body = {"error": {"code": 502, "message": "provider fell over"}}
    openrouter.reply(SONNET.model, httpx.Response(200, json=body))

    with pytest.raises(ModelError, match="provider fell over"):
        _complete()


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "   "}}]},
    ],
)
def test_reply_without_an_answer_is_an_error(openrouter, body):
    openrouter.reply(SONNET.model, httpx.Response(200, json=body))

    with pytest.raises(ModelError):
        _complete()


def test_network_failure_is_reported_after_retries(monkeypatch):
    import conclave.client
    import conclave.http

    calls = []

    def broken(request):
        calls.append(request)
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(conclave.http, "TRANSPORT", httpx.MockTransport(broken))
    monkeypatch.setattr(conclave.client, "RETRY_DELAYS", (0.0, 0.0))

    with pytest.raises(ModelError, match="network error"):
        _complete()
    assert len(calls) == 3


def test_command_line_route_is_refused_for_now(openrouter):
    with pytest.raises(ModelError, match="milestone 8"):
        _complete(member=Member("anthropic/claude-sonnet-5.5", route="cli"))

    assert openrouter.chat_requests == []


def test_reasoning_effort_comes_from_the_config(openrouter):
    async def go():
        async with new_client() as http:
            client = OpenRouterClient(http, KEY, reasoning="none")
            return await client.complete(SONNET, MESSAGES, 500)

    asyncio.run(go())

    assert openrouter.chat_requests[0]["reasoning"] == {"effort": "none"}


def test_answer_cut_off_at_the_length_limit_is_flagged(openrouter):
    openrouter.reply(
        SONNET.model, answer("Half an ans", finish_reason="length", reasoning_tokens=120)
    )

    done = _complete()

    assert done.text == "Half an ans"
    assert done.cut_off is True
    assert done.reasoning_tokens == 120


def test_finished_answer_is_not_flagged(openrouter):
    done = _complete()

    assert done.cut_off is False
    assert done.reasoning_tokens == 0


def test_all_thinking_and_no_answer_says_what_to_change(openrouter):
    openrouter.reply(SONNET.model, answer("", finish_reason="length", reasoning_tokens=500))

    with pytest.raises(ModelError, match="whole length limit thinking"):
        _complete()


def test_search_adds_the_web_search_tool_and_reads_citations(openrouter):
    cites = [
        ("https://a.example/1", "One", "first"),
        ("https://a.example/1", "One", "again"),
        ("https://b.example/2", "Two", ""),
        ("ftp://c.example/3", "Not web", ""),
    ]
    openrouter.reply(SONNET.model, answer("Found it.", cites=cites, searches=2))

    async def go():
        async with new_client() as http:
            return await OpenRouterClient(http, KEY).complete(SONNET, MESSAGES, 500, searches=3)

    done = asyncio.run(go())

    (tool,) = openrouter.chat_requests[0]["tools"]
    assert tool == {
        "type": "openrouter:web_search",
        "parameters": {"engine": "exa", "max_results": 5, "max_uses": 3, "max_total_results": 10},
    }
    assert done.searches == 2
    assert [(s.url, s.title, s.excerpt) for s in done.sources] == [
        ("https://a.example/1", "One", "first\n[...]\nagain"),
        ("https://b.example/2", "Two", ""),
    ]


def test_no_search_means_no_tool(openrouter):
    done = _complete()

    assert "tools" not in openrouter.chat_requests[0]
    assert (done.searches, done.sources) == (None, ())  # not reported, so not known


def _in_reply_error(code, message):
    return httpx.Response(200, json={"error": {"code": code, "message": message}})


def test_provider_failure_inside_a_200_reply_is_retried(openrouter):
    openrouter.reply(SONNET.model, _in_reply_error("502", "provider down"), answer("Back."))

    assert _complete().text == "Back."
    assert len(openrouter.chat_requests) == 2


def test_failing_search_falls_back_to_answering_without_it(openrouter):
    broken = _in_reply_error(
        504, 'Server tool "openrouter:web_search" failed: upstream returned 504'
    )

    def reply(body):
        return broken if "tools" in body else answer("From memory.")

    openrouter.replies[SONNET.model] = reply

    async def go():
        async with new_client() as http:
            return await OpenRouterClient(http, KEY).complete(SONNET, MESSAGES, 500, searches=3)

    done = asyncio.run(go())

    assert done.text == "From memory."
    assert "upstream returned 504" in done.search_failed
    with_tool = [b for b in openrouter.chat_requests if "tools" in b]
    assert len(with_tool) == 3  # tried, retried twice, then answered without search
    assert "tools" not in openrouter.chat_requests[-1]


def test_other_errors_do_not_trigger_the_fallback(openrouter):
    openrouter.reply(SONNET.model, failure(401))

    async def go():
        async with new_client() as http:
            return await OpenRouterClient(http, KEY).complete(SONNET, MESSAGES, 500, searches=3)

    with pytest.raises(ModelError, match="rejected the API key"):
        asyncio.run(go())
    assert len(openrouter.chat_requests) == 1


def test_usage_is_kept_as_reported(openrouter):
    openrouter.reply(SONNET.model, answer(searches=2))

    done = _complete()

    assert done.usage["server_tool_use_details"] == {"web_search_requests": 2}
    assert done.searches == 2


def test_search_count_is_also_read_from_the_older_field(openrouter):
    reply = answer()
    data = reply.json()
    data["usage"]["server_tool_use"] = {"web_search_requests": 4}
    openrouter.reply(SONNET.model, httpx.Response(200, json=data))

    assert _complete().searches == 4

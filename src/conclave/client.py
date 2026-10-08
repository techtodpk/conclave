"""Call a model and get back its answer, token counts and cost."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

import httpx

from conclave.config import Member

# Reasoning models think before they answer, and that thinking is billed as output and counts
# against max_tokens. Every call gets this much extra room for it, so the visible answer keeps
# its full length. With effort "low", OpenRouter gives Anthropic models a 1,024-token thinking
# budget and other models about a fifth of max_tokens, both within this allowance.
REASONING_ALLOWANCE = 2048

# Web search runs through OpenRouter's web_search server tool on the Exa engine, so every
# model searches the same way at the same price (decision 0011). The model decides when to
# search, up to the configured number of searches per answer.
SEARCH_ENGINE = "exa"
RESULTS_PER_SEARCH = 5
MAX_RESULTS_PER_ANSWER = 10
SEARCH_PRICE_USD = 0.007  # per search on Exa's default mode, up to 10 results included

RETRY_STATUSES = {408, 429, 500, 502, 503, 504, 524, 529}
RETRY_DELAYS = (1.0, 3.0)  # seconds before the second and third attempts

FRIENDLY = {
    401: "OpenRouter rejected the API key. Check the key is correct and active.",
    402: (
        "OpenRouter refused for lack of credit: the account balance or this key's spending "
        "limit is too low for this request. Add credit or raise the key's limit at "
        "https://openrouter.ai/keys."
    ),
    403: "OpenRouter blocked the request for this key or model.",
    404: "OpenRouter does not know this model id. Run `conclave models --search` to find it.",
    429: "Rate limited by OpenRouter or the model's provider. Try again shortly.",
}


class ModelError(Exception):
    """A model call failed. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Source:
    """A web page a model cited, with the excerpt the search returned when there was one."""

    url: str
    title: str = ""
    excerpt: str = ""


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None  # None when OpenRouter did not report a cost
    seconds: float
    cut_off: bool = False  # the model stopped at the length limit, so the text is incomplete
    reasoning_tokens: int = 0  # hidden thinking, included in completion_tokens
    searches: int | None = 0  # web searches run for this answer; None when not reported
    sources: tuple[Source, ...] = ()  # pages the model cited, in the order first cited
    usage: dict | None = None  # OpenRouter's usage figures as sent, kept for the run record
    search_failed: str | None = None  # why web search failed, when the answer came without it


Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class KeyStatus:
    """What OpenRouter reports about the key: its limit and what is left of it, in US dollars."""

    limit: float | None  # None when the key has no limit
    remaining: float | None  # None when the key has no limit


async def key_status(http: httpx.AsyncClient, api_key: str) -> KeyStatus | None:
    """Ask OpenRouter how much the key may still spend. None if that cannot be found out."""
    try:
        response = await http.get("/key", headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code != 200:
            return None
        data = response.json()["data"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None

    def amount(value: object) -> float | None:
        return (
            float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
        )

    return KeyStatus(limit=amount(data.get("limit")), remaining=amount(data.get("limit_remaining")))


class OpenRouterClient:
    """Calls models through OpenRouter's chat completions endpoint."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        sleep: Sleep = asyncio.sleep,
        reasoning: str = "low",
    ) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._sleep = sleep
        self._reasoning = reasoning

    async def complete(
        self,
        member: Member,
        messages: list[dict[str, str]],
        max_tokens: int,
        searches: int = 0,
    ) -> Completion:
        """`max_tokens` is the longest visible answer; room for reasoning is added on top.

        `searches` above 0 lets the model search the web up to that many times.
        """
        if member.route != "api":
            raise ModelError(
                f"{member.model} is set to route '{member.route}'. Only route 'api' works so far; "
                "command-line routes arrive in milestone 8."
            )

        body = {
            "model": member.model,
            "messages": messages,
            "max_tokens": max_tokens + REASONING_ALLOWANCE,
            "reasoning": {"effort": self._reasoning},
            "usage": {"include": True},
        }
        if searches > 0:
            body["tools"] = [
                {
                    "type": "openrouter:web_search",
                    "parameters": {
                        "engine": SEARCH_ENGINE,
                        "max_results": RESULTS_PER_SEARCH,
                        "max_uses": searches,
                        "max_total_results": MAX_RESULTS_PER_ANSWER,
                    },
                }
            ]
        started = time.monotonic()
        try:
            return await self._post(body, started)
        except ModelError as error:
            if "tools" not in body or "web_search" not in str(error):
                raise
            # The search service failed, not the model. Answer without searching rather
            # than lose this member, and say so.
            del body["tools"]
            done = await self._post(body, started)
            return replace(done, search_failed=str(error))

    async def _post(self, body: dict, started: float) -> Completion:
        """Send one request, retrying network errors and busy or failing providers."""
        attempts = len(RETRY_DELAYS) + 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = await self._http.post(
                    "/chat/completions", json=body, headers=self._headers
                )
            except httpx.HTTPError as error:
                if not last:
                    await self._sleep(RETRY_DELAYS[attempt])
                    continue
                raise ModelError(f"network error calling OpenRouter ({error!r})") from None

            if response.status_code in RETRY_STATUSES and not last:
                await self._sleep(RETRY_DELAYS[attempt])
                continue
            try:
                return _read(response, time.monotonic() - started)
            except ModelError as error:
                # A provider failure reported inside an HTTP 200 reply is retried the same way.
                if error.status in RETRY_STATUSES and not last:
                    await self._sleep(RETRY_DELAYS[attempt])
                    continue
                raise

        raise ModelError("the request was retried and still failed")  # pragma: no cover


def _error_message(response: httpx.Response) -> str:
    detail = ""
    try:
        error = response.json().get("error")
        if isinstance(error, dict) and error.get("message"):
            detail = str(error["message"])
    except (ValueError, AttributeError):
        pass
    friendly = FRIENDLY.get(response.status_code)
    if friendly and detail:
        return f"{friendly} (OpenRouter said: {detail})"
    return friendly or detail or f"OpenRouter returned HTTP {response.status_code}"


def _read(response: httpx.Response, seconds: float) -> Completion:
    if response.status_code != 200:
        raise ModelError(_error_message(response), status=response.status_code)

    try:
        data = response.json()
    except ValueError:
        raise ModelError("OpenRouter returned a reply that is not JSON") from None

    # OpenRouter can report a provider failure inside an HTTP 200 reply.
    if isinstance(data.get("error"), dict):
        message = data["error"].get("message") or "the provider returned an error"
        code = data["error"].get("code")
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = None
        raise ModelError(str(message), status=status)

    try:
        choice = data["choices"][0]
        message = choice["message"]
        text = message["content"]
    except (KeyError, IndexError, TypeError):
        raise ModelError("OpenRouter's reply had no answer in it") from None
    cut_off = choice.get("finish_reason") == "length"
    if not isinstance(text, str) or not text.strip():
        if cut_off:
            raise ModelError(
                "the model used its whole length limit thinking and wrote no answer. "
                "Lower run.reasoning or raise run.max_answer_tokens in the config."
            )
        raise ModelError("the model returned an empty answer")

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    # OpenRouter reports searches under server_tool_use_details; older replies used
    # server_tool_use.
    tools = usage.get("server_tool_use_details") or usage.get("server_tool_use")
    searches = tools.get("web_search_requests") if isinstance(tools, dict) else None
    counted = isinstance(searches, int) and not isinstance(searches, bool) and searches >= 0
    cost = usage.get("cost")
    reported = isinstance(cost, int | float) and not isinstance(cost, bool)
    return Completion(
        text=text.strip(),
        prompt_tokens=_whole(usage.get("prompt_tokens")),
        completion_tokens=_whole(usage.get("completion_tokens")),
        cost_usd=float(cost) if reported else None,
        seconds=seconds,
        cut_off=cut_off,
        reasoning_tokens=_whole(reasoning),
        searches=searches if counted else None,
        sources=_sources(message.get("annotations")),
        usage=usage or None,
    )


def _sources(annotations: object) -> tuple[Source, ...]:
    """The pages cited in a reply, one per URL, in the order first cited."""
    found: dict[str, Source] = {}
    if not isinstance(annotations, list):
        return ()
    for item in annotations:
        if not isinstance(item, dict) or item.get("type") != "url_citation":
            continue
        cite = item.get("url_citation")
        if not isinstance(cite, dict):
            continue
        url = cite.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        title = cite.get("title") if isinstance(cite.get("title"), str) else ""
        excerpt = cite.get("content") if isinstance(cite.get("content"), str) else ""
        known = found.get(url)
        if known is None:
            found[url] = Source(url, title.strip(), excerpt.strip())
        elif excerpt and excerpt not in known.excerpt:
            joined = f"{known.excerpt}\n[...]\n{excerpt.strip()}".strip()
            found[url] = Source(url, known.title or title.strip(), joined)
    return tuple(found.values())


def _whole(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

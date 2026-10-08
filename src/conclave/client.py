"""Call a model and get back its answer, token counts and cost."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from conclave.config import Member

# Reasoning models think before they answer, and that thinking is billed as output and counts
# against max_tokens. Every call gets this much extra room for it, so the visible answer keeps
# its full length. With effort "low", OpenRouter gives Anthropic models a 1,024-token thinking
# budget and other models about a fifth of max_tokens, both within this allowance.
REASONING_ALLOWANCE = 2048

RETRY_STATUSES = {408, 429, 500, 502, 503, 524, 529}
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
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None  # None when OpenRouter did not report a cost
    seconds: float
    cut_off: bool = False  # the model stopped at the length limit, so the text is incomplete
    reasoning_tokens: int = 0  # hidden thinking, included in completion_tokens


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
        self, member: Member, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        """`max_tokens` is the longest visible answer; room for reasoning is added on top."""
        if member.route != "api":
            raise ModelError(
                f"{member.model} is set to route '{member.route}'. Only route 'api' works so far; "
                "command-line routes arrive in milestone 7."
            )

        body = {
            "model": member.model,
            "messages": messages,
            "max_tokens": max_tokens + REASONING_ALLOWANCE,
            "reasoning": {"effort": self._reasoning},
            "usage": {"include": True},
        }
        started = time.monotonic()
        attempts = len(RETRY_DELAYS) + 1
        for attempt in range(attempts):
            try:
                response = await self._http.post(
                    "/chat/completions", json=body, headers=self._headers
                )
            except httpx.HTTPError as error:
                if attempt < attempts - 1:
                    await self._sleep(RETRY_DELAYS[attempt])
                    continue
                raise ModelError(f"network error calling OpenRouter ({error!r})") from None

            if response.status_code in RETRY_STATUSES and attempt < attempts - 1:
                await self._sleep(RETRY_DELAYS[attempt])
                continue
            return _read(response, time.monotonic() - started)

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
        raise ModelError(str(message), status=data["error"].get("code"))

    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
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
    )


def _whole(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

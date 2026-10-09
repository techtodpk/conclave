"""Shared test helpers: a simulated OpenRouter, so no test touches the network."""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable

import httpx
import pytest

import conclave.client
import conclave.http
import conclave.sources

KEY = "sk-or-test-key"

MODELS = [
    ("anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet 5.5", "0.000002", "0.00001"),
    ("anthropic/claude-opus-5.5", "Anthropic: Claude Opus 5.5", "0.000004", "0.00002"),
    ("openai/gpt-6.1-sol", "OpenAI: GPT-6.1 Sol", "0.000002", "0.00001"),
    ("google/gemini-3.8-flash", "Google: Gemini 3.8 Flash", "0.00000075", "0.00000375"),
    ("deepseek/deepseek-v4.1-flash", "DeepSeek: DeepSeek V4.1 Flash", "0.000000055", "0.00000132"),
]

Reply = Callable[[dict], httpx.Response]


def answer(
    text: str = "## Answer\n\nForty-two.",
    cost: float | None = 0.004,
    finish_reason: str = "stop",
    reasoning_tokens: int | None = None,
    cites: list[tuple[str, str, str]] | None = None,
    searches: int | None = None,
) -> httpx.Response:
    """A chat reply. `cites` is (url, title, excerpt) for each search citation."""
    usage: dict = {"prompt_tokens": 300, "completion_tokens": 200, "total_tokens": 500}
    if cost is not None:
        usage["cost"] = cost
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    if searches is not None:
        usage["server_tool_use_details"] = {"web_search_requests": searches}
    message: dict = {"role": "assistant", "content": text}
    if cites:
        message["annotations"] = [
            {
                "type": "url_citation",
                "url_citation": {"url": url, "title": title, "content": excerpt},
            }
            for url, title, excerpt in cites
        ]
    choice = {"message": message, "finish_reason": finish_reason}
    body = {"choices": [choice], "usage": usage}
    return httpx.Response(200, json=body)


def stage_of(body: dict) -> str:
    """Which stage a request belongs to, read from its system prompt."""
    system = body["messages"][0]["content"]
    if "reviewing answers" in system:
        return "critique"
    if "chairman of a research council" in system:
        return "synthesis"
    if "research memory for one topic" in system:
        return "memory"
    if "You pick the key claims" in system:
        return "extract"
    if "You check claims against" in system:
        return "check"
    return "research"


# Pages the simulated web serves. Members cite them when they are allowed to search.
PAGE_A = "https://docs.example.org/sky"
PAGE_B = "https://blog.example.net/sky-colour"
PAGE_A_TEXT = (
    "The colour of the sky. "
    + "Background on light and the atmosphere. " * 20
    + "The sky looks blue because molecules in the air scatter short blue wavelengths of "
    "sunlight more than long red ones, which is called Rayleigh scattering. "
    + "Further reading on optics. "
    * 20
)
PAGE_A_HTML = (
    f"<html><head><title>Why the sky is blue</title><script>var x = 1;</script></head>"
    f"<body><nav>Home | Docs</nav><p>{PAGE_A_TEXT}</p></body></html>"
)
EXCERPT_B = "Sunsets look red because light crosses more air when the sun is low."


def web_reply(body: dict) -> httpx.Response:
    """A member's answer when it may search: cites page A, and Sonnet also page B."""
    model = body["model"]
    cites = [(PAGE_A, "Why the sky is blue", "molecules in the air scatter short blue wavelengths")]
    if model.startswith("anthropic/"):
        cites.append((PAGE_B, "Sky colour", EXCERPT_B))
    text = (
        f"## Answer\n\nAnswer from {model}.\n\n## Key claims\n\n"
        f"1. Rayleigh scattering makes the sky blue. [high] Sources: [docs]({PAGE_A})"
    )
    return answer(text, cites=cites, searches=len(cites))


def extract_reply(body: dict) -> httpx.Response:
    """The checker's claims: one backed by page A, one by page B, one with no source."""
    user = body["messages"][1]["content"]
    ids = dict((url, sid) for sid, url in re.findall(r"^- (S\d+): (\S+)", user, re.M))
    letters = re.findall(r"^### Response ([A-Z])$", user, re.M)
    claims = [
        {
            "text": "The sky is blue because air scatters blue sunlight more (Rayleigh).",
            "responses": letters,
            "sources": [ids[PAGE_A]] if PAGE_A in ids else [],
            "disagreement": False,
        }
    ]
    if PAGE_B in ids:
        claims.append(
            {
                "text": "Sunsets are red because of a longer path through the air.",
                "responses": letters[:1],
                "sources": [ids[PAGE_B]],
                "disagreement": False,
            }
        )
    claims.append(
        {"text": "An unsourced claim.", "responses": letters, "sources": [], "disagreement": False}
    )
    return answer("```json\n" + json.dumps({"claims": claims}) + "\n```", cost=0.002)


def check_reply(body: dict) -> httpx.Response:
    """Claim 1 supported by page A with a real quote; anything else not found."""
    user = body["messages"][1]["content"]
    a_id = re.search(r"^### (S\d+): " + re.escape(PAGE_A), user, re.M)
    verdicts = [
        {
            "claim": 1,
            "verdict": "supported",
            "source": a_id.group(1) if a_id else "S1",
            "quote": "scatter short blue wavelengths of sunlight more than long red ones",
            "note": "",
        },
        {"claim": 2, "verdict": "not found", "source": "", "quote": "", "note": "Excerpt only."},
    ]
    return answer("```json\n" + json.dumps({"verdicts": verdicts}) + "\n```", cost=0.002)


def default_reply(body: dict) -> httpx.Response:
    """A plausible reply for whichever stage the request belongs to."""
    model = body["model"]
    stage = stage_of(body)
    if stage == "research" and body.get("tools"):
        return web_reply(body)
    if stage == "extract":
        return extract_reply(body)
    if stage == "check":
        return check_reply(body)
    if stage == "critique":
        letters = re.findall(r"^### Response ([A-Z])$", body["messages"][1]["content"], re.M)
        sections = "\n\n".join(
            f"## Response {letter}\n\n**Errors:** None found." for letter in letters
        )
        ranking = "\n".join(f"{n}. Response {x}" for n, x in enumerate(sorted(letters), 1))
        return answer(f"{sections}\n\n## Ranking\n\n{ranking}", cost=0.002)
    if stage == "synthesis":
        return answer(
            "## Answer\n\nThe council's answer.\n\n## Key claims\n\n"
            "1. A claim. [agreed but unchecked]\n\n## Disagreements\n\nNone.\n\n"
            "## Open questions\n\nNone.",
            cost=0.006,
        )
    if stage == "memory":
        patch = {
            "add": [{"text": "A claim.", "label": "agreed but unchecked"}],
            "open_disputes": [{"text": "Whether the claim holds everywhere."}],
        }
        return answer("```json\n" + json.dumps(patch) + "\n```", cost=0.003)
    return answer(f"## Answer\n\nAnswer from {model}.")


def failure(status: int, message: str = "nope") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message}})


class FakeOpenRouter:
    """Stands in for OpenRouter. Records every request it receives."""

    def __init__(self) -> None:
        self.models_status = 200
        self.replies: dict[str, list[httpx.Response] | Reply] = {}
        self.chat_requests: list[dict] = []
        self.auth_headers: list[str | None] = []
        self.model_list_requests = 0
        self.key_limit: float | None = None
        self.key_remaining: float | None = None
        self.key_status = 200
        # url -> (status, content type, body); anything else on the web is a 404.
        self.pages: dict[str, tuple[int, str, str]] = {
            PAGE_A: (200, "text/html; charset=utf-8", PAGE_A_HTML),
        }
        self.fetched: list[str] = []

    def reply(self, model: str, *responses: httpx.Response, stage: str | None = None) -> None:
        """Queue responses for a model, optionally for one stage only.

        The last response repeats once the queue runs out.
        """
        self.replies[f"{stage}:{model}" if stage else model] = list(responses)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "openrouter.ai":
            url = str(request.url)
            self.fetched.append(url)
            status, kind, page = self.pages.get(url, (404, "text/html", "Not found"))
            return httpx.Response(status, headers={"content-type": kind}, text=page)
        if request.url.path.endswith("/models"):
            self.model_list_requests += 1
            if self.models_status != 200:
                return httpx.Response(self.models_status, json={"error": {"message": "down"}})
            data = [
                {
                    "id": model_id,
                    "name": name,
                    "pricing": {"prompt": prompt, "completion": completion},
                    "context_length": 1_000_000,
                }
                for model_id, name, prompt, completion in MODELS
            ]
            return httpx.Response(200, json={"data": data})

        if request.url.path.endswith("/key"):
            if self.key_status != 200:
                return httpx.Response(self.key_status, json={"error": {"message": "no"}})
            data = {"limit": self.key_limit, "limit_remaining": self.key_remaining, "usage": 0}
            return httpx.Response(200, json={"data": data})

        body = json.loads(request.content)
        self.chat_requests.append(body)
        self.auth_headers.append(request.headers.get("authorization"))
        queued = self.replies.get(f"{stage_of(body)}:{body['model']}") or self.replies.get(
            body["model"]
        )
        if queued is None:
            return default_reply(body)
        if callable(queued):
            return queued(body)
        return queued.pop(0) if len(queued) > 1 else queued[0]

    @property
    def asked(self) -> list[str]:
        return [body["model"] for body in self.chat_requests]

    def asked_in(self, stage: str) -> list[str]:
        return [body["model"] for body in self.chat_requests if stage_of(body) == stage]


@pytest.fixture
def openrouter(monkeypatch) -> FakeOpenRouter:
    fake = FakeOpenRouter()
    monkeypatch.setattr(conclave.http, "TRANSPORT", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(conclave.client, "RETRY_DELAYS", (0.0, 0.0))
    # Page fetches must not touch the network. Hostnames look public; IP literals are still checked.
    monkeypatch.setattr(
        conclave.sources, "resolve_host", lambda host: [ipaddress.ip_address("8.8.8.8")]
    )
    return fake


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """An isolated home: its own config, store and working folder, and no key in the environment."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CONCLAVE_CONFIG", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    class Workspace:
        config = tmp_path / "settings" / "config.toml"
        store = tmp_path / "research"
        cwd = work

        def runs(self, topic: str = "general") -> list:
            return sorted((self.store / "topics" / topic / "runs").glob("*"))

        def set_key(self) -> None:
            monkeypatch.setenv("OPENROUTER_API_KEY", KEY)

    return Workspace()

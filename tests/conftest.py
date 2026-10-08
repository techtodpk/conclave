"""Shared test helpers: a simulated OpenRouter, so no test touches the network."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import httpx
import pytest

import conclave.client
import conclave.http

KEY = "sk-or-test-key"

MODELS = [
    ("anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet 5.5", "0.000002", "0.00001"),
    ("anthropic/claude-opus-5.5", "Anthropic: Claude Opus 5.5", "0.000004", "0.00002"),
    ("openai/gpt-6.1-sol", "OpenAI: GPT-6.1 Sol", "0.000002", "0.00001"),
    ("google/gemini-3.8-flash", "Google: Gemini 3.8 Flash", "0.00000075", "0.00000375"),
    ("deepseek/deepseek-v4.1-flash", "DeepSeek: DeepSeek V4.1 Flash", "0.000000055", "0.00000132"),
]

Reply = Callable[[dict], httpx.Response]


def answer(text: str = "## Answer\n\nForty-two.", cost: float | None = 0.004) -> httpx.Response:
    usage: dict = {"prompt_tokens": 300, "completion_tokens": 200, "total_tokens": 500}
    if cost is not None:
        usage["cost"] = cost
    body = {"choices": [{"message": {"role": "assistant", "content": text}}], "usage": usage}
    return httpx.Response(200, json=body)


def stage_of(body: dict) -> str:
    """Which stage a request belongs to, read from its system prompt."""
    system = body["messages"][0]["content"]
    if "reviewing answers" in system:
        return "critique"
    if "chairman of a research council" in system:
        return "synthesis"
    return "research"


def default_reply(body: dict) -> httpx.Response:
    """A plausible reply for whichever stage the request belongs to."""
    model = body["model"]
    stage = stage_of(body)
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

    def reply(self, model: str, *responses: httpx.Response, stage: str | None = None) -> None:
        """Queue responses for a model, optionally for one stage only.

        The last response repeats once the queue runs out.
        """
        self.replies[f"{stage}:{model}" if stage else model] = list(responses)

    def handle(self, request: httpx.Request) -> httpx.Response:
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

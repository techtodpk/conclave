"""The council's stages. Milestone 2 has the first one: Research."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from importlib import resources
from typing import Protocol

from conclave.client import Completion, ModelError
from conclave.config import Member


class ModelClient(Protocol):
    async def complete(
        self, member: Member, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion: ...


@dataclass(frozen=True)
class Seat:
    """A model and the part it plays in this run."""

    member: Member
    role: str  # "member" or "chairman"


@dataclass(frozen=True)
class SeatResult:
    seat: Seat
    completion: Completion | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.completion is not None


def load_prompt(name: str) -> str:
    """Read a stage prompt that ships with the package."""
    prompt = resources.files("conclave").joinpath("prompts", f"{name}.md")
    return prompt.read_text(encoding="utf-8").strip()


def research_messages(question: str, today: date) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": load_prompt("research")},
        {"role": "user", "content": f"Today's date: {today.isoformat()}\n\nQuestion: {question}"},
    ]


async def research(
    client: ModelClient, seats: list[Seat], question: str, max_tokens: int, today: date
) -> list[SeatResult]:
    """Ask every seat the question at the same time. One failure never stops the others."""
    messages = research_messages(question, today)

    async def ask(seat: Seat) -> SeatResult:
        try:
            completion = await client.complete(seat.member, messages, max_tokens)
        except ModelError as error:
            return SeatResult(seat=seat, error=str(error))
        except Exception as error:  # noqa: BLE001 - keep the other members' answers
            return SeatResult(seat=seat, error=f"unexpected {type(error).__name__}: {error}")
        return SeatResult(seat=seat, completion=completion)

    return list(await asyncio.gather(*(ask(seat) for seat in seats)))

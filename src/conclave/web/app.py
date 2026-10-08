"""The app's server: a JSON API over the research store and the council, plus the page.

It listens on 127.0.0.1 only. Requests must name a local host (which stops DNS-rebinding
pages from reaching it), and anything that changes state or spends money must carry the
`X-Conclave` header, which a page on another site cannot add without the app's consent.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from conclave import __version__, library, service
from conclave.catalog import CatalogError, ModelInfo, fetch_models
from conclave.config import (
    MIN_MEMBERS,
    REASONING_LEVELS,
    Config,
    ConfigError,
    Member,
    default_config_path,
    load_config,
)
from conclave.gitstore import commit
from conclave.http import API_BASE, new_client
from conclave.keys import KEY_NAME
from conclave.memory import MemoryFileError, load_memory
from conclave.runner import Outcome, Refused, check_ids, evidence_of
from conclave.service import Stop
from conclave.settings_file import (
    SettingsError,
    create_config,
    key_hint,
    put_profile,
    remove_profile,
    save_api_key,
    update,
)
from conclave.store import DEFAULT_TOPIC, init_store, month_spend, slugify
from conclave.web.render import front_matter, markdown

STATIC = Path(__file__).parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
# The page may load nothing from elsewhere: no scripts, images, fonts or frames.
POLICY = (
    b"default-src 'self'; script-src 'self'; img-src 'self' data:; "
    b"style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
    b"base-uri 'none'; form-action 'self'"
)
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
CATALOG_SECONDS = 15 * 60


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --- protection -------------------------------------------------------------------


class LocalOnly:
    """Refuse requests that do not come from this machine's own pages."""

    def __init__(self, app: ASGIApp, extra_hosts: set[str] | None = None) -> None:
        self.app = app
        self.extra = extra_hosts or set()
        self.hosts = LOCAL_HOSTS | self.extra

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        problem = None
        if name not in self.hosts:
            problem = "This app only answers requests addressed to this computer."
        elif scope["method"] not in ("GET", "HEAD"):
            origin = headers.get("origin")
            if headers.get("x-conclave") != "1":
                problem = "Missing the app's request header."
            elif origin and origin.split("://", 1)[-1] not in (host, *self.extra):
                problem = "Requests from other sites are not allowed."
        if problem:
            response = JSONResponse({"error": problem}, status_code=403)
            await response(scope, receive, send)
            return

        async def with_policy(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"content-security-policy", POLICY),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
            await send(message)

        await self.app(scope, receive, with_policy)


# --- running questions --------------------------------------------------------------


@dataclass
class Job:
    id: str
    question: str
    topic: str
    mode: str
    profile: str
    started: float = field(default_factory=time.monotonic)
    state: str = "running"  # running, done or failed
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    task: asyncio.Task | None = None


def outcome_payload(outcome: Outcome, settings: Config, spent: float) -> dict[str, Any]:
    answered = [c for c in outcome.calls if c.stage == "research" and c.result.ok]
    answer = None
    if outcome.final_text is None and outcome.mode == "quick" and answered:
        answer = answered[0].result.completion.text  # type: ignore[union-attr]
    cap = settings.budget.cap_for(outcome.mode)
    return {
        "mode": outcome.mode,
        "topic": outcome.topic,
        "run": outcome.run.path.name if outcome.run else None,
        "html": markdown(outcome.final_text or answer or ""),
        "has_page": outcome.final_text is not None,
        "cost": round(outcome.total_cost, 6),
        "cap": cap,
        "month": round(spent + outcome.total_cost, 6),
        "monthly_cap": settings.budget.monthly_usd,
        "evidence": evidence_of(outcome),
        "changes": outcome.changes.lines() if outcome.changes else [],
        "notes": outcome.notes,
        "stopped": outcome.stopped,
        "calls": [
            {
                "stage": c.stage,
                "model": c.result.seat.member.model,
                "ok": c.result.ok,
                "cost": c.cost,
                "error": c.result.error,
            }
            for c in outcome.calls
        ],
    }


# --- the app --------------------------------------------------------------------------


def create_app(
    config_path: Path | None = None,
    *,
    extra_hosts: set[str] | None = None,
    on_quit: Any = None,
) -> Starlette:
    path = (config_path or default_config_path()).expanduser()
    jobs: dict[str, Job] = {}
    catalog_cache: dict[str, Any] = {"at": 0.0, "models": None}

    def settings() -> Config:
        if not path.exists():
            raise ApiError("Conclave is not set up yet.", 409)
        try:
            return load_config(path)
        except ConfigError as error:
            raise ApiError(f"Config problem: {error}") from None

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except ValueError:
            raise ApiError("The request was not valid JSON.") from None
        if not isinstance(data, dict):
            raise ApiError("The request was not valid JSON.")
        return data

    async def catalog() -> dict[str, ModelInfo]:
        if catalog_cache["models"] and time.monotonic() - catalog_cache["at"] < CATALOG_SECONDS:
            return catalog_cache["models"]
        try:
            async with new_client() as http:
                models = await fetch_models(http)
        except CatalogError as error:
            raise ApiError(f"Could not load the model list from OpenRouter: {error}", 502) from None
        catalog_cache.update(at=time.monotonic(), models=models)
        return models

    def topic_dir(cfg: Config, topic: str) -> Path:
        if not SAFE_NAME.match(topic):
            raise ApiError(f"No topic named '{topic}'.", 404)
        folder = cfg.store_path / "topics" / topic
        if not folder.is_dir():
            raise ApiError(f"No topic named '{topic}'.", 404)
        return folder

    # --- status and setup ---------------------------------------------------------

    async def status(request: Request) -> Response:
        has_config = path.exists()
        info: dict[str, Any] = {
            "version": __version__,
            "config_path": str(path),
            "has_config": has_config,
            "key": key_hint(path),
            "running": next((j.id for j in jobs.values() if j.state == "running"), None),
        }
        if has_config:
            try:
                cfg = load_config(path)
            except ConfigError as error:
                info["config_error"] = str(error)
            else:
                info.update(
                    store=str(cfg.store_path),
                    default_profile=cfg.default_profile,
                    default_mode=cfg.default_mode,
                    profiles=sorted(cfg.profiles),
                    month=round(month_spend(cfg.store_path, datetime.now().astimezone()), 6),
                    monthly_cap=cfg.budget.monthly_usd,
                    web_search=cfg.web_search,
                )
        info["setup_needed"] = not has_config or info["key"] is None or "config_error" in info
        return JSONResponse(info)

    async def setup_store(request: Request) -> Response:
        data = await body(request)
        raw = data.get("path")
        store = Path(str(raw)).expanduser() if raw else None
        if store is not None and not store.is_absolute():
            raise ApiError("Give the full path of the folder, for example C:\\Research.")
        created = create_config(path, store)
        cfg = settings()
        try:
            init_store(cfg.store_path)
        except OSError as error:
            raise ApiError(f"Could not create the research folder: {error}") from None
        return JSONResponse({"created_config": created, "store": str(cfg.store_path)})

    async def setup_key(request: Request) -> Response:
        data = await body(request)
        key = str(data.get("key", "")).strip()
        if not key:
            raise ApiError("Paste your OpenRouter key first.")
        try:
            async with httpx.AsyncClient(
                base_url=API_BASE, timeout=20, transport=_transport()
            ) as h:
                reply = await h.get("/key", headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            raise ApiError(
                "Could not reach OpenRouter to check the key. Check your internet connection "
                "and try again.",
                502,
            ) from None
        if reply.status_code in (401, 403):
            raise ApiError(
                "OpenRouter did not accept this key. Copy it again from openrouter.ai/keys."
            )
        if reply.status_code != 200:
            raise ApiError(f"OpenRouter could not check the key (HTTP {reply.status_code}).", 502)
        if not path.exists():
            create_config(path)
        try:
            saved = save_api_key(path, key)
        except SettingsError as error:
            raise ApiError(str(error)) from None
        try:
            details = reply.json().get("data") or {}
        except (ValueError, AttributeError):
            details = {}
        in_use = key_hint(path)
        return JSONResponse(
            {
                "saved_to": str(saved),
                "ends": key[-4:],
                "limit": details.get("limit"),
                "remaining": details.get("limit_remaining"),
                "env_override": KEY_NAME in os.environ,
                # Another key that takes precedence over the one just saved, if any.
                "other_key_in_use": None
                if in_use and in_use["source"] == str(saved) and in_use["ends"] == key[-4:]
                else in_use,
            }
        )

    # --- asking ----------------------------------------------------------------------

    async def ask(request: Request) -> Response:
        cfg = settings()
        data = await body(request)
        if any(j.state == "running" for j in jobs.values()):
            raise ApiError("A question is already running. Wait for it to finish.", 409)
        question = str(data.get("question", ""))
        topic = str(data.get("topic") or DEFAULT_TOPIC)
        full = bool(data.get("full"))
        started = datetime.now().astimezone()
        try:
            plan = service.plan_ask(
                cfg,
                question,
                started,
                profile=data.get("profile") or None,
                full=full,
                quick=not full,
                fresh=bool(data.get("fresh")),
            )
        except Stop as stop:
            raise ApiError(str(stop)) from None
        job = Job(
            id=uuid.uuid4().hex[:12],
            question=question.strip(),
            topic=slugify(topic, fallback=DEFAULT_TOPIC),
            mode=plan.mode,
            profile=plan.profile.name,
        )

        def progress(event: dict[str, Any]) -> None:
            event["at"] = round(time.monotonic() - job.started, 1)
            job.events.append(event)

        async def work() -> None:
            try:
                outcome = await service.run_plan_async(
                    plan,
                    cfg,
                    path,
                    question,
                    topic,
                    started,
                    fresh=bool(data.get("fresh")),
                    search=not data.get("no_search"),
                    progress=progress,
                )
            except Stop as stop:
                job.state, job.error = "failed", str(stop)
                return
            except Exception as error:  # noqa: BLE001 - the page must hear about any failure
                job.state, job.error = (
                    "failed",
                    f"Unexpected error: {type(error).__name__}: {error}",
                )
                return
            if outcome.run is None:
                errors = "; ".join(
                    f"{c.result.seat.member.model}: {c.result.error}" for c in outcome.calls
                )
                job.state, job.error = (
                    "failed",
                    f"No model answered, so nothing was saved. {errors}",
                )
                return
            job.result = outcome_payload(outcome, cfg, plan.spent)
            job.state = "done"

        jobs[job.id] = job
        job.task = asyncio.create_task(work())
        members = [s.member.model for s in plan.seats]
        return JSONResponse(
            {
                "job": job.id,
                "mode": plan.mode,
                "profile": plan.profile.name,
                "members": members,
                "chairman": plan.chairman.member.model,
                "checker": plan.profile.checker.model,
                "search": cfg.web_search and not data.get("no_search") and plan.mode == "full",
            },
            status_code=202,
        )

    async def job_status(request: Request) -> Response:
        job = jobs.get(request.path_params["job"])
        if job is None:
            raise ApiError("No such question is running.", 404)
        try:
            since = max(0, int(request.query_params.get("since", 0) or 0))
        except ValueError:
            since = 0
        return JSONResponse(
            {
                "state": job.state,
                "question": job.question,
                "topic": job.topic,
                "mode": job.mode,
                "elapsed": round(time.monotonic() - job.started, 1),
                "events": job.events[since:],
                "next": len(job.events),
                "result": job.result,
                "error": job.error,
            }
        )

    # --- topics, runs and notes -----------------------------------------------------

    async def list_topics(request: Request) -> Response:
        cfg = settings()
        try:
            found = library.topics(cfg.store_path)
        except MemoryFileError as error:
            raise ApiError(str(error)) from None
        return JSONResponse([vars(t) for t in found])

    async def get_topic(request: Request) -> Response:
        cfg = settings()
        folder = topic_dir(cfg, request.path_params["topic"])
        try:
            memory = load_memory(folder, folder.name)
        except MemoryFileError as error:
            raise ApiError(str(error)) from None
        runs = [vars(r) for r in library.run_records(cfg.store_path) if r.topic == folder.name]
        return JSONResponse(
            {
                "topic": folder.name,
                "claims": [
                    {
                        "id": c.id,
                        "text": c.text,
                        "label": c.label,
                        "added": c.added,
                        "updated": c.updated,
                        "history": c.history,
                        "retired": c.retired,
                        "retired_reason": c.retired_reason,
                    }
                    for c in memory.claims
                ],
                "disputes": [vars(d) for d in memory.disputes],
                "notes": _notes(folder),
                "runs": runs,
                "has_sources": (folder / "sources.md").is_file(),
            }
        )

    async def add_topic_note(request: Request) -> Response:
        cfg = settings()
        topic = request.path_params["topic"]
        if not SAFE_NAME.match(topic):
            raise ApiError("Topic names use letters, digits and '-' only.")
        data = await body(request)
        try:
            service.note(cfg, topic, str(data.get("text", "")))
        except Stop as stop:
            raise ApiError(str(stop)) from None
        return JSONResponse({"notes": _notes(cfg.store_path / "topics" / slugify(topic))})

    async def delete_topic_note(request: Request) -> Response:
        cfg = settings()
        folder = topic_dir(cfg, request.path_params["topic"])
        index = int(request.path_params["index"])
        notes_file = folder / "notes.md"
        lines = notes_file.read_text(encoding="utf-8").splitlines() if notes_file.is_file() else []
        positions = [i for i, line in enumerate(lines) if line.startswith("- ")]
        if not 0 <= index < len(positions):
            raise ApiError("No such note.", 404)
        del lines[positions[index]]
        notes_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        problem = commit(cfg.store_path, [notes_file], f"conclave: note removed on {folder.name}")
        return JSONResponse({"notes": _notes(folder), "commit_problem": problem})

    async def get_run(request: Request) -> Response:
        cfg = settings()
        folder = topic_dir(cfg, request.path_params["topic"])
        name = request.path_params["run"]
        run = folder / "runs" / name
        if not SAFE_NAME.match(name) or not run.is_dir():
            raise ApiError(f"No run named '{name}'.", 404)

        def read_json(file: str) -> Any:
            try:
                return json.loads((run / file).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None

        def texts(sub: str) -> list[dict[str, Any]]:
            out = []
            for file in sorted((run / sub).glob("*.md")) if (run / sub).is_dir() else []:
                raw = file.read_text(encoding="utf-8")
                head = front_matter(raw)
                out.append(
                    {
                        "model": head.get("model", file.stem),
                        "letter": head.get("response"),
                        "role": head.get("role"),
                        "html": markdown(raw),
                    }
                )
            return out

        meta = read_json("meta.json") or {}
        final = run / "final.md"
        verification = run / "verification.md"
        return JSONResponse(
            {
                "topic": folder.name,
                "run": name,
                "question": meta.get("question", ""),
                "mode": library.run_mode(run),
                "started": meta.get("started"),
                "profile": meta.get("profile"),
                "cost": (meta.get("totals") or {}).get("cost_usd"),
                "evidence": meta.get("evidence"),
                "notes": meta.get("notes") or [],
                "calls": [
                    {
                        k: c.get(k)
                        for k in ("stage", "model", "status", "cost_usd", "seconds", "error")
                    }
                    for c in meta.get("calls") or []
                ],
                "final_html": markdown(final.read_text(encoding="utf-8"))
                if final.is_file()
                else None,
                "answers": texts("answers"),
                "critiques": texts("critiques"),
                "verification_html": markdown(verification.read_text(encoding="utf-8"))
                if verification.is_file()
                else None,
                "sources": read_json("sources.json") or [],
                "rankings": read_json("rankings.json"),
                "memory_patch": read_json("memory_patch.json"),
            }
        )

    # --- search and spending ------------------------------------------------------

    async def search(request: Request) -> Response:
        cfg = settings()
        query = request.query_params.get("q", "").strip()
        if not query:
            return JSONResponse([])
        topic = request.query_params.get("topic") or None
        hits = library.search(cfg.store_path, query, topic, 30)
        out = []
        for hit in hits:
            found = Path(hit.path)
            parts = (found.relative_to(cfg.store_path) if found.is_absolute() else found).parts
            out.append(
                {
                    "kind": hit.kind,
                    "snippet": hit.snippet,
                    "topic": parts[1] if len(parts) > 1 else None,
                    "run": parts[3] if len(parts) > 3 and parts[2] == "runs" else None,
                    "path": str(hit.path),
                }
            )
        return JSONResponse(out)

    async def spending(request: Request) -> Response:
        cfg = settings()
        records = library.run_records(cfg.store_path)
        months: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0, "runs": 0})
        for r in records:
            month = r.started[:7]
            months[month]["total"] += r.cost
            months[month]["runs"] += 1
        now = datetime.now().astimezone()
        return JSONResponse(
            {
                "month": round(month_spend(cfg.store_path, now), 6),
                "monthly_cap": cfg.budget.monthly_usd,
                "full_cap": cfg.budget.full_run_usd,
                "quick_cap": cfg.budget.quick_run_usd,
                "months": [
                    {"month": m, "total": round(v["total"], 4), "runs": int(v["runs"])}
                    for m, v in sorted(months.items(), reverse=True)
                ],
                "runs": [vars(r) for r in records[:100]],
                "leaderboard": [vars(p) for p in library.leaderboard(cfg.store_path)],
            }
        )

    # --- settings and councils ---------------------------------------------------

    def settings_payload(cfg: Config) -> dict[str, Any]:
        return {
            "config_path": str(path),
            "store": str(cfg.store_path),
            "key": key_hint(path),
            "run": {
                "default_profile": cfg.default_profile,
                "default_mode": cfg.default_mode,
                "max_answer_tokens": cfg.max_answer_tokens,
                "reasoning": cfg.reasoning,
                "claims_checked": cfg.claims_checked,
            },
            "search": {"enabled": cfg.web_search, "max_searches": cfg.max_searches},
            "budget": {
                "full_run_usd": cfg.budget.full_run_usd,
                "quick_run_usd": cfg.budget.quick_run_usd,
                "monthly_usd": cfg.budget.monthly_usd,
            },
            "reasoning_levels": list(REASONING_LEVELS),
            "profiles": [
                {
                    "name": p.name,
                    "members": [m.model for m in p.members],
                    "chairman": p.chairman.model,
                    "checker": p.checker.model,
                    "shared_vendors": p.shared_vendors(),
                    "api_only": all(m.route == "api" for m in [*p.members, p.chairman, p.checker]),
                }
                for p in cfg.profiles.values()
            ],
        }

    async def get_settings(request: Request) -> Response:
        return JSONResponse(settings_payload(settings()))

    async def put_settings(request: Request) -> Response:
        settings()
        data = await body(request)
        allowed = {
            ("run", "default_profile"): str,
            ("run", "default_mode"): str,
            ("run", "max_answer_tokens"): int,
            ("run", "reasoning"): str,
            ("run", "claims_checked"): int,
            ("search", "enabled"): bool,
            ("search", "max_searches"): int,
            ("budget", "full_run_usd"): float,
            ("budget", "quick_run_usd"): float,
            ("budget", "monthly_usd"): float,
        }
        changes: dict[tuple[str, str], object] = {}
        for section, values in data.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                kind = allowed.get((section, key))
                if kind is None:
                    raise ApiError(f"{section}.{key} cannot be changed here.")
                try:
                    converted = bool(value) if kind is bool else kind(value)  # type: ignore[operator]
                except (TypeError, ValueError, OverflowError):
                    raise ApiError(f"{section}.{key}: '{value}' is not a valid value.") from None
                if isinstance(converted, float) and not math.isfinite(converted):
                    raise ApiError(f"{section}.{key}: '{value}' is not a valid amount.")
                changes[(section, key)] = converted
        try:
            cfg = update(path, changes)
        except SettingsError as error:
            raise ApiError(str(error)) from None
        return JSONResponse(settings_payload(cfg))

    async def models(request: Request) -> Response:
        found = await catalog()
        return JSONResponse(
            [
                {
                    "id": m.id,
                    "name": m.name,
                    "vendor": m.vendor,
                    "prompt": round(m.prompt_per_million, 4),
                    "completion": round(m.completion_per_million, 4),
                    "context": m.context_length,
                }
                for m in sorted(found.values(), key=lambda m: m.id)
            ]
        )

    async def save_council(request: Request) -> Response:
        settings()
        data = await body(request)
        name = str(data.get("name", "")).strip().lower()
        ids = [str(x).strip() for x in data.get("members") or [] if str(x).strip()]
        chair = str(data.get("chairman", "")).strip()
        checker = str(data.get("checker", "")).strip() or chair
        if len(ids) < MIN_MEMBERS:
            raise ApiError(f"Pick at least {MIN_MEMBERS} members.")
        if not chair:
            raise ApiError("Pick a chairman.")
        try:
            members = [Member(i) for i in ids]
            chair_m, check_m = Member(chair), Member(checker)
            check_ids([*members, chair_m, check_m], await catalog())
        except Refused as refused:
            raise ApiError(str(refused)) from None
        try:
            cfg = put_profile(path, name, members, chair_m, check_m, bool(data.get("replace")))
        except SettingsError as error:
            raise ApiError(str(error)) from None
        return JSONResponse(settings_payload(cfg))

    async def delete_council(request: Request) -> Response:
        settings()
        try:
            cfg = remove_profile(path, request.path_params["name"])
        except SettingsError as error:
            raise ApiError(str(error)) from None
        return JSONResponse(settings_payload(cfg))

    async def quit_app(request: Request) -> Response:
        data = await body(request)
        if any(j.state == "running" for j in jobs.values()) and not data.get("force"):
            raise ApiError("A question is still running. Close the app when it has finished.", 409)
        if on_quit is not None:
            asyncio.get_running_loop().call_later(0.3, on_quit)
        return JSONResponse({"ok": True})

    # --- wiring ----------------------------------------------------------------------

    def api(handler):
        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except ApiError as error:
                return JSONResponse({"error": str(error)}, status_code=error.status)

        return wrapped

    routes = [
        Route("/api/status", api(status)),
        Route("/api/setup/store", api(setup_store), methods=["POST"]),
        Route("/api/setup/key", api(setup_key), methods=["POST"]),
        Route("/api/ask", api(ask), methods=["POST"]),
        Route("/api/jobs/{job}", api(job_status)),
        Route("/api/topics", api(list_topics)),
        Route("/api/topics/{topic}", api(get_topic)),
        Route("/api/topics/{topic}/notes", api(add_topic_note), methods=["POST"]),
        Route("/api/topics/{topic}/notes/{index:int}", api(delete_topic_note), methods=["DELETE"]),
        Route("/api/topics/{topic}/runs/{run}", api(get_run)),
        Route("/api/search", api(search)),
        Route("/api/spending", api(spending)),
        Route("/api/settings", api(get_settings)),
        Route("/api/settings", api(put_settings), methods=["PUT"]),
        Route("/api/models", api(models)),
        Route("/api/councils", api(save_council), methods=["POST"]),
        Route("/api/councils/{name}", api(delete_council), methods=["DELETE"]),
        Route("/api/quit", api(quit_app), methods=["POST"]),
        Mount("/", StaticFiles(directory=STATIC, html=True)),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(LocalOnly, extra_hosts=extra_hosts)])
    app.state.jobs = jobs
    return app


def _transport():
    from conclave import http as http_module

    return http_module.TRANSPORT


def _notes(folder: Path) -> list[dict[str, Any]]:
    """The topic's notes, in order, with whether an assistant added each one."""
    notes_file = folder / "notes.md"
    if not notes_file.is_file():
        return []
    out = []
    for line in notes_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith("- "):
            continue
        date, _, text = line[2:].partition(": ")
        if not text:
            date, text = "", line[2:]
        by = re.search(r"\(added by (.+?)\)$", text)
        out.append(
            {
                "index": len(out),
                "date": date,
                "text": text[: by.start()].rstrip() if by else text,
                "added_by": by.group(1) if by else None,
            }
        )
    return out

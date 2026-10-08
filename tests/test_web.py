import time

import pytest

pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

from conclave.web.app import create_app  # noqa: E402
from conclave.web.render import markdown  # noqa: E402
from conftest import KEY, PAGE_A, failure  # noqa: E402

HEADERS = {"X-Conclave": "1"}


@pytest.fixture
def client(workspace, openrouter):
    app = create_app(workspace.config, extra_hosts={"testserver"})
    with TestClient(app) as c:
        yield c


def _setup(client, workspace):
    r = client.post("/api/setup/store", json={"path": str(workspace.store)}, headers=HEADERS)
    assert r.status_code == 200, r.text
    r = client.post("/api/setup/key", json={"key": KEY}, headers=HEADERS)
    assert r.status_code == 200, r.text


def _ask(client, **body):
    r = client.post(
        "/api/ask",
        json={"question": "Why is the sky blue?", "topic": "sky", **body},
        headers=HEADERS,
    )
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    for _ in range(200):
        data = client.get(f"/api/jobs/{job}").json()
        if data["state"] != "running":
            return data
        time.sleep(0.02)
    raise AssertionError("the run did not finish")


def test_first_launch_needs_setup_then_the_wizard_completes_it(client, workspace):
    status = client.get("/api/status").json()
    assert status["setup_needed"] is True and status["has_config"] is False

    _setup(client, workspace)

    status = client.get("/api/status").json()
    assert status["setup_needed"] is False
    assert status["key"]["ends"] == KEY[-4:]
    assert status["store"] == str(workspace.store)
    assert (workspace.store / "topics").is_dir()
    assert KEY in (workspace.config.parent / ".env").read_text(encoding="utf-8")


def test_a_rejected_key_is_not_saved(client, workspace, openrouter):
    client.post("/api/setup/store", json={}, headers=HEADERS)
    openrouter.key_status = 401

    r = client.post("/api/setup/key", json={"key": "sk-or-bad"}, headers=HEADERS)

    assert r.status_code == 400
    assert "did not accept this key" in r.json()["error"]
    assert not (workspace.config.parent / ".env").exists()


def test_a_relative_store_path_is_refused(client):
    r = client.post("/api/setup/store", json={"path": "research"}, headers=HEADERS)
    assert r.status_code == 400 and "full path" in r.json()["error"]


def test_requests_from_other_sites_and_hosts_are_refused(workspace, openrouter):
    app = create_app(workspace.config)  # no test host allowed
    with TestClient(app, base_url="http://127.0.0.1:8765") as local:
        assert local.get("/api/status").status_code == 200
        assert local.post("/api/setup/store", json={}).status_code == 403  # no app header
        evil = local.post(
            "/api/setup/store", json={}, headers={**HEADERS, "Origin": "https://evil.example"}
        )
        assert evil.status_code == 403
        same = local.post(
            "/api/setup/store", json={}, headers={**HEADERS, "Origin": "http://127.0.0.1:8765"}
        )
        assert same.status_code == 200
    with TestClient(app, base_url="http://attacker.example") as rebound:
        assert rebound.get("/api/status").status_code == 403


def test_full_question_runs_with_live_progress_and_returns_the_page(client, workspace):
    _setup(client, workspace)

    data = _ask(client, full=True)

    assert data["state"] == "done", data
    kinds = [(e["type"], e.get("stage")) for e in data["events"]]
    for stage in ("research", "critique", "verify", "synthesis", "memory"):
        assert ("stage", stage) in kinds
    calls = [e for e in data["events"] if e["type"] == "call"]
    assert {e["state"] for e in calls} == {"started", "done"}
    result = data["result"]
    assert result["has_page"] is True
    assert "<h2>Sources</h2>" in result["html"]
    assert '<span class="label label-agreed-but-unchecked">' in result["html"]
    assert result["evidence"]["verified"] == 1
    assert result["changes"]


def test_quick_question_and_events_can_be_read_in_pieces(client, workspace):
    _setup(client, workspace)
    data = _ask(client)

    assert data["result"]["mode"] == "quick"
    assert "Answer from anthropic/claude-sonnet-5.5" in data["result"]["html"]
    job = client.get("/api/status").json()
    assert job["running"] is None


def test_refusals_come_back_before_anything_runs(client, workspace, openrouter):
    _setup(client, workspace)
    r = client.post("/api/ask", json={"question": "   "}, headers=HEADERS)
    assert r.status_code == 400 and "empty" in r.json()["error"]
    assert openrouter.chat_requests == []


def test_failed_run_reports_why(client, workspace, openrouter):
    _setup(client, workspace)
    openrouter.reply("anthropic/claude-sonnet-5.5", failure(401))

    data = _ask(client)

    assert data["state"] == "failed"
    assert "No model answered" in data["error"]


def test_topics_runs_notes_and_search(client, workspace):
    _setup(client, workspace)
    data = _ask(client, full=True)
    run = data["result"]["run"]

    topics = client.get("/api/topics").json()
    assert [t["name"] for t in topics] == ["sky"]

    topic = client.get("/api/topics/sky").json()
    assert topic["claims"][0]["id"] == "C1"
    assert topic["disputes"][0]["id"] == "D1"
    assert topic["runs"][0]["name"] == run

    added = client.post("/api/topics/sky/notes", json={"text": "Sunsets matter."}, headers=HEADERS)
    assert added.json()["notes"][0]["text"] == "Sunsets matter."
    found = client.get("/api/search", params={"q": "sunsets"}).json()
    assert found and found[0]["topic"] == "sky"
    removed = client.delete("/api/topics/sky/notes/0", headers=HEADERS)
    assert removed.json()["notes"] == []

    detail = client.get(f"/api/topics/sky/runs/{run}").json()
    assert detail["question"] == "Why is the sky blue?"
    assert len(detail["answers"]) == 3 and detail["answers"][0]["letter"] == "A"
    assert len(detail["critiques"]) == 3
    assert "Claim checks" in detail["verification_html"]
    assert detail["sources"][0]["url"] == PAGE_A
    assert detail["final_html"].startswith("<h1>")


def test_unknown_or_unsafe_names_are_not_found(client, workspace):
    _setup(client, workspace)
    for path in ("/api/topics/nope", "/api/topics/sky/runs/x", "/api/topics/sky/runs/.."):
        assert client.get(path).status_code == 404, path
    # A slash inside a name never reaches the API; the page itself is served instead.
    escaped = client.get("/api/topics/..%2F..")
    assert '"claims"' not in escaped.text


def test_spending_and_leaderboard(client, workspace):
    _setup(client, workspace)
    _ask(client, full=True)

    s = client.get("/api/spending").json()
    assert s["month"] == pytest.approx(0.031)
    assert s["runs"][0]["topic"] == "sky"
    assert s["months"][0]["runs"] == 1
    assert s["leaderboard"]


def test_settings_change_and_bad_values_are_refused(client, workspace):
    _setup(client, workspace)

    r = client.put(
        "/api/settings",
        json={"budget": {"monthly_usd": "20"}, "search": {"enabled": False}},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["budget"]["monthly_usd"] == 20.0
    assert r.json()["search"]["enabled"] is False

    bad = client.put("/api/settings", json={"budget": {"monthly_usd": "0"}}, headers=HEADERS)
    assert bad.status_code == 400
    sneaky = client.put("/api/settings", json={"store": {"path": "/"}}, headers=HEADERS)
    assert sneaky.status_code == 400 and "cannot be changed here" in sneaky.json()["error"]


def test_councils_are_built_from_the_live_model_list(client, workspace):
    _setup(client, workspace)
    models = client.get("/api/models").json()
    assert any(m["id"] == "openai/gpt-6.1-sol" and m["completion"] == 10.0 for m in models)

    body = {
        "name": "mine",
        "members": ["google/gemini-3.8-flash", "deepseek/deepseek-v4.1-flash"],
        "chairman": "openai/gpt-6.1-sol",
    }
    r = client.post("/api/councils", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    mine = next(p for p in r.json()["profiles"] if p["name"] == "mine")
    assert mine["checker"] == "openai/gpt-6.1-sol"

    unknown = client.post(
        "/api/councils", json={**body, "name": "x", "chairman": "nobody/model"}, headers=HEADERS
    )
    assert (
        unknown.status_code == 400 and "not in OpenRouter's model list" in unknown.json()["error"]
    )

    assert client.delete("/api/councils/mine", headers=HEADERS).status_code == 200
    assert client.delete("/api/councils/balanced", headers=HEADERS).status_code == 400


def test_the_page_and_its_files_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "<title>Conclave</title>" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.css").status_code == 200


def test_model_text_cannot_inject_html_or_scripts():
    html = markdown("<script>alert(1)</script> [x](javascript:alert(1)) [ok](https://a.example)")

    assert "<script>" not in html
    assert "javascript:" not in html.split("&lt;")[0]
    assert 'href="https://a.example" target="_blank" rel="noopener noreferrer"' in html


def test_pages_get_a_strict_content_security_policy(client):
    policy = client.get("/").headers["content-security-policy"]
    assert "default-src 'self'" in policy and "script-src 'self'" in policy
    assert "img-src 'self' data:" in policy
    assert client.get("/api/status").headers["x-content-type-options"] == "nosniff"


def test_limits_must_be_real_amounts(client, workspace):
    _setup(client, workspace)
    for bad in ("nan", "inf", "1e400", "-1"):
        r = client.put("/api/settings", json={"budget": {"monthly_usd": bad}}, headers=HEADERS)
        assert r.status_code == 400, bad
    assert client.get("/api/status").status_code == 200


def test_odd_progress_offsets_do_not_break_polling(client, workspace):
    _setup(client, workspace)
    job = client.post("/api/ask", json={"question": "Q?"}, headers=HEADERS).json()["job"]
    for since in ("abc", "-5"):
        assert client.get(f"/api/jobs/{job}", params={"since": since}).status_code == 200


def test_the_app_will_not_close_while_a_question_runs(client, workspace):
    _setup(client, workspace)
    app = client.app
    from conclave.web.app import Job

    app.state.jobs["x"] = Job(id="x", question="Q", topic="t", mode="quick", profile="p")
    blocked = client.post("/api/quit", json={}, headers=HEADERS)
    assert blocked.status_code == 409 and "still running" in blocked.json()["error"]
    assert client.post("/api/quit", json={"force": True}, headers=HEADERS).status_code == 200


def test_saving_a_key_warns_when_another_key_wins(client, workspace, monkeypatch):
    client.post("/api/setup/store", json={}, headers=HEADERS)
    (workspace.cwd / ".env").write_text("OPENROUTER_API_KEY=sk-or-old-9999\n", encoding="utf-8")

    r = client.post("/api/setup/key", json={"key": KEY}, headers=HEADERS).json()

    assert r["other_key_in_use"]["ends"] == "9999"


def test_images_in_model_output_are_not_loaded_and_labels_stay_out_of_attributes():
    html = markdown(
        '![x](https://evil.example/c?d=1) [y](https://a.example "[verified]") `[disputed]`'
    )

    assert "<img" not in html
    assert 'title="[verified]"' in html
    assert "<code>[disputed]</code>" in html


def test_a_trusted_forwarded_address_works_and_others_do_not(workspace, openrouter):
    forwarded = "fuzzy-space-abc-8765.app.github.dev"
    app = create_app(workspace.config, extra_hosts={forwarded})
    with TestClient(app, base_url=f"https://{forwarded}") as remote:
        assert remote.get("/api/status").status_code == 200
        ok = remote.post(
            "/api/setup/store", json={}, headers={**HEADERS, "Origin": f"https://{forwarded}"}
        )
        assert ok.status_code == 200
    # GitHub's proxy may present the request as local while the page's origin is forwarded.
    with TestClient(app, base_url="http://localhost:8765") as proxied:
        ok = proxied.post(
            "/api/setup/store", json={}, headers={**HEADERS, "Origin": f"https://{forwarded}"}
        )
        assert ok.status_code == 200
        evil = proxied.post(
            "/api/setup/store",
            json={},
            headers={**HEADERS, "Origin": "https://other-8765.app.github.dev"},
        )
        assert evil.status_code == 403

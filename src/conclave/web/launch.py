"""Start the app: serve it on this computer only, and open it in the browser."""

from __future__ import annotations

import os
import socket
import threading
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from conclave.web.app import create_app

FIRST_PORT = 8765
LAST_PORT = 8785


def _running_at(port: int) -> bool:
    """Whether a Conclave app already answers on this port."""
    try:
        reply = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=1.5)
        return reply.status_code == 200 and "setup_needed" in reply.json()
    except (httpx.HTTPError, ValueError):
        return False


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def codespace_hosts(port: int) -> set[str]:
    """In a GitHub Codespace, the one web address GitHub forwards to this port.

    GitHub sets CODESPACE_NAME and the forwarding domain inside every Codespace, and
    the address is private to the Codespace's owner unless they choose to share it.
    Outside a Codespace this is empty, so only this computer is trusted.
    """
    name = os.environ.get("CODESPACE_NAME", "").strip()
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "").strip()
    if not name or not domain:
        return set()
    return {f"{name}-{port}.{domain}"}


def launch(config_path: Path | None = None, port: int | None = None, browser: bool = True) -> str:
    """Run the app until it is closed. Returns a message if it did not need to start."""
    ports = [port] if port else list(range(FIRST_PORT, LAST_PORT + 1))
    for candidate in ports:
        if _running_at(candidate):
            url = f"http://127.0.0.1:{candidate}/"
            if browser:
                webbrowser.open(url)
            return f"Conclave is already running at {url} and has been opened in your browser."
    chosen = next((p for p in ports if _free(p)), None)
    if chosen is None:
        raise OSError(f"No free port between {ports[0]} and {ports[-1]}.")

    url = f"http://127.0.0.1:{chosen}/"
    server: uvicorn.Server | None = None

    def stop() -> None:
        if server is not None:
            server.should_exit = True

    trusted = codespace_hosts(chosen)
    app = create_app(config_path, on_quit=stop, extra_hosts=trusted or None)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=chosen, log_level="warning", access_log=False)
    )
    if trusted:
        url = f"https://{next(iter(trusted))}/"
        browser = False  # the Codespace opens the forwarded page itself
    print(f"Conclave is running at {url}")
    print("Keep this window open while you use it. Close it, or press Ctrl+C, to stop Conclave.")
    if browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    server.run()
    return "Conclave has stopped."

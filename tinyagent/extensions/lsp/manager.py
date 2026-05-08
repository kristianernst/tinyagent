"""Lazy LSP client manager."""

from __future__ import annotations

from pathlib import Path

from tinyagent.extensions.lsp.client import LspClient
from tinyagent.extensions.lsp.config import LspConfig, LspServerConfig


class LspManager:
    def __init__(self, *, config: LspConfig | None = None, clients: dict[str, LspClient] | None = None) -> None:
        self.config = config or LspConfig()
        self.clients = dict(clients or {})
        self.started: list[str] = []

    def server_for_path(self, path: str | Path | None) -> LspServerConfig | None:
        if not self.config.enabled or path is None:
            return None
        suffix = Path(path).suffix
        for server in self.config.servers:
            if not server.disabled and suffix in server.extensions:
                return server
        return None

    def ensure_started(self, server_name: str) -> LspClient | None:
        client = self.clients.get(server_name)
        if client is not None and server_name not in self.started:
            self.started.append(server_name)
        return client

    def client_for_path(self, path: str | Path | None) -> LspClient | None:
        server = self.server_for_path(path)
        return self.ensure_started(server.name) if server is not None else None

    def first_client(self) -> LspClient | None:
        for client in self.clients_for_workspace():
            return client
        return None

    def clients_for_workspace(self) -> list[LspClient]:
        if not self.config.enabled:
            return []
        clients: list[LspClient] = []
        for server in self.config.servers:
            if server.disabled:
                continue
            client = self.ensure_started(server.name)
            if client is not None:
                clients.append(client)
        return clients

    def shutdown_idle(self) -> None:
        return None

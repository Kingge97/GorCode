"""
LSP Manager
===========

Dispatch LSP notifications to registered clients.
"""

from __future__ import annotations

from typing import List, Optional, Protocol


class LspClient(Protocol):
    def did_change(self, file_path: str, content: str) -> None:
        ...

    def did_save(self, file_path: str) -> None:
        ...

    def clear_diagnostics(self, file_path: str) -> None:
        ...


class LspManager:
    def __init__(self) -> None:
        self._clients: List[LspClient] = []

    def register(self, client: LspClient) -> None:
        if client not in self._clients:
            self._clients.append(client)

    def unregister(self, client: LspClient) -> None:
        if client in self._clients:
            self._clients.remove(client)

    def notify_did_change(self, file_path: str, content: str) -> bool:
        return self._notify("did_change", file_path, content)

    def notify_did_save(self, file_path: str) -> bool:
        return self._notify("did_save", file_path, None)

    def clear_diagnostics(self, file_path: str) -> bool:
        return self._notify("clear_diagnostics", file_path, None)

    def _notify(self, method: str, file_path: str, content: Optional[str]) -> bool:
        notified = False
        for client in list(self._clients):
            handler = getattr(client, method, None)
            if not callable(handler):
                continue
            if content is None:
                handler(file_path)
            else:
                handler(file_path, content)
            notified = True
        return notified

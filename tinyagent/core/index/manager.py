"""Workspace index manager."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tinyagent.app.product import ProductHome, workspace_id_for
from tinyagent.core.index.rg import RgWorkspaceIndex
from tinyagent.core.index.types import IndexHit, IndexMode, IndexStatus, SyncMode, SyncResult, WorkspaceIndex


class WorkspaceIndexManager:
    def __init__(self, *, index: WorkspaceIndex | None = None, index_root: Path | None = None) -> None:
        self.index = index or RgWorkspaceIndex()
        self.index_root = index_root

    @classmethod
    def for_workspace(cls, root: Path, *, home: ProductHome | None = None) -> WorkspaceIndexManager:
        product_home = home or ProductHome.from_env()
        workspace_id = workspace_id_for(str(root.expanduser().resolve()))
        return cls.for_workspace_id(workspace_id, home=product_home)

    @classmethod
    def for_workspace_id(cls, workspace_id: str, *, home: ProductHome | None = None) -> WorkspaceIndexManager:
        product_home = home or ProductHome.from_env()
        index_root = product_home.workspaces_dir / workspace_id / "search"
        index_root.mkdir(parents=True, exist_ok=True)
        return cls(index=RgWorkspaceIndex(), index_root=index_root)

    def status(self) -> IndexStatus:
        return self.index.status()

    def sync(self, *, root: Path, paths: Sequence[str] | None = None, mode: SyncMode = "fast") -> SyncResult:
        if self.index_root is not None:
            self.index_root.mkdir(parents=True, exist_ok=True)
        return self.index.sync(root=root, paths=paths, mode=mode)

    def search(
        self,
        query: str,
        *,
        root: Path,
        path: str | None = None,
        kind: str | None = None,
        mode: IndexMode = "auto",
        limit: int = 10,
        explain: bool = False,
    ) -> Sequence[IndexHit]:
        return self.index.search(query, root=root, path=path, kind=kind, mode=mode, limit=limit, explain=explain)

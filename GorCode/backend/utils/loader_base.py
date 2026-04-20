"""
Shared loader base classes for agents and skills.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generic, List, Optional, TypeVar, Union

from .search_paths import ResolvedSearchPath, add_search_path

T = TypeVar("T")


@dataclass(frozen=True)
class DiscoveredItem:
    """Represents a discoverable loader item."""

    name: str
    path: Optional[Path] = None


class LoaderBase(Generic[T]):
    """
    Base class providing common loader flow:
    discover -> load -> get/reload/unload -> load_all
    """

    def __init__(self, encoding: str = "utf-8"):
        self.encoding = encoding
        self._items: Dict[str, T] = {}
        self._search_paths: List[Path] = []

    def _add_search_path(
        self,
        path: Union[str, Path],
        *,
        allow_redirect: bool = False,
        allow_symlink: bool = False,
    ) -> Optional[ResolvedSearchPath]:
        return add_search_path(
            self._search_paths,
            path,
            encoding=self.encoding,
            allow_redirect=allow_redirect,
            allow_symlink=allow_symlink,
        )

    def _discover_items(self) -> List[DiscoveredItem]:
        raise NotImplementedError

    def _load_item(self, name: str, path: Optional[Path]) -> Optional[T]:
        raise NotImplementedError

    def _is_loaded(self, item: DiscoveredItem) -> bool:
        return item.name in self._items

    def _get_reload_path(self, name: str) -> Optional[Path]:
        return None

    def _on_unload(self, name: str) -> None:
        pass

    def _load_all(self) -> Dict[str, T]:
        for item in self._discover_items():
            if not self._is_loaded(item):
                self._load_item(item.name, item.path)
        return self._items

    def _get_item(self, name: str) -> Optional[T]:
        return self._items.get(name)

    def _get_all_items(self) -> Dict[str, T]:
        return self._items

    def _reload_item(self, name: str) -> Optional[T]:
        if name in self._items:
            path = self._get_reload_path(name)
            del self._items[name]
            return self._load_item(name, path)
        return None

    def _unload_item(self, name: str) -> bool:
        if name in self._items:
            del self._items[name]
            self._on_unload(name)
            return True
        return False

    def load_all(self) -> Dict[str, T]:
        """Load all discovered items."""
        return self._load_all()

    def get_item(self, name: str) -> Optional[T]:
        """Get a loaded item by name."""
        return self._get_item(name)

    def get_all_items(self) -> Dict[str, T]:
        """Get all loaded items."""
        return self._get_all_items()

    def reload_item(self, name: str) -> Optional[T]:
        """Reload an item from disk."""
        return self._reload_item(name)

    def unload_item(self, name: str) -> bool:
        """Unload an item."""
        return self._unload_item(name)

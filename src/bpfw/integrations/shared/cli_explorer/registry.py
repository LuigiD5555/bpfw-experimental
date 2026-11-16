"""Explicit source registry: switch project/data without global state or plugins.

Each open builds a *fresh* source; no selections, credentials, caches or cursors
are shared across projects. The core never chooses or knows an adapter kind.
"""
from __future__ import annotations

from typing import Any, Callable
from .models import ExplorerAdapter


class ExplorerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., ExplorerAdapter]] = {}

    def register(self, kind: str, factory: Callable[..., ExplorerAdapter]) -> None:
        if not kind or kind in self._factories:
            raise ValueError('Adapter name must be nonempty and unique')
        self._factories[kind] = factory

    def create(self, kind: str, **settings: Any) -> ExplorerAdapter:
        if kind not in self._factories:
            raise ValueError('Unknown adapter: ' + kind)
        adapter = self._factories[kind](**settings)
        if not adapter.identity:
            raise ValueError('Adapter did not provide a source identity')
        return adapter

    def available(self) -> tuple[str, ...]:
        return tuple(self._factories)

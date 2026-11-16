"""Portable, project-neutral text CLI browsing engine. No TUI runtime."""
from .models import ExplorerAdapter, ExplorerQuery, ExplorerPage
from .controller import BrowserController
from .registry import ExplorerRegistry

__all__ = ['ExplorerAdapter','ExplorerQuery','ExplorerPage','BrowserController','ExplorerRegistry']

"""Connector package with lazy imports to avoid heavy dependencies during tests."""

from importlib import import_module
from typing import TYPE_CHECKING

from .base import ConnectorBase

__all__ = ["ConnectorBase", "DriftConnector", "HyperliquidConnector"]


def __getattr__(name: str):
    if name in {"DriftConnector", "HyperliquidConnector"}:
        module_name = ".drift_connector" if name == "DriftConnector" else ".hyperliquid_connector"
        try:
            module = import_module(module_name, __name__)
            return getattr(module, name)
        except Exception:  # pragma: no cover - missing deps during tests
            class _Missing:  # pylint: disable=too-few-public-methods
                def __init__(self, *a, **kw):  # noqa: D401 - simple placeholder
                    """Placeholder when optional dependencies are absent."""
                    raise ImportError(f"{name} dependencies are not installed")

            return _Missing
    raise AttributeError(name)


if TYPE_CHECKING:  # pragma: no cover - used for type checkers only
    from .drift_connector import DriftConnector
    from .hyperliquid_connector import HyperliquidConnector

"""Contract strategies, keyed by name.

Importing this package registers every built-in contract. A game may still restrict which of them
are legal to bid through its :class:`~t42.engine.config.RuleConfig`.
"""

from __future__ import annotations

from . import nello, plunge, sevens, splash, standard  # noqa: F401  (registers the contracts)
from .base import Contract
from .registry import available, get, get_enabled, register, validate_enabled

__all__ = [
    "Contract",
    "available",
    "get",
    "get_enabled",
    "register",
    "validate_enabled",
]

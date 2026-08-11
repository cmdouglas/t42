"""Name-keyed registry of contract strategies.

New contracts plug in by registering themselves; nothing in the engine switches on contract name
(DESIGN.md §5).
"""

from __future__ import annotations

from ..config import RuleConfig
from ..errors import UnknownContract
from .base import Contract

_REGISTRY: dict[str, Contract] = {}


def register(contract: Contract) -> Contract:
    """Register ``contract`` under its name. Returns it, so it can be used as a decorator."""
    if contract.name in _REGISTRY:
        raise ValueError(f"contract already registered: {contract.name!r}")
    _REGISTRY[contract.name] = contract
    return contract


def get(name: str) -> Contract:
    """Look up a registered contract. Raises :class:`UnknownContract` if there is none."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownContract(f"unknown contract: {name!r}") from None


def get_enabled(name: str, config: RuleConfig) -> Contract:
    """Look up a contract, rejecting one this game has not enabled."""
    contract = get(name)
    if not config.allows(name):
        raise UnknownContract(f"contract not enabled for this game: {name!r}")
    return contract


def available() -> tuple[str, ...]:
    """Every registered contract name, sorted."""
    return tuple(sorted(_REGISTRY))


def validate_enabled(config: RuleConfig) -> None:
    """Check every contract named in ``config`` exists. Call this at game creation."""
    for name in sorted(config.enabled_contracts):
        get(name)

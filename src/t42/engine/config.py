"""Per-game rule configuration (DESIGN.md §4.1, §5).

Rule variants are per-game data set at creation, never global constants, so that games created
under different variants replay and score correctly side by side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

STANDARD_CONTRACT: Final = "standard"

DEFAULT_CONTRACTS: Final[frozenset[str]] = frozenset(
    {STANDARD_CONTRACT, "nello", "plunge", "sevens"}
)

DEFAULT_MARKS_TO_WIN: Final = 7


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """Rule variants chosen when the game is created.

    Contract names are validated against the registry by
    :func:`t42.engine.contracts.registry.validate_enabled`; this type stays dependency-free.
    """

    enabled_contracts: frozenset[str] = DEFAULT_CONTRACTS
    doubles_are_own_suit: bool = False
    marks_to_win: int = DEFAULT_MARKS_TO_WIN

    def __post_init__(self) -> None:
        if self.marks_to_win < 1:
            raise ValueError(f"marks_to_win must be positive, got {self.marks_to_win}")
        if STANDARD_CONTRACT not in self.enabled_contracts:
            raise ValueError(f"the {STANDARD_CONTRACT!r} contract cannot be disabled")

    def allows(self, contract: str) -> bool:
        return contract in self.enabled_contracts

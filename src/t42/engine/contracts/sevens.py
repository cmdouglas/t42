"""Sevens: no trump; the tile closest to seven pips wins the trick, ties to the leader.

Declarer's side must take all seven tricks. Scoring variant still to be pinned down
(DESIGN.md §12).
"""

from __future__ import annotations

from ._unimplemented import UnimplementedContract
from .registry import register


class SevensContract(UnimplementedContract):
    name = "sevens"


register(SevensContract())

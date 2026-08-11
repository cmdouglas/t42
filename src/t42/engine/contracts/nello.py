"""Nello: the declarer's partner sits out and the declarer must lose every trick.

Open questions to settle before implementing: doubles handling under nello (own suit, high or
low) is a per-game variant in some rule sets - see DESIGN.md §12.
"""

from __future__ import annotations

from ._unimplemented import UnimplementedContract
from .registry import register


class NelloContract(UnimplementedContract):
    name = "nello"


register(NelloContract())

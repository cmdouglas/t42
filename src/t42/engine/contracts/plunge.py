"""Plunge: bid 4+ marks holding at least four doubles; the partner names trump and leads.

Exact mark minimum and scoring variant still to be pinned down (DESIGN.md §12).
"""

from __future__ import annotations

from ._unimplemented import UnimplementedContract
from .registry import register


class PlungeContract(UnimplementedContract):
    name = "plunge"


register(PlungeContract())

"""Plunge: bid 4+ marks holding at least 4 of the 7 doubles; the bidder's partner must explicitly
agree before the bid goes live, then names trump and leads (DESIGN.md §12).
"""

from __future__ import annotations

from ._partner_declares_common import PartnerDeclaresBase
from .registry import register


class PlungeContract(PartnerDeclaresBase):
    name = "plunge"
    _minimum_doubles = 4
    _minimum_marks = 4
    _requires_confirmation = True


register(PlungeContract())

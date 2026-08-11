"""Splash: like plunge with a higher double requirement; the partner names trump and leads.

Off by default in :data:`~t42.engine.config.DEFAULT_CONTRACTS` until its scoring variant is
settled (DESIGN.md §12), but registered so a game can enable it.
"""

from __future__ import annotations

from ._unimplemented import UnimplementedContract
from .registry import register


class SplashContract(UnimplementedContract):
    name = "splash"


register(SplashContract())

"""Standard point contract: bid 30-42, name trump, take at least the bid.

Also reachable as a mark bid (1 mark = 42, 2 marks = 84, ...).
"""

from __future__ import annotations

from ._unimplemented import UnimplementedContract
from .registry import register


class StandardContract(UnimplementedContract):
    name = "standard"


register(StandardContract())

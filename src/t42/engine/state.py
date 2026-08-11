"""Game state data shapes.

Everything here is a frozen dataclass: the engine returns new state rather than mutating, so a
state can be replayed, cached and compared safely (DESIGN.md §4.1). Behaviour lives in
:mod:`t42.engine.bidding`, :mod:`t42.engine.tricks` and the contract strategies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from .config import RuleConfig
from .dominoes import Domino
from .suits import Trump

type PlayerId = str
type GameId = str


class Seat(IntEnum):
    """Seats clockwise. Partners sit across from each other: 0+2 play 1+3."""

    NORTH = 0
    EAST = 1
    SOUTH = 2
    WEST = 3


class Team(IntEnum):
    NORTH_SOUTH = 0
    EAST_WEST = 1


class Phase(StrEnum):
    BIDDING = "BIDDING"
    DECLARING = "DECLARING"
    PLAYING = "PLAYING"
    HAND_COMPLETE = "HAND_COMPLETE"
    GAME_OVER = "GAME_OVER"


def team_of(seat: Seat) -> Team:
    return Team(seat % 2)


def partner_of(seat: Seat) -> Seat:
    return Seat((seat + 2) % 4)


@dataclass(frozen=True, slots=True)
class Bid:
    """One auction entry. A pass has neither ``points`` nor ``marks`` set.

    Exactly one of ``points`` (30-42) and ``marks`` (1+) is set on a live bid; ``contract`` names
    the contract being bid, so that mark bids carry which special contract they are for.
    """

    bidder: Seat
    contract: str | None = None
    points: int | None = None
    marks: int | None = None

    @property
    def is_pass(self) -> bool:
        return self.points is None and self.marks is None


@dataclass(frozen=True, slots=True)
class PlayedDomino:
    seat: Seat
    domino: Domino


@dataclass(frozen=True, slots=True)
class Trick:
    plays: tuple[PlayedDomino, ...] = ()
    winner: Seat | None = None

    @property
    def is_complete(self) -> bool:
        return len(self.plays) == len(Seat)


@dataclass(frozen=True, slots=True)
class HandState:
    """One hand: the deal, its auction, and the tricks played under the winning contract."""

    dealer: Seat
    hands: Mapping[Seat, tuple[Domino, ...]] = field(default_factory=dict)
    bids: tuple[Bid, ...] = ()
    declarer: Seat | None = None
    contract: str | None = None
    trump: Trump = None
    completed_tricks: tuple[Trick, ...] = ()
    current_trick: Trick = Trick()


@dataclass(frozen=True, slots=True)
class GameState:
    """Full server-side state, including every hand. Never sent to a client as-is - see
    :func:`t42.engine.projection.project`."""

    game_id: GameId
    config: RuleConfig
    players: Mapping[Seat, PlayerId]
    phase: Phase = Phase.BIDDING
    marks: Mapping[Team, int] = field(default_factory=dict)
    hand: HandState | None = None
    to_act: Seat | None = None

from __future__ import annotations

import dataclasses

import pytest

from t42.engine.config import DEFAULT_MARKS_TO_WIN, RuleConfig


def test_defaults_match_the_design() -> None:
    config = RuleConfig()
    assert config.marks_to_win == DEFAULT_MARKS_TO_WIN == 7
    assert not config.doubles_are_own_suit
    assert config.enabled_contracts == frozenset({"standard", "nello", "plunge", "sevens"})


def test_allows_reports_enabled_contracts() -> None:
    config = RuleConfig(enabled_contracts=frozenset({"standard", "nello"}))
    assert config.allows("nello")
    assert not config.allows("sevens")


def test_config_is_immutable() -> None:
    config = RuleConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.marks_to_win = 3  # type: ignore[misc]


@pytest.mark.parametrize("marks", [0, -1])
def test_marks_to_win_must_be_positive(marks: int) -> None:
    with pytest.raises(ValueError, match="marks_to_win must be positive"):
        RuleConfig(marks_to_win=marks)


def test_the_standard_contract_cannot_be_disabled() -> None:
    with pytest.raises(ValueError, match="cannot be disabled"):
        RuleConfig(enabled_contracts=frozenset({"nello"}))

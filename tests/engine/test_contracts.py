from __future__ import annotations

import pytest

from t42.engine import contracts
from t42.engine.config import RuleConfig
from t42.engine.errors import UnknownContract


def test_every_designed_contract_is_registered() -> None:
    assert contracts.available() == (
        "nello",
        "nello_low",
        "plunge",
        "sevens",
        "splash",
        "standard",
    )


@pytest.mark.parametrize("name", contracts.available())
def test_registered_contracts_satisfy_the_contract_protocol(name: str) -> None:
    contract = contracts.get(name)
    assert contract.name == name
    assert isinstance(contract, contracts.Contract)


def test_unknown_contracts_are_rejected() -> None:
    with pytest.raises(UnknownContract, match="unknown contract"):
        contracts.get("moonshine")


def test_a_contract_disabled_for_the_game_is_rejected() -> None:
    config = RuleConfig()  # splash is off by default
    assert contracts.get_enabled("nello", config).name == "nello"
    with pytest.raises(UnknownContract, match="not enabled"):
        contracts.get_enabled("splash", config)


def test_default_config_names_only_known_contracts() -> None:
    contracts.validate_enabled(RuleConfig())
    contracts.validate_enabled(RuleConfig(enabled_contracts=frozenset({"standard", "splash"})))


def test_validate_enabled_rejects_a_typo_at_game_creation() -> None:
    with pytest.raises(UnknownContract, match="nelo"):
        contracts.validate_enabled(RuleConfig(enabled_contracts=frozenset({"standard", "nelo"})))


def test_registering_a_duplicate_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="already registered"):
        contracts.register(contracts.get("standard"))

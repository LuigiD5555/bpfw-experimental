from __future__ import annotations

import pytest

from bpfw.cli import normalize_command


def test_scan_maps_to_discover() -> None:
    assert normalize_command("scan", None, None, None) == "discover"


def test_proposal_show_command_maps_with_target() -> None:
    assert normalize_command("proposal", "show", "proposal-001", None) == "show_proposal"


def test_proposal_accept_command_maps_with_target() -> None:
    assert normalize_command("proposal", "accept", "proposal-001", None) == "accept_proposal"


def test_proposal_reject_command_maps_with_target() -> None:
    assert normalize_command("proposal", "reject", "proposal-001", None) == "reject_proposal"


def test_proposal_command_requires_valid_subcommand() -> None:
    with pytest.raises(ValueError, match="proposal command requires subcommand"):
        normalize_command("proposal", "list", None, None)


def test_proposal_command_requires_proposal_id() -> None:
    with pytest.raises(ValueError, match="proposal show requires a proposal_id"):
        normalize_command("proposal", "show", None, None)


def test_legacy_proposal_commands_still_work() -> None:
    assert normalize_command("show-proposal", "proposal-001", None, None) == "show_proposal"
    assert normalize_command("accept-proposal", "proposal-001", None, None) == "accept_proposal"
    assert normalize_command("reject-proposal", "proposal-001", None, None) == "reject_proposal"

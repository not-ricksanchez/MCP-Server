"""Unit tests for plain logic functions (no MCP protocol)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from server import logic
from server.logic import (
    check_request_eligibility,
    flag_for_human_review,
    get_employee_info,
    get_policy_limits,
)

AS_OF = date(2026, 10, 2)


def test_get_employee_info_known() -> None:
    info = get_employee_info("E001")
    assert info["found"] is True
    assert info["role"] == "standard"
    assert info["name"] == "Avery Chen"
    items = {row["item"] for row in info["equipment"]}
    assert "laptop" in items


def test_get_employee_info_unknown() -> None:
    info = get_employee_info("E999")
    assert info["found"] is False
    assert info["error"] == "unknown_employee"


def test_get_policy_limits_standard_vs_manager() -> None:
    standard = get_policy_limits("standard")
    manager = get_policy_limits("manager")
    assert standard["found"] is True
    assert manager["found"] is True
    assert standard["rules"]["laptop"]["interval_years"] == 4
    assert manager["rules"]["laptop"]["interval_years"] == 2
    assert standard["rules"]["monitor"]["max_count"] == 1
    assert manager["rules"]["monitor"]["max_count"] == 2


def test_get_policy_limits_unknown_role() -> None:
    result = get_policy_limits("executive")
    assert result["found"] is False
    assert result["error"] == "unknown_role"


@pytest.mark.parametrize(
    ("employee_id", "item", "status", "reason"),
    [
        ("E001", "laptop", "eligible", "refresh_interval_met"),
        ("E002", "monitor", "ineligible", "refresh_interval_not_met"),
        ("E003", "laptop", "eligible", "refresh_interval_met"),
        ("E004", "laptop", "ineligible", "role_not_eligible_for_item"),
        ("E004", "keyboard", "eligible", "below_max_count"),
        ("E005", "laptop", "unknown", "contractor_role"),
        ("E006", "monitor", "unknown", "missing_issue_date"),
        ("E009", "monitor", "ineligible", "refresh_interval_not_met"),
        ("E010", "monitor", "eligible", "below_max_count"),
        ("E014", "laptop", "eligible", "below_max_count"),
        ("E001", "standing desk", "unknown", "unknown_item"),
        ("E999", "laptop", "unknown", "unknown_employee"),
    ],
)
def test_check_request_eligibility_paths(
    employee_id: str, item: str, status: str, reason: str
) -> None:
    result = check_request_eligibility(employee_id, item, as_of=AS_OF)
    assert result["status"] == status
    assert result["reason"] == reason


def test_flag_for_human_review_writes_ticket(tmp_path, monkeypatch) -> None:
    ticket_path = tmp_path / "escalations.jsonl"
    monkeypatch.setattr(logic, "ESCALATIONS_PATH", ticket_path)

    ticket = flag_for_human_review("E005", "I need a laptop", "contractor_role")
    assert ticket["escalated"] is True
    assert ticket["employee_id"] == "E005"
    assert ticket["ticket_id"].startswith("ESC-")
    assert ticket_path.exists()
    stored = json.loads(ticket_path.read_text(encoding="utf-8").strip())
    assert stored["ticket_id"] == ticket["ticket_id"]
    assert stored["reason"] == "contractor_role"


def test_flag_for_human_review_empty_reason_still_records(tmp_path, monkeypatch) -> None:
    ticket_path = tmp_path / "escalations.jsonl"
    monkeypatch.setattr(logic, "ESCALATIONS_PATH", ticket_path)

    ticket = flag_for_human_review("E006", "replace my monitor", "")
    assert ticket["reason"] == ""
    stored = json.loads(ticket_path.read_text(encoding="utf-8").strip())
    assert stored["employee_id"] == "E006"
    assert "ticket_id" in stored

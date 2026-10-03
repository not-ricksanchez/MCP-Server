"""Unit tests for plain logic functions (no MCP protocol)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from server import logic
from server.logic import (
    CATALOG,
    check_request_eligibility,
    flag_for_human_review,
    get_employee_info,
    get_policy_limits,
)

AS_OF = date(2026, 10, 2)

STANDARD_POLICY = {
    "always_escalate": False,
    "laptop": {"eligible": True, "max_count": 1, "interval_years": 4},
    "monitor": {"eligible": True, "max_count": 1, "interval_years": 3},
}
MANAGER_POLICY = {
    "always_escalate": False,
    "monitor": {"eligible": True, "max_count": 2, "interval_years": 3},
}


@pytest.fixture
def custom_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point logic at throwaway employee/policy files for edge cases the seed data lacks."""

    def install(employees: list[dict[str, Any]], policies: dict[str, Any]) -> None:
        employees_path = tmp_path / "employees.json"
        policies_path = tmp_path / "policies.json"
        employees_path.write_text(json.dumps(employees), encoding="utf-8")
        policies_path.write_text(json.dumps(policies), encoding="utf-8")
        monkeypatch.setattr(logic, "EMPLOYEES_PATH", employees_path)
        monkeypatch.setattr(logic, "POLICIES_PATH", policies_path)

    return install


@pytest.fixture
def ticket_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "escalations.jsonl"
    monkeypatch.setattr(logic, "ESCALATIONS_PATH", path)
    return path


def _employee(employee_id: str, role: str, equipment: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "employee_id": employee_id,
        "name": "Test Person",
        "role": role,
        "tenure_years": 1.0,
        "equipment": equipment,
    }


# --- get_employee_info -------------------------------------------------------


def test_get_employee_info_known() -> None:
    info = get_employee_info("E001")
    assert info["found"] is True
    assert info["role"] == "standard"
    assert info["name"] == "Avery Chen"
    assert info["tenure_years"] == 6.0
    items = {row["item"] for row in info["equipment"]}
    assert items == {"laptop", "monitor"}


@pytest.mark.parametrize(
    ("employee_id", "role"),
    [
        ("E001", "standard"),
        ("E002", "standard"),
        ("E003", "manager"),
        ("E004", "intern"),
        ("E005", "contractor"),
        ("E006", "standard"),
        ("E007", "intern"),
        ("E008", "intern"),
        ("E009", "manager"),
        ("E010", "manager"),
        ("E011", "standard"),
        ("E012", "standard"),
        ("E013", "standard"),
        ("E014", "standard"),
        ("E015", "manager"),
    ],
)
def test_get_employee_info_seed_roles_match_requirements(employee_id: str, role: str) -> None:
    info = get_employee_info(employee_id)
    assert info["found"] is True
    assert info["role"] == role


def test_get_employee_info_no_equipment_returns_empty_list() -> None:
    info = get_employee_info("E004")
    assert info["found"] is True
    assert info["equipment"] == []


def test_get_employee_info_preserves_missing_issue_date() -> None:
    info = get_employee_info("E006")
    monitor = next(row for row in info["equipment"] if row["item"] == "monitor")
    assert monitor["issued_on"] is None


def test_get_employee_info_missing_equipment_key_defaults_to_empty(custom_data) -> None:
    row = _employee("T001", "standard", [])
    del row["equipment"]
    custom_data([row], {"standard": STANDARD_POLICY})
    assert get_employee_info("T001")["equipment"] == []


@pytest.mark.parametrize("employee_id", ["E999", "", "e001", " E001"])
def test_get_employee_info_unknown(employee_id: str) -> None:
    info = get_employee_info(employee_id)
    assert info["found"] is False
    assert info["error"] == "unknown_employee"
    assert info["employee_id"] == employee_id


# --- get_policy_limits -------------------------------------------------------


def test_get_policy_limits_standard_vs_manager() -> None:
    standard = get_policy_limits("standard")
    manager = get_policy_limits("manager")
    assert standard["found"] is True
    assert manager["found"] is True
    assert standard["rules"]["laptop"]["interval_years"] == 4
    assert manager["rules"]["laptop"]["interval_years"] == 2
    assert standard["rules"]["monitor"]["max_count"] == 1
    assert manager["rules"]["monitor"]["max_count"] == 2
    for peripheral in ("keyboard", "mouse", "headset"):
        assert standard["rules"][peripheral]["interval_years"] == 2
        assert manager["rules"][peripheral]["interval_years"] == 0


def test_get_policy_limits_intern() -> None:
    intern = get_policy_limits("intern")
    assert intern["found"] is True
    assert intern["always_escalate"] is False
    assert intern["rules"]["laptop"]["eligible"] is False
    assert intern["rules"]["monitor"]["eligible"] is False
    for peripheral in ("keyboard", "mouse", "headset"):
        assert intern["rules"][peripheral] == {"eligible": True, "max_count": 1, "interval_years": 0}


def test_get_policy_limits_contractor_always_escalates() -> None:
    contractor = get_policy_limits("contractor")
    assert contractor["found"] is True
    assert contractor["always_escalate"] is True
    assert all(rule["eligible"] is False for rule in contractor["rules"].values())


@pytest.mark.parametrize("role", ["intern", "standard", "manager", "contractor"])
def test_get_policy_limits_covers_whole_catalog(role: str) -> None:
    assert set(get_policy_limits(role)["rules"]) == CATALOG


def test_get_policy_limits_ignores_non_catalog_items(custom_data) -> None:
    policy = {**STANDARD_POLICY, "tablet": {"eligible": True, "max_count": 1, "interval_years": 1}}
    custom_data([], {"standard": policy})
    rules = get_policy_limits("standard")["rules"]
    assert "tablet" not in rules
    assert set(rules) == {"laptop", "monitor"}


def test_get_policy_limits_returns_copies(custom_data) -> None:
    custom_data([], {"standard": STANDARD_POLICY})
    first = get_policy_limits("standard")
    first["rules"]["laptop"]["interval_years"] = 99
    assert get_policy_limits("standard")["rules"]["laptop"]["interval_years"] == 4


@pytest.mark.parametrize("role", ["executive", "", "Manager", "STANDARD"])
def test_get_policy_limits_unknown_role(role: str) -> None:
    result = get_policy_limits(role)
    assert result["found"] is False
    assert result["error"] == "unknown_role"
    assert result["role"] == role


# --- check_request_eligibility -----------------------------------------------


@pytest.mark.parametrize(
    ("employee_id", "item", "status", "reason"),
    [
        ("E001", "laptop", "eligible", "refresh_interval_met"),
        ("E002", "monitor", "ineligible", "refresh_interval_not_met"),
        ("E003", "laptop", "eligible", "refresh_interval_met"),
        ("E003", "keyboard", "eligible", "below_max_count"),
        ("E004", "laptop", "ineligible", "role_not_eligible_for_item"),
        ("E004", "monitor", "ineligible", "role_not_eligible_for_item"),
        ("E004", "keyboard", "eligible", "below_max_count"),
        ("E005", "laptop", "unknown", "contractor_role"),
        ("E005", "mouse", "unknown", "contractor_role"),
        ("E006", "monitor", "unknown", "missing_issue_date"),
        ("E007", "keyboard", "eligible", "replace_anytime"),
        ("E007", "mouse", "eligible", "below_max_count"),
        ("E007", "headset", "eligible", "below_max_count"),
        ("E008", "laptop", "ineligible", "role_not_eligible_for_item"),
        ("E008", "monitor", "ineligible", "role_not_eligible_for_item"),
        ("E008", "headset", "eligible", "replace_anytime"),
        ("E009", "monitor", "ineligible", "refresh_interval_not_met"),
        ("E010", "monitor", "eligible", "below_max_count"),
        ("E011", "laptop", "ineligible", "refresh_interval_not_met"),
        ("E012", "monitor", "eligible", "refresh_interval_met"),
        ("E013", "keyboard", "ineligible", "refresh_interval_not_met"),
        ("E014", "laptop", "eligible", "below_max_count"),
        ("E015", "laptop", "ineligible", "refresh_interval_not_met"),
        ("E001", "standing desk", "unknown", "unknown_item"),
        ("E999", "laptop", "unknown", "unknown_employee"),
    ],
)
def test_check_request_eligibility_seed_paths(
    employee_id: str, item: str, status: str, reason: str
) -> None:
    result = check_request_eligibility(employee_id, item, as_of=AS_OF)
    assert result["status"] == status
    assert result["reason"] == reason
    assert result["employee_id"] == employee_id


@pytest.mark.parametrize("item", ["  Laptop ", "LAPTOP", "laptop\n"])
def test_check_request_eligibility_normalizes_item(item: str) -> None:
    result = check_request_eligibility("E001", item, as_of=AS_OF)
    assert result["item"] == "laptop"
    assert result["status"] == "eligible"


@pytest.mark.parametrize("item", ["", "   ", "laptops", "tablet", "second laptop"])
def test_check_request_eligibility_non_catalog_item_is_unknown(item: str) -> None:
    result = check_request_eligibility("E001", item, as_of=AS_OF)
    assert result["status"] == "unknown"
    assert result["reason"] == "unknown_item"


def test_check_request_eligibility_checks_item_before_employee() -> None:
    result = check_request_eligibility("E999", "tablet", as_of=AS_OF)
    assert result["reason"] == "unknown_item"


def test_check_request_eligibility_refresh_boundary(custom_data) -> None:
    # 2020-01-01 to 2024-01-01 is 1461 days, exactly 4.0 years at 365.25 days/year.
    custom_data(
        [_employee("T001", "standard", [{"item": "laptop", "issued_on": "2020-01-01"}])],
        {"standard": STANDARD_POLICY},
    )
    on_boundary = check_request_eligibility("T001", "laptop", as_of=date(2024, 1, 1))
    day_before = check_request_eligibility("T001", "laptop", as_of=date(2023, 12, 31))
    assert on_boundary["status"] == "eligible"
    assert on_boundary["reason"] == "refresh_interval_met"
    assert day_before["status"] == "ineligible"
    assert day_before["reason"] == "refresh_interval_not_met"


def test_check_request_eligibility_unknown_role(custom_data) -> None:
    custom_data([_employee("T001", "executive", [])], {"standard": STANDARD_POLICY})
    result = check_request_eligibility("T001", "laptop", as_of=AS_OF)
    assert result["status"] == "unknown"
    assert result["reason"] == "unknown_role"


def test_check_request_eligibility_item_missing_from_role_policy(custom_data) -> None:
    custom_data([_employee("T001", "manager", [])], {"manager": MANAGER_POLICY})
    result = check_request_eligibility("T001", "laptop", as_of=AS_OF)
    assert result["status"] == "ineligible"
    assert result["reason"] == "role_not_eligible_for_item"


def test_check_request_eligibility_at_cap_with_any_undated_item_is_unknown(custom_data) -> None:
    equipment: list[dict[str, Any]] = [
        {"item": "monitor", "issued_on": "2018-01-01"},
        {"item": "monitor", "issued_on": None},
    ]
    custom_data([_employee("T001", "manager", equipment)], {"manager": MANAGER_POLICY})
    result = check_request_eligibility("T001", "monitor", as_of=AS_OF)
    assert result["status"] == "unknown"
    assert result["reason"] == "missing_issue_date"


def test_check_request_eligibility_below_cap_ignores_undated_item(custom_data) -> None:
    equipment = [{"item": "monitor", "issued_on": ""}]
    custom_data([_employee("T001", "manager", equipment)], {"manager": MANAGER_POLICY})
    result = check_request_eligibility("T001", "monitor", as_of=AS_OF)
    assert result["status"] == "eligible"
    assert result["reason"] == "below_max_count"


def test_check_request_eligibility_refresh_uses_oldest_item(custom_data) -> None:
    equipment = [
        {"item": "monitor", "issued_on": "2025-06-01"},
        {"item": "monitor", "issued_on": "2022-01-01"},
    ]
    custom_data([_employee("T001", "manager", equipment)], {"manager": MANAGER_POLICY})
    result = check_request_eligibility("T001", "monitor", as_of=AS_OF)
    assert result["status"] == "eligible"
    assert result["facts_used"]["oldest_issued_on"] == "2022-01-01"


def test_check_request_eligibility_facts_used() -> None:
    result = check_request_eligibility("E002", "monitor", as_of=AS_OF)
    facts = result["facts_used"]
    assert facts["as_of"] == "2026-10-02"
    assert facts["employee"]["role"] == "standard"
    assert facts["policy"]["role"] == "standard"
    assert facts["held_count"] == 1
    assert facts["max_count"] == 1
    assert facts["interval_years"] == 3
    assert facts["oldest_issued_on"] == "2025-01-10"
    assert 0 < facts["age_years"] < 3


def test_check_request_eligibility_defaults_as_of_to_today() -> None:
    result = check_request_eligibility("E001", "laptop")
    assert result["facts_used"]["as_of"] == datetime.now(timezone.utc).date().isoformat()


# --- flag_for_human_review ---------------------------------------------------


def test_flag_for_human_review_writes_ticket(ticket_path: Path) -> None:
    ticket = flag_for_human_review("E005", "I need a laptop", "contractor_role")
    assert ticket["escalated"] is True
    assert ticket["employee_id"] == "E005"
    assert ticket["request"] == "I need a laptop"
    assert ticket["ticket_id"].startswith("ESC-")
    assert datetime.fromisoformat(ticket["timestamp"]).tzinfo is not None
    stored = json.loads(ticket_path.read_text(encoding="utf-8").strip())
    assert stored == ticket


def test_flag_for_human_review_appends_unique_tickets(ticket_path: Path) -> None:
    first = flag_for_human_review("E005", "laptop", "contractor_role")
    second = flag_for_human_review("E006", "monitor", "missing_issue_date")
    lines = ticket_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["ticket_id"] for line in lines] == [first["ticket_id"], second["ticket_id"]]
    assert first["ticket_id"] != second["ticket_id"]


def test_flag_for_human_review_creates_missing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "does" / "not" / "exist" / "escalations.jsonl"
    monkeypatch.setattr(logic, "ESCALATIONS_PATH", nested)
    flag_for_human_review("E001", "standing desk", "unknown_item")
    assert nested.exists()


def test_flag_for_human_review_keeps_multiline_request_on_one_line(ticket_path: Path) -> None:
    request = 'line one\nline two with "quotes" and café'
    flag_for_human_review("E011", request, "special_circumstances")
    lines = ticket_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["request"] == request


def test_flag_for_human_review_unknown_employee_still_records(ticket_path: Path) -> None:
    ticket = flag_for_human_review("UNKNOWN", "need a laptop", "missing_employee_id")
    assert ticket["employee_id"] == "UNKNOWN"
    assert json.loads(ticket_path.read_text(encoding="utf-8"))["reason"] == "missing_employee_id"


def test_flag_for_human_review_empty_reason_still_records(ticket_path: Path) -> None:
    ticket = flag_for_human_review("E006", "replace my monitor", "")
    assert ticket["reason"] == ""
    stored = json.loads(ticket_path.read_text(encoding="utf-8").strip())
    assert stored["employee_id"] == "E006"
    assert "ticket_id" in stored

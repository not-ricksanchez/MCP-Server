"""Plain functions for the IT equipment request system. No MCP protocol here."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
EMPLOYEES_PATH = DATA_DIR / "employees.json"
POLICIES_PATH = DATA_DIR / "policies.json"
ESCALATIONS_PATH = DATA_DIR / "escalations.jsonl"

CATALOG = frozenset({"laptop", "monitor", "keyboard", "mouse", "headset"})


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _employees() -> dict[str, dict[str, Any]]:
    rows = _load_json(EMPLOYEES_PATH)
    return {row["employee_id"]: row for row in rows}


def _policies() -> dict[str, dict[str, Any]]:
    return _load_json(POLICIES_PATH)


def _normalize_item(item: str) -> str:
    return item.strip().lower()


def _parse_issued_on(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw)


def _years_between(issued_on: date, as_of: date) -> float:
    return (as_of - issued_on).days / 365.25


def _items_of_type(equipment: list[dict[str, Any]], item: str) -> list[dict[str, Any]]:
    return [row for row in equipment if row.get("item") == item]


def get_employee_info(employee_id: str) -> dict[str, Any]:
    """Return role, tenure, and current equipment, or found=false if unknown."""
    employee = _employees().get(employee_id)
    if employee is None:
        return {"found": False, "employee_id": employee_id, "error": "unknown_employee"}
    return {
        "found": True,
        "employee_id": employee["employee_id"],
        "name": employee["name"],
        "role": employee["role"],
        "tenure_years": employee["tenure_years"],
        "equipment": employee.get("equipment", []),
    }


def get_policy_limits(role: str) -> dict[str, Any]:
    """Return what that role is eligible for and how often."""
    policies = _policies()
    if role not in policies:
        return {"found": False, "role": role, "error": "unknown_role"}
    policy = policies[role]
    rules = {
        item: dict(policy[item])
        for item in CATALOG
        if item in policy
    }
    return {
        "found": True,
        "role": role,
        "always_escalate": bool(policy.get("always_escalate")),
        "rules": rules,
    }


def check_request_eligibility(
    employee_id: str,
    item: str,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Return eligible, ineligible, or unknown. Does not decide approve/deny/escalate."""
    as_of = as_of or datetime.now(timezone.utc).date()
    normalized = _normalize_item(item)
    facts: dict[str, Any] = {"as_of": as_of.isoformat()}

    if normalized not in CATALOG:
        return {
            "status": "unknown",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "unknown_item",
            "facts_used": facts,
        }

    employee = get_employee_info(employee_id)
    facts["employee"] = employee
    if not employee["found"]:
        return {
            "status": "unknown",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "unknown_employee",
            "facts_used": facts,
        }

    policy = get_policy_limits(employee["role"])
    facts["policy"] = policy
    if not policy["found"]:
        return {
            "status": "unknown",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "unknown_role",
            "facts_used": facts,
        }

    if policy["always_escalate"]:
        return {
            "status": "unknown",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "contractor_role",
            "facts_used": facts,
        }

    rule = policy["rules"].get(normalized)
    if rule is None or not rule.get("eligible"):
        return {
            "status": "ineligible",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "role_not_eligible_for_item",
            "facts_used": facts,
        }

    held = _items_of_type(employee.get("equipment") or [], normalized)
    max_count = int(rule.get("max_count") or 0)
    interval_years = rule.get("interval_years")
    facts["held_count"] = len(held)
    facts["max_count"] = max_count
    facts["interval_years"] = interval_years

    missing_dates = [row for row in held if _parse_issued_on(row.get("issued_on")) is None]
    if missing_dates and len(held) >= max_count:
        return {
            "status": "unknown",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "missing_issue_date",
            "facts_used": facts,
        }

    dated = [(_parse_issued_on(row.get("issued_on")), row) for row in held]
    dated_ok = [(issued, row) for issued, row in dated if issued is not None]
    oldest = min((issued for issued, _ in dated_ok), default=None)
    facts["oldest_issued_on"] = oldest.isoformat() if oldest else None

    if len(held) < max_count:
        return {
            "status": "eligible",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "below_max_count",
            "facts_used": facts,
        }

    # At or over the cap: eligible only as a refresh when the interval has elapsed.
    # interval_years 0 means replace anytime.
    if interval_years is None:
        return {
            "status": "ineligible",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "at_max_count",
            "facts_used": facts,
        }
    if interval_years == 0:
        return {
            "status": "eligible",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "replace_anytime",
            "facts_used": facts,
        }
    if oldest is None:
        return {
            "status": "unknown",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "missing_issue_date",
            "facts_used": facts,
        }
    age_years = _years_between(oldest, as_of)
    facts["age_years"] = round(age_years, 2)
    if age_years >= float(interval_years):
        return {
            "status": "eligible",
            "employee_id": employee_id,
            "item": normalized,
            "reason": "refresh_interval_met",
            "facts_used": facts,
        }
    return {
        "status": "ineligible",
        "employee_id": employee_id,
        "item": normalized,
        "reason": "refresh_interval_not_met",
        "facts_used": facts,
    }


def flag_for_human_review(employee_id: str, request: str, reason: str) -> dict[str, Any]:
    """Append an escalation ticket. Side-effecting."""
    ticket = {
        "ticket_id": f"ESC-{uuid.uuid4().hex[:8]}",
        "employee_id": employee_id,
        "request": request,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "escalated": True,
    }
    ESCALATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ESCALATIONS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ticket) + "\n")
    return ticket

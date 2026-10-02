# IT Equipment Request Handler — Requirements

Internal system for employee equipment requests. The MCP server holds employee and policy data. The agent looks that data up through tools and either **approves**, **denies**, or **escalates**. It must not guess missing facts.

## Request data

A request is natural language. Internally it is these fields:

| Field | Source | Required |
|---|---|---|
| `employee_id` | Parsed from the message | Yes. If missing → escalate |
| `item` | Parsed and normalized to the catalog | Yes. If missing or not in catalog → escalate |
| `reason` | Parsed from the message | Yes (used to detect special circumstances) |
| `role`, tenure, current equipment | **Tools only** (`get_employee_info`) | Never taken from the employee’s wording |

Do not trust a message that claims a role or last-refresh date. Always use tool results.

## Item catalog

Allowed items: `laptop`, `monitor`, `keyboard`, `mouse`, `headset`.

Anything else (standing desk, tablet, second laptop, dock, etc.) is out of catalog → **escalate**.

## Policy rules (by role)

“Refresh” means the last issue date for that item type is older than the interval, or there is no record of that item.

| Role | Laptop | Monitor | Peripherals (keyboard / mouse / headset) |
|---|---|---|---|
| intern | not eligible | not eligible | 1 of each, anytime |
| standard | 1 laptop, refresh every **4 years** | **1** monitor every **3 years** | 1 of each every **2 years** |
| manager | 1 laptop, refresh every **2 years** | up to **2** monitors, each every **3 years** | 1 of each, anytime |
| contractor | not eligible | not eligible | not eligible — **always escalate** |

## Outcomes

1. **Approve** — employee is known, item is in catalog, `check_request_eligibility` is `eligible`, and the reason is ordinary (broken, too old, standard kit).
2. **Deny** — same facts are known, eligibility is `ineligible`, and the reason is ordinary. Draft a polite denial that cites the policy the tools returned. **Do not** call `flag_for_human_review`.
3. **Escalate** — anything that would require guessing. Call `flag_for_human_review` with a concrete reason.

## What is ambiguous (escalate, do not decide)

- Unknown `employee_id`
- Item not in the catalog
- Role is `contractor`
- Eligibility is `unknown` (including missing equipment issue dates)
- Reason mentions accessibility, medical, legal, security, or an executive exception
- One message asks for **two different items**
- Message has **no employee id**
- Eligibility is ineligible **but** the reason claims special circumstances
- User’s claimed role or kit disagrees with tools and they insist they were promoted — trust the tool data, then escalate rather than override it

## Seed employees (for implementation and demos)

These people must exist in mock data so later tests and demos can hit every path:

| ID | Role | Purpose |
|---|---|---|
| E001 | standard | Clear **approve** (laptop older than 4 years) |
| E002 | standard | Clear **deny** (second monitor; already has a recent one) |
| E003 | manager | Clear **approve** (laptop older than 2 years) |
| E004 | intern | Intern policy (no kit yet; peripherals **approve**, laptop **deny**) |
| E005 | contractor | **Escalate** (no equipment policy) |
| E006 | standard | **Escalate** (monitor on file with missing issue date) |
| E007 | intern | Has keyboard already; still **approve** mouse/headset (anytime) |
| E008 | intern | Has peripherals; laptop/monitor still **deny** |
| E009 | manager | Already has 2 recent monitors; third monitor **deny** |
| E010 | manager | Has 1 old monitor; second monitor **approve** |
| E011 | standard | Laptop issued recently; laptop **deny** |
| E012 | standard | Monitor older than 3 years; monitor **approve** |
| E013 | standard | Keyboard issued recently; keyboard **deny** |
| E014 | standard | New hire, no kit on file; laptop **approve** |
| E015 | manager | Laptop issued recently; laptop **deny** |

## Tools the server must expose

Defined here so implementation matches the spec; not implemented in this document.

- `get_employee_info(employee_id)`
- `get_policy_limits(role)`
- `check_request_eligibility(employee_id, item)` → `eligible` \| `ineligible` \| `unknown`
- `flag_for_human_review(employee_id, request, reason)` — writes an escalation ticket

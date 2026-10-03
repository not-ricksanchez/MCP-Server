"""MCP client wrapper tests — no live server."""

from types import SimpleNamespace

from agent.mcp_client import McpClient, payload, server_url


def test_payload_unwraps_nested_result() -> None:
    result = SimpleNamespace(
        is_error=False,
        structured_content={"result": {"found": True, "role": "standard"}},
    )
    assert payload(result) == {"found": True, "role": "standard"}


def test_payload_keeps_plain_dict() -> None:
    result = SimpleNamespace(
        is_error=False,
        structured_content={"status": "eligible"},
    )
    assert payload(result)["status"] == "eligible"


def test_payload_error() -> None:
    result = SimpleNamespace(is_error=True)
    data = payload(result)
    assert data["error"] is True


def test_server_url_default(monkeypatch) -> None:
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    assert server_url() == "http://127.0.0.1:3000/mcp"


def test_server_url_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp-server:3000/mcp")
    assert server_url() == "http://mcp-server:3000/mcp"


def test_tools_list_empty_until_server_replies() -> None:
    client = McpClient("http://example.invalid/mcp")
    assert client.tools_list == []


def test_tools_list_comes_from_cached_server_tools() -> None:
    client = McpClient("http://example.invalid/mcp")
    client._tools = [
        SimpleNamespace(
            name="get_employee_info",
            description="Return role and kit.",
            input_schema={"properties": {"employee_id": {}}, "required": ["employee_id"]},
        ),
        SimpleNamespace(
            name="get_policy_limits",
            description="Return policy.",
            input_schema={"properties": {"role": {}}, "required": ["role"]},
        ),
    ]
    assert client.tools_list == ["get_employee_info", "get_policy_limits"]
    text = client.format_tools()
    assert "get_employee_info(employee_id)" in text
    assert "get_policy_limits(role)" in text

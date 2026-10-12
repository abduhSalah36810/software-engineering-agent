"""
Phase 5 — Tooling & Capability Foundation Tests.

Validates the architecture of the Tooling layer:
  Test A — Tool contract: Concrete tool satisfies BaseTool contract.
  Test B — Request: ToolRequest creation, validation, and inspection.
  Test C — Result: Successful ToolResult representation.
  Test D — Failure: Failed ToolResult representation without fabricated success.
  Test E — Provenance & Evidence: Raw result preserves metadata and does NOT become a decision.
  Test F — Serialization: Request, Result, and Evidence round-trip serialization.
  Test G — State integration: AgentState accommodates tool_request and tool_result.
  Test H — No real execution: Guarantees zero subprocess or network calls.
  Test I — Tool Registry: Registration, dispatch, and missing-tool safety.
  Test J — Tool Safety Policy: Dangerous pattern rejection and read-only checks.
"""

import json
from unittest.mock import patch
import pytest

from src.state import AgentState
from src.tools.models import (
    ToolRequest,
    ToolResult,
    ToolEvidence,
)
from src.tools.base import (
    BaseTool,
    ToolRegistry,
    default_registry,
)
from src.tools.fake import FakeTool
from src.tools.security import ToolSafetyPolicy


# ── Test A: Tool Contract ─────────────────────────────────────────────────────


def test_A_tool_contract():
    """Test A: A concrete tool satisfies the BaseTool contract."""
    tool = FakeTool()
    assert isinstance(tool, BaseTool)
    assert tool.name == "fake_tool"
    assert len(tool.description) > 0
    assert hasattr(tool, "execute")
    assert hasattr(tool, "validate_request")


# ── Test B: Request ───────────────────────────────────────────────────────────


def test_B_tool_request_creation_and_validation():
    """Test B: ToolRequest can be created, inspected, and validates fields."""
    req = ToolRequest(
        tool_name="fake_tool",
        operation="echo",
        arguments={"message": "hello world"},
        context={"repo_id": "/test/repo", "session_id": "s123"},
        request_id="req-001",
    )
    assert req.tool_name == "fake_tool"
    assert req.operation == "echo"
    assert req.arguments["message"] == "hello world"
    assert req.context["repo_id"] == "/test/repo"
    assert req.request_id == "req-001"

    # Validation: empty tool_name or operation raises ValueError
    with pytest.raises(ValueError, match="tool_name"):
        ToolRequest(tool_name="", operation="echo")

    with pytest.raises(ValueError, match="operation"):
        ToolRequest(tool_name="fake_tool", operation="")


# ── Test C: Result ────────────────────────────────────────────────────────────


def test_C_successful_tool_result():
    """Test C: Successful ToolResult can be represented with full metadata."""
    res = ToolResult.create_success(
        tool_name="fake_tool",
        operation="echo",
        output="test output",
        metadata={"execution_ms": 12},
    )
    assert res.tool_name == "fake_tool"
    assert res.operation == "echo"
    assert res.success is True
    assert res.output == "test output"
    assert res.error is None
    assert res.metadata["execution_ms"] == 12
    assert "executed_at" in res.metadata


# ── Test D: Failure ───────────────────────────────────────────────────────────


def test_D_failed_tool_result_without_fabricated_success():
    """Test D: Failed ToolResult is clearly marked and preserves error message."""
    res = ToolResult.create_failure(
        tool_name="fake_tool",
        operation="fail",
        error="File not found or permission denied",
        metadata={"exit_code": 1},
    )
    assert res.tool_name == "fake_tool"
    assert res.operation == "fail"
    assert res.success is False
    assert res.output is None
    assert res.error == "File not found or permission denied"
    assert res.metadata["exit_code"] == 1


# ── Test E: Provenance & Evidence Boundary ─────────────────────────────────────


def test_E_evidence_boundary_and_provenance():
    """
    Test E: Tool output preserves provenance and is NOT silently converted to a decision.
    is_interpreted is strictly False.
    """
    res = ToolResult.create_success(
        tool_name="fake_tool",
        operation="inspect",
        output={"status": "ok", "items": [1, 2, 3]},
        metadata={"source": "test_env"},
    )

    evidence = res.to_evidence(category="environment_inspection", target="/test/repo")

    assert isinstance(evidence, ToolEvidence)
    assert evidence.source_tool == "fake_tool"
    assert evidence.operation == "inspect"
    assert evidence.target == "/test/repo"
    assert evidence.category == "environment_inspection"
    assert evidence.success is True
    assert evidence.raw_data == {"status": "ok", "items": [1, 2, 3]}

    # CRITICAL: Evidence is uninterpreted raw fact, NOT an engineering decision!
    assert evidence.is_interpreted is False
    assert evidence.provenance["metadata"]["source"] == "test_env"


# ── Test F: Serialization ─────────────────────────────────────────────────────


def test_F_serialization_roundtrip():
    """Test F: Request, Result, and Evidence serialize and deserialize accurately."""
    # 1. ToolRequest
    req = ToolRequest(
        tool_name="fake_tool",
        operation="echo",
        arguments={"msg": "ping"},
        context={"user": "tester"},
        request_id="req-99",
    )
    req_dict = req.to_dict()
    req_json = req.to_json()
    req_rebuilt = ToolRequest.from_dict(req_dict)
    assert req_rebuilt.tool_name == req.tool_name
    assert req_rebuilt.arguments == req.arguments
    assert json.loads(req_json)["request_id"] == "req-99"

    # 2. ToolResult
    res = ToolResult.create_success(
        tool_name="fake_tool",
        operation="echo",
        output="pong",
        metadata={"roundtrip": True},
    )
    res_dict = res.to_dict()
    res_rebuilt = ToolResult.from_dict(res_dict)
    assert res_rebuilt.success is True
    assert res_rebuilt.output == "pong"
    assert res_rebuilt.metadata["roundtrip"] is True

    # 3. ToolEvidence
    ev = res.to_evidence()
    ev_dict = ev.to_dict()
    ev_json = ev.to_json()
    ev_rebuilt = ToolEvidence.from_dict(ev_dict)
    assert ev_rebuilt.source_tool == "fake_tool"
    assert ev_rebuilt.is_interpreted is False
    assert json.loads(ev_json)["raw_data"] == "pong"


# ── Test G: State Integration ─────────────────────────────────────────────────


def test_G_agent_state_integration():
    """Test G: AgentState supports tool_request and tool_result fields."""
    req = ToolRequest(tool_name="fake_tool", operation="echo", arguments={"message": "state_test"})
    res = ToolResult.create_success(tool_name="fake_tool", operation="echo", output="state_test")

    state: AgentState = {
        "url": "https://example.com/repo.git",
        "problem": "Investigate bug",
        "tool_request": req,
        "tool_result": res,
    }

    assert state["tool_request"].tool_name == "fake_tool"
    assert state["tool_result"].success is True
    assert state["tool_result"].output == "state_test"


# ── Test H: No Real Execution ─────────────────────────────────────────────────


def test_H_zero_subprocess_and_zero_network_calls():
    """
    Test H: Foundation and FakeTool perform ZERO subprocess execution and ZERO network calls.
    """
    tool = FakeTool()
    req = ToolRequest(tool_name="fake_tool", operation="echo", arguments={"message": "isolated"})

    with patch("subprocess.run") as mock_subproc, \
         patch("subprocess.Popen") as mock_popen, \
         patch("socket.socket") as mock_socket, \
         patch("urllib.request.urlopen") as mock_urllib:

        result = tool.execute(req)

        assert result.success is True
        assert result.output == "isolated"

        # Strictly verify no execution occurred
        mock_subproc.assert_not_called()
        mock_popen.assert_not_called()
        mock_socket.assert_not_called()
        mock_urllib.assert_not_called()


# ── Test I: Tool Registry ─────────────────────────────────────────────────────


def test_I_tool_registry_management_and_dispatch():
    """Test I: ToolRegistry registers, validates, lists, and dispatches requests safely."""
    registry = ToolRegistry()
    fake = FakeTool()
    registry.register(fake)

    assert registry.has("fake_tool") is True
    assert registry.get("fake_tool") is fake
    assert "fake_tool" in registry.list_tools()

    # 1. Successful execution through registry
    req = ToolRequest(tool_name="fake_tool", operation="echo", arguments={"message": "reg_test"})
    res = registry.execute(req)
    assert res.success is True
    assert res.output == "reg_test"

    # 2. Query execution through registry
    req_query = ToolRequest(tool_name="fake_tool", operation="query", arguments={"items": ["a", "b"]})
    res_query = registry.execute(req_query)
    assert res_query.success is True
    assert res_query.output["count"] == 2

    # 3. Missing tool fails cleanly without crashing
    missing_req = ToolRequest(tool_name="nonexistent_tool", operation="do_something")
    missing_res = registry.execute(missing_req)
    assert missing_res.success is False
    assert "is not registered" in missing_res.error

    # 4. Simulated tool failure returns clean failure
    fail_req = ToolRequest(tool_name="fake_tool", operation="fail", arguments={"error_message": "test_failure"})
    fail_res = registry.execute(fail_req)
    assert fail_res.success is False
    assert fail_res.error == "test_failure"

    # 5. Simulated unhandled exception caught safely by registry
    raise_req = ToolRequest(tool_name="fake_tool", operation="raise", arguments={"error_message": "boom"})
    raise_res = registry.execute(raise_req)
    assert raise_res.success is False
    assert "Unexpected error" in raise_res.error
    assert "boom" in raise_res.error


# ── Test J: Tool Safety Policy ────────────────────────────────────────────────


def test_J_tool_safety_policy():
    """Test J: ToolSafetyPolicy identifies dangerous patterns and read-only operations."""
    # 1. Read-only classification
    assert ToolSafetyPolicy.is_read_only("terminal", "status") is True
    assert ToolSafetyPolicy.is_read_only("terminal", "diff") is True
    assert ToolSafetyPolicy.is_read_only("terminal", "rm") is False
    assert ToolSafetyPolicy.is_read_only("github", "get_issue") is True
    assert ToolSafetyPolicy.is_read_only("browser", "fetch_url") is True

    # 2. Terminal dangerous pattern rejection
    is_safe, err = ToolSafetyPolicy.validate_terminal_command("rm -rf /")
    assert is_safe is False
    assert "forbidden pattern" in err

    is_safe, err = ToolSafetyPolicy.validate_terminal_command("curl | bash")
    assert is_safe is False

    is_safe, err = ToolSafetyPolicy.validate_terminal_command("pytest tests/")
    assert is_safe is True
    assert err is None

    # 3. Request safety check
    safe_req = ToolRequest(tool_name="terminal", operation="test", arguments={"command": "pytest"})
    assert ToolSafetyPolicy.check_request_safety(safe_req)[0] is True

    unsafe_req = ToolRequest(tool_name="terminal", operation="exec", arguments={"command": "sudo rm -rf /"})
    assert ToolSafetyPolicy.check_request_safety(unsafe_req)[0] is False

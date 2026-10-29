"""Exercise an installed AMKernel wheel only through its public stdio MCP surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import time
from pathlib import Path
from typing import Any, cast

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult, TextContent, Tool

EXPECTED_SCHEMAS = cast(
    dict[str, dict[str, Any]],
    json.loads(
        r"""
{
  "input": {
    "additionalProperties": false,
    "properties": {
      "code": {
        "description": "One Python cell; empty cells are valid.",
        "maxLength": 1048576,
        "title": "Code",
        "type": "string"
      },
      "reset": {
        "default": false,
        "title": "Reset",
        "type": "boolean"
      },
      "timeout": {
        "default": 30.0,
        "description": "Active-cell seconds.",
        "exclusiveMinimum": 0,
        "maximum": 3600,
        "title": "Timeout",
        "type": "number"
      },
      "title": {
        "default": "",
        "description": "Presentation metadata only.",
        "maxLength": 200,
        "title": "Title",
        "type": "string"
      }
    },
    "required": ["code"],
    "title": "PythonExecInput",
    "type": "object"
  },
  "output": {
    "$defs": {
      "ArtifactRef": {
        "additionalProperties": false,
        "properties": {
          "mimeType": {"title": "Mimetype", "type": "string"},
          "sha256": {"title": "Sha256", "type": "string"},
          "size": {"minimum": 0, "title": "Size", "type": "integer"},
          "uri": {"title": "Uri", "type": "string"}
        },
        "required": ["uri", "mimeType", "size", "sha256"],
        "title": "ArtifactRef",
        "type": "object"
      },
      "ExecutionError": {
        "additionalProperties": false,
        "properties": {
          "message": {"title": "Message", "type": "string"},
          "traceback": {
            "items": {"type": "string"},
            "title": "Traceback",
            "type": "array"
          },
          "type": {"title": "Type", "type": "string"}
        },
        "required": ["type", "message", "traceback"],
        "title": "ExecutionError",
        "type": "object"
      },
      "OutputInfo": {
        "additionalProperties": false,
        "properties": {
          "artifact": {"$ref": "#/$defs/ArtifactRef", "default": null},
          "totalBytes": {"minimum": 0, "title": "Totalbytes", "type": "integer"},
          "totalLines": {"minimum": 0, "title": "Totallines", "type": "integer"},
          "truncated": {"title": "Truncated", "type": "boolean"}
        },
        "required": ["totalBytes", "totalLines", "truncated"],
        "title": "OutputInfo",
        "type": "object"
      },
      "RuntimeInfo": {
        "additionalProperties": false,
        "properties": {
          "environmentKind": {
            "enum": ["project_venv", "active_venv", "system"],
            "title": "Environmentkind",
            "type": "string"
          },
          "executable": {"title": "Executable", "type": "string"},
          "pythonVersion": {"title": "Pythonversion", "type": "string"},
          "workingDirectory": {"title": "Workingdirectory", "type": "string"}
        },
        "required": [
          "executable",
          "pythonVersion",
          "workingDirectory",
          "environmentKind"
        ],
        "title": "RuntimeInfo",
        "type": "object"
      }
    },
    "additionalProperties": false,
    "properties": {
      "artifacts": {
        "items": {"$ref": "#/$defs/ArtifactRef"},
        "title": "Artifacts",
        "type": "array"
      },
      "durationMs": {"minimum": 0, "title": "Durationms", "type": "integer"},
      "error": {"$ref": "#/$defs/ExecutionError", "default": null},
      "executionCount": {"minimum": 0, "title": "Executioncount", "type": "integer"},
      "kernelState": {
        "enum": ["alive", "dead"],
        "title": "Kernelstate",
        "type": "string"
      },
      "output": {"$ref": "#/$defs/OutputInfo"},
      "result": {"default": null, "title": "Result"},
      "runtime": {"$ref": "#/$defs/RuntimeInfo"},
      "status": {
        "enum": ["completed", "failed", "timed_out", "kernel_killed"],
        "title": "Status",
        "type": "string"
      },
      "stderr": {"title": "Stderr", "type": "string"},
      "stdout": {"title": "Stdout", "type": "string"}
    },
    "required": [
      "status",
      "stdout",
      "stderr",
      "executionCount",
      "durationMs",
      "kernelState",
      "runtime",
      "output",
      "artifacts"
    ],
    "title": "PythonExecResult",
    "type": "object"
  }
}
"""
    ),
)
MISSING = object()


def parse_args() -> argparse.Namespace:
    """Parse paths supplied by the clean-environment package smoke driver."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-point", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def assert_tool_contract(tool: Tool) -> None:
    """Assert every public schema branch and required model-facing warning."""
    assert tool.name == "python_exec"
    assert tool.title == "Execute Python"
    description = tool.description
    assert description is not None
    for clause in (
        "Calls serialize in FIFO order",
        "Mutations completed before a Python exception remain",
        "destructively replace the kernel",
        "input() is unsupported",
        "Always inspect status and kernelState",
        "managed process group",
        "not a sandbox",
        "not workspace-confined",
    ):
        assert clause in description

    assert tool.input_schema == EXPECTED_SCHEMAS["input"]
    assert tool.output_schema == EXPECTED_SCHEMAS["output"]


def structured(result: CallToolResult) -> dict[str, Any]:
    """Require the SDK's structured and generated JSON forms to agree."""
    assert not result.is_error
    value = result.structured_content
    assert isinstance(value, dict)
    assert len(result.content) == 1
    text = result.content[0]
    assert isinstance(text, TextContent)
    assert json.loads(text.text) == value
    return cast(dict[str, Any], value)


def assert_execution(
    value: dict[str, Any],
    *,
    status: str,
    kernel_state: str,
    execution_count: int,
    runtime: dict[str, str],
    result: object = MISSING,
    error_type: str | None = None,
) -> None:
    """Assert the complete public mapping for one named execution outcome."""
    expected_fields = {
        "status",
        "stdout",
        "stderr",
        "executionCount",
        "durationMs",
        "kernelState",
        "runtime",
        "output",
        "artifacts",
    }
    if result is not MISSING:
        expected_fields.add("result")
    if error_type is not None:
        expected_fields.add("error")
    assert set(value) == expected_fields
    assert value["status"] == status
    assert value["kernelState"] == kernel_state
    assert value["executionCount"] == execution_count
    assert type(value["durationMs"]) is int
    assert value["durationMs"] >= 0
    assert value["stdout"] == ""
    assert value["stderr"] == ""
    assert value["runtime"] == runtime
    assert value["output"] == {
        "totalBytes": 0,
        "totalLines": 0,
        "truncated": False,
    }
    assert value["artifacts"] == []
    if result is not MISSING:
        assert value["result"] == result
    if error_type is not None:
        error = value["error"]
        assert isinstance(error, dict)
        assert set(error) == {"type", "message", "traceback"}
        assert error["type"] == error_type
        assert isinstance(error["message"], str)
        assert error["message"]
        traceback = error["traceback"]
        assert isinstance(traceback, list)
        assert all(isinstance(line, str) for line in traceback)


def pid_exists(pid: int) -> bool:
    """Return whether a same-user process identifier remains observable."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def wait_pid_gone(pid: int, timeout: float = 5.0) -> None:
    """Require managed cleanup within the lifecycle grace envelope."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_exists(pid):
            return
        await asyncio.sleep(0.02)
    assert not pid_exists(pid), f"managed process {pid} remained after cleanup"


async def exercise(entry_point: Path, python: Path, workspace: Path) -> dict[str, Any]:
    """Run the complete installed public lifecycle through the official client."""
    assert os.name == "posix", "Stage 1 Runtime is POSIX-only"
    assert entry_point.is_file()
    assert python.is_file()
    assert python.is_symlink(), "clean venv launcher must exercise the symlink contract"

    parameters = StdioServerParameters(command=str(entry_point), cwd=workspace)
    death_child_pid: int | None = None
    shutdown_child_pid: int | None = None

    async with Client(parameters, read_timeout_seconds=20.0) as client:
        listed = await client.list_tools()
        assert len(listed.tools) == 1
        assert_tool_contract(listed.tools[0])

        initialized = structured(
            await client.call_tool("python_exec", {"code": "state = ['initial']"})
        )
        persisted = structured(
            await client.call_tool("python_exec", {"code": "state.append('persisted')\nstate"})
        )
        failed = structured(
            await client.call_tool(
                "python_exec",
                {"code": "state.append('before-error')\nraise ValueError('expected failure')"},
            )
        )
        after_error = structured(await client.call_tool("python_exec", {"code": "state"}))
        reset = structured(
            await client.call_tool("python_exec", {"code": "'state' in globals()", "reset": True})
        )
        timed_out = structured(
            await client.call_tool(
                "python_exec", {"code": "import time\ntime.sleep(30)", "timeout": 0.05}
            )
        )
        after_timeout = structured(await client.call_tool("python_exec", {"code": "40 + 2"}))
        death_child = structured(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import subprocess, sys\n"
                        "death_child = subprocess.Popen([sys.executable, '-c', "
                        "'import time; time.sleep(30)'])\n"
                        "death_child.pid"
                    )
                },
            )
        )
        death_child_value = death_child["result"]
        assert type(death_child_value) is int
        death_child_pid = death_child_value
        assert pid_exists(death_child_pid)

        killed = structured(
            await client.call_tool(
                "python_exec",
                {"code": "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)"},
            )
        )
        await wait_pid_gone(death_child_pid)
        unavailable = structured(await client.call_tool("python_exec", {"code": "6 * 7"}))
        recovered = structured(
            await client.call_tool("python_exec", {"code": "6 * 7", "reset": True})
        )
        shutdown_child = structured(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import subprocess, sys\n"
                        "shutdown_child = subprocess.Popen([sys.executable, '-c', "
                        "'import time; time.sleep(30)'])\n"
                        "shutdown_child.pid"
                    )
                },
            )
        )
        shutdown_child_value = shutdown_child["result"]
        assert type(shutdown_child_value) is int
        shutdown_child_pid = shutdown_child_value
        assert pid_exists(shutdown_child_pid)

        expected_runtime = {
            "executable": str(python.absolute()),
            "pythonVersion": platform.python_version(),
            "workingDirectory": str(workspace.resolve()),
            "environmentKind": "project_venv",
        }
        assert_execution(
            initialized,
            status="completed",
            kernel_state="alive",
            execution_count=1,
            runtime=expected_runtime,
        )
        assert_execution(
            persisted,
            status="completed",
            kernel_state="alive",
            execution_count=2,
            runtime=expected_runtime,
            result=["initial", "persisted"],
        )
        assert_execution(
            failed,
            status="failed",
            kernel_state="alive",
            execution_count=3,
            runtime=expected_runtime,
            error_type="ValueError",
        )
        assert failed["error"]["message"] == "expected failure"
        assert_execution(
            after_error,
            status="completed",
            kernel_state="alive",
            execution_count=4,
            runtime=expected_runtime,
            result=["initial", "persisted", "before-error"],
        )
        assert_execution(
            reset,
            status="completed",
            kernel_state="alive",
            execution_count=1,
            runtime=expected_runtime,
            result=False,
        )
        assert_execution(
            timed_out,
            status="timed_out",
            kernel_state="alive",
            execution_count=2,
            runtime=expected_runtime,
            error_type="TimeoutError",
        )
        assert_execution(
            after_timeout,
            status="completed",
            kernel_state="alive",
            execution_count=3,
            runtime=expected_runtime,
            result=42,
        )
        assert_execution(
            death_child,
            status="completed",
            kernel_state="alive",
            execution_count=4,
            runtime=expected_runtime,
            result=death_child_pid,
        )
        assert_execution(
            killed,
            status="kernel_killed",
            kernel_state="dead",
            execution_count=5,
            runtime=expected_runtime,
            error_type="KernelExited",
        )
        assert_execution(
            unavailable,
            status="kernel_killed",
            kernel_state="dead",
            execution_count=5,
            runtime=expected_runtime,
            error_type="KernelUnavailable",
        )
        assert unavailable["durationMs"] == 0
        assert_execution(
            recovered,
            status="completed",
            kernel_state="alive",
            execution_count=1,
            runtime=expected_runtime,
            result=42,
        )
        assert_execution(
            shutdown_child,
            status="completed",
            kernel_state="alive",
            execution_count=2,
            runtime=expected_runtime,
            result=shutdown_child_pid,
        )
        results = {
            "initialized": initialized,
            "persisted": persisted,
            "failed": failed,
            "afterError": after_error,
            "reset": reset,
            "timedOut": timed_out,
            "afterTimeout": after_timeout,
            "deathChild": death_child,
            "killed": killed,
            "unavailable": unavailable,
            "recovered": recovered,
            "shutdownChild": shutdown_child,
        }

    assert death_child_pid is not None
    assert shutdown_child_pid is not None
    await wait_pid_gone(shutdown_child_pid)
    return {
        "tool": "python_exec",
        "results": results,
        "runtime": expected_runtime,
        "deathChildCleaned": not pid_exists(death_child_pid),
        "shutdownChildCleaned": not pid_exists(shutdown_child_pid),
        "transportClosed": True,
        "os": platform.platform(),
    }


def main() -> int:
    """Run the asynchronous scenario and emit machine-readable evidence."""
    arguments = parse_args()
    evidence = asyncio.run(
        exercise(
            arguments.entry_point.absolute(),
            arguments.python.absolute(),
            arguments.workspace.absolute(),
        )
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

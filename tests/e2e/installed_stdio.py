"""Exercise an installed AMKernel wheel only through its public stdio MCP surface."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import mcp.types as types
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.dispatcher import ProgressFnT
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent, Tool
from PIL import Image as PillowImage

MISSING = object()
SERVER_RSS_BOUND_BYTES = 805_306_368


def process_metrics(pid: int) -> dict[str, int]:
    """Measure one installed server process without importing project internals."""
    rss_kib = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True).strip())
    if platform.system() == "Linux":
        open_files = len(list(Path(f"/proc/{pid}/fd").iterdir()))
        task_count = len(list(Path(f"/proc/{pid}/task").iterdir()))
    else:
        lsof = subprocess.check_output(
            ["lsof", "-a", "-p", str(pid), "-d", "0-999999", "-Ff"], text=True
        )
        open_files = sum(line.startswith("f") for line in lsof.splitlines())
        tasks = subprocess.check_output(["ps", "-M", "-p", str(pid), "-o", "pid="], text=True)
        task_count = len(tasks.splitlines())

    rows = subprocess.check_output(["ps", "-axo", "pid=,ppid="], text=True)
    children: dict[int, list[int]] = {}
    for row in rows.splitlines():
        child, parent = (int(value) for value in row.split())
        children.setdefault(parent, []).append(child)
    descendants = list(children.get(pid, ()))
    for child in descendants:
        descendants.extend(children.get(child, ()))
    return {
        "rssBytes": rss_kib * 1024,
        "openFiles": open_files,
        "taskCount": task_count,
        "childProcessCount": len(descendants),
    }


def parse_args() -> argparse.Namespace:
    """Parse paths supplied by the clean-environment package smoke driver."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-point", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--schema-fixture", type=Path, required=True)
    return parser.parse_args()


def assert_tool_contract(tool: Tool, expected_schemas: dict[str, dict[str, Any]]) -> None:
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

    assert tool.input_schema == expected_schemas["inputSchema"]
    assert tool.output_schema == expected_schemas["outputSchema"]


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


def structured_rich(result: CallToolResult) -> tuple[dict[str, Any], list[types.ContentBlock]]:
    """Require canonical JSON first while retaining rich MCP content blocks."""
    assert not result.is_error
    value = result.structured_content
    assert isinstance(value, dict)
    assert result.content
    text = result.content[0]
    assert isinstance(text, TextContent)
    assert json.loads(text.text) == value
    return cast(dict[str, Any], value), result.content


def assert_execution(
    value: dict[str, Any],
    *,
    status: str,
    kernel_state: str,
    execution_count: int,
    runtime: dict[str, Any],
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
        "displays",
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
        "discardedBytes": 0,
        "discardedLines": 0,
        "truncated": False,
        "limitBytes": 268_435_456,
        "limitExceeded": False,
        "live": "unavailable",
    }
    assert value["displays"] == []
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


async def read_resource(client: Client, uri: str) -> tuple[str, bytes]:
    """Read one public resource and decode its exact MCP representation."""
    response = await client.read_resource(uri)
    assert len(response.contents) == 1
    content = response.contents[0]
    assert content.mime_type is not None
    if isinstance(content, types.TextResourceContents):
        return content.mime_type, content.text.encode()
    assert isinstance(content, types.BlobResourceContents)
    return content.mime_type, base64.b64decode(content.blob, validate=True)


async def verify_manifest(client: Client, record: dict[str, Any], *, expected_parts: int) -> int:
    """Read and hash every part of one public manifest resource."""
    manifest_mime, manifest_bytes = await read_resource(client, cast(str, record["uri"]))
    assert manifest_mime == "application/vnd.amkernel.artifact-manifest+json"
    manifest = json.loads(manifest_bytes)
    parts = manifest["parts"]
    assert len(parts) == expected_parts
    digest = hashlib.sha256()
    total = 0
    for part in parts:
        part_mime, part_bytes = await read_resource(client, cast(str, part["uri"]))
        assert part_mime == "application/octet-stream"
        assert len(part_bytes) == part["size"]
        assert hashlib.sha256(part_bytes).hexdigest() == part["sha256"]
        digest.update(part_bytes)
        total += len(part_bytes)
    assert total == manifest["size"] == record["size"]
    assert digest.hexdigest() == manifest["sha256"] == record["sha256"]
    return total


async def exercise(
    entry_point: Path,
    python: Path,
    workspace: Path,
    schema_fixture: Path,
) -> dict[str, Any]:
    """Run the complete installed public lifecycle through the official client."""
    assert os.name == "posix", "the supported Runtime is POSIX-only"
    assert entry_point.is_file()
    assert python.is_file()
    assert python.is_symlink(), "clean venv launcher must exercise the symlink contract"
    assert os.path.samefile(python, sys.executable)
    expected_schemas = cast(dict[str, dict[str, Any]], json.loads(schema_fixture.read_text()))
    parameters = StdioServerParameters(command=str(entry_point), cwd=workspace)
    death_child_pid: int | None = None
    shutdown_child_pid: int | None = None
    progress_messages: list[str | None] = []

    async def capture_progress(_progress: float, _total: float | None, message: str | None) -> None:
        progress_messages.append(message)

    async with Client(parameters, read_timeout_seconds=60.0) as client:
        listed = await client.list_tools()
        assert len(listed.tools) == 1
        assert_tool_contract(listed.tools[0], expected_schemas)
        resources = await client.list_resources()
        assert resources.resources == []
        assert resources.cache_scope == "private"
        assert resources.ttl_ms == 0

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

        diagnostics = structured(
            await client.call_tool(
                "python_exec",
                {
                    "code": "42",
                    "packages": ["amkernel", "Pillow", "Definitely-Not-Installed-AMKernel"],
                },
            )
        )
        helpers, _ = structured_rich(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import os\n"
                        "os.mkdir('nested')\n"
                        "write('nested/note.txt', 'hello')\n"
                        "env('AMKERNEL_E2E', 'persisted')\n"
                        "display([read('nested/note.txt'), env('AMKERNEL_E2E'), "
                        "env('AMKERNEL_MISSING')])\n"
                        "'helpers'"
                    )
                },
            )
        )
        server_identity = structured(
            await client.call_tool("python_exec", {"code": "import os\nos.getppid()"})
        )
        server_pid = cast(int, server_identity["result"])
        metrics_before = process_metrics(server_pid)
        rich, rich_content = structured_rich(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import io\n"
                        "from PIL import Image\n"
                        "display({'answer': [42, True]})\n"
                        "artifact('note.txt', 'hello')\n"
                        "buffer = io.BytesIO()\n"
                        "Image.new('RGB', (2, 3), 'red').save(buffer, format='PNG')\n"
                        "display(buffer.getvalue(), mime_type='image/png')\n"
                        "artifact('large.bin', b'm' * 8388609)\n"
                        "'rich'"
                    ),
                    "timeout": 20.0,
                },
            )
        )
        assert rich["status"] == "completed", rich
        assert rich["result"] == "rich"
        assert [display["kind"] for display in rich["displays"]] == [
            "json",
            "artifact",
            "image",
            "artifact",
        ]
        assert len(rich["artifacts"]) == 3
        images = [block for block in rich_content if isinstance(block, types.ImageContent)]
        assert len(images) == 1
        image_bytes = base64.b64decode(images[0].data, validate=True)
        assert images[0].mime_type == "image/png"
        assert hashlib.sha256(image_bytes).hexdigest() == rich["artifacts"][1]["sha256"]
        assert len(image_bytes) == rich["artifacts"][1]["size"]
        with PillowImage.open(io.BytesIO(image_bytes)) as decoded:
            decoded.load()
            assert decoded.size == (2, 3)

        raw = rich["artifacts"][0]
        raw_mime, raw_bytes = await read_resource(client, raw["uri"])
        assert raw["representation"] == "raw"
        assert raw_mime == "text/plain; charset=utf-8"
        assert raw_bytes == b"hello"
        manifest_record = rich["artifacts"][2]
        manifest_mime, manifest_bytes = await read_resource(client, manifest_record["uri"])
        assert manifest_record["representation"] == "manifest"
        assert manifest_mime == "application/vnd.amkernel.artifact-manifest+json"
        manifest = json.loads(manifest_bytes)
        assert manifest["size"] == 8_388_609
        assert len(manifest["parts"]) == 2
        first_part_mime, first_part = await read_resource(
            client, cast(str, manifest["parts"][0]["uri"])
        )
        assert first_part_mime == "application/octet-stream"
        assert first_part == b"m" * 8_388_608
        raster_variants: dict[str, dict[str, Any]] = {}
        for image_format, image_mime in (
            ("JPEG", "image/jpeg"),
            ("GIF", "image/gif"),
            ("WEBP", "image/webp"),
        ):
            raster, raster_content = structured_rich(
                await client.call_tool(
                    "python_exec",
                    {
                        "code": (
                            "import io\n"
                            "from PIL import Image\n"
                            "buffer = io.BytesIO()\n"
                            "Image.new('RGB', (2, 3), (0, 0, 0)).save(buffer, "
                            f"format='{image_format}')\n"
                            f"display(buffer.getvalue(), mime_type='{image_mime}')\n"
                            f"'{image_format}'"
                        )
                    },
                )
            )
            assert raster["status"] == "completed", raster
            assert raster["result"] == image_format
            raster_images = [
                block for block in raster_content if isinstance(block, types.ImageContent)
            ]
            assert len(raster_images) == 1
            raster_bytes = base64.b64decode(raster_images[0].data, validate=True)
            assert raster_images[0].mime_type == image_mime
            assert hashlib.sha256(raster_bytes).hexdigest() == raster["artifacts"][0]["sha256"]
            assert len(raster_bytes) == raster["artifacts"][0]["size"]
            with PillowImage.open(io.BytesIO(raster_bytes)) as decoded:
                decoded.load()
                assert decoded.size == (2, 3)
            raster_variants[image_mime] = raster

        progress, _ = structured_rich(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import os, time\n"
                        "for _ in range(3):\n"
                        "    os.write(1, b'p' * 700000)\n"
                        "    time.sleep(0.1)"
                    )
                },
                progress_callback=cast(ProgressFnT, capture_progress),
                meta=cast(
                    types.RequestParamsMeta,
                    {"progressToken": "installed-stage-2"},
                ),
            )
        )
        assert progress["status"] == "completed"
        assert progress["output"]["totalBytes"] == 2_100_000
        assert progress["output"]["truncated"] is True
        assert progress["output"]["live"] == "progress"
        assert progress_messages
        assert all(
            message is None or len(message.encode()) <= 8_192 for message in progress_messages
        )

        async def reject_progress(
            _progress: float, _total: float | None, _message: str | None
        ) -> None:
            raise RuntimeError("expected client progress callback failure")

        progress_logger = logging.getLogger("mcp.shared.jsonrpc_dispatcher")
        prior_progress_log_level = progress_logger.level
        progress_logger.setLevel(logging.CRITICAL)
        try:
            callback_failure, _ = structured_rich(
                await client.call_tool(
                    "python_exec",
                    {"code": "import os\nos.write(1, b'f' * 2100000)"},
                    progress_callback=cast(ProgressFnT, reject_progress),
                    meta=cast(
                        types.RequestParamsMeta,
                        {"progressToken": "installed-progress-failure"},
                    ),
                )
            )
        finally:
            progress_logger.setLevel(prior_progress_log_level)
        assert callback_failure["status"] == "completed"
        assert callback_failure["output"]["totalBytes"] == 2_100_000
        assert callback_failure["output"]["live"] == "progress"
        json_flood, _ = structured_rich(
            await client.call_tool(
                "python_exec", {"code": "for value in range(64): display(value)"}
            )
        )
        assert json_flood["status"] == "completed"
        assert len(json_flood["displays"]) == 64
        artifact_flood, _ = structured_rich(
            await client.call_tool(
                "python_exec",
                {"code": "for value in range(64): artifact(f'{value}.txt', str(value))"},
            )
        )
        assert artifact_flood["status"] == "completed"
        assert len(artifact_flood["artifacts"]) == 64
        newest, _ = structured_rich(
            await client.call_tool(
                "python_exec",
                {"code": "for value in range(3): artifact(f'new-{value}.txt', str(value))"},
            )
        )
        assert len(newest["artifacts"]) == 3
        _, newest_bytes = await read_resource(client, cast(str, newest["artifacts"][-1]["uri"]))
        assert newest_bytes == b"2"

        limited, _ = structured_rich(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import os\n"
                        "chunk = b'x' * 65536\n"
                        "for _ in range(4096): os.write(1, chunk)\n"
                        "os.write(1, b'tail\\n')"
                    ),
                    "timeout": 20.0,
                },
            )
        )
        assert limited["status"] == "failed"
        assert limited["kernelState"] == "alive"
        assert limited["error"]["type"] == "OutputLimitExceeded"
        assert limited["output"]["totalBytes"] == 268_435_461
        assert limited["output"]["discardedBytes"] == 5
        assert limited["output"]["limitExceeded"] is True
        limited_record = cast(dict[str, Any], limited["output"]["stdoutArtifact"])
        assert limited_record == limited["artifacts"][0]
        assert await verify_manifest(client, limited_record, expected_parts=32) == 268_435_456
        filler_uri = ""
        for _ in range(7):
            filler, _ = structured_rich(
                await client.call_tool(
                    "python_exec",
                    {
                        "code": (
                            "import os\n"
                            "chunk = b'e' * 65536\n"
                            "for _ in range(4095): os.write(1, chunk)"
                        ),
                        "timeout": 20.0,
                    },
                )
            )
            assert filler["status"] == "completed"
            assert filler["output"]["totalBytes"] == 268_369_920
            filler_uri = cast(str, filler["artifacts"][0]["uri"])
        try:
            await client.read_resource(cast(str, raw["uri"]))
        except MCPError as error:
            assert error.message == "resource not found"
        else:
            raise AssertionError("quota eviction did not revoke the oldest bundle")
        filler_manifest_mime, _ = await read_resource(client, filler_uri)
        assert filler_manifest_mime == "application/vnd.amkernel.artifact-manifest+json"
        metrics_after = process_metrics(server_pid)
        before_values = metrics_before
        after_values = metrics_after
        assert after_values["rssBytes"] <= SERVER_RSS_BOUND_BYTES
        assert after_values["openFiles"] - before_values["openFiles"] <= 16
        assert after_values["openFiles"] <= 128
        assert after_values["taskCount"] - before_values["taskCount"] <= 4
        assert after_values["taskCount"] <= 32
        assert before_values["childProcessCount"] == 1
        assert after_values["childProcessCount"] == 1

        plateau_filler, _ = structured_rich(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import os\nchunk = b'e' * 65536\nfor _ in range(4095): os.write(1, chunk)"
                    ),
                    "timeout": 20.0,
                },
            )
        )
        assert plateau_filler["status"] == "completed"
        plateau_values = process_metrics(server_pid)
        assert plateau_values["rssBytes"] <= SERVER_RSS_BOUND_BYTES
        assert plateau_values["rssBytes"] - after_values["rssBytes"] <= 67_108_864
        assert plateau_values["openFiles"] - after_values["openFiles"] <= 4
        assert plateau_values["taskCount"] - after_values["taskCount"] <= 2
        assert plateau_values["childProcessCount"] == 1

        tamper_source, _ = structured_rich(
            await client.call_tool("python_exec", {"code": "artifact('tamper.bin', b'original')"})
        )
        tamper_uri = cast(str, tamper_source["artifacts"][0]["uri"])
        artifact_id = tamper_uri.rsplit("/", 1)[-1]
        tampered = structured(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import glob, os, tempfile\n"
                        f"matches = glob.glob(os.path.join(tempfile.gettempdir(), "
                        f"'amkernel-*', 'bundle-*', 'artifact-{artifact_id}', 'part-0'))\n"
                        "if len(matches) == 1:\n"
                        "    os.chmod(matches[0], 0o600)\n"
                        "    with open(matches[0], 'r+b') as resource:\n"
                        "        resource.write(b'X')\n"
                        "len(matches)"
                    )
                },
            )
        )
        assert tampered["status"] == "completed", tampered
        assert tampered["result"] == 1
        try:
            await client.read_resource(tamper_uri)
        except MCPError as error:
            assert error.message == "resource integrity failure"
            assert "part-0" not in str(error)
        else:
            raise AssertionError("tampered resource remained readable")

        stage2_reset = structured(
            await client.call_tool("python_exec", {"code": "42", "reset": True})
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
                "python_exec", {"code": "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)"}
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
        cleanup_anchor, _ = structured_rich(
            await client.call_tool(
                "python_exec",
                {"code": "_ = artifact('cleanup-anchor.txt', 'anchor')\n'cleanup-anchor'"},
            )
        )
        cleanup_uri = cast(str, cleanup_anchor["artifacts"][0]["uri"])
        cleanup_artifact_id = cleanup_uri.rsplit("/", 1)[-1]
        cleanup_refusal = structured(
            await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import glob, os, tempfile\n"
                        f"matches = glob.glob(os.path.join(tempfile.gettempdir(), '**', "
                        f"'artifact-{cleanup_artifact_id}', 'part-*'), recursive=True)\n"
                        "assert len(matches) == 1\n"
                        "root = os.path.dirname(os.path.dirname(os.path.dirname(matches[0])))\n"
                        "with open(os.path.join(root, 'foreign'), 'wb') as unexpected:\n"
                        "    unexpected.write(b'retain')\n"
                        "write('cleanup-root.txt', root)\n"
                        "True"
                    )
                },
            )
        )

        expected_runtime: dict[str, Any] = {
            "executable": os.path.abspath(sys.executable),
            "pythonVersion": platform.python_version(),
            "workingDirectory": str(workspace.resolve()),
            "environmentKind": "project_venv",
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "packages": [],
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
        assert diagnostics["status"] == "completed"
        assert diagnostics["runtime"]["packages"][0]["name"] == "amkernel"
        assert diagnostics["runtime"]["packages"][0]["version"]
        assert diagnostics["runtime"]["packages"][1]["name"] == "Pillow"
        assert diagnostics["runtime"]["packages"][1]["version"]
        assert diagnostics["runtime"]["packages"][2] == {
            "name": "Definitely-Not-Installed-AMKernel",
            "error": "not installed",
        }
        assert helpers["result"] == "helpers"
        assert helpers["displays"][0]["value"] == ["hello", "persisted", None]
        assert_execution(
            stage2_reset,
            status="completed",
            kernel_state="alive",
            execution_count=1,
            runtime=expected_runtime,
            result=42,
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
        assert cleanup_anchor["status"] == "completed"
        assert cleanup_anchor["kernelState"] == "alive"
        assert cleanup_anchor["executionCount"] == 3
        assert cleanup_anchor["runtime"] == expected_runtime
        assert cleanup_anchor["result"] == "cleanup-anchor"
        assert cleanup_anchor["artifacts"][0]["name"] == "cleanup-anchor.txt"
        assert_execution(
            cleanup_refusal,
            status="completed",
            kernel_state="alive",
            execution_count=4,
            runtime=expected_runtime,
            result=True,
        )
        results = {
            "initialized": initialized,
            "persisted": persisted,
            "failed": failed,
            "afterError": after_error,
            "reset": reset,
            "diagnostics": diagnostics,
            "helpers": helpers,
            "rich": rich,
            "progress": progress,
            "progressCallbackFailure": callback_failure,
            "jsonFloodCount": len(json_flood["displays"]),
            "artifactFloodCount": len(artifact_flood["artifacts"]),
            "manifestPartsVerified": 32,
            "measurements": {
                "before": before_values,
                "after": after_values,
                "plateau": plateau_values,
                "rssBoundBytes": SERVER_RSS_BOUND_BYTES,
                "storedItemBoundary": len(artifact_flood["artifacts"]),
                "resultJsonBytes": len(
                    json.dumps(limited, sort_keys=True, separators=(",", ":")).encode()
                ),
            },
            "rasterVariants": raster_variants,
            "evictionProved": True,
            "outputLimited": limited,
            "tamperRefused": True,
            "stage2Reset": stage2_reset,
            "timedOut": timed_out,
            "afterTimeout": after_timeout,
            "deathChild": death_child,
            "killed": killed,
            "unavailable": unavailable,
            "recovered": recovered,
            "shutdownChild": shutdown_child,
            "cleanupRefusal": cleanup_refusal,
            "cleanupAnchor": cleanup_anchor,
        }

    assert death_child_pid is not None
    assert shutdown_child_pid is not None
    await wait_pid_gone(shutdown_child_pid)
    refused_root = Path((workspace / "cleanup-root.txt").read_text())
    assert (refused_root / "foreign").read_bytes() == b"retain"
    shutil.rmtree(refused_root)

    async with Client(parameters, read_timeout_seconds=60.0) as fresh_client:
        fresh_tools = await fresh_client.list_tools()
        assert [tool.name for tool in fresh_tools.tools] == ["python_exec"]
        try:
            await fresh_client.read_resource(cleanup_uri)
        except MCPError as error:
            assert error.message == "resource not found"
        else:
            raise AssertionError("resource URI survived its owning server process")

    return {
        "tool": "python_exec",
        "results": results,
        "runtime": expected_runtime,
        "progressEvents": len(progress_messages),
        "deathChildCleaned": not pid_exists(death_child_pid),
        "shutdownChildCleaned": not pid_exists(shutdown_child_pid),
        "cleanupRefused": True,
        "freshProcessInvalidation": True,
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
            arguments.schema_fixture.absolute(),
        )
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

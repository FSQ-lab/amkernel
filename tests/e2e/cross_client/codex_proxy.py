from __future__ import annotations

import argparse
import base64
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _uris(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if value.startswith("amkernel://"):
            found.add(value)
    elif isinstance(value, dict):
        for child in value.values():
            found.update(_uris(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_uris(child))
    return found


def _write_resource(root: Path, index: int, uri: str, result: dict[str, Any]) -> dict[str, Any]:
    contents = result.get("contents")
    if not isinstance(contents, list) or len(contents) != 1 or not isinstance(contents[0], dict):
        raise RuntimeError(f"unexpected resources/read result for {uri}")
    content = contents[0]
    if isinstance(content.get("blob"), str):
        payload = base64.b64decode(content["blob"], validate=True)
        encoding = "blob"
    elif isinstance(content.get("text"), str):
        payload = content["text"].encode("utf-8")
        encoding = "text"
    else:
        raise RuntimeError(f"resource has neither blob nor text: {uri}")
    name = f"resource-{index:02d}.bin"
    (root / name).write_bytes(payload)
    return {
        "uri": uri,
        "mimeType": content.get("mimeType"),
        "encoding": encoding,
        "path": name,
        "sizeBytes": len(payload),
    }


def serve(server: Path, cwd: Path, capture: Path) -> int:
    capture.mkdir(parents=True, exist_ok=False)
    child = subprocess.Popen(
        [str(server)],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    assert child.stderr is not None
    child_stdout = child.stdout
    child_stderr = child.stderr

    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    observed_uris: set[str] = set()
    forward = threading.Event()
    forward.set()

    def read_server() -> None:
        while line := child_stdout.readline():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                observed_uris.update(_uris(message))
                messages.put(message)
            if forward.is_set():
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()

    stderr_chunks: list[bytes] = []

    def read_stderr() -> None:
        while chunk := child_stderr.read(65536):
            stderr_chunks.append(chunk)

    stdout_thread = threading.Thread(target=read_server, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    try:
        while line := sys.stdin.buffer.readline():
            child.stdin.write(line)
            child.stdin.flush()
    finally:
        forward.clear()

    time.sleep(0.15)
    while True:
        try:
            messages.get_nowait()
        except queue.Empty:
            break

    resources: list[dict[str, Any]] = []
    pending = sorted(observed_uris)
    read_uris: set[str] = set()
    request_id = 1_000_000
    while pending:
        uri = pending.pop(0)
        if uri in read_uris:
            continue
        read_uris.add(uri)
        request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "resources/read",
            "params": {"uri": uri},
        }
        child.stdin.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        child.stdin.flush()
        deadline = time.monotonic() + 10
        response: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                candidate = messages.get(timeout=0.2)
            except queue.Empty:
                if child.poll() is not None:
                    break
                continue
            if candidate.get("id") == request_id:
                response = candidate
                break
        if response is None or not isinstance(response.get("result"), dict):
            raise RuntimeError(f"resources/read failed for {uri}: {response!r}")
        record = _write_resource(capture, len(resources), uri, response["result"])
        resources.append(record)
        payload = (capture / record["path"]).read_bytes()
        if record["mimeType"] == "application/json":
            try:
                parsed = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            for discovered in sorted(_uris(parsed)):
                if discovered not in read_uris:
                    pending.append(discovered)

    child.stdin.close()
    return_code = child.wait(timeout=10)
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    (capture / "resources.json").write_text(
        json.dumps(resources, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (capture / "server.json").write_text(
        json.dumps(
            {
                "returnCode": return_code,
                "stderr": b"".join(stderr_chunks).decode("utf-8", errors="replace")[-8192:],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    return serve(args.server, args.cwd, args.capture)


if __name__ == "__main__":
    raise SystemExit(main())

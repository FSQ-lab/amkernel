from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

import amkernel.output as output_module
from amkernel.artifact_store import ArtifactBundle, ArtifactStoreError
from amkernel.protocol import MAX_STRUCTURED_RESULT_BYTES
from amkernel.runtime import KernelRuntime
from amkernel.server import _structured_result
from amkernel.structured_output import StructuredOutputError

pytestmark = pytest.mark.anyio


async def test_helpers_emit_ordered_json_artifact_and_image(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            """
import io
from PIL import Image

data = {"answer": [42, True]}
display(data)
data["answer"][0] = 0
artifact("note.txt", "hello")
buffer = io.BytesIO()
Image.new("RGB", (2, 3), "red").save(buffer, format="PNG")
display(buffer.getvalue(), mime_type="image/png")
"done"
"""
        )
        assert result.status == "completed"
        assert result.result == "done"
        assert [item.sequence for item in result.output.displays] == [1, 2, 3]
        assert [item.kind for item in result.output.displays] == ["json", "artifact", "image"]
        assert result.output.displays[0].value == {"answer": [42, True]}
        image = result.output.displays[2]
        assert image.image is not None
        assert (image.image.width, image.image.height, image.image.frames) == (2, 3, 1)
        assert [artifact.name for artifact in result.output.artifacts] == ["note.txt", "image"]
        resources = [
            await runtime.read_resource(artifact.uri) for artifact in result.output.artifacts
        ]
        assert resources[0].data == b"hello"
        with Image.open(io.BytesIO(resources[1].data)) as decoded:
            assert decoded.size == (2, 3)
    finally:
        assert (await runtime.shutdown()).cleaned


@pytest.mark.parametrize(
    "expression",
    [
        "display(float('nan'))",
        "display({1: 'not a string key'})",
        "value=[]; value.append(value); display(value)",
        "display(object())",
    ],
)
async def test_invalid_json_is_a_user_error_and_preserves_prior_items(
    tmp_path: Path, expression: str
) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(f'display("retained")\n{expression}')
        assert result.status == "failed"
        assert result.kernel_state == "alive"
        assert result.error is not None
        assert result.error.type == "amkernel.structured_output.DisplayError"
        assert [item.value for item in result.output.displays] == ["retained"]
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_helper_count_limits_preserve_completed_items(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        json_result = await runtime.execute("for value in range(65): display(value)")
        assert json_result.status == "failed"
        assert len(json_result.output.displays) == 64

        artifact_result = await runtime.execute(
            "for value in range(65): artifact(f'{value}.txt', '')"
        )
        assert artifact_result.status == "failed"
        assert len(artifact_result.output.artifacts) == 64

        image_result = await runtime.execute(
            """
import io
from PIL import Image
buffer = io.BytesIO()
Image.new("RGB", (1, 1)).save(buffer, format="PNG")
for value in range(17):
    display(buffer.getvalue(), mime_type="image/png")
"""
        )
        assert image_result.status == "failed"
        assert len(image_result.output.displays) == 16
        assert len(image_result.output.artifacts) == 16
        assert image_result.kernel_state == "alive"
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_image_rejects_trailing_bytes_and_mime_mismatch(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        trailing = await runtime.execute(
            """
import io
from PIL import Image
buffer = io.BytesIO()
Image.new("RGB", (1, 1)).save(buffer, format="PNG")
display(buffer.getvalue() + b"trailing", mime_type="image/png")
"""
        )
        mismatch = await runtime.execute(
            """
import io
from PIL import Image
buffer = io.BytesIO()
Image.new("RGB", (1, 1)).save(buffer, format="JPEG")
display(buffer.getvalue(), mime_type="image/png")
"""
        )
        for result in (trailing, mismatch):
            assert result.status == "failed"
            assert result.kernel_state == "alive"
            assert result.error is not None
            assert result.error.type == "amkernel.structured_output.DisplayError"
            assert result.output.displays == ()
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_host_image_validation_failure_is_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_host_image(data: object, mime_type: str) -> None:
        del data, mime_type
        raise StructuredOutputError("injected Host rejection")

    monkeypatch.setattr(output_module, "validate_safe_artifact", reject_host_image)
    runtime = KernelRuntime(tmp_path)
    result = await runtime.execute(
        """
import io
from PIL import Image
buffer = io.BytesIO()
Image.new("RGB", (1, 1)).save(buffer, format="PNG")
display(buffer.getvalue(), mime_type="image/png")
"""
    )
    assert result.status == "kernel_killed"
    assert result.kernel_state == "dead"
    assert result.error is not None
    assert result.error.type == "ArtifactStoreError"
    assert result.error.message == "execution output storage failed"
    assert result.output.displays == ()
    assert (await runtime.shutdown()).cleaned


async def test_artifact_safe_mime_requires_validated_content(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            """
artifact("inferred.txt", "safe text")
artifact("opaque.html", b"<b>opaque</b>", mime_type="text/html")
"""
        )
        inferred, opaque = result.output.artifacts
        assert inferred.mime_type == "text/plain; charset=utf-8"
        assert opaque.declared_mime_type == "text/html"
        assert opaque.mime_type == "application/octet-stream"

        downgraded = await runtime.execute(
            'artifact("claimed.png", b"not an image", mime_type="image/png")'
        )
        assert downgraded.status == "completed"
        claimed = downgraded.output.artifacts[0]
        assert claimed.declared_mime_type == "image/png"
        assert claimed.mime_type == "application/octet-stream"
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_terminal_capacity_covers_replacement_expansion_and_final_result(
    tmp_path: Path,
) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            """
import os
os.write(1, b'\\xff' * 262_144)
os.write(2, b'\\xff' * 262_144)
display('d' * 900_000)
'r' * 1_000_000
"""
        )
        assert result.status == "completed"
        encoded = json.dumps(
            _structured_result(result),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        assert len(encoded) <= MAX_STRUCTURED_RESULT_BYTES
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_publish_failure_exposes_no_unpublished_artifact_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_publish(self: ArtifactBundle) -> tuple[object, ...]:
        del self
        raise ArtifactStoreError("injected publish failure")

    monkeypatch.setattr(ArtifactBundle, "publish", fail_publish)
    runtime = KernelRuntime(tmp_path)
    result = await runtime.execute(
        'display("retained json")\nartifact("unpublished.txt", "hidden")'
    )
    assert result.status == "kernel_killed"
    assert result.output.displays[0].value == "retained json"
    assert len(result.output.displays) == 1
    assert result.output.artifacts == ()
    assert (await runtime.shutdown()).cleaned


async def test_artifact_transaction_stays_atomic_across_deadline(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        prepared = await runtime.execute("payload = b'x' * (32 * 1024 * 1024)")
        assert prepared.status == "completed"
        interrupted = await runtime.execute('artifact("large.bin", payload)', timeout=0.001)
        assert interrupted.status in {"timed_out", "interrupted"}
        assert interrupted.kernel_state == "alive"
        assert len(interrupted.output.artifacts) in {0, 1}
        assert (await runtime.execute("42")).result == 42
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_helper_signatures_shadowing_persistence_and_reset(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        signatures = await runtime.execute(
            """
import inspect
[
    str(inspect.signature(display)),
    str(inspect.signature(artifact)),
]
"""
        )
        assert signatures.result == [
            "(value: 'object', *, mime_type: 'str | None' = None) -> 'None'",
            "(name: 'str', content: 'object', *, mime_type: 'str | None' = None) -> 'None'",
        ]
        assert (await runtime.execute("display = 'shadowed'\ndisplay")).result == "shadowed"
        assert (await runtime.execute("display")).result == "shadowed"
        restored = await runtime.execute("callable(display)", reset=True)
        assert restored.status == "completed"
        assert restored.result is True
    finally:
        assert (await runtime.shutdown()).cleaned

from __future__ import annotations

import io
import mmap
import tempfile

import pytest
from PIL import Image

import amkernel.structured_output as structured
from amkernel.structured_output import StructuredOutputError, validate_image


def _image_bytes(format_name: str, *, frames: int = 1, size: tuple[int, int] = (2, 3)) -> bytes:
    buffer = io.BytesIO()
    images = [Image.new("RGB", size, (index, 0, 0)) for index in range(frames)]
    options: dict[str, object] = {}
    if frames > 1:
        options = {"save_all": True, "append_images": images[1:]}
    images[0].save(buffer, format=format_name, **options)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("format_name", "mime_type"),
    [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
    ],
)
def test_complete_image_formats_decode_with_exact_extent(format_name: str, mime_type: str) -> None:
    data = _image_bytes(format_name)
    info = validate_image(data, mime_type)
    assert (info.width, info.height, info.frames, info.pixel_frames) == (2, 3, 1, 6)

    with pytest.raises(StructuredOutputError):
        validate_image(data + b"trailing", mime_type)
    with pytest.raises(StructuredOutputError):
        validate_image(data[:-1], mime_type)

    with tempfile.TemporaryFile() as artifact:
        artifact.write(data)
        artifact.flush()
        with mmap.mmap(artifact.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            mapped_info = validate_image(mapped, mime_type)
    assert (mapped_info.width, mapped_info.height, mapped_info.frames) == (2, 3, 1)


@pytest.mark.parametrize(
    ("format_name", "claimed_mime"),
    [("PNG", "image/jpeg"), ("JPEG", "image/gif"), ("GIF", "image/webp")],
)
def test_image_claimed_mime_must_match_container(format_name: str, claimed_mime: str) -> None:
    with pytest.raises(StructuredOutputError):
        validate_image(_image_bytes(format_name), claimed_mime)


def test_image_dimension_frame_and_cumulative_pixel_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(structured, "MAX_IMAGE_DIMENSION", 1)
    with pytest.raises(StructuredOutputError, match="dimensions"):
        validate_image(_image_bytes("PNG", size=(2, 1)), "image/png")

    monkeypatch.setattr(structured, "MAX_IMAGE_DIMENSION", 16_384)
    monkeypatch.setattr(structured, "MAX_IMAGE_FRAMES", 1)
    animated = _image_bytes("GIF", frames=2)
    with pytest.raises(StructuredOutputError, match="frame count"):
        validate_image(animated, "image/gif")

    monkeypatch.setattr(structured, "MAX_IMAGE_FRAMES", 1_024)
    monkeypatch.setattr(structured, "MAX_IMAGE_PIXEL_FRAMES", 10)
    with pytest.raises(StructuredOutputError, match="cumulative pixels"):
        validate_image(animated, "image/gif")


def test_image_decode_warning_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 4)
    with pytest.raises(StructuredOutputError, match="validation failed"):
        validate_image(_image_bytes("PNG"), "image/png")

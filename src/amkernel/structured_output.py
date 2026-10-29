"""Strict structured-output coercion and complete raster validation."""

from __future__ import annotations

import io
import json
import mmap
import struct
import warnings
import zlib
from dataclasses import dataclass
from typing import BinaryIO, Final, Literal, cast

from PIL import Image
from PIL.Image import DecompressionBombError

from amkernel.protocol import (
    IMAGE_MIME_TYPES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_FRAMES,
    MAX_IMAGE_PIXEL_FRAMES,
    SAFE_MIME_TYPES,
    JsonValue,
    ProtocolViolation,
    snapshot_json,
)

ImageMime = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
ImageData = bytes | mmap.mmap
_IMAGE_FORMATS: Final[dict[str, ImageMime]] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


class StructuredOutputError(ValueError):
    """A user structured-output value violates the public helper contract."""


class DisplayError(StructuredOutputError):
    """A display value is invalid or exceeds a display bound."""


class ArtifactError(StructuredOutputError):
    """An explicit artifact value is invalid or exceeds an artifact bound."""


@dataclass(frozen=True, slots=True)
class ImageInfo:
    width: int
    height: int
    frames: int
    pixel_frames: int


class _MmapImageReader:
    """Expose one mmap with ordinary file seek semantics without copying it whole."""

    __slots__ = ("_data", "_position")

    def __init__(self, data: mmap.mmap) -> None:
        self._data = data
        self._position = 0

    def read(self, size: int = -1) -> bytes:
        if self._position >= len(self._data):
            return b""
        end = len(self._data) if size < 0 else min(len(self._data), self._position + size)
        value = self._data[self._position : end]
        self._position = end
        return value

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self._position + offset
        elif whence == io.SEEK_END:
            position = len(self._data) + offset
        else:
            raise ValueError("unsupported seek origin")
        if position < 0:
            raise ValueError("negative seek position")
        self._position = position
        return position

    def tell(self) -> int:
        return self._position


def strict_json(value: object, maximum_bytes: int) -> JsonValue:
    """Detach a strict JSON value and translate protocol failures for user code."""
    try:
        return snapshot_json(cast(JsonValue, value), maximum_bytes)
    except ProtocolViolation as error:
        raise StructuredOutputError(str(error)) from error


def bytes_like(value: object) -> bytes:
    """Copy one ordinary contiguous bytes-like value."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        try:
            return bytes(value)
        except (TypeError, ValueError) as error:
            raise StructuredOutputError("content must be a contiguous bytes-like value") from error
    raise StructuredOutputError("content must be bytes-like")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def validate_safe_artifact(data: ImageData, mime_type: str) -> ImageInfo | None:
    """Validate content before advertising one allowlisted serving MIME."""
    if mime_type not in SAFE_MIME_TYPES:
        return None
    if mime_type in IMAGE_MIME_TYPES:
        return validate_image(data, mime_type)
    raw = data[:] if isinstance(data, mmap.mmap) else data
    try:
        text = raw.decode("utf-8", errors="strict")
        if mime_type == "application/json":
            value = json.loads(text, parse_constant=_reject_json_constant)
            snapshot_json(cast(JsonValue, value), len(raw))
    except (UnicodeError, ValueError, RecursionError, ProtocolViolation) as error:
        raise StructuredOutputError("artifact content does not match its safe MIME type") from error
    return None


def validate_image(data: ImageData, claimed_mime: str) -> ImageInfo:
    """Prove exact container extent and fully decode every bounded raster frame."""
    if claimed_mime not in IMAGE_MIME_TYPES:
        raise StructuredOutputError("unsupported image MIME type")
    try:
        _validate_container(data, cast(ImageMime, claimed_mime))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            source = (
                cast(BinaryIO, _MmapImageReader(data))
                if isinstance(data, mmap.mmap)
                else io.BytesIO(data)
            )
            with Image.open(source) as image:
                observed_mime = _IMAGE_FORMATS.get(image.format or "")
                if observed_mime != claimed_mime:
                    raise StructuredOutputError("image MIME type does not match the decoded format")
                frames = 0
                pixel_frames = 0
                first_width = 0
                first_height = 0
                while True:
                    try:
                        image.seek(frames)
                    except EOFError:
                        break
                    width, height = image.size
                    if not (
                        1 <= width <= MAX_IMAGE_DIMENSION and 1 <= height <= MAX_IMAGE_DIMENSION
                    ):
                        raise StructuredOutputError("image dimensions exceed the supported bound")
                    if frames == 0:
                        first_width, first_height = width, height
                    frames += 1
                    if frames > MAX_IMAGE_FRAMES:
                        raise StructuredOutputError("image frame count exceeds the supported bound")
                    pixel_frames += width * height
                    if pixel_frames > MAX_IMAGE_PIXEL_FRAMES:
                        raise StructuredOutputError(
                            "image cumulative pixels exceed the supported bound"
                        )
                    image.load()
                if frames == 0:
                    raise StructuredOutputError("image contains no decodable frame")
                return ImageInfo(first_width, first_height, frames, pixel_frames)
    except StructuredOutputError:
        raise
    except (OSError, ValueError, SyntaxError, Warning, DecompressionBombError) as error:
        raise StructuredOutputError("image validation failed") from error


def _validate_container(data: ImageData, mime: ImageMime) -> None:
    if mime == "image/png":
        _validate_png(data)
    elif mime == "image/jpeg":
        _validate_jpeg(data)
    elif mime == "image/gif":
        _validate_gif(data)
    else:
        _validate_webp(data)


def _validate_png(data: ImageData) -> None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise StructuredOutputError("invalid PNG container")
    offset = 8
    first = True
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise StructuredOutputError("truncated PNG container")
        expected_crc = int.from_bytes(data[offset + 8 + length : end], "big")
        observed_crc = zlib.crc32(data[offset + 4 : offset + 8 + length]) & 0xFFFFFFFF
        if observed_crc != expected_crc:
            raise StructuredOutputError("PNG chunk checksum mismatch")
        if first and kind != b"IHDR":
            raise StructuredOutputError("PNG IHDR is not first")
        first = False
        offset = end
        if kind == b"IEND":
            if length != 0 or offset != len(data):
                raise StructuredOutputError("PNG does not end exactly at IEND")
            return
    raise StructuredOutputError("PNG has no terminal IEND")


def _validate_jpeg(data: ImageData) -> None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise StructuredOutputError("invalid JPEG container")
    offset = 2
    in_scan = False
    while offset < len(data):
        if not in_scan:
            if data[offset] != 0xFF:
                raise StructuredOutputError("invalid JPEG marker stream")
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
        else:
            marker_start = data.find(b"\xff", offset)
            if marker_start < 0:
                break
            offset = marker_start + 1
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                continue
            in_scan = False
        if marker == 0xD9:
            if offset != len(data):
                raise StructuredOutputError("JPEG does not end exactly at EOI")
            return
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if offset + 2 > len(data):
            break
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            raise StructuredOutputError("truncated JPEG segment")
        offset += length
        if marker == 0xDA:
            in_scan = True
    raise StructuredOutputError("JPEG has no terminal EOI")


def _validate_gif(data: ImageData) -> None:
    if len(data) < 13 or data[:6] not in {b"GIF87a", b"GIF89a"}:
        raise StructuredOutputError("invalid GIF container")
    packed = data[10]
    offset = 13 + (3 * (2 << (packed & 7)) if packed & 0x80 else 0)
    while offset < len(data):
        introducer = data[offset]
        offset += 1
        if introducer == 0x3B:
            if offset != len(data):
                raise StructuredOutputError("GIF does not end exactly at trailer")
            return
        if introducer == 0x21:
            if offset >= len(data):
                break
            offset += 1
            offset = _skip_subblocks(data, offset)
        elif introducer == 0x2C:
            if offset + 9 > len(data):
                break
            local_packed = data[offset + 8]
            offset += 9
            if local_packed & 0x80:
                offset += 3 * (2 << (local_packed & 7))
            if offset >= len(data):
                break
            offset += 1
            offset = _skip_subblocks(data, offset)
        else:
            raise StructuredOutputError("invalid GIF block")
    raise StructuredOutputError("GIF has no terminal trailer")


def _skip_subblocks(data: ImageData, offset: int) -> int:
    while offset < len(data):
        size = data[offset]
        offset += 1
        if size == 0:
            return offset
        offset += size
        if offset > len(data):
            break
    raise StructuredOutputError("truncated GIF sub-block")


def _validate_webp(data: ImageData) -> None:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise StructuredOutputError("invalid WebP container")
    declared = struct.unpack_from("<I", data, 4)[0]
    if declared + 8 != len(data):
        raise StructuredOutputError("WebP RIFF length does not end exactly at EOF")
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise StructuredOutputError("truncated WebP chunk")
        size = struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8 + size + (size & 1)
        if offset > len(data):
            raise StructuredOutputError("truncated WebP chunk")
    if offset != len(data):
        raise StructuredOutputError("invalid WebP chunk alignment")

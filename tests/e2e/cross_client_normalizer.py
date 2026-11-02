from __future__ import annotations

import hashlib
import json
from typing import Any, cast
from urllib.parse import urlsplit


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def request_projection(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Project a request into a privacy-safe, byte-measurable representation."""
    return {"arguments": _project_value(arguments), "toolName": tool_name}


def normalize_request(tool_name: str, arguments: dict[str, Any]) -> int:
    """Return the canonical byte count for one privacy-safe request projection."""
    return len(canonical_json_bytes(request_projection(tool_name, arguments)))


def _project_value(value: Any) -> Any:
    if isinstance(value, dict):
        properties = [
            {"nameSha256": hashlib.sha256(key.encode()).hexdigest(), "value": _project_value(item)}
            for key, item in value.items()
        ]
        return {
            "properties": sorted(properties, key=lambda item: item["nameSha256"]),
            "type": "object",
        }
    if isinstance(value, list):
        return {"items": [_project_value(item) for item in value], "type": "array"}
    if isinstance(value, str):
        encoded = value.encode()
        return {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "type": "string",
            "utf8Bytes": len(encoded),
        }
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, (int, float)):
        return {"type": "number", "value": value}
    raise TypeError(f"unsupported request value: {type(value).__name__}")


def valid_request_projection(projection: Any) -> bool:
    """Return whether a retained request projection contains projected values only."""
    return (
        isinstance(projection, dict)
        and set(projection) == {"arguments", "toolName"}
        and projection["toolName"] == "python_exec"
        and _valid_projected_value(projection["arguments"])
    )


def _valid_projected_value(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("type") == "object":
        return (
            set(value) == {"properties", "type"}
            and isinstance(value["properties"], list)
            and all(
                isinstance(item, dict)
                and set(item) == {"nameSha256", "value"}
                and isinstance(item["nameSha256"], str)
                and len(item["nameSha256"]) == 64
                and all(character in "0123456789abcdef" for character in item["nameSha256"])
                and _valid_projected_value(item["value"])
                for item in value["properties"]
            )
            and len({item["nameSha256"] for item in value["properties"]})
            == len(value["properties"])
            and value["properties"]
            == sorted(value["properties"], key=lambda item: item["nameSha256"])
        )
    if value.get("type") == "array":
        return (
            set(value) == {"items", "type"}
            and isinstance(value["items"], list)
            and all(_valid_projected_value(item) for item in value["items"])
        )
    if value.get("type") == "string":
        return (
            set(value) == {"sha256", "type", "utf8Bytes"}
            and isinstance(value["sha256"], str)
            and len(value["sha256"]) == 64
            and all(character in "0123456789abcdef" for character in value["sha256"])
            and isinstance(value["utf8Bytes"], int)
            and not isinstance(value["utf8Bytes"], bool)
            and value["utf8Bytes"] >= 0
        )
    if value.get("type") == "null":
        return set(value) == {"type"}
    if value.get("type") == "boolean":
        return set(value) == {"type", "value"} and isinstance(value["value"], bool)
    if value.get("type") == "number":
        return (
            set(value) == {"type", "value"}
            and isinstance(value["value"], (int, float))
            and not isinstance(value["value"], bool)
        )
    return False


def normalize_event(event: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Normalize one client event using the frozen, client-neutral policy."""
    retained = cast(list[str], policy["retainedEventFields"])
    derived = {
        "normalizedBytes",
        "resultSha256",
        "resourceUriSha256",
        "resourceScheme",
        "resourceMimeType",
    }
    normalized = {key: event[key] for key in retained if key in event and key not in derived}
    measured = dict(normalized)
    if "result" in event:
        measured["result"] = event["result"]
        normalized["resultSha256"] = hashlib.sha256(
            canonical_json_bytes(event["result"])
        ).hexdigest()
    if "resourceUri" in event:
        uri = cast(str, event["resourceUri"])
        measured["resourceUri"] = uri
        normalized["resourceUriSha256"] = hashlib.sha256(uri.encode()).hexdigest()
        normalized["resourceScheme"] = urlsplit(uri).scheme
        normalized["resourceMimeType"] = cast(str, event["mimeType"])
        normalized["resourceSizeBytes"] = cast(int, event["resourceSizeBytes"])
    normalized["normalizedBytes"] = len(canonical_json_bytes(measured))
    return normalized

"""Verify that an existing GitHub Release is the immutable expected record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class GitHubReleaseError(RuntimeError):
    """An existing GitHub Release differs from the expected release record."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GitHubReleaseError(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise GitHubReleaseError(f"expected a JSON object in {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(
    release_json: Path,
    notes: Path,
    asset_dir: Path,
    tag: str,
    title: str,
    wheel: str,
    sha256: str,
) -> None:
    """Reject any metadata, asset-set, or content difference."""
    release = _object(release_json)
    expected = {
        "tagName": tag,
        "name": title,
        "body": notes.read_text(encoding="utf-8"),
        "isDraft": False,
        "isPrerelease": False,
    }
    for field, value in expected.items():
        if release.get(field) != value:
            raise GitHubReleaseError(
                f"existing release {field} must be {value!r}, got {release.get(field)!r}"
            )
    assets = release.get("assets")
    if not isinstance(assets, list) or len(assets) != 1:
        count = len(assets) if isinstance(assets, list) else "non-list"
        raise GitHubReleaseError(f"existing release must have exactly one asset, got {count}")
    asset = assets[0]
    if not isinstance(asset, dict) or asset.get("name") != wheel:
        raise GitHubReleaseError(f"existing release asset must be {wheel!r}")
    downloaded = asset_dir / wheel
    if not downloaded.is_file():
        raise GitHubReleaseError(f"downloaded release asset is missing: {downloaded}")
    actual = _sha256(downloaded)
    if actual != sha256:
        raise GitHubReleaseError(f"existing release wheel SHA-256 must be {sha256}, got {actual}")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    try:
        verify(
            args.release_json,
            args.notes,
            args.asset_dir,
            args.tag,
            args.title,
            args.wheel,
            args.sha256,
        )
    except (OSError, UnicodeError, GitHubReleaseError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

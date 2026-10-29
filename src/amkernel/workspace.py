"""Descriptor-confined workspace and environment prelude helpers.

These helpers are a safe default for generated code, not a sandbox. User Python
retains unrestricted access to ordinary same-user filesystem and process APIs.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from dataclasses import dataclass
from typing import Final, cast

MAX_READ_BYTES: Final = 67_108_864
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class WorkspaceError(ValueError):
    """A confined workspace operation is invalid or unsafe."""


class ReadError(WorkspaceError):
    """A confined read could not safely return a regular file."""


class ReadLimitError(ReadError):
    """A regular file exceeds the requested read limit."""


class WriteError(WorkspaceError):
    """A confined atomic write could not safely replace a regular file."""


class EnvError(ValueError):
    """An environment helper argument is invalid."""


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


@dataclass(frozen=True, slots=True)
class _RootIdentity:
    device: int
    inode: int


class Workspace:
    """Pin one launch directory and create fresh callable prelude helpers."""

    def __init__(self, launch_directory: str) -> None:
        self._require_platform_support()
        canonical = launch_directory
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            descriptor = os.open(".", flags)
            metadata = os.fstat(descriptor)
        except OSError as error:
            raise WorkspaceError("workspace initialization failed") from error
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            raise WorkspaceError("workspace root is not a regular directory")
        self._canonical = canonical
        self._descriptor = descriptor
        self._identity = _RootIdentity(metadata.st_dev, metadata.st_ino)

    def close(self) -> None:
        descriptor = self._descriptor
        if descriptor < 0:
            return
        self._descriptor = -1
        os.close(descriptor)

    def helpers(self) -> tuple[ReadHelper, WriteHelper, EnvHelper]:
        return ReadHelper(self), WriteHelper(self), EnvHelper()

    def read(self, path: object, *, binary: bool, limit: int) -> str | bytes:
        if type(binary) is not bool:
            raise ReadError("binary must be a boolean")
        if type(limit) is not int or not 0 <= limit <= MAX_READ_BYTES:
            raise ReadError("limit must be an integer from 0 through 67108864")
        parent, name = self._open_parent(path, ReadError)
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent,
            )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ReadError("read target is not a regular file")
            remaining = limit + 1
            data = bytearray()
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                data.extend(chunk)
                remaining -= len(chunk)
            if len(data) > limit:
                raise ReadLimitError("read target exceeds limit")
            raw = bytes(data)
            if binary:
                return raw
            try:
                return raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise ReadError("read target is not valid UTF-8") from error
        except ReadError:
            raise
        except OSError as error:
            raise ReadError("workspace read failed") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)

    def write(self, path: object, content: object) -> int:
        data = self._write_bytes(content)
        parent, name = self._open_parent(path, WriteError)
        temporary = f".amkernel-write-{secrets.token_hex(16)}"
        descriptor = -1
        temporary_created = False
        try:
            before = self._destination_identity(parent, name)
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            temporary_created = True
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise WriteError("workspace write made no progress")
                view = view[written:]
            os.fchmod(descriptor, 0o600)
            os.close(descriptor)
            descriptor = -1
            if self._destination_identity(parent, name) != before:
                raise WriteError("write destination changed during replacement")
            os.rename(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            temporary = ""
            final = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(final.st_mode):
                raise WriteError("write destination is not a regular file")
            return len(data)
        except WriteError:
            raise
        except OSError as error:
            raise WriteError("workspace write failed") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_created and temporary:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            os.close(parent)

    def _open_parent(self, path: object, error_type: type[WorkspaceError]) -> tuple[int, str]:
        components = self._components(path, error_type)
        current = os.dup(self._descriptor)
        try:
            for component in components[:-1]:
                following = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
                metadata = os.fstat(following)
                if not stat.S_ISDIR(metadata.st_mode):
                    os.close(following)
                    raise error_type("workspace parent is not a regular directory")
                os.close(current)
                current = following
            return current, components[-1]
        except error_type:
            os.close(current)
            raise
        except OSError as error:
            os.close(current)
            raise error_type("workspace path resolution failed") from error

    def _components(self, path: object, error_type: type[WorkspaceError]) -> tuple[str, ...]:
        try:
            raw = os.fspath(cast(str | os.PathLike[str], path))
        except TypeError as error:
            raise error_type("path must be a string or path-like value") from error
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise error_type("path must be a nonempty NUL-free text path")
        if os.path.isabs(raw):
            try:
                if os.path.commonpath((self._canonical, raw)) != self._canonical:
                    raise error_type("absolute path is outside the launch workspace")
            except ValueError as error:
                raise error_type("absolute path is outside the launch workspace") from error
            relative = raw[len(self._canonical) :]
            if relative.startswith(os.sep):
                relative = relative[1:]
        else:
            relative = raw
        components = tuple(relative.split(os.sep))
        if not components or any(part in {"", ".", ".."} for part in components):
            raise error_type("path contains an empty or traversal component")
        return components

    @staticmethod
    def _write_bytes(content: object) -> bytes:
        if isinstance(content, str):
            return content.encode("utf-8", errors="strict")
        if isinstance(content, bytes):
            return content
        raise WriteError("content must be text or bytes")

    @staticmethod
    def _destination_identity(parent: int, name: str) -> tuple[int, int] | None:
        try:
            metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(metadata.st_mode):
            raise WriteError("write destination is not a regular file")
        return metadata.st_dev, metadata.st_ino

    @staticmethod
    def _require_platform_support() -> None:
        required = (os.open, os.stat, os.unlink)
        if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
            raise WorkspaceError("descriptor-relative no-follow workspace helpers are unavailable")
        if any(function not in os.supports_dir_fd for function in required):
            raise WorkspaceError("descriptor-relative no-follow workspace helpers are unavailable")
        if os.replace not in os.supports_dir_fd and os.rename not in os.supports_dir_fd:
            raise WorkspaceError("descriptor-relative atomic replacement is unavailable")


class ReadHelper:
    """Descriptor-confined convenience read; unrestricted Python is not sandboxed."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def __call__(
        self, path: object, *, binary: bool = False, limit: int = 1_048_576
    ) -> str | bytes:
        return self._workspace.read(path, binary=binary, limit=limit)

    def __repr__(self) -> str:
        return "<AMKernel helper read>"


class WriteHelper:
    """Descriptor-confined atomic write; unrestricted Python is not sandboxed."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def __call__(self, path: object, content: object) -> int:
        return self._workspace.write(path, content)

    def __repr__(self) -> str:
        return "<AMKernel helper write>"


class EnvHelper:
    """Convenient process environment access; this is not a credential boundary."""

    def __call__(self, key: object = _MISSING, value: object = _MISSING) -> object:
        if key is _MISSING:
            if value is not _MISSING:
                raise EnvError("value requires a key")
            return dict(os.environ)
        if value is _MISSING:
            name = self._key(key)
            return os.environ.get(name)
        name = self._key(key)
        previous = os.environ.get(name)
        if value is None:
            os.environ.pop(name, None)
            return previous
        if not isinstance(value, str) or "\x00" in value:
            raise EnvError("environment value must be NUL-free text or None")
        os.environ[name] = value
        return previous

    def __repr__(self) -> str:
        return "<AMKernel helper env>"

    @staticmethod
    def _key(key: object) -> str:
        if not isinstance(key, str) or _ENV_KEY.fullmatch(key) is None:
            raise EnvError("environment key must be a portable nonempty name")
        return key

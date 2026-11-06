"""Global Runtime installation and project-scoped Agent activation."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from importlib import metadata, resources
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import urlparse

import tomlkit
from tomlkit.items import AbstractTable, InlineTable

from amkernel import __version__

Client = Literal["omp", "pi", "codex", "copilot"]
SUPPORTED_CLIENTS: tuple[Client, ...] = ("omp", "pi", "codex", "copilot")
MAX_COMMAND_BYTES = 65_536
MAX_JSON_BYTES = 262_144
MAX_OFFICIAL_ARCHIVE_BYTES = 8_000_000
MAX_OFFICIAL_EXTRACTED_BYTES = 16_000_000
_SCHEMA = "https://raw.githubusercontent.com/can1357/oh-my-pi/main/packages/coding-agent/src/config/mcp-schema.json"
_BEGIN = "# BEGIN AMKERNEL MANAGED MCP"
_END = "# END AMKERNEL MANAGED MCP"
_OFFICIAL_STATE = PurePosixPath(".agents/amkernel-official.json")
_COPILOT_TRUST_NOTICE = (
    "Copilot loads project MCP servers only after you trust this project folder; "
    "confirm the trust prompt before treating the setup as ready."
)


class DistributionError(RuntimeError):
    """A user-actionable installation or configuration failure."""


def _remove_codex_amkernel(text: str) -> str:
    try:
        document = tomlkit.parse(text)
    except tomlkit.exceptions.ParseError as error:
        raise DistributionError(f"cannot parse Codex TOML: {error}") from error
    servers = document.get("mcp_servers")
    if isinstance(servers, AbstractTable):
        servers.pop("amkernel", None)
        if isinstance(servers, InlineTable):
            replacement = tomlkit.table()
            replacement.update(servers)
            document["mcp_servers"] = replacement
    return tomlkit.dumps(document)


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    truncated: bool


@dataclass(frozen=True)
class ProjectStatus:
    project: str
    client: str | None
    runtime_executable: str | None
    runtime_installed: bool
    skill_installed: bool
    mcp_configured: bool
    restart_required: bool
    detail: str | None = None
    runtime_version: str | None = None
    skill_version: str | None = None
    known_project_references: tuple[str, ...] = ()
    references_truncated: bool = False
    skill_provenance: bool = False
    skill_content_verified: bool = False
    skill_commit: str | None = None
    notice: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


Runner = Callable[[Sequence[str]], CommandResult]


def run_command(argv: Sequence[str]) -> CommandResult:
    """Run one argv-only command and retain bounded diagnostic output."""
    completed = subprocess.run(argv, capture_output=True, check=False)
    stdout, stdout_cut = _bounded_decode(completed.stdout)
    stderr, stderr_cut = _bounded_decode(completed.stderr)
    return CommandResult(
        tuple(argv), completed.returncode, stdout, stderr, stdout_cut or stderr_cut
    )


def _bounded_decode(value: bytes) -> tuple[str, bool]:
    truncated = len(value) > MAX_COMMAND_BYTES
    return value[:MAX_COMMAND_BYTES].decode("utf-8", errors="replace"), truncated


def _require_success(result: CommandResult, action: str) -> CommandResult:
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise DistributionError(f"{action} failed: {detail}")
    return result


def _json_bytes(value: object) -> bytes:
    payload = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if len(payload) > MAX_JSON_BYTES:
        raise DistributionError(f"managed JSON exceeds {MAX_JSON_BYTES} bytes")
    return payload


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DistributionError(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise DistributionError(f"expected a JSON object in {path}")
    return value


def _atomic_write(path: Path, content: bytes, *, permissions: int | None = None) -> None:
    try:
        if path.is_file() and path.read_bytes() == content:
            return
    except OSError:
        pass
    if permissions is None:
        try:
            permissions = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.amkernel-{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            if permissions is not None:
                os.fchmod(stream.fileno(), permissions)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_relative(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise DistributionError(f"{label} must be a non-empty relative path")
    if "\\" in value:
        raise DistributionError(f"{label} must use forward slashes: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DistributionError(f"{label} contains an unsafe path: {value}")
    return path


def _managed_path_mode(project: Path, path: Path, label: str) -> int | None:
    """Return the final lstat mode only when every managed component is real."""
    try:
        relative = path.relative_to(project)
    except ValueError as error:
        raise DistributionError(f"{label} escapes the project: {path}") from error
    current = project
    parts = relative.parts
    mode = project.lstat().st_mode
    for index, component in enumerate(parts):
        current = current / component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return None
        except OSError as error:
            raise DistributionError(f"{label} cannot be inspected safely: {error}") from error
        if stat.S_ISLNK(mode):
            raise DistributionError(f"{label}: linked path component is forbidden: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise DistributionError(f"{label}: path component is not a directory: {current}")
    return mode


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_map(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise DistributionError(f"{label} must be a non-empty object")
    result: dict[str, str] = {}
    for relative, digest in value.items():
        path = _safe_relative(relative, label)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise DistributionError(f"{label} contains an invalid sha256 for {path}")
        result[path.as_posix()] = digest
    return result


def _scan_tree(root: Path, label: str, *, allow_root_git: bool = False) -> dict[str, str]:
    if root.is_symlink():
        raise DistributionError(f"{label}: symbolic links are forbidden: {root}")
    if not root.is_dir():
        raise DistributionError(f"{label}: missing directory: {root}")
    root_git = False
    if allow_root_git:
        try:
            root_git_mode = (root / ".git").lstat().st_mode
        except FileNotFoundError:
            pass
        except OSError as error:
            raise DistributionError(f"{label}: cannot inspect .git safely: {error}") from error
        else:
            if not stat.S_ISDIR(root_git_mode):
                raise DistributionError(f"{label}: .git must be a real directory")
            root_git = True
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        name = relative.as_posix()
        if root_git and relative.parts and relative.parts[0] == ".git":
            continue
        if ".git" in relative.parts:
            raise DistributionError(f"{label}: .git is forbidden: {name}")
        if path.is_symlink():
            raise DistributionError(f"{label}: symbolic links are forbidden: {name}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise DistributionError(f"{label}: non-regular entry is forbidden: {name}")
        result[name] = _digest_file(path)
    return result


def _tree_problems(root: Path, expected: Mapping[str, str], label: str) -> list[str]:
    try:
        actual = _scan_tree(root, label)
    except DistributionError as error:
        return [str(error)]
    errors: list[str] = []
    for relative in sorted(set(expected) - set(actual)):
        errors.append(f"{label}: missing file: {relative}")
    for relative in sorted(set(actual) - set(expected)):
        errors.append(f"{label}: unexpected file: {relative}")
    for relative in sorted(set(actual) & set(expected)):
        if actual[relative] != expected[relative]:
            errors.append(f"{label}: sha256 mismatch: {relative}")
    return errors


def _validated_archive_members(
    payload: bytes, expected: Mapping[str, str], label: str
) -> dict[str, bytes]:
    if len(payload) > MAX_OFFICIAL_ARCHIVE_BYTES:
        raise DistributionError(f"{label} exceeds {MAX_OFFICIAL_ARCHIVE_BYTES} compressed bytes")
    members: dict[str, bytes] = {}
    total = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")
    except (tarfile.TarError, OSError, EOFError) as error:
        raise DistributionError(f"{label} is not a readable tar.gz archive: {error}") from error
    try:
        for member in archive:
            name = _safe_relative(member.name, f"{label} member")
            if member.isdir():
                prefix = name.as_posix() + "/"
                if not any(relative.startswith(prefix) for relative in expected):
                    raise DistributionError(f"{label} contains an unexpected directory: {name}")
                continue
            if not member.isfile():
                raise DistributionError(f"{label} contains a non-regular member: {name}")
            relative = name.as_posix()
            if relative in members:
                raise DistributionError(f"{label} contains a duplicate member: {relative}")
            if relative not in expected:
                raise DistributionError(f"{label} contains an unexpected member: {relative}")
            stream = archive.extractfile(member)
            if stream is None:
                raise DistributionError(f"{label} cannot read member: {relative}")
            content = stream.read()
            total += len(content)
            if total > MAX_OFFICIAL_EXTRACTED_BYTES:
                raise DistributionError(
                    f"{label} exceeds {MAX_OFFICIAL_EXTRACTED_BYTES} extracted bytes"
                )
            if _digest_bytes(content) != expected[relative]:
                raise DistributionError(f"{label} sha256 mismatch: {relative}")
            members[relative] = content
    except (tarfile.TarError, OSError, EOFError) as error:
        raise DistributionError(f"{label} is not a readable tar.gz archive: {error}") from error
    finally:
        archive.close()
    missing = sorted(set(expected) - set(members))
    if missing:
        raise DistributionError(f"{label} is missing file: {missing[0]}")
    return members


@contextmanager
def _exclusive_lock(lock: Path) -> Any:
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = lock.lstat().st_mode
    except FileNotFoundError:
        pass
    except OSError as error:
        raise DistributionError(
            f"cannot inspect the AMKernel lock safely: {lock}: {error}"
        ) from error
    else:
        if stat.S_ISLNK(existing):
            raise DistributionError(f"AMKernel lock must not be a symbolic link: {lock}")
        if not stat.S_ISREG(existing):
            raise DistributionError(f"AMKernel lock is not a regular file: {lock}")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock, flags, 0o600)
    except OSError as error:
        raise DistributionError(f"cannot open the AMKernel lock safely: {lock}: {error}") from error
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DistributionError(f"AMKernel lock is not a regular file: {lock}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DistributionError(f"another AMKernel update is active: {lock}") from error
        locked = True
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode())
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class ProjectTransaction:
    """Snapshot and restore only paths managed by one project operation."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self._snapshots: dict[Path, bytes | None] = {}
        self._file_permissions: dict[Path, int] = {}
        self._created_dirs: set[Path] = set()
        self._removed_dirs: dict[Path, int] = {}

    def _check_ancestors(self, path: Path) -> None:
        try:
            relative = path.parent.relative_to(self.project)
        except ValueError as error:
            raise DistributionError(f"managed path escapes the project: {path}") from error
        current = self.project
        for component in relative.parts:
            current = current / component
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                return
            except OSError as error:
                raise DistributionError(
                    f"managed path component cannot be inspected: {current}: {error}"
                ) from error
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise DistributionError(
                    f"managed path component is not a real directory: {current}"
                )

    def _ensure_parent(self, path: Path) -> None:
        try:
            relative = path.parent.relative_to(self.project)
        except ValueError as error:
            raise DistributionError(f"managed path escapes the project: {path}") from error
        current = self.project
        for component in relative.parts:
            current = current / component
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                current.mkdir()
                self._created_dirs.add(current)
                continue
            except OSError as error:
                raise DistributionError(
                    f"managed path component cannot be inspected: {current}: {error}"
                ) from error
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise DistributionError(
                    f"managed path component is not a real directory: {current}"
                )

    def snapshot(self, path: Path) -> None:
        if path in self._snapshots:
            return
        self._check_ancestors(path)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            self._snapshots[path] = None
            return
        except OSError as error:
            raise DistributionError(f"managed path cannot be inspected: {path}: {error}") from error
        if stat.S_ISLNK(mode):
            raise DistributionError(f"managed path must not be a symbolic link: {path}")
        if not stat.S_ISREG(mode):
            raise DistributionError(f"managed path must be a regular file: {path}")
        self._snapshots[path] = path.read_bytes()
        self._file_permissions[path] = stat.S_IMODE(mode)

    def write(self, path: Path, content: bytes) -> None:
        self._ensure_parent(path)
        self.snapshot(path)
        _atomic_write(path, content)

    def remove(self, path: Path) -> None:
        self.snapshot(path)
        path.unlink(missing_ok=True)

    def prune_empty_ancestors(self, path: Path, stop: Path) -> None:
        """Remove only empty ancestors of a removed managed file, bounded by stop."""
        if not path.is_relative_to(stop) or path == stop:
            return
        current = path.parent
        while current != stop and current.is_relative_to(stop):
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                break
            except OSError as error:
                raise DistributionError(
                    f"managed directory cannot be inspected: {current}: {error}"
                ) from error
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                break
            if current in self._created_dirs:
                try:
                    current.rmdir()
                except OSError:
                    break
            else:
                permissions = stat.S_IMODE(mode)
                try:
                    current.rmdir()
                except OSError:
                    break
                self._removed_dirs.setdefault(current, permissions)
            current = current.parent

    def rollback(self) -> None:
        # Remove replacement leaves and directories before restoring the old shape.
        for path in reversed(self._snapshots):
            if path not in self._created_dirs:
                path.unlink(missing_ok=True)
        for path in sorted(self._created_dirs, key=lambda item: len(item.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        for path, permissions in sorted(
            self._removed_dirs.items(), key=lambda item: len(item[0].parts)
        ):
            try:
                path.mkdir(parents=True, exist_ok=True)
                path.chmod(permissions)
            except OSError:
                pass
        for path, content in self._snapshots.items():
            if content is not None:
                _atomic_write(path, content, permissions=self._file_permissions[path])


class DistributionManager:
    """Own the global Runtime package and one project's thin Agent attachment."""

    def __init__(
        self,
        project: Path,
        *,
        runner: Runner = run_command,
        data_home: Path | None = None,
    ) -> None:
        self.project = project.expanduser().resolve()
        self.runner = runner
        configured_home = os.environ.get("AMKERNEL_DATA_HOME")
        self.data_home = (
            data_home.expanduser().resolve()
            if data_home is not None
            else Path(configured_home).expanduser().resolve()
            if configured_home
            else Path.home() / ".local" / "share" / "amkernel"
        )
        if not self.project.is_dir():
            raise DistributionError(f"project directory does not exist: {self.project}")

    def client_candidates(self) -> tuple[Client, ...]:
        candidates: tuple[tuple[Client, Path], ...] = (
            ("omp", self.project / ".omp"),
            ("pi", self.project / ".pi"),
            ("codex", self.project / ".codex"),
            ("copilot", self.project / ".mcp.json"),
        )
        marked = tuple(client for client, marker in candidates if marker.exists())
        if marked:
            return marked
        return tuple(client for client in SUPPORTED_CLIENTS if self._client_installed(client))

    def select_client(self, requested: str) -> Client:
        if requested in SUPPORTED_CLIENTS:
            return requested
        if requested != "auto":
            raise DistributionError(f"unsupported client: {requested}")
        candidates = self.client_candidates()
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise DistributionError(
                "multiple Coding Agents detected; pass --client omp, pi, codex, or copilot"
            )
        raise DistributionError(
            "no supported Coding Agent detected; pass --client omp, pi, codex, or copilot"
        )

    def _client_installed(self, client: Client) -> bool:
        executable = shutil.which(client)
        if not executable:
            return False
        if client != "copilot":
            return True
        # The Homebrew `copilot` formula is AWS Copilot, not GitHub Copilot CLI.
        result = self.runner((executable, "--help"))
        output = f"{result.stdout}\n{result.stderr}".lower()
        return result.returncode == 0 and "github copilot" in output

    def uv_tool_bin(self) -> Path:
        uv = shutil.which("uv")
        if not uv:
            raise DistributionError("uv is required; install it from https://docs.astral.sh/uv/")
        result = _require_success(self.runner((uv, "tool", "dir", "--bin")), "locating uv tool bin")
        value = result.stdout.strip()
        if not value:
            raise DistributionError("uv returned an empty tool bin directory")
        return Path(value).expanduser().resolve()

    def runtime_executable(self) -> Path:
        name = "amkernel.exe" if os.name == "nt" else "amkernel"
        return self.uv_tool_bin() / name

    def _package_spec(self) -> str:
        direct_url = metadata.distribution("amkernel").read_text("direct_url.json")
        if direct_url:
            try:
                url = json.loads(direct_url)["url"]
            except (KeyError, TypeError, json.JSONDecodeError):
                url = None
            if isinstance(url, str) and urlparse(url).scheme == "file":
                return url
        return "amkernel"

    def install_runtime(self) -> Path:
        uv = shutil.which("uv")
        if not uv:
            raise DistributionError("uv is required; install it from https://docs.astral.sh/uv/")
        argv = (
            uv,
            "tool",
            "install",
            self._package_spec(),
            "--with",
            "Appium-Python-Client>=5.2.5",
        )
        _require_success(self.runner(argv), "installing the global AMKernel Runtime")
        executable = self.runtime_executable()
        if not executable.is_file():
            raise DistributionError(
                f"uv completed but the AMKernel executable is missing: {executable}"
            )
        return executable

    def _config_path(self, client: Client) -> Path:
        if client == "omp":
            return self.project / ".omp" / "mcp.json"
        if client == "pi":
            return self.project / ".pi" / "mcp.json"
        if client == "copilot":
            # Copilot applies one config file at a time with whole-file
            # precedence. Reuse the file it already reads rather than creating
            # a duplicate that hides unrelated native servers.
            canonical = self.project / ".mcp.json"
            native = self.project / ".github" / "mcp.json"
            if canonical.exists() or canonical.is_symlink():
                return canonical
            if native.exists() or native.is_symlink():
                return native
            return canonical
        return self.project / ".codex" / "config.toml"

    def _project_lock_path(self) -> Path:
        digest = hashlib.sha256(str(self.project).encode()).hexdigest()
        return self.data_home / "locks" / f"project-{digest}.lock"

    def planned_changes(self, client: Client) -> tuple[str, ...]:
        return (
            f"User Runtime: {self.runtime_executable()}",
            f"Project Skill: {self.project / '.agents' / 'skills' / 'amkernel'}",
            f"Project Official Skills: {self.project / '.agents' / 'skills'}",
            f"Project Official source: {self.project / '.agents' / 'vendor' / 'appium-skills'}",
            f"Project MCP ({client}): {self._config_path(client)}",
        )

    def _skill_source(self) -> Any:
        return resources.files("amkernel").joinpath("skill")

    def _skill_files(self) -> tuple[str, ...]:
        return (
            "SKILL.md",
            "references/official-sources.json",
            "references/official-skills.json",
            "references/amkernel-appium.md",
            "references/android-setup.md",
            "references/android-execution.md",
            "references/ios-setup.md",
            "references/ios-simulator.md",
            "references/macos-setup.md",
            "references/readiness-contract.md",
            "scripts/verify_official_skills.py",
        )

    def _packaged_skill_digests(self) -> dict[str, str]:
        source = self._skill_source()
        return {
            relative: hashlib.sha256(source.joinpath(relative).read_bytes()).hexdigest()
            for relative in self._skill_files()
        }

    def _install_skill(self, transaction: ProjectTransaction) -> None:
        destination = self.project / ".agents" / "skills" / "amkernel"
        source = self._skill_source()
        digests = self._packaged_skill_digests()
        for relative in self._skill_files():
            target = destination / relative
            transaction.write(target, source.joinpath(relative).read_bytes())
        metadata_target = destination / ".amkernel-metadata.json"
        transaction.write(
            metadata_target,
            _json_bytes({"runtimeVersion": __version__, "files": digests}),
        )

    def _official_state_path(self) -> Path:
        return self.project.joinpath(*_OFFICIAL_STATE.parts)

    def _load_official_manifest(self) -> dict[str, Any]:
        source = self._skill_source()
        try:
            document = json.loads(
                source.joinpath("references", "official-skills.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DistributionError(
                f"cannot read the packaged official Skills manifest: {error}"
            ) from error
        if not isinstance(document, dict) or document.get("schemaVersion") != 1:
            raise DistributionError("official Skills manifest schemaVersion must be 1")
        repository = document.get("repository")
        commit = document.get("commit")
        if not isinstance(repository, str) or not repository:
            raise DistributionError("official Skills manifest repository must be a string")
        if (
            not isinstance(commit, str)
            or len(commit) != 40
            or any(character not in "0123456789abcdef" for character in commit)
        ):
            raise DistributionError("official Skills manifest commit must be a full object ID")
        source_value = document.get("source")
        if not isinstance(source_value, dict):
            raise DistributionError("official Skills manifest source must be an object")
        location = _safe_relative(
            source_value.get("generatedLocation"), "official source generatedLocation"
        )
        if location.as_posix() != f".agents/vendor/appium-skills/{commit}":
            raise DistributionError(
                "official source generatedLocation must match the pinned commit"
            )
        archive = source_value.get("archive")
        if not isinstance(archive, dict):
            raise DistributionError("official Skills manifest source.archive must be an object")
        if archive.get("format") != "tar.gz":
            raise DistributionError("official Skills manifest archive format must be tar.gz")
        archive_location = _safe_relative(archive.get("path"), "official source archive path")
        if not archive_location.parts or archive_location.parts[0] != "references":
            raise DistributionError("official source archive must live under references/")
        archive_digest = archive.get("sha256")
        if (
            not isinstance(archive_digest, str)
            or len(archive_digest) != 64
            or any(character not in "0123456789abcdef" for character in archive_digest)
        ):
            raise DistributionError("official source archive sha256 is invalid")
        source_files = _file_map(source_value.get("files"), "official source files")
        installed = document.get("installedSkills")
        if not isinstance(installed, list) or not installed:
            raise DistributionError("official Skills must include a non-empty installedSkills list")
        names: set[str] = set()
        for index, item in enumerate(installed):
            label = f"official Skills installedSkills[{index}]"
            if not isinstance(item, dict):
                raise DistributionError(f"{label} must be an object")
            name = item.get("name")
            if (
                not isinstance(name, str)
                or not name
                or name == "amkernel"
                or any(
                    character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name
                )
            ):
                raise DistributionError(f"{label}.name must be a stable directory name")
            if name in names:
                raise DistributionError(f"duplicate official Skill name: {name}")
            names.add(name)
            source_path = _safe_relative(item.get("sourcePath"), f"{label}.sourcePath")
            agent_location = _safe_relative(
                item.get("generatedLocation"), f"{label}.generatedLocation"
            )
            if agent_location.as_posix() != f".agents/skills/{name}":
                raise DistributionError(f"{label}.generatedLocation must be .agents/skills/{name}")
            files = _file_map(item.get("files"), f"{label}.files")
            for relative, digest in files.items():
                source_relative = PurePosixPath(source_path, relative).as_posix()
                if source_files.get(source_relative) != digest:
                    raise DistributionError(
                        f"{label}.files does not match the pinned source: {relative}"
                    )
        return cast(dict[str, Any], document)

    def _read_official_archive(self, manifest: Mapping[str, Any]) -> bytes:
        archive = cast(Mapping[str, Any], manifest["source"])["archive"]
        archive_path = _safe_relative(archive["path"], "official source archive path")
        resource = self._skill_source()
        for component in archive_path.parts:
            resource = resource.joinpath(component)
        try:
            payload: bytes = resource.read_bytes()
        except OSError as error:
            raise DistributionError(
                f"packaged official source archive is missing: {archive_path}"
            ) from error
        if len(payload) > MAX_OFFICIAL_ARCHIVE_BYTES:
            raise DistributionError(
                f"packaged official source archive exceeds {MAX_OFFICIAL_ARCHIVE_BYTES} bytes"
            )
        if _digest_bytes(payload) != archive["sha256"]:
            raise DistributionError(
                f"packaged official source archive sha256 does not match: {archive_path}"
            )
        return payload

    def _read_receipt(self, path: Path) -> dict[str, Any] | None:
        label = "official Skills state"
        mode = _managed_path_mode(self.project, path, label)
        if mode is None:
            return None
        if not stat.S_ISREG(mode):
            raise DistributionError(f"{label} must be a regular file: {path}")
        return _load_json_object(path)

    def _official_state(self, manifest: Mapping[str, Any]) -> dict[str, Any] | None:
        value = self._read_receipt(self._official_state_path())
        if value is None:
            return None
        self._validate_official_state(value, manifest)
        return value

    def _validate_official_state(
        self, value: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        if value.get("schemaVersion") != 1:
            raise DistributionError("official Skills state schemaVersion must be 1")
        if not isinstance(value.get("runtimeVersion"), str):
            raise DistributionError("official Skills state runtimeVersion must be a string")
        source = cast(Mapping[str, Any], manifest["source"])
        archive = cast(Mapping[str, Any], source["archive"])
        if value.get("repository") != manifest["repository"]:
            raise DistributionError("official Skills state repository does not match")
        if value.get("commit") != manifest["commit"]:
            raise DistributionError("official Skills state commit does not match")
        state_archive = value.get("archive")
        if not isinstance(state_archive, dict):
            raise DistributionError("official Skills state archive must be an object")
        if (
            state_archive.get("path") != archive["path"]
            or state_archive.get("sha256") != archive["sha256"]
        ):
            raise DistributionError("official Skills state archive does not match")
        state_source = value.get("source")
        if not isinstance(state_source, dict):
            raise DistributionError("official Skills state source must be an object")
        if state_source.get("path") != source["generatedLocation"]:
            raise DistributionError("official Skills state source path does not match")
        if state_source.get("files") != source["files"]:
            raise DistributionError("official Skills state source files do not match")
        state_skills = value.get("skills")
        if not isinstance(state_skills, dict):
            raise DistributionError("official Skills state skills must be an object")
        installed = {
            item["name"]: item
            for item in cast(Sequence[Mapping[str, Any]], manifest["installedSkills"])
        }
        if set(state_skills) != set(installed):
            raise DistributionError("official Skills state skill list does not match")
        for name, item in installed.items():
            state_skill = state_skills.get(name)
            if not isinstance(state_skill, dict):
                raise DistributionError(f"official Skills state entry is invalid for {name}")
            if state_skill.get("path") != item["generatedLocation"]:
                raise DistributionError(f"official Skills state path does not match for {name}")
            if state_skill.get("files") != item["files"]:
                raise DistributionError(f"official Skills state files do not match for {name}")

    def _previous_official_state(self) -> dict[str, Any] | None:
        value = self._read_receipt(self._official_state_path())
        if value is None:
            return None
        # Older receipts may name a different pinned commit; validate their
        # ownership shape and paths so they can only release managed files.
        if value.get("schemaVersion") != 1:
            raise DistributionError("official Skills state schemaVersion must be 1")
        if not isinstance(value.get("runtimeVersion"), str):
            raise DistributionError("official Skills state runtimeVersion must be a string")
        if not isinstance(value.get("repository"), str) or not isinstance(value.get("commit"), str):
            raise DistributionError("official Skills state provenance must be strings")
        archive = value.get("archive")
        if (
            not isinstance(archive, dict)
            or not isinstance(archive.get("path"), str)
            or not isinstance(archive.get("sha256"), str)
        ):
            raise DistributionError("official Skills state archive is invalid")
        source = value.get("source")
        if not isinstance(source, dict):
            raise DistributionError("official Skills state source must be an object")
        source_path = _safe_relative(source.get("path"), "official Skills state source path")
        source_posix = source_path.as_posix()
        prefix = ".agents/vendor/appium-skills/"
        old_commit = source_posix[len(prefix) :] if source_posix.startswith(prefix) else ""
        if (
            not old_commit
            or "/" in old_commit
            or len(old_commit) != 40
            or any(character not in "0123456789abcdef" for character in old_commit)
        ):
            raise DistributionError("official Skills state source path is not managed")
        _file_map(source.get("files"), "official Skills state source files")
        skills = value.get("skills")
        if not isinstance(skills, dict):
            raise DistributionError("official Skills state skills must be an object")
        for name, entry in skills.items():
            if (
                not isinstance(name, str)
                or not name
                or name == "amkernel"
                or any(
                    character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name
                )
            ):
                raise DistributionError("official Skills state skill name is invalid")
            if not isinstance(entry, dict):
                raise DistributionError(f"official Skills state entry is invalid for {name}")
            location = _safe_relative(entry.get("path"), f"official Skills state path for {name}")
            if location.as_posix() != f".agents/skills/{name}":
                raise DistributionError(f"official Skills state path is not managed for {name}")
            _file_map(entry.get("files"), f"official Skills state files for {name}")
        return value

    def _official_state_bytes(self, manifest: Mapping[str, Any]) -> bytes:
        source = cast(Mapping[str, Any], manifest["source"])
        archive = cast(Mapping[str, Any], source["archive"])
        skills = {
            item["name"]: {
                "path": item["generatedLocation"],
                "files": item["files"],
            }
            for item in cast(Sequence[Mapping[str, Any]], manifest["installedSkills"])
        }
        return _json_bytes(
            {
                "schemaVersion": 1,
                "runtimeVersion": __version__,
                "repository": manifest["repository"],
                "commit": manifest["commit"],
                "archive": {"path": archive["path"], "sha256": archive["sha256"]},
                "source": {
                    "path": source["generatedLocation"],
                    "files": source["files"],
                },
                "skills": skills,
            }
        )

    def _owned_files(
        self, state: Mapping[str, Any] | None, path: str, *, skill: str | None = None
    ) -> set[str]:
        if state is None:
            return set()
        if skill is None:
            source = state.get("source")
            if isinstance(source, dict) and source.get("path") == path:
                files = source.get("files")
                if isinstance(files, dict):
                    return set(files)
            return set()
        skills = state.get("skills")
        entry = skills.get(skill) if isinstance(skills, dict) else None
        if isinstance(entry, dict) and entry.get("path") == path:
            files = entry.get("files")
            if isinstance(files, dict):
                return set(files)
        return set()

    def _prepare_tree(
        self,
        root: Path,
        expected: Mapping[str, str],
        owned: set[str],
        transaction: ProjectTransaction,
        label: str,
    ) -> bool:
        """Return True when an exact tree can be reused, otherwise repair it."""
        mode = _managed_path_mode(self.project, root, label)
        if mode is None:
            return False
        if not stat.S_ISDIR(mode):
            raise DistributionError(f"{label}: managed path is not a directory: {root}")
        actual = _scan_tree(root, label)
        if actual == dict(expected):
            return True
        if not actual:
            return False
        foreign = set(actual) - set(expected) - owned
        if not owned:
            raise DistributionError(
                f"{label}: existing files are not managed by AMKernel; remove them first"
            )
        if foreign:
            raise DistributionError(
                f"{label}: unexpected file is not managed by AMKernel: {sorted(foreign)[0]}"
            )
        removed: list[Path] = []
        for relative in sorted(actual, reverse=True):
            path = root / relative
            transaction.remove(path)
            removed.append(path)
        stop = self.project / ".agents"
        if root.is_relative_to(stop):
            for path in removed:
                transaction.prune_empty_ancestors(path, stop)
        return False

    def _release_owned_tree(
        self,
        transaction: ProjectTransaction,
        root: Path,
        files: Mapping[str, str],
        label: str,
    ) -> None:
        mode = _managed_path_mode(self.project, root, label)
        if mode is None or not stat.S_ISDIR(mode):
            return
        actual = _scan_tree(root, label, allow_root_git=True)
        removed: list[Path] = []
        for relative, digest in files.items():
            if actual.get(relative) != digest:
                continue
            path = root.joinpath(*PurePosixPath(relative).parts)
            transaction.remove(path)
            removed.append(path)
        stop = self.project / ".agents"
        for path in removed:
            transaction.prune_empty_ancestors(path, stop)

    def _release_obsolete_official(
        self,
        transaction: ProjectTransaction,
        previous: Mapping[str, Any] | None,
        manifest: Mapping[str, Any],
    ) -> None:
        if previous is None:
            return
        source = cast(Mapping[str, Any], manifest["source"])
        source_location = cast(str, source["generatedLocation"])
        current_skills = {
            cast(str, item["generatedLocation"])
            for item in cast(Sequence[Mapping[str, Any]], manifest["installedSkills"])
        }
        old_source = cast(Mapping[str, Any], previous["source"])
        old_source_location = cast(str, old_source["path"])
        old_skills = cast(Mapping[str, Any], previous["skills"])
        entries: list[tuple[str, Mapping[str, str], str]] = [
            (
                old_source_location,
                cast(Mapping[str, str], old_source["files"]),
                "official source",
            )
        ]
        for name, raw_entry in old_skills.items():
            entry = cast(Mapping[str, Any], raw_entry)
            entries.append(
                (
                    cast(str, entry["path"]),
                    cast(Mapping[str, str], entry["files"]),
                    f"official Skill {name}",
                )
            )
        managed_locations = {source_location, *current_skills, ".agents/skills/amkernel"}
        for location, files, label in entries:
            if location in managed_locations:
                continue
            old_root = self.project.joinpath(*PurePosixPath(location).parts)
            for managed in managed_locations:
                managed_root = self.project.joinpath(*PurePosixPath(managed).parts)
                if (
                    old_root == managed_root
                    or old_root.is_relative_to(managed_root)
                    or managed_root.is_relative_to(old_root)
                ):
                    raise DistributionError(
                        f"{label}: obsolete location overlaps a current managed path"
                    )
            self._release_owned_tree(transaction, old_root, files, label)

    def _install_official(self, transaction: ProjectTransaction) -> None:
        manifest = self._load_official_manifest()
        archive = self._read_official_archive(manifest)
        source = cast(Mapping[str, Any], manifest["source"])
        source_files = cast(Mapping[str, str], source["files"])
        members = _validated_archive_members(archive, source_files, "official source archive")
        previous = self._previous_official_state()
        source_location = cast(str, source["generatedLocation"])
        source_root = self.project.joinpath(*PurePosixPath(source_location).parts)
        owned_source = self._owned_files(previous, source_location)
        source_exact = self._prepare_tree(
            source_root,
            source_files,
            owned_source,
            transaction,
            "official source",
        )
        if not source_exact:
            for relative, content in members.items():
                transaction.write(source_root.joinpath(*PurePosixPath(relative).parts), content)

        installed = cast(Sequence[Mapping[str, Any]], manifest["installedSkills"])
        for item in installed:
            name = cast(str, item["name"])
            location = cast(str, item["generatedLocation"])
            root = self.project.joinpath(*PurePosixPath(location).parts)
            expected = cast(Mapping[str, str], item["files"])
            source_path = cast(str, item["sourcePath"])
            owned = self._owned_files(previous, location, skill=name)
            exact = self._prepare_tree(root, expected, owned, transaction, f"official Skill {name}")
            if not exact:
                for relative in expected:
                    source_relative = PurePosixPath(source_path, relative).as_posix()
                    skill_content = members.get(source_relative)
                    if skill_content is None:
                        raise DistributionError(
                            f"official source is missing Skill file: {source_relative}"
                        )
                    transaction.write(root.joinpath(*PurePosixPath(relative).parts), skill_content)
        self._release_obsolete_official(transaction, previous, manifest)
        transaction.write(self._official_state_path(), self._official_state_bytes(manifest))

    def _official_health(self) -> tuple[bool, bool, str | None]:
        try:
            manifest = self._load_official_manifest()
            self._read_official_archive(manifest)
            state = self._official_state(manifest)
            if state is None:
                return False, False, None
            if state.get("runtimeVersion") != __version__:
                return False, False, cast(str | None, state.get("commit"))
            source = cast(Mapping[str, Any], manifest["source"])
            source_location = cast(str, source["generatedLocation"])
            source_root = self.project.joinpath(*PurePosixPath(source_location).parts)
            source_mode = _managed_path_mode(self.project, source_root, "official source")
            if source_mode is None or not stat.S_ISDIR(source_mode):
                return False, False, cast(str, manifest["commit"])
            if _tree_problems(
                source_root,
                cast(Mapping[str, str], source["files"]),
                "official source",
            ):
                return False, False, cast(str, manifest["commit"])
            for item in cast(Sequence[Mapping[str, Any]], manifest["installedSkills"]):
                location = cast(str, item["generatedLocation"])
                root = self.project.joinpath(*PurePosixPath(location).parts)
                label = f"official Skill {item['name']}"
                mode = _managed_path_mode(self.project, root, label)
                if mode is None or not stat.S_ISDIR(mode):
                    return False, False, cast(str, manifest["commit"])
                if _tree_problems(
                    root,
                    cast(Mapping[str, str], item["files"]),
                    label,
                ):
                    return False, False, cast(str, manifest["commit"])
            return True, True, cast(str, manifest["commit"])
        except (DistributionError, OSError, UnicodeError, KeyError, TypeError):
            return False, False, None

    def _write_json_client(
        self, client: Client, executable: Path, transaction: ProjectTransaction
    ) -> None:
        path = self._config_path(client)
        value = _load_json_object(path)
        if client == "copilot":
            servers = value.get("mcpServers")
            bare = False
            if not isinstance(servers, dict):
                if "mcpServers" in value:
                    raise DistributionError(f"mcpServers must be an object in {path}")
                if value and all(
                    isinstance(entry, dict)
                    and ("command" in entry or "url" in entry or "type" in entry)
                    for entry in value.values()
                ):
                    servers = value
                    bare = True
                else:
                    servers = {}
                    value["mcpServers"] = servers
            entry: dict[str, Any] = {
                "type": "stdio",
                "command": str(executable),
                "cwd": str(self.project),
                "args": [],
                "tools": ["*"],
            }
            servers["amkernel"] = entry
            if bare:
                value = dict(value)
        else:
            servers = value.setdefault("mcpServers", {})
            if not isinstance(servers, dict):
                raise DistributionError(f"mcpServers must be an object in {path}")
            servers["amkernel"] = {
                "type": "stdio",
                "command": str(executable),
                "cwd": str(self.project),
            }
            if client == "omp":
                value.setdefault("$schema", _SCHEMA)
        transaction.write(path, _json_bytes(value))

    def _write_codex(self, executable: Path, transaction: ProjectTransaction) -> None:
        path = self._config_path("codex")
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise DistributionError(f"cannot read valid TOML from {path}: {error}") from error
        if _BEGIN in text or _END in text:
            if (
                text.count(_BEGIN) != 1
                or text.count(_END) != 1
                or text.index(_BEGIN) > text.index(_END)
            ):
                raise DistributionError(f"invalid AMKernel managed block in {path}")
            prefix, rest = text.split(_BEGIN, 1)
            _, suffix = rest.split(_END, 1)
            text = prefix.rstrip() + "\n" + suffix.lstrip("\n")
        text = _remove_codex_amkernel(text).rstrip() + ("\n" if text.strip() else "")
        block = (
            f"{_BEGIN}\n[mcp_servers.amkernel]\n"
            f"command = {json.dumps(str(executable))}\n"
            f"cwd = {json.dumps(str(self.project))}\n{_END}\n"
        )
        updated = text.rstrip() + ("\n\n" if text.strip() else "") + block
        try:
            tomllib.loads(updated)
        except tomllib.TOMLDecodeError as error:
            raise DistributionError(f"generated invalid TOML for {path}: {error}") from error
        transaction.write(path, updated.encode("utf-8"))

    def _registry_path(self) -> Path:
        return self.data_home / "projects.json"

    def known_projects(self) -> dict[str, str]:
        value = _load_json_object(self._registry_path())
        projects = value.get("projects", {})
        if not isinstance(projects, dict) or not all(
            isinstance(path, str) and isinstance(client, str) for path, client in projects.items()
        ):
            raise DistributionError(f"invalid project registry: {self._registry_path()}")
        return dict(projects)

    def _set_project_registration(self, client: Client | None) -> None:
        path = self._registry_path()
        with _exclusive_lock(path.with_suffix(".lock")):
            value = _load_json_object(path)
            projects = value.setdefault("projects", {})
            if not isinstance(projects, dict):
                raise DistributionError(f"invalid project registry: {path}")
            if client is None:
                projects.pop(str(self.project), None)
            else:
                projects[str(self.project)] = client
            _atomic_write(path, _json_bytes(value))

    def configure_project(self, client: Client, executable: Path) -> ProjectStatus:
        with _exclusive_lock(self._project_lock_path()):
            transaction = ProjectTransaction(self.project)
            try:
                self._install_skill(transaction)
                self._install_official(transaction)
                if client == "codex":
                    self._write_codex(executable, transaction)
                else:
                    self._write_json_client(client, executable, transaction)
                self._set_project_registration(client)
            except BaseException:
                transaction.rollback()
                raise
        return self.status(client)

    def install(self, requested_client: str) -> ProjectStatus:
        client = self.select_client(requested_client)
        executable = self.install_runtime()
        return self.configure_project(client, executable)

    def status(self, client: Client | None = None) -> ProjectStatus:
        if client is None:
            try:
                client = self.select_client("auto")
            except DistributionError as error:
                return ProjectStatus(
                    str(self.project), None, None, False, False, False, False, str(error)
                )
        try:
            executable = self.runtime_executable()
        except DistributionError as error:
            return ProjectStatus(
                str(self.project), client, None, False, False, False, False, str(error)
            )
        skill = self.project / ".agents" / "skills" / "amkernel" / "SKILL.md"
        metadata_path = skill.parent / ".amkernel-metadata.json"
        configured = self._is_configured(client, executable)
        installed = executable.is_file()
        runtime_version = None
        if installed:
            result = self.runner((str(executable), "--version"))
            if not result.returncode and result.stdout.strip():
                runtime_version = result.stdout.strip().rsplit(maxsplit=1)[-1]
        skill_version = None
        skill_digest_ok = False
        skill_present = False
        try:
            metadata_mode = _managed_path_mode(self.project, metadata_path, "main Skill metadata")
            if metadata_mode is None or not stat.S_ISREG(metadata_mode):
                raise DistributionError("main Skill metadata is not a regular file")
            metadata_value = _load_json_object(metadata_path)
            recorded_files = metadata_value.get("files")
            recorded_version = metadata_value.get("runtimeVersion")
            if isinstance(recorded_version, str):
                skill_version = recorded_version
            packaged_digests = self._packaged_skill_digests()
            files_ok = True
            for relative, digest in packaged_digests.items():
                path = skill.parent / relative
                mode = _managed_path_mode(self.project, path, "main Skill file")
                if mode is None or not stat.S_ISREG(mode):
                    files_ok = False
                    break
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    files_ok = False
                    break
            skill_digest_ok = (
                isinstance(recorded_files, dict)
                and recorded_files == packaged_digests
                and recorded_version == __version__
                and files_ok
            )
            skill_mode = _managed_path_mode(self.project, skill, "main Skill file")
            skill_present = skill_mode is not None and stat.S_ISREG(skill_mode)
        except (DistributionError, OSError):
            pass
        provenance, official_content, skill_commit = self._official_health()
        content_verified = skill_digest_ok and official_content
        healthy = (
            installed
            and content_verified
            and provenance
            and configured
            and runtime_version is not None
            and runtime_version == skill_version
        )
        detail = (
            None if healthy else "run `amkernel install` to repair Runtime, Skill, or MCP drift"
        )
        notice = _COPILOT_TRUST_NOTICE if client == "copilot" and configured else None
        return ProjectStatus(
            str(self.project),
            client,
            str(executable),
            installed,
            skill_present,
            configured,
            healthy,
            detail,
            runtime_version,
            skill_version,
            skill_provenance=provenance,
            skill_content_verified=content_verified,
            skill_commit=skill_commit,
            notice=notice,
        )

    def _is_configured(self, client: Client, executable: Path) -> bool:
        path = self._config_path(client)
        try:
            if client == "codex":
                value = tomllib.loads(path.read_text(encoding="utf-8"))
                entry = value.get("mcp_servers", {}).get("amkernel", {})
            else:
                value = _load_json_object(path)
                servers = value.get("mcpServers")
                entry = servers.get("amkernel", {}) if isinstance(servers, dict) else {}
                if not entry and client == "copilot":
                    entry = value.get("amkernel", {})
            if not isinstance(entry, dict):
                return False
            if entry.get("command") != str(executable) or entry.get("cwd") != str(self.project):
                return False
            if client != "copilot":
                return True
            return (
                entry.get("type") == "stdio"
                and entry.get("args") == []
                and entry.get("tools") == ["*"]
                and entry.get("disabled") is not True
            )
        except (DistributionError, OSError, UnicodeError, tomllib.TOMLDecodeError, AttributeError):
            return False

    def doctor(self, client: Client) -> ProjectStatus:
        status = self.status(client)
        if not (status.runtime_installed and status.skill_installed and status.mcp_configured):
            return status
        executable = Path(status.runtime_executable or "")
        result = self.runner((str(executable), "--version"))
        if result.returncode:
            return replace(
                status,
                detail=result.stderr or result.stdout,
                restart_required=False,
            )
        return status

    def update(self, client: Client) -> ProjectStatus:
        uv = shutil.which("uv")
        if not uv:
            raise DistributionError("uv is required to update the global AMKernel Runtime")
        _require_success(
            self.runner((uv, "tool", "upgrade", "amkernel")),
            "updating the global AMKernel Runtime",
        )
        executable = self.runtime_executable()
        _require_success(
            self.runner(
                (
                    str(executable),
                    "install",
                    "--client",
                    client,
                    "--scope",
                    "project",
                    "--project",
                    str(self.project),
                    "--yes",
                    "--json",
                )
            ),
            "synchronizing the project from the updated Runtime",
        )
        return self.status(client)

    def _remove_main_skill(self, transaction: ProjectTransaction) -> None:
        root = self.project / ".agents" / "skills" / "amkernel"
        root_mode = _managed_path_mode(self.project, root, "main Skill")
        if root_mode is None or not stat.S_ISDIR(root_mode):
            return
        metadata_path = root / ".amkernel-metadata.json"
        metadata_mode = _managed_path_mode(self.project, metadata_path, "main Skill metadata")
        if metadata_mode is None or not stat.S_ISREG(metadata_mode):
            return
        try:
            metadata = _load_json_object(metadata_path)
        except DistributionError:
            return
        files = metadata.get("files")
        if not isinstance(files, dict):
            return
        removed: list[Path] = []
        for relative, digest in files.items():
            if not isinstance(relative, str) or not isinstance(digest, str):
                continue
            try:
                relative_path = _safe_relative(relative, "main Skill metadata")
                path = root.joinpath(*relative_path.parts)
            except DistributionError:
                continue
            mode = _managed_path_mode(self.project, path, "main Skill file")
            if mode is None or not stat.S_ISREG(mode):
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                transaction.remove(path)
                removed.append(path)
        transaction.remove(metadata_path)
        removed.append(metadata_path)
        stop = self.project / ".agents"
        for path in removed:
            transaction.prune_empty_ancestors(path, stop)

    def _remove_official_state(self, transaction: ProjectTransaction) -> None:
        state = self._previous_official_state()
        if state is None:
            return
        source_entry = cast(dict[str, Any], state["source"])
        entries: list[tuple[str, dict[str, Any], str]] = [
            (cast(str, source_entry["path"]), source_entry, "official source")
        ]
        for name, raw_entry in cast(dict[str, Any], state["skills"]).items():
            entry = cast(dict[str, Any], raw_entry)
            entries.append((cast(str, entry["path"]), entry, f"official Skill {name}"))
        for location, entry, label in entries:
            root = self.project.joinpath(*PurePosixPath(location).parts)
            self._release_owned_tree(
                transaction, root, cast(Mapping[str, str], entry["files"]), label
            )
        state_path = self._official_state_path()
        mode = _managed_path_mode(self.project, state_path, "official Skills state")
        if mode is None:
            return
        if not stat.S_ISREG(mode):
            raise DistributionError(f"official Skills state must be a regular file: {state_path}")
        transaction.remove(state_path)

    def uninstall_project(self, client: Client) -> ProjectStatus:
        with _exclusive_lock(self._project_lock_path()):
            path = self._config_path(client)
            transaction = ProjectTransaction(self.project)
            try:
                if client == "codex" and path.exists():
                    text = path.read_text(encoding="utf-8")
                    if _BEGIN in text and _END in text:
                        prefix, rest = text.split(_BEGIN, 1)
                        _, suffix = rest.split(_END, 1)
                        updated = prefix.rstrip() + "\n" + suffix.lstrip("\n")
                    else:
                        updated = text
                    updated = _remove_codex_amkernel(updated).rstrip() + "\n"
                    transaction.write(path, updated.encode())
                elif path.exists():
                    value = _load_json_object(path)
                    servers = value.get("mcpServers")
                    if isinstance(servers, dict):
                        servers.pop("amkernel", None)
                    if client == "copilot":
                        value.pop("amkernel", None)
                    transaction.write(path, _json_bytes(value))
                self._remove_official_state(transaction)
                self._remove_main_skill(transaction)
                self._set_project_registration(None)
            except BaseException:
                transaction.rollback()
                raise
        return self.status(client)

    def uninstall_global(self) -> None:
        uv = shutil.which("uv")
        if not uv:
            raise DistributionError("uv is required to remove the global AMKernel Runtime")
        _require_success(
            self.runner((uv, "tool", "uninstall", "amkernel")), "removing global AMKernel Runtime"
        )

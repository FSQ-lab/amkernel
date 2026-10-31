"""Global Runtime installation and project-scoped Agent activation."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from importlib import metadata, resources
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

import tomlkit
from tomlkit.items import AbstractTable, InlineTable

from amkernel import __version__

Client = Literal["omp", "pi", "codex"]
MAX_COMMAND_BYTES = 65_536
MAX_JSON_BYTES = 262_144
_SCHEMA = "https://raw.githubusercontent.com/can1357/oh-my-pi/main/packages/coding-agent/src/config/mcp-schema.json"
_BEGIN = "# BEGIN AMKERNEL MANAGED MCP"
_END = "# END AMKERNEL MANAGED MCP"


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


def _atomic_write(path: Path, content: bytes) -> None:
    try:
        if path.is_file() and path.read_bytes() == content:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.amkernel-{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(lock: Path) -> Any:
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DistributionError(f"another AMKernel update is active: {lock}") from error
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode())
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class ProjectTransaction:
    """Snapshot and restore only paths managed by one project operation."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self._snapshots: dict[Path, bytes | None] = {}

    def snapshot(self, path: Path) -> None:
        if path not in self._snapshots:
            self._snapshots[path] = path.read_bytes() if path.is_file() else None

    def rollback(self) -> None:
        for path, content in reversed(tuple(self._snapshots.items())):
            if content is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, content)
        skill = self.project / ".agents" / "skills" / "amkernel"
        if not any(
            path.is_relative_to(skill) and content is not None
            for path, content in self._snapshots.items()
        ):
            shutil.rmtree(skill, ignore_errors=True)


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

    def select_client(self, requested: str) -> Client:
        if requested in {"omp", "pi", "codex"}:
            return cast(Client, requested)
        if requested != "auto":
            raise DistributionError(f"unsupported client: {requested}")
        candidates: tuple[tuple[Client, Path], ...] = (
            ("omp", self.project / ".omp"),
            ("pi", self.project / ".pi"),
            ("codex", self.project / ".codex"),
        )
        marked = [client for client, marker in candidates if marker.exists()]
        if len(marked) == 1:
            return marked[0]
        if len(marked) > 1:
            raise DistributionError(
                "multiple Coding Agents detected for this project; pass --client omp, pi, or codex"
            )
        supported_clients: tuple[Client, ...] = ("omp", "pi", "codex")
        installed = [client for client in supported_clients if shutil.which(client)]
        if len(installed) == 1:
            return installed[0]
        if len(installed) > 1:
            raise DistributionError(
                "multiple Coding Agents detected; pass --client omp, pi, or codex"
            )
        raise DistributionError(
            "no supported Coding Agent detected; pass --client omp, pi, or codex"
        )

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
        if __version__ != "0.0.0":
            return "amkernel"
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
            "Appium-Python-Client>=6,<7",
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
        return self.project / ".codex" / "config.toml"

    def _project_lock_path(self) -> Path:
        digest = hashlib.sha256(str(self.project).encode()).hexdigest()
        return self.data_home / "locks" / f"project-{digest}.lock"

    def planned_changes(self, client: Client) -> tuple[str, ...]:
        return (
            f"Runtime: {self.runtime_executable()}",
            f"Skill: {self.project / '.agents' / 'skills' / 'amkernel'}",
            f"MCP ({client}): {self._config_path(client)}",
        )

    def _skill_source(self) -> Any:
        return resources.files("amkernel").joinpath("skill")

    def _skill_files(self) -> tuple[str, ...]:
        return (
            "SKILL.md",
            "references/official-sources.json",
            "references/official-skills.json",
            "references/amkernel-appium.md",
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
            transaction.snapshot(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, source.joinpath(relative).read_bytes())
        metadata_target = destination / ".amkernel-metadata.json"
        transaction.snapshot(metadata_target)
        _atomic_write(
            metadata_target,
            _json_bytes({"runtimeVersion": __version__, "files": digests}),
        )

    def _write_json_client(
        self, client: Client, executable: Path, transaction: ProjectTransaction
    ) -> None:
        path = self._config_path(client)
        transaction.snapshot(path)
        value = _load_json_object(path)
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
        _atomic_write(path, _json_bytes(value))

    def _write_codex(self, executable: Path, transaction: ProjectTransaction) -> None:
        path = self._config_path("codex")
        transaction.snapshot(path)
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
        _atomic_write(path, updated.encode("utf-8"))

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
        try:
            metadata_value = _load_json_object(metadata_path)
            recorded_files = metadata_value.get("files")
            recorded_version = metadata_value.get("runtimeVersion")
            if isinstance(recorded_version, str):
                skill_version = recorded_version
            packaged_digests = self._packaged_skill_digests()
            skill_digest_ok = (
                isinstance(recorded_files, dict)
                and recorded_files == packaged_digests
                and all(
                    (skill.parent / relative).is_file()
                    and hashlib.sha256((skill.parent / relative).read_bytes()).hexdigest() == digest
                    for relative, digest in packaged_digests.items()
                )
            )
        except (DistributionError, OSError):
            pass
        healthy = (
            installed
            and skill_digest_ok
            and configured
            and runtime_version is not None
            and runtime_version == skill_version
        )
        detail = (
            None if healthy else "run `amkernel install` to repair Runtime, Skill, or MCP drift"
        )
        return ProjectStatus(
            str(self.project),
            client,
            str(executable),
            installed,
            skill.is_file(),
            configured,
            healthy,
            detail,
            runtime_version,
            skill_version,
        )

    def _is_configured(self, client: Client, executable: Path) -> bool:
        path = self._config_path(client)
        try:
            if client == "codex":
                value = tomllib.loads(path.read_text(encoding="utf-8"))
                entry = value.get("mcp_servers", {}).get("amkernel", {})
            else:
                entry = _load_json_object(path).get("mcpServers", {}).get("amkernel", {})
            return (
                isinstance(entry, dict)
                and entry.get("command") == str(executable)
                and entry.get("cwd") == str(self.project)
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

    def uninstall_project(self, client: Client) -> ProjectStatus:
        with _exclusive_lock(self._project_lock_path()):
            path = self._config_path(client)
            transaction = ProjectTransaction(self.project)
            transaction.snapshot(path)
            skill = self.project / ".agents" / "skills" / "amkernel"
            for relative in (
                "SKILL.md",
                ".amkernel-metadata.json",
                "references/official-sources.json",
                "references/official-skills.json",
                "references/amkernel-appium.md",
                "scripts/verify_official_skills.py",
            ):
                transaction.snapshot(skill / relative)
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
                    _atomic_write(path, updated.encode())
                elif path.exists():
                    value = _load_json_object(path)
                    servers = value.get("mcpServers")
                    if isinstance(servers, dict):
                        servers.pop("amkernel", None)
                    _atomic_write(path, _json_bytes(value))
                shutil.rmtree(skill, ignore_errors=True)
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

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from amkernel.runtime import KernelRuntime

pytestmark = pytest.mark.anyio


async def test_read_write_cover_paths_types_encoding_and_limits(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "exact.bin").write_bytes(b"abc")
    (tmp_path / "invalid.bin").write_bytes(b"\xff")
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            """
import os

absolute = os.path.join(os.getcwd(), "nested", "absolute.txt")
values = {
    "textBytes": write("nested/text.txt", "héllo"),
    "binaryBytes": write(absolute, b"abc"),
    "text": read("nested/text.txt"),
    "binary": list(read("nested/absolute.txt", binary=True)),
    "exact": read("nested/exact.bin", binary=True, limit=3).decode(),
}
for label, expression in {
    "limit": lambda: read("nested/exact.bin", limit=2),
    "zero": lambda: read("nested/exact.bin", limit=0),
    "utf8": lambda: read("invalid.bin"),
    "writeType": lambda: write("bad.bin", bytearray(b"x")),
}.items():
    try:
        expression()
    except Exception as error:
        values[label] = type(error).__module__ + "." + type(error).__name__
display(values)
"""
        )
        assert result.status == "completed"
        assert result.output.displays[0].value == {
            "textBytes": 6,
            "binaryBytes": 3,
            "text": "héllo",
            "binary": [97, 98, 99],
            "exact": "abc",
            "limit": "amkernel.workspace.ReadLimitError",
            "zero": "amkernel.workspace.ReadLimitError",
            "utf8": "amkernel.workspace.ReadError",
            "writeType": "amkernel.workspace.WriteError",
        }
        assert (tmp_path / "nested" / "text.txt").stat().st_mode & 0o777 == 0o600
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_helpers_reject_traversal_symlinks_and_special_files(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside")
    (tmp_path / "directory").mkdir()
    (tmp_path / "locked").mkdir()
    (tmp_path / "locked" / "secret.txt").write_text("secret")
    (tmp_path / "locked").chmod(0)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    original_directory = os.open(".", os.O_RDONLY)
    try:
        os.chdir(tmp_path)
        listener.bind("socket")
    finally:
        os.fchdir(original_directory)
        os.close(original_directory)
    os.symlink(outside, tmp_path / "file-link")
    os.symlink(tmp_path.parent, tmp_path / "parent-link")
    os.symlink(tmp_path / "missing", tmp_path / "dangling")
    os.mkfifo(tmp_path / "fifo")
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            """
paths = [
    "", ".", "..", "../outside", "directory", "file-link",
    "parent-link/escape", "dangling", "dangling/child", "fifo", "socket",
    "locked/secret.txt", "/dev/null",
]
failures = {}
for path in paths:
    for operation in ("read", "write"):
        try:
            if operation == "read":
                read(path)
            else:
                write(path, "changed")
        except Exception as error:
            failures[path + ":" + operation] = type(error).__module__ + "." + type(error).__name__
display(failures)
"""
        )
        assert result.status == "completed"
        failures = result.output.displays[0].value
        assert isinstance(failures, dict)
        assert len(failures) == 26
        assert set(failures.values()) <= {
            "amkernel.workspace.ReadError",
            "amkernel.workspace.WriteError",
        }
        assert outside.read_text() == "outside"
    finally:
        (tmp_path / "locked").chmod(0o700)
        assert (await runtime.shutdown()).cleaned
        listener.close()
        outside.unlink()


async def test_write_pins_renamed_parent_and_rejects_destination_substitution(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside")
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            f"""\
import os
import threading

real_write = os.write
write_started = threading.Event()
write_may_finish = threading.Event()
armed = False

def controlled_write(descriptor, data):
    global armed
    written = real_write(descriptor, data)
    if armed:
        armed = False
        write_started.set()
        if not write_may_finish.wait(5):
            raise RuntimeError("race action did not finish")
    return written

def arm_race(action):
    global armed
    write_started.clear()
    write_may_finish.clear()
    armed = True

    def run_action():
        if write_started.wait(5):
            action()
            write_may_finish.set()

    thread = threading.Thread(target=run_action)
    thread.start()
    return thread

os.write = controlled_write
try:
    os.mkdir("parent")
    thread = arm_race(lambda: os.rename("parent", "moved-parent"))
    parent_count = write("parent/data.bin", b"x")
    thread.join()

    write("victim.txt", "original")

    def substitute_destination():
        os.unlink("victim.txt")
        os.symlink({str(outside)!r}, "victim.txt")

    thread = arm_race(substitute_destination)
    try:
        write("victim.txt", b"y")
    except Exception as error:
        race_error = type(error).__module__ + "." + type(error).__name__
    thread.join()
finally:
    os.write = real_write

write("atomic.txt", "retained")
try:
    write("atomic.txt", "\\ud800")
except Exception as error:
    atomic_error = type(error).__name__

display([
    parent_count,
    read("moved-parent/data.bin")[-1],
    race_error,
    atomic_error,
    read("atomic.txt"),
])
"""
        )
        assert result.status == "completed"
        assert result.output.displays[0].value == [
            1,
            "x",
            "amkernel.workspace.WriteError",
            "UnicodeEncodeError",
            "retained",
        ]
        assert outside.read_text() == "outside"
    finally:
        assert (await runtime.shutdown()).cleaned
        outside.unlink()


async def test_pinned_workspace_survives_root_rename(tmp_path: Path) -> None:
    (tmp_path / "before.txt").write_text("before")
    moved = tmp_path.with_name(f"{tmp_path.name}-moved")
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            f"""
import os

os.rename({str(tmp_path)!r}, {str(moved)!r})
os.mkdir({str(tmp_path)!r})
with open({str(tmp_path / "before.txt")!r}, "w") as substitute:
    substitute.write("substitute")
written = write("after.txt", "after")
display([read("before.txt"), read({str(tmp_path / "before.txt")!r}), written, read("after.txt")])
"""
        )
        assert result.status == "completed"
        assert result.output.displays[0].value == ["before", "before", 5, "after"]
        assert (tmp_path / "before.txt").read_text() == "substitute"
        assert (moved / "after.txt").read_text() == "after"
    finally:
        assert (await runtime.shutdown()).cleaned
        if moved.exists():
            if tmp_path.exists():
                (tmp_path / "before.txt").unlink()
                tmp_path.rmdir()
            moved.rename(tmp_path)


async def test_env_exact_semantics_persistence_and_reset(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        signatures = await runtime.execute(
            """
import inspect
[str(inspect.signature(read)), str(inspect.signature(write)), str(inspect.signature(env))]
"""
        )
        assert signatures.result == [
            "(path: 'object', *, binary: 'bool' = False, limit: 'int' = 1048576) -> 'str | bytes'",
            "(path: 'object', content: 'object') -> 'int'",
            "(key: 'object' = <missing>, value: 'object' = <missing>) -> 'object'",
        ]
        first = await runtime.execute(
            """
import os

snapshot = env()
name = "AMKERNEL_HELPER_TEST"
os.environ.pop(name, None)
values = [env(name), env(name, "one"), env(name), env(name, "two"), env(name, None), env(name)]
os.environ[name] = "direct"
values.append(env(name))
snapshot[name] = "detached"
values.append(env(name))
try:
    env(None)
except Exception as error:
    values.append(type(error).__module__ + "." + type(error).__name__)
for arguments in [("",), ("A=B",), (1,), ("VALID", "bad\\x00value"), ("VALID", 1)]:
    try:
        env(*arguments)
    except Exception as error:
        values.append(type(error).__module__ + "." + type(error).__name__)
env(name, "persistent")
display(values)
"""
        )
        assert first.status == "completed"
        assert first.output.displays[0].value == [
            None,
            None,
            "one",
            "one",
            "two",
            None,
            "direct",
            "direct",
            "amkernel.workspace.EnvError",
            "amkernel.workspace.EnvError",
            "amkernel.workspace.EnvError",
            "amkernel.workspace.EnvError",
            "amkernel.workspace.EnvError",
            "amkernel.workspace.EnvError",
        ]

        persistent = await runtime.execute('display(env("AMKERNEL_HELPER_TEST"))')
        assert persistent.output.displays[0].value == "persistent"

        overwritten = await runtime.execute('env = "shadowed"\nenv')
        assert overwritten.result == "shadowed"
        reset = await runtime.execute(
            'display([callable(env), env("AMKERNEL_HELPER_TEST"), '
            "repr(read), repr(write), repr(env)])",
            reset=True,
        )
        assert reset.status == "completed"
        assert reset.output.displays[0].value == [
            True,
            None,
            "<AMKernel helper read>",
            "<AMKernel helper write>",
            "<AMKernel helper env>",
        ]
    finally:
        assert (await runtime.shutdown()).cleaned

# ADR-0004: Stage 1 Runner Protocol

- Status: Accepted
- Date: 2026-10-28
- Deciders: Project owner; Contract and Integration Lead
- Supersedes: None
- Related: [`../architecture.md`](../architecture.md), [ADR-0003](0003-stage-1-execution-contract.md), [S1-001](https://github.com/FSQ-lab/amkernel/issues/10), [S1-020](https://github.com/FSQ-lab/amkernel/issues/9), [R-001](https://github.com/FSQ-lab/amkernel/issues/23), [R-002](https://github.com/FSQ-lab/amkernel/issues/32), [R-007](https://github.com/FSQ-lab/amkernel/issues/20), [R-011](https://github.com/FSQ-lab/amkernel/issues/33)

## Context

The MCP server and persistent Python Runner are separate processes. MCP stdio already occupies the host's stdin/stdout, while arbitrary Python and inherited subprocesses may emit any bytes to their stdout/stderr. A line-delimited protocol on a user stream would let JSON-looking output corrupt control state. The private protocol therefore needs explicit channels, framing, versioning, correlation, limits, initialization, and deterministic crash mapping before Runner and Supervisor work can proceed independently.

## Decision

### Channels and ownership

The Supervisor creates five one-way POSIX pipes before spawning the Runner:

```text
host -> runner  request control
runner -> host  response control
runner -> host  diagnostics
runner -> host  user stdout
runner -> host  user stderr
```

The spawn seam is exact:

```text
os.path.abspath(sys.executable)  # preserve venv symlinks; never realpath
  -I -u -X utf8
  -m amkernel.runner
  --request-fd <child request-read fd>
  --response-fd <child response-write fd>
  --diagnostic-fd <child diagnostic-write fd>
```

The Supervisor uses `stdin=DEVNULL`, `stdout=PIPE`, `stderr=PIPE`, the captured launch cwd, ADR-0005's filtered environment, `start_new_session=true`, `close_fds=true`, and `pass_fds` containing exactly the three numbered control/diagnostic child ends. It uses no `preexec_fn`. The parent retains request-write, response-read, diagnostic-read, stdout-read, and stderr-read ends and closes every opposite end immediately after spawn.

`protocol.py`, owned by the Contract and Integration Lead, defines the three argument names and a bootstrap parser shared by both owners. Runner bootstrap accepts no other arguments, validates three distinct open descriptors ≥ 3, marks them non-inheritable, installs the fork hook, opens unbuffered binary control streams, and only then handles `initialize`. Bootstrap output before readiness is idle host diagnostics, never user output. These argv/descriptor rules are the complete Supervisor/Runner construction interface; neither owner invents a second environment variable or fixed-fd convention.


The Runner receives only the child ends it needs. Control and diagnostic descriptors are marked close-on-exec immediately after bootstrap, and the Runner registers an `after_in_child` fork hook that closes them in ordinary `os.fork` and `multiprocessing` fork children; stdout/stderr remain available to user-created descendants. Close-on-exec alone does not prevent fork inheritance. Raw native-extension forks that bypass CPython's registered fork hooks remain inside the non-sandbox limitation, so the Supervisor also observes the owned Runner PID concurrently and never relies on response-pipe EOF alone to detect Runner death.

The MCP process keeps its own stdin/stdout exclusively for the official SDK transport. No Runner or user byte is copied unframed to MCP stdout.

User stdout/stderr are raw byte streams, not JSON. The Supervisor opens a correlation's output-capture window immediately before attempting the first byte of its `execute` frame and closes it only after terminal-frame drain or fatal process cleanup. This ordering captures output from a very fast cell even though control and output use different pipes. Bytes observed while no capture window is open are bounded idle diagnostics and are not attached to a later cell. Output from an earlier background thread/process that arrives during a later capture window is indistinguishable at this seam and is attributed to that later call; Stage 1 makes no stronger origin claim. Before sending `done`, the Runner flushes normal Python text streams. The Supervisor drains bytes already readable when it receives the terminal frame, then closes the window; later asynchronous output observed while idle is orphan output. Stage 2 may replace this completion snapshot with a streaming design without changing control framing.

This isolation defends accidental and inherited output, including JSON-looking lines and invalid UTF-8. AMKernel remains unrestricted same-user execution, not a sandbox: code that deliberately enumerates and writes arbitrary process descriptors is outside the isolation claim.

### Control framing

Each control message is:

```text
4-byte unsigned big-endian payload length
UTF-8 JSON object of exactly that length
```

The maximum JSON payload is 8,388,608 bytes. The codec serializes with UTF-8, `ensure_ascii=false`, and compact separators; this bound accommodates the worst-case JSON escaping of every publicly accepted 1,048,576-byte code cell plus its envelope. Zero-length, oversized, truncated, non-UTF-8, non-object, duplicate-key, unknown-field, and schema-invalid payloads are protocol violations. JSON numbers used by the protocol must be finite.

Every message has this envelope:

```json
{
  "protocolVersion": 1,
  "type": "execute",
  "correlationId": "32 lowercase hexadecimal characters",
  "payload": {}
}
```

`protocolVersion`, `type`, `correlationId`, and `payload` are the envelope's only fields and are all required. `protocolVersion` is the integer `1`. `correlationId` matches `^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$`, is generated as UUIDv4 without hyphens by the host, and is repeated by every response to that request. `payload` is an object. Unknown fields are rejected in the envelope and every protocol-defined payload/runtime/error object; keys inside the opaque user `result` value are unrestricted JSON object keys. String bounds below are measured as UTF-8 bytes after JSON decoding.

Host and Runner ship together. Version 1 has no negotiation range: any other version fails closed. When a valid envelope supplies a correlation ID, the Runner emits `protocol_error` before exit; an undecodable envelope is logged on the diagnostic channel and exits without a response. A future incompatible schema increments the integer version and updates both peers in one clean cutover.

### Host requests

Version 1 accepts exactly these request schemas:

| Type | Exact payload | Valid transition |
| --- | --- | --- |
| `initialize` | `{"launchWorkingDirectory": string, "environmentKind": "project_venv" | "active_venv" | "system"}` | first request only |
| `execute` | `{"code": string}` | after `ready`, while idle |
| `shutdown` | `{}` | after `ready`, while idle |

`launchWorkingDirectory` is an absolute canonical path of at most 16,384 UTF-8 bytes. `code` is at most 1,048,576 UTF-8 bytes. The envelope already carries the expected protocol version; no payload repeats it.

The Runner validates its actual executable, Python version, working directory, and environment kind before answering `initialize` with `ready`. On `execute`, it computes the next count, writes `started` before running any user code, and makes that count current only after the frame write succeeds. A failed/missing `started` therefore leaves the host's last validated count unchanged and the fatal path destroys the uncertain Runner. `shutdown` asks the Runner to leave its request loop and exit cleanly without an acknowledgement frame. Reset is not a Runner request: the Runtime shuts down the old process group, creates a new Runner, initializes it, and then executes the reset call's cell. This makes replacement observable at the process seam rather than pretending an in-process namespace clear is equivalent.

### Runner responses

Version 1 emits exactly `ready`, `started`, `done`, and `protocol_error`.

`RuntimeDiagnostics` is the exact object:

```json
{
  "executable": "/absolute/path/to/python",
  "pythonVersion": "3.x.y",
  "workingDirectory": "/absolute/path",
  "environmentKind": "project_venv"
}
```

`executable` is the absolute launcher path, deliberately not realpathed; `workingDirectory` is an absolute canonical path. Each is at most 16,384 UTF-8 bytes. `pythonVersion` is a non-empty string of at most 128 UTF-8 bytes. `environmentKind` uses the same three-value enum as `initialize`.

The response payload schemas and conditional fields are:

| Type | Exact payload fields | Conditions |
| --- | --- | --- |
| `ready` | `executionCount`, `runtime` | `executionCount` is exactly `0`; answers `initialize` |
| `started` | `executionCount` | integer ≥ 1 and exactly previous count + 1; first response to `execute` |
| `done` | `outcome`, `executionCount`, `runtime`, `hasResult`, optional `result`, optional `error` | sole terminal response after `started` |
| `protocol_error` | `code`, `message` | correlated request rejection or fatal runtime/internal error in an explicitly valid sequence; Runner exits after sending |

For `done`, `outcome` is `completed`, `failed`, or `interrupted`; it never contains public `timed_out` or `kernel_killed`. `executionCount` equals `started.executionCount`. `hasResult` is boolean. `result` is present iff `outcome=completed` and `hasResult=true`, and its compact JSON encoding is at most 1,048,576 bytes. `error` is present iff `outcome` is `failed` or `interrupted` and is exactly `{"type": string, "message": string, "traceback": string[]}`. Error type is at most 256 decoded UTF-8 bytes and message at most 16,384, but the **entire compact encoded error object**, including JSON escaping, field overhead, and traceback, may not exceed 65,536 bytes; conversion truncates message/traceback to satisfy the aggregate bound and marks truncation in the last traceback line. For `interrupted`, error type is `KeyboardInterrupt` and `hasResult=false`. The Runner does not send public duration or kernel state; the Supervisor measures `durationMs` from `started` and observes survival.

`protocol_error.code` is one of `version_mismatch`, `invalid_sequence`, `invalid_request`, `runtime_diagnostics_error`, or `internal_protocol_error`; `message` is a non-empty diagnostic of at most 4,096 UTF-8 bytes. User-code exceptions never use `protocol_error`.

The Supervisor dispatches responses as follows:

- `ready`: validate correlation, zero count, configured executable/cwd/environment kind, then enter `alive`;
- `started`: validate the next count, finish the command-delivery/ack phase, and start the cell deadline;
- any valid `done` after the Supervisor recorded SIGINT for that correlation ID and before it validated a terminal frame: deadline wins and maps to public `timed_out/alive`; trailing result/error is discarded in favor of `TimeoutError`, while output and mutations remain;
- otherwise `done/completed` maps to public `completed/alive`, and `done/failed` maps to public `failed/alive`;
- otherwise `done/interrupted` maps to `failed/alive` with `KeyboardInterrupt`;
- `protocol_error`: record the bounded diagnostic, clean the process group, and map to `kernel_killed/dead`; `runtime_diagnostics_error` becomes public `RuntimeDiagnosticsError`, all other codes become `RunnerProtocolError`;
- any other frame/schema/transition: fail closed as `RunnerProtocolError` and map to `kernel_killed/dead`.

The diagnostic pipe is not another structured protocol. The Runner writes UTF-8 diagnostic text only; the Supervisor drains it continuously, retains a 65,536-byte UTF-8-safe tail, decodes invalid bytes with replacement, and emits it only to the host diagnostic logger after infrastructure failure. It is never user stderr, MCP content, or a `done` field. Diagnostic EOF alone does not decide kernel survival.

Stage 1 defines no `display` or `artifact` frames because their complete behavior belongs to Stage 2. Adding them requires a later protocol ADR/version.

### Sequencing and failure mapping

The only valid sequences are:

```text
initialize -> ready
initialize -> protocol_error -> exit
execute -> started -> done
execute -> protocol_error -> exit
execute -> started -> protocol_error -> exit
shutdown -> clean EOF/exit 0
shutdown -> protocol_error -> exit
```

No pipelining is allowed on a single Runner. The Supervisor opens output capture and starts a fixed 5.0-second command-delivery/ack deadline **before attempting the first frame byte**. Request-pipe writes are asynchronous/non-blocking with respect to the host event loop; the complete length prefix and JSON frame must be written and a matching valid `started` must be received inside that single deadline. Partial write, blocked write/drain, cancellation after the first-byte commit point, or missing `started` is fatal `RunnerProtocolTimeout`; the Supervisor closes the request pipe, terminates the managed group, and reports the last validated execution count. An unexpected frame, duplicate terminal frame, invalid transition, correlation mismatch, malformed control message, response EOF before a terminal frame, or Runner exit before `done` is likewise fatal and maps to `kernel_killed/dead`.

EOF after the host has sent a valid `shutdown` request is expected only when the owned Runner exits with status 0 and the managed group is gone. EOF while idle without shutdown is kernel death. Runner PID exit is decisive even if a forked child still holds copied pipe descriptors. Diagnostic-channel EOF alone is not death.

### Cell semantics

The Runner owns one namespace and one execution counter. Initialization creates the namespace with `__name__ = "__main__"`, normal builtins, and no Stage 1 helper bindings.

For every accepted execute request the Runner:

1. blocks SIGINT while the idle handler remains installed;
2. computes the next execution count and marks execution active;
3. emits `started` and, only after that write succeeds, commits the count;
4. unblocks SIGINT, after which the Supervisor may start the cell deadline;
5. parses the cell with `ast.parse(..., mode="exec")` using filename `<amkernel-cell-N>`;
6. executes all statements before a final `ast.Expr` and evaluates that expression in the persistent namespace;
7. converts its value or error under ADR-0003's bounds;
8. blocks SIGINT, marks execution inactive, restores the idle handler and baseline signal mask, flushes stdout/stderr, emits `done`, then unblocks SIGINT.

The Runner catches ordinary `BaseException` subclasses from user compilation/evaluation, including `SystemExit`, and emits `done/failed`; it does not catch process termination signals or unrecoverable interpreter failure. Any caught `KeyboardInterrupt` emits the neutral `done/interrupted` outcome. The Runner does not know whether the signal came from a Supervisor deadline/cancellation or user code; only the Supervisor maps that outcome under the dispatch rules above.

The Runner reserves SIGINT for lifecycle control. Its installed idle handler records and absorbs SIGINT without raising in the request loop. User code may replace or block that handler during a cell, in which case timeout may require destructive escalation. In every cell-finalization path the Runner blocks SIGINT with `pthread_sigmask`, marks execution inactive, restores the idle handler, flushes streams, emits `done`, and then unblocks SIGINT before reading another request. A pending or late deadline signal is therefore handled by the idle handler and cannot kill the Runner after a terminal frame. Public precedence remains Supervisor-owned: once it records SIGINT before validating `done`, deadline wins and any Runner outcome maps to `timed_out/alive`; without that record, normal `completed`, `failed`, or `interrupted` mapping applies.

Mutations performed before an exception remain. Runner protocol and bookkeeping objects are not placed in the user namespace. A reset gets a new process and cannot retain Python object identity.

## Consequences

### Positive

- Printing arbitrary text, partial UTF-8, or JSON-looking lines cannot be parsed as control frames.
- Host and Runner share a small, bounded, fail-closed protocol.
- Correlation, execution count, and state transitions are observable before independent implementation begins.
- Reset cannot accidentally degrade into a shallow namespace clear.
- Completion-time capture works for Python, native writes, and inherited subprocess output without buffering all output in the Runner.

### Costs and constraints

- Version 1 is POSIX-specific because it relies on passed file descriptors and process groups.
- Output observed while idle is not attributed to a later call; output from an earlier background producer that overlaps a later active cell is attributed to the later cell in Stage 1.
- The private protocol is intentionally single-flight; concurrency belongs to the Runtime queue, not the Runner.
- Deliberate same-process descriptor attacks are not prevented and are outside the non-sandbox security claim.

## Alternatives considered

### JSON Lines on Runner stdout

Rejected. User and descendant output can produce identical lines, partial writes, and invalid UTF-8.

### Reuse MCP stdin/stdout for Runner control

Rejected. It creates two protocols on one transport and lets user output corrupt the public MCP connection.

### Execute cells in the MCP host process

Rejected by ADR-0001. It cannot provide truthful hard-kill state or isolate protocol transport from arbitrary code.

### Send reset as a Runner command

Rejected. Clearing a dictionary cannot guarantee removal of threads, imported module state, signal handlers, file descriptors, or descendants; reset is process replacement.

### Add Stage 2 display/artifact frames preemptively

Rejected. Unused frame types would be speculative interface weight and would invite incomplete behavior.

## Verification

S1-020 and S1-030 must prove:

1. fragmented/coalesced reads decode one bounded frame, while a stopped reader and maximum-size partial write time out from the first byte without blocking the host event loop;
2. maximum-size high-escape public code fits the private frame, while one-byte-over code is rejected by the Adapter before Runner dispatch;
3. every exact message schema and conditional field rejects missing, extra, mistyped, oversized, non-finite, version-mismatched, and correlation-mismatched values, including the aggregate encoded error bound;
4. immediate first-instruction output, `os.write`, invalid UTF-8, large writes, JSON-looking output, and inherited subprocess output never become frames or race out of the pre-write capture window;
5. ordinary `os.fork`/fork-context children close private descriptors, while Runner PID observation and group cleanup remain bounded even when a raw fork retains a pipe;
6. initialization, execution, neutral interruption mapping, completion-at-deadline races, late idle SIGINT, withheld `started`, shutdown, protocol-error exits, unexpected EOF, and crash follow only valid transitions;
7. validated execution counts and mutation retention survive ordinary failures; missing `started` preserves the last validated count; reset restarts at zero;
8. output observed outside a capture window is not attributed later, and overlapping background output follows the documented window attribution limit;
9. every fatal protocol event becomes observed `kernel_killed/dead`, never an inferred live kernel.

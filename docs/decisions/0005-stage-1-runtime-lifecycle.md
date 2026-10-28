# ADR-0005: Stage 1 Runtime Lifecycle

- Status: Accepted
- Date: 2026-10-28
- Deciders: Project owner; Contract and Integration Lead
- Supersedes: None
- Related: [`../architecture.md`](../architecture.md), [ADR-0003](0003-stage-1-execution-contract.md), [ADR-0004](0004-stage-1-runner-protocol.md), [S1-001](https://github.com/FSQ-lab/amkernel/issues/10), [S1-030](https://github.com/FSQ-lab/amkernel/issues/8), [S1-040](https://github.com/FSQ-lab/amkernel/issues/2), [R-002](https://github.com/FSQ-lab/amkernel/issues/32), [R-003](https://github.com/FSQ-lab/amkernel/issues/24), [R-004](https://github.com/FSQ-lab/amkernel/issues/22), [R-005](https://github.com/FSQ-lab/amkernel/issues/34), [R-006](https://github.com/FSQ-lab/amkernel/issues/18), [R-008](https://github.com/FSQ-lab/amkernel/issues/29), [R-013](https://github.com/FSQ-lab/amkernel/issues/26)

## Context

One MCP process owns one persistent Runner. Before implementation, the Runtime and Supervisor need one state machine for FIFO execution, lazy startup, reset, cancellation, timeout escalation, process ownership, shutdown, interpreter/cwd selection, environment exposure, and platform claims. Ambiguity in any of these areas can race one namespace, leak descendants, recreate lost state silently, or report a live kernel after process death.

## Decision

### Runtime state and queue

The Runtime has four internal states:

```text
new -> alive -> dead -> closed
  \             ^
   \-> dead ----|
```

- `new`: no Runner has been started.
- `alive`: one initialized Runner is accepting serialized work.
- `dead`: the Runner or its protocol is unusable. No automatic transition to `alive` exists.
- `closed`: MCP shutdown has started; no new work is accepted.

One Runtime-owned FIFO command queue and one worker task serialize execute and reset transitions. The Runner is single-flight. Queue wait does not consume the cell timeout. A request cancelled while still queued is marked abandoned and skipped without creating or mutating a kernel.

After dequeue, startup, reset cleanup, and replacement are non-cancellable stabilization work. Immediately before execute delivery, the worker performs a cancellation checkpoint. Cancellation observed before any frame byte is attempted finishes already-started lazy startup/reset, sends no cell, leaves the initialized Runner alive at its prior count (replacement count 0), and returns no result to the disconnected caller. Attempting the first execute-frame byte is the execution commit point: output capture opens and one 5.0-second delivery/ack deadline covers the entire asynchronous write plus matching `started`. Cancellation or timeout during a partial/blocked write is fatal and kills the uncertain Runner with no public count increment; after a complete write, cancellation waits only for `started` within the remaining deadline and then enters active cancellation. The worker stabilizes alive/dead state before the next queue item.

The first `reset=false` call in `new` lazily starts and initializes the Runner, then commits the cell unless cancelled. Lazy startup lets the official SDK serve discovery even when Runner startup will fail; startup failure returns a truthful structured `kernel_killed/dead` outcome rather than corrupting MCP initialization.

In `dead`, `reset=false` never starts a process and returns `KernelUnavailable`. `reset=true` is the only recovery transition: it cleans any remaining managed group and starts an initialized replacement even if the caller cancels after dequeue; its cell runs only after the commit point above. In `closed`, the Adapter rejects new calls as an MCP tool error because no execution is accepted.

### Reset order

A queued `reset=true` command performs exactly:

1. stop accepting work on the current Runner;
2. request graceful Runner shutdown when its protocol is usable;
3. clean the entire managed process group with bounded escalation;
4. verify that no process remains in that group;
5. start a replacement with the same interpreter, launch cwd, and filtered environment;
6. validate its `ready` diagnostics;
7. unless cancellation was observed before the execution commit point, execute the reset call's cell as execution 1; otherwise retain the replacement alive at count 0.

The Runtime never starts the replacement before step 4 succeeds. A cleanup or startup failure leaves state `dead` and returns `kernel_killed/dead` with `ResetCleanupError` or `KernelStartError`. Reset does not promise cleanup of resources outside the managed process group.

### Timeout and cancellation

The Supervisor uses monotonic deadlines. It opens output capture and starts the fixed 5.0-second command-delivery/ack deadline before the first execute-frame byte. The complete frame write and matching valid `started` must both finish within it; failure is fatal `RunnerProtocolTimeout` and destructively cleans the group. The user timeout begins only after `started`. At that deadline the Supervisor first checks whether it has already validated a terminal frame; otherwise it records the correlation ID, sends `SIGINT` to the managed process group, and starts a 1.0-second interrupt grace period.

- Once SIGINT is recorded, deadline wins: any valid `done` during grace maps to `timed_out/alive`, with user result/error discarded for `TimeoutError` while output and completed mutations remain.
- Runner finalization blocks SIGINT, restores its idle non-raising handler, emits `done`, then unblocks; a pending/late signal therefore cannot turn that alive result into a dead process after the fact.
- A managed descendant that ignores SIGINT may remain in the still-owned live process group after `timed_out/alive`; that outcome does **not** claim descendant cleanup. It remains managed and must be removed by later reset or shutdown.
- If no valid terminal `done` arrives, the Supervisor sends `SIGTERM` to the group and waits 1.0 second.
- If any managed process remains, it sends `SIGKILL` and waits a final 1.0 second.
- Any path that reaches `SIGTERM`, observes Runner exit, loses the response channel, or cannot prove the Runner request loop survived returns `kernel_killed/dead`.
- If the process group still exists after final grace, the result remains `kernel_killed/dead` and the error is `CleanupError`; it never claims successful cleanup.

Cancellation after valid `started` uses the same SIGINT/TERM/KILL path and deadline-wins rule. The disconnected caller is not guaranteed a result; the next caller observes the resulting namespace and kernel state. If the cell completed before cancellation was recorded, its mutations remain.

Without a Supervisor SIGINT record—including `raise KeyboardInterrupt` or a user-sent SIGINT—`done/interrupted` maps to ordinary `failed/alive`. Other ordinary `done` outcomes retain their completed/failed mapping.

### Startup and shutdown bounds

A Runner must emit valid `ready` diagnostics within 5.0 seconds of spawn. From the first attempted execute-frame byte, the entire write plus matching valid `started` must finish within 5.0 seconds. Startup/delivery/ack timeout, partial write, early exit, malformed readiness, diagnostic mismatch, or live-but-silent Runner moves the Runtime to `dead` and cleans the group.

Graceful reset while idle sends the private `shutdown` request and waits 1.0 second. Remaining processes then receive `SIGTERM` with 1.0-second grace and `SIGKILL` with 1.0-second final grace. Escalation is acceptable only when the group is confirmed gone; an unremoved group is a cleanup failure.

MCP transport shutdown is a priority lifecycle signal, not a FIFO command behind user work. The Adapter atomically enters `closed`, rejects new calls, cancels queued calls, and wakes the Runtime worker. If a cell is committed, the Supervisor sends SIGINT immediately and waits 1.0 second; when the Runner returns `done`, it sends `shutdown` and waits 1.0 second, otherwise it proceeds directly to TERM/KILL with the fixed 1.0-second graces. If startup or reset replacement is in progress, no further replacement is started and every created group is cleaned. Shutdown therefore ignores a user timeout as large as 3600 seconds and is bounded by the lifecycle graces.

The Adapter waits for shutdown cleanup. A cleanup failure is written to the dedicated host diagnostic stream and makes the console entry point exit non-zero after MCP stdout closes. It is never inserted into MCP stdout or user stderr. Deterministic process-primitive failure seams verify this mapping because a genuinely unkillable same-user process is not a portable test fixture.

### Process ownership

On POSIX the Supervisor starts each Runner with a new session and process group whose ID is the Runner PID. The managed set is:

> the Runner and every process still belonging to that process group.

Signals target the group, not only the Runner PID. The group intentionally persists across normal cells and handled timeouts; those outcomes do not claim descendant cleanup. Destructive timeout escalation, reset, and shutdown verify both the reaped Runner process and absence of the group. PID values are internal and never part of the public result.

Arbitrary code can create external sessions, daemons, Appium sessions, sockets, and other resources that leave this group. AMKernel cannot discover or claim those resources. Such resources are explicitly `unknown/external`, and project skills or the calling Agent remain responsible for them.

### Interpreter and working directory

Stage 1 has no interpreter-selection registry or runtime configuration. The Runner executable is exactly `os.path.abspath(sys.executable)` from the installed `amkernel` entry point. It is made absolute but never passed through `realpath`/`Path.resolve`, because the common `.venv/bin/python` symlink must remain the launcher path that lets CPython discover `pyvenv.cfg` and venv site-packages. This makes the package environment selected by the host command the execution environment and avoids a second PATH lookup.

The server captures `Path.cwd().resolve()` once at launch. Every Runner starts in that directory. User code may call `os.chdir`; diagnostics report the resulting current directory on each completed cell. If the Runner cannot resolve the required post-cell cwd—for example because user code removed it—it emits `runtime_diagnostics_error` and exits; the Supervisor returns `RuntimeDiagnosticsError` as `kernel_killed/dead`, using the last valid/configured runtime diagnostics, and reset is required. Reset restores the captured launch directory. Stage 1 provides no confined file helpers, and unrestricted Python filesystem access retains the permissions of the launching user.

`environmentKind` is derived without heuristics based on directory names alone:

- `project_venv`: `sys.prefix != sys.base_prefix` and the resolved prefix is the launch cwd's `.venv` directory;
- `active_venv`: `sys.prefix != sys.base_prefix` but it is not that project `.venv`;
- `system`: `sys.prefix == sys.base_prefix`.

### Environment exposure

The Supervisor builds the Runner environment from an allowlist rather than inheriting the host mapping. On POSIX it may forward only these existing variables:

```text
HOME LANG LC_ALL LC_CTYPE LOGNAME PATH SHELL TERM TMPDIR TZ USER
```

No `PYTHON*` variable is forwarded or synthesized. The frozen spawn command uses `-I -u -X utf8`: isolated mode ignores user site and all `PYTHON*` configuration, unbuffered mode exposes writes promptly, and UTF-8 mode fixes text encoding independently of the parent locale.

When a virtual environment is active the Supervisor adds only `VIRTUAL_ENV`, set to resolved `sys.prefix`; it does not trust an inherited value. The resulting mapping is exactly the existing allowlisted keys plus this derived key when applicable. Proxy variables, cloud credentials, model/provider credentials, project secrets, and arbitrary application variables are not forwarded. Stage 1 has no user-configurable environment pass-through. Later credential or environment support requires a separate security decision and explicit configuration.

The interpreter path, Python version, cwd, and environment kind are public diagnostics. The full environment is never reported.

### Initial platform policy

The Stage 1 implementation target is CPython on POSIX systems that provide passed file descriptors, process groups, `os.register_at_fork`, `signal.pthread_sigmask`, and `SIGINT`, `SIGTERM`, and `SIGKILL`. The entry point fails clearly with `UnsupportedPlatformError` before starting a Runner when those primitives are unavailable. Windows lifecycle support is deferred rather than approximated.

This target is not a published support claim. S1-080 must run native lifecycle scenarios for every candidate Python/OS pair. S1-085 may publish only the bounded contiguous Python range and operating systems approved from that evidence. Untested systems remain unsupported.

## Consequences

### Positive

- Exactly one owner controls mutation ordering and kernel state.
- Dead-kernel recovery is explicit and destructive.
- Timeout, cancellation, reset, and shutdown share one bounded escalation implementation.
- Interpreter, cwd, environment exposure, and managed-process claims are deterministic.
- External resources are not misreported as cleaned.

### Costs and constraints

- A cancelled client may not receive the state transition it caused; the next call remains truthful.
- Credentials and arbitrary environment variables are unavailable until explicit secure configuration exists.
- POSIX process primitives defer Windows support.
- Background processes that deliberately leave the managed group are outside cleanup guarantees.
- Fixed grace periods favor deterministic Stage 1 behavior over tunable policy; changing them is a lifecycle contract change.

## Alternatives considered

### Run each tool call immediately under an async lock

Rejected. A dedicated FIFO worker makes cancellation, reset ordering, and post-cancellation stabilization explicit instead of relying on scheduler fairness.

### Recreate a dead kernel on the next normal call

Rejected. It hides loss of Python objects and violates the central state-truth invariant.

### Count queue and reset time against the user timeout

Rejected. The architecture defines timeout as active cell work; lifecycle delays are separately bounded.

### Signal only the Runner PID

Rejected. Inherited subprocesses would remain and continue holding resources or output pipes.

### Inherit the launching environment

Rejected. It would expose unrelated credentials and allow `PYTHONPATH`/`PYTHONHOME` to change the selected execution environment.

### Claim macOS and Linux support from shared POSIX code

Rejected. Similar primitives do not prove equivalent lifecycle behavior; native evidence is required.

## Verification

S1-030, S1-040, S1-060, S1-070, and S1-080 must prove:

1. strict FIFO ordering for simultaneous execute/reset/cancel requests;
2. queue wait exclusion from active timeout plus bounded fatal outcomes for blocked/partial frame write and withheld `started`, all timed from the first attempted byte;
3. cancellation at queued, lazy-start, reset-cleanup, replacement-ready, before-first-byte, partial-write, fully-delivered/pre-`started`, and active-cell barriers follows the frozen commit-point rules;
4. handled interrupt and repeated completion-at-deadline races yield truthful `timed_out/alive`, survive pending/late idle SIGINT, permit immediate reuse, and keep a SIGINT-ignoring descendant explicitly managed until reset/shutdown;
5. ignored/caught interrupt and a blocking native-extension/C-call workload escalate to `kernel_killed/dead` and require reset;
6. reset never overlaps old and replacement process groups, normally restarts at execution 1, and cancellation before commit retains the replacement at count 0;
7. destructive timeout escalation, reset, active transport shutdown, Runner crash, and cancellation that reaches TERM/KILL remove every managed descendant; normal completion and handled timeout/cancellation make no cleanup claim;
8. deterministic signal/group-verification failure seams produce dead state, suppress replacement, keep MCP/user streams clean, and make shutdown exit non-zero;
9. an escaped external process is not claimed as managed or cleaned;
10. a symlinked venv launcher remains the exact absolute interpreter path, Runner imports the installed package, and launch/reset cwd, changed cwd, deleted/inaccessible cwd failure, plus environment kind remain truthful;
11. the child environment contains exactly forwarded allowlist keys plus derived `VIRTUAL_ENV`; every `PYTHON*`, proxy, provider/cloud credential, and arbitrary parent sentinel is absent, while `-I -u -X utf8` behavior is observed;
12. official-SDK stdio cancellation and transport close during stubborn execution complete within lifecycle bounds;
13. unsupported platforms fail clearly and no OS/Python support claim is published without S1-080 evidence.

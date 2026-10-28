# ADR-0003: Stage 1 Execution Contract

- Status: Accepted
- Date: 2026-10-28
- Deciders: Project owner; Contract and Integration Lead
- Supersedes: None
- Related: [`../architecture.md`](../architecture.md), [`../development.md`](../development.md), [S1-001](https://github.com/FSQ-lab/amkernel/issues/10), [S1-050](https://github.com/FSQ-lab/amkernel/issues/3), [R-002](https://github.com/FSQ-lab/amkernel/issues/32), [R-007](https://github.com/FSQ-lab/amkernel/issues/20), [R-010](https://github.com/FSQ-lab/amkernel/issues/25), [R-011](https://github.com/FSQ-lab/amkernel/issues/33)

## Context

The architecture fixes the shape and state-truth requirements of the first MCP tool, but Stage 1 cannot implement or test the Adapter until its exact name, validation, result population, MCP mapping, bounds, and diagnostics are stable. Execution failures are expected domain outcomes, not MCP transport failures. Stage 2 will add live streaming, structured display, images, and artifact spill; Stage 1 still needs bounded and truthful completion-time output.

## Decision

### Tool

The sole model-facing tool is named `python_exec` and has the display title `Execute Python`.

Its input is:

```ts
type PythonExecInput = {
  code: string;
  title?: string;
  timeout?: number;
  reset?: boolean;
};
```

The exact rules are:

- `code` is required. Empty and whitespace-only cells are valid. Its UTF-8 encoding may not exceed 1,048,576 bytes.
- `title` is optional presentation metadata, limited to 200 Unicode code points. It never changes execution, ordering, timeout, or result semantics.
- `timeout` is optional wall-clock seconds for active cell execution. The default is `30.0`; accepted values are finite numbers greater than `0` and at most `3600.0`.
- `reset` defaults to `false`. When true, the Runtime completes destructive replacement before executing `code`.
- Unknown input fields and invalid values fail SDK/tool validation before the Runtime is called.
- There is no runtime identifier, non-blocking flag, platform action, or environment override.

The tool description states that the namespace persists, calls serialize, mutations before an exception remain, `reset` is destructive, `input()` is unsupported, and callers must check `status` and `kernelState`. It also states that code runs unrestricted with the launching user's permissions, is not sandboxed or workspace-confined, and reset/shutdown clean only the managed process group—not escaped processes, sockets, or external sessions.

### Result

Every accepted call that remains connected through completion returns one structured object with the architecture fields plus required runtime diagnostics:

```ts
type PythonExecResult = {
  status: "completed" | "failed" | "timed_out" | "kernel_killed";
  stdout: string;
  stderr: string;
  result?: unknown;
  error?: {
    type: string;
    message: string;
    traceback: string[];
  };
  executionCount: number;
  durationMs: number;
  kernelState: "alive" | "dead";
  runtime: {
    executable: string;
    pythonVersion: string;
    workingDirectory: string;
    environmentKind: "project_venv" | "active_venv" | "system";
  };
  output: {
    totalBytes: number;
    totalLines: number;
    truncated: boolean;
    artifact?: ArtifactRef;
  };
  artifacts: ArtifactRef[];
};
```

`runtime` is required even when the kernel is dead. It reports the configured executable and initial working directory from the host, refined by the latest valid Runner diagnostics when available. `workingDirectory` is the Runner's current directory after the cell; a reset restores the server launch directory.

Result invariants are:

| Status | Required state | Error | Meaning |
| --- | --- | --- | --- |
| `completed` | `alive` | absent | The cell finished normally. `result` is present only when the cell had a trailing expression; a trailing `None` is represented by a present JSON `null`. |
| `failed` | `alive` | present | Compilation, execution, or bounded result conversion raised an ordinary Python error. Completed mutations remain. |
| `timed_out` | `alive` | `TimeoutError` | The Supervisor recorded deadline/cancellation SIGINT before validating a terminal frame, and the Runner returned safely during grace. Deadline wins even if the cell completed concurrently: trailing result/error is discarded, while output and completed mutations remain. |
| `kernel_killed` | `dead` | present | The Runner died, was destructively escalated, violated the private protocol, could not be started, or is already unavailable. Prior Python objects are unusable. |

A dead kernel is never recreated by `reset=false`. Such a call returns `kernel_killed/dead` with `KernelUnavailable`, zero active duration, and the last execution count. Recovery requires `reset=true`.

`executionCount` increments publicly only when the Supervisor validates `started`, including cells that later fail, time out, or force kernel death. Calls rejected/cancelled before the first-byte commit, or killed during partial delivery/before valid `started`, report the last validated count even if the destroyed Runner had transient internal state. Once reset confirms the old group is gone, the Runtime resets its remembered count to 0 before replacement startup; a later replacement-start failure therefore reports 0, while cleanup failure before that point reports the old last count. A successful reset cell is execution 1.

`durationMs` is a non-negative integer derived from a monotonic clock between valid `started` and the terminal outcome. Queue wait, reset cleanup, replacement startup, and command-delivery/ack time are excluded. A failure before valid `started` reports `0`; death or escalation after `started` reports elapsed active time through the observed terminal process outcome.

### Trailing values and errors

The Runner executes all but the final expression with `exec` and evaluates a final `ast.Expr` with `eval` in the same namespace. JSON-compatible values are values accepted by strict JSON encoding with string object keys and no NaN or infinity. Their compact UTF-8 JSON encoding may not exceed 1,048,576 bytes.

A non-JSON value or an oversized JSON value becomes this bounded structured representation:

```json
{
  "kind": "repr",
  "typeName": "package.Type",
  "value": "bounded representation",
  "truncated": false
}
```

`typeName` is safely derived from `type(value).__module__` and `__qualname__`, bounded to 256 UTF-8 bytes; `value` is initially bounded to 4,096 UTF-8 bytes. Both fields are truncated further as needed so the **entire compact encoded representation object**, including JSON escaping and field overhead, is at most 8,192 bytes and never splits a code point. `truncated` is true when the original representation, type name, or oversized JSON value was shortened/replaced. Failing type metadata or `repr` produces stable bounded `<unknown>` / representation-error fallbacks. Representation work remains inside the cell deadline.

An ordinary error reports the exception class name, a safely rendered message, and `traceback.format_exception` output split into logical lines. The complete compact JSON encoding of the error object is bounded to 65,536 UTF-8 bytes, including escaping and field overhead; truncation is explicit in the final traceback line. Runner, Supervisor, and Adapter diagnostics are never mixed into user `stderr`.

Stage 1 injects no helper names. The namespace contains normal Python execution globals (`__name__`, `__builtins__`, and related interpreter metadata) only. `display`, `artifact`, `read`, `write`, and `env` begin with their complete behavior in Stage 2; Stage 1 does not ship placeholders. Runner stdin is not user stdin, so `input()` fails rather than reading the MCP control channel.

### Completion-time text output

Stage 1 captures stdout and stderr bytes observed in a per-call window opened immediately before the first execute-frame byte is attempted and closed after terminal-frame drain or fatal cleanup. This prevents fast output racing `started` across different pipes. It does not emit MCP progress or live-stream content. With one shared Runner stream per channel, output from an earlier background producer that arrives during a later call's window is attributed to the later call; origin-level attribution is deferred.

For each channel the host:

- counts every raw byte and logical line observed in that call's capture window;
- retains a UTF-8-safe tail of at most 262,144 raw bytes;
- decodes invalid UTF-8 with replacement characters;
- discards output observed while no capture window is open as asynchronous/orphan output rather than attributing it to a later cell.

`output.totalBytes` is the sum of raw stdout and stderr bytes. `output.totalLines` is the sum, per non-empty channel, of LF bytes plus one when the final observed byte is not LF. `output.truncated` is true when either returned channel omits observed bytes. Stage 1 never claims recovery for omitted bytes: `output.artifact` is absent and `artifacts` is always `[]`. Stage 2 replaces this limitation with streaming and artifact spill.

### MCP mapping

The Adapter returns the typed result through the official SDK's output-schema path. The same object appears as `structured_content` and as the SDK-generated JSON text content. A valid execution request returns `is_error=false` for all four statuses; `failed`, `timed_out`, and `kernel_killed` are structured execution outcomes that callers must inspect.

SDK validation failures, an unknown tool, or an Adapter defect use MCP tool/protocol error behavior and do not fabricate a `PythonExecResult`. Private Runner frames, process identifiers, signals, and internal tracebacks are never exposed as MCP content.

## Consequences

### Positive

- One small interface covers persistence, reset, failure, timeout, death, output, and diagnostics.
- Models and clients receive the same typed result for every accepted execution outcome.
- State loss cannot be hidden by MCP error formatting or automatic replacement.
- Stage 1 output memory is bounded without pretending truncated evidence is recoverable.
- Stage 2 can add live content and artifacts without changing execution status semantics.

### Costs and constraints

- Stage 1 output beyond the retained tails is deliberately unrecoverable.
- A failed Python cell is not represented by MCP `is_error`; clients must inspect `status`.
- The additional `runtime` object is a permanent public field and must be kept truthful after death.
- Result representation is intentionally conservative and does not preserve arbitrary Python object identity or structure.

## Alternatives considered

### Name the tool `execute_python`

Rejected. `python_exec` matches the accepted input/result vocabulary and is short without becoming generic `execute`.

### Return Python failures as MCP tool errors

Rejected. Tool errors lose the structured survival state, execution count, output metadata, and typed traceback needed for recovery.

### Return only text in Stage 1

Rejected. It would force models and clients to parse decoration and would discard the architecture's typed result contract.

### Buffer complete stdout and stderr until Stage 2

Rejected. Unrestricted Python can produce unbounded output; an implementation milestone cannot knowingly add unbounded host memory.

### Add incomplete prelude helpers now

Rejected. Stubs would enlarge the interface without the workspace, artifact, display, and environment behavior that makes those helpers truthful.

## Verification

S1-020, S1-040, S1-050, S1-060, and S1-070 must prove:

1. exact tool discovery, input/output schemas, and model-facing non-sandbox/managed-cleanup description;
2. maximum high-escape valid code traverses MCP and private framing, while one-byte-over input is rejected before Runtime dispatch;
3. absent trailing expression versus a trailing `None`;
4. JSON values, non-JSON values, cycles, failing `repr`, NaN/infinity, and oversized values;
5. typed syntax/runtime errors, mutation retention, execution counts, and live-kernel reuse;
6. all four status/state combinations, cancelled-call state visibility, and dead-kernel non-recreation;
7. bounded stdout/stderr tails, exact byte/line counts, invalid UTF-8, RSS plateau under much larger output, and truthful no-artifact metadata;
8. runtime diagnostics before and after valid `chdir`, deleted/inaccessible cwd, reset, timeout, and death;
9. identical structured result mapping through the installed stdio MCP entry point.

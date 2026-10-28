# Stage 1 Implementation Plan

Status: accepted implementation baseline for Stage 1 execution correctness.

This plan integrates [ADR-0001](decisions/0001-stage-1-implementation-stack.md), [ADR-0003](decisions/0003-stage-1-execution-contract.md), [ADR-0004](decisions/0004-stage-1-runner-protocol.md), and [ADR-0005](decisions/0005-stage-1-runtime-lifecycle.md). Product invariants remain in [`architecture.md`](architecture.md); GitHub Project #2 and linked Issues remain the sole live status source.

## 1. Scope

Stage 1 delivers one installed stdio MCP server, one `python_exec` tool, and one persistent Python Runner per server process. It proves namespace persistence, trailing values, ordinary failure recovery, FIFO serialization, destructive reset, truthful timeout/death state, protocol isolation, diagnostics, and managed-process cleanup.

Stage 1 does not deliver live output, recoverable artifacts, images, `display`/file/environment helpers, Appium or other platform semantics, remote transport, multiple runtimes, a workflow language, a sandbox, or a Windows lifecycle claim.

## 2. Dependency and Python policy

### Candidate matrix

The initial evidence matrix is CPython 3.11, 3.12, 3.13, and 3.14. Python 3.11 runs format, lint, strict type, package, and full behavior gates. Each other candidate runs the full test suite and installed stdio scenario. Native lifecycle jobs run on current GitHub-hosted Ubuntu and macOS images where the candidate interpreter is available.

This is a test matrix, not package compatibility metadata. `requires-python` and Python/OS classifiers remain absent until S1-080 records a contiguous passing range and S1-085 applies exactly that approved claim. Python 3.15 is excluded initially because the locked MCP 2.3 release metadata does not claim it; it can enter S1-080 as an explicit candidate after the SDK release line supports it.

### Constraints

S1-010 establishes these direct constraints and commits their exact transitive resolution in `uv.lock`:

```text
runtime:
  mcp>=2.3,<3

development:
  pytest>=9.2,<10
  ruff>=0.17.3,<0.18
  mypy>=2.4,<3
  coverage[toml]>=7.17,<8
  psutil>=7.2.2,<8

build backend:
  uv_build==0.12.5

uv command runner:
  >=0.12.5,<0.13
```

No platform automation package enters Stage 1. A package imported directly by production or tests must be a direct dependency in the corresponding group; transitive availability is not an interface. Dependency updates require a regenerated lock, focused changelog review, and the same package/stdio evidence as the current lock.

`.python-version` selects CPython 3.11 for the canonical local environment. `[tool.uv].environments` constrains lock resolution to CPython 3.11 through 3.14 without publishing compatibility metadata. The project uses the plain `mcp` distribution, not `mcp[cli]`.

## 3. Canonical commands

S1-010 makes these commands pass from a fresh checkout:

```text
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

Mypy configuration is strict for `src` and `tests`. Pytest treats warnings as errors except for an individually documented upstream warning with a linked reason. Coverage is recorded with branch data but has no arbitrary percentage threshold.

CI calls these repository-defined commands rather than embedding different lint, type, test, or build behavior in workflow YAML. The package smoke test builds both sdist and wheel, installs the wheel into a clean uv-created environment, invokes `amkernel --version`, and later, in S1-070, launches the installed `amkernel` entry point with the official MCP client.

## 4. Module seams and path ownership

The smallest accepted production layout is:

```text
src/amkernel/
  __init__.py
  __main__.py
  cli.py
  protocol.py
  runner.py
  supervisor.py
  runtime.py
  server.py
```

No `platform`, `appium`, `artifact`, `workflow`, `registry`, or generic plugin package is created in Stage 1.

| Path or module | Sole writer while active | Read-only consumers | Contract dependency | Work item |
| --- | --- | --- | --- | --- |
| `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore` | Contract and Integration Lead | all roles | ADR-0001; this plan §2-3 | S1-010; later S1-085 only for approved compatibility metadata |
| `src/amkernel/__init__.py` | Contract and Integration Lead | package users/tests | package version only | S1-010 |
| `src/amkernel/__main__.py`, `src/amkernel/cli.py` | Contract and Integration Lead | package/E2E tests | console entry point; final stdio handoff | S1-010, then serial S1-050 cutover |
| `src/amkernel/protocol.py` | Contract and Integration Lead | Runner; Supervisor | ADR-0004 frame schemas/codec | S1-020 before Runner implementation fan-out |
| `src/amkernel/runner.py` | Runner and Protocol Owner | Supervisor through process seam only | ADR-0003 cell semantics; ADR-0004 | S1-020 |
| `src/amkernel/supervisor.py` | Runtime and Supervision Owner | Runtime | ADR-0004 process seam; ADR-0005 lifecycle | S1-030 |
| `src/amkernel/runtime.py` | Runtime and Supervision Owner | MCP Adapter | ADR-0003 result semantics; ADR-0005 queue/state | S1-040 |
| `src/amkernel/server.py` | Contract and Integration Lead | CLI; stdio client tests | ADR-0003 MCP mapping | S1-050 |
| `tests/protocol/`, `tests/runner/` | Behavior and Evidence Reviewer | Runner owner reads failures | ADR-0003/0004 scenarios | S1-020 |
| `tests/supervisor/`, `tests/runtime/` | Runtime and Supervision Owner for focused tests; reviewer is read-only | reviewer | ADR-0005 | S1-030/S1-040 |
| `tests/integration/` | Behavior and Evidence Reviewer | all production owners read failures | cross-module contracts | S1-060 |
| `tests/e2e/` | Behavior and Evidence Reviewer | Integration Lead fixes defects | installed public contract | S1-070 |
| `.github/workflows/` | Contract and Integration Lead | reviewers | canonical commands only | GOV-002/GOV-003 |
| architecture, ADR index, README, handoff | Contract and Integration Lead | all roles | accepted evidence only | serial integration changes |

A work item releases ownership after its handoff and focused checks. Later listed changes to the same file are serial clean cutovers, not concurrent ownership. Tests may import stable public/package interfaces and test-only helpers; black-box approval never imports private Runner/Supervisor implementation in place of the real process seam.

## 5. Delivery order

The dependency order is:

```text
S1-001 accept contracts and plan
  -> S1-010 reproducible package/toolchain
  -> GOV-002 executable CI definitions
  -> GOV-003 observed CI and branch protection
  -> S1-020 Runner/protocol ----\
                               -> S1-040 Runtime serialization/reset
     S1-030 Supervisor --------/
  -> S1-050 official MCP stdio Adapter
  -> S1-060 cross-module behavior
  -> S1-070 installed stdio end to end
  -> S1-080 independent Python/OS lifecycle evidence
  -> S1-085 compatibility metadata and Stage 1 closure
```

S1-020 and S1-030 may run concurrently only after `protocol.py` is frozen and their remaining paths are disjoint. The Adapter waits for the Runtime result interface. Stage 2 work does not overlap this milestone.

## 6. State and behavior scenarios

Focused tests are added with the implementation that can first satisfy them. S1-060 closes cross-module combinations; S1-070 repeats the public subset through an installed wheel and official stdio client.

### Persistence and evaluation

1. Assign a mutable object, mutate it in later calls, and observe identical state without setup repetition.
2. Return nested JSON scalars/objects/lists structurally; distinguish no final expression from a final `None`.
3. Return a set, cycle, oversized value, object with failing `repr`, object with oversized/malformed type metadata, NaN, and infinity; verify the aggregate 8,192-byte representation bound and fallback rules.
4. Raise syntax/runtime exceptions and very large high-escape exception messages/tracebacks; verify aggregate 65,536-byte error bounds, typed failures, mutation retention, execution counts, and successful next use.
5. Mutate state and then raise; verify the mutation remains.

### Serialization and reset

6. Submit concurrent cells with deterministic barriers; observe strict FIFO mutation order and no overlap.
7. Cancel a queued cell; verify it never creates/mutates a kernel or increments execution count.
8. Cancel at lazy-start, reset-cleanup, replacement-ready, and the checkpoint before the first execute byte; verify stabilization completes, no frame/cell starts, and a replacement remains alive at count 0.
9. Cancel during partial/blocked frame write, after complete delivery but before `started`, and during the active cell; verify fatal delivery handling versus active interrupt rules, last validated counts, and stabilization before the next queued call.
10. Reset after live use; verify old objects disappear, launch cwd returns, no old group remains, and the reset cell is execution 1.
11. Force a dead kernel; verify normal calls never recreate it and only `reset=true` recovers.

### Timeout and process lifecycle

12. Time out interruptible Python and repeatedly race completion at the exact deadline; verify deadline-wins `timed_out/alive`, late SIGINT safety, and immediate reuse of the same namespace.
13. Let a same-group descendant ignore SIGINT while the Runner handles timeout; verify it remains explicitly managed after `timed_out/alive` and is removed by later reset and shutdown.
14. Catch/ignore interrupt in Python and block inside a native-extension/C call that delays Python signal handling; observe bounded TERM/KILL escalation and `kernel_killed/dead` on every candidate Python/OS pair.
15. Spawn managed descendants across reset, cancellation that handles SIGINT, cancellation that reaches TERM/KILL, Runner crash, destructive timeout, and transport shutdown. Verify every destructive path removes the group; normal completion and handled timeout/cancellation assert continued ownership, not cleanup.
16. Inject deterministic signal/send/group-verification failures at the Supervisor process-primitive seam; verify dead state, stable `ResetCleanupError`/`CleanupError`, no replacement overlap, host-only diagnostics, clean MCP/user streams, and nonzero shutdown exit.
17. Deliberately create an escaped external process in an isolated test; verify AMKernel does not claim it was managed or cleaned and the test removes it explicitly.
18. Crash, stop, or silence the live Runner; stop reading while a maximum frame is written; withhold `started`; truncate/mangle frames; and keep a fork-only child alive with copied descriptors. Verify the 5-second deadline starts before the first byte, partial writes cannot block the host, last validated counts remain truthful, PID observation wins over held pipes, and fatal cleanup completes without automatic replacement.
19. Through the official SDK stdio client, cancel an active request and close transport during stubborn execution; verify cleanup completes within lifecycle grace bounds rather than the user timeout.

### Output and protocol isolation

20. Emit ordinary text and an immediate first-instruction `os.write`, JSON-looking frames, fragmented writes, invalid UTF-8, large writes, interleaved stdout/stderr, exec descendants, and ordinary fork-context descendants; verify the pre-write capture window loses no fast output and neither MCP nor Runner control is corrupted.
21. Exceed retained tails with simultaneous stdout/stderr totals of 16 MiB and 256 MiB. Sample host/Runner RSS with `psutil`; require peak growth between runs to stay below 16 MiB while byte/line counts remain exact, returned tails stay bounded, `truncated=true`, `output.artifact` is absent, and `artifacts=[]`.
22. Emit output while the Runner is idle and verify it is not attached to a later request; emit an earlier background producer during a later active cell and verify the documented active-cell attribution limitation.
23. Exercise the exact Runner argv/fd bootstrap and every message schema: missing/duplicate/extra descriptors, fragmentation/coalescing, duplicate/unknown fields, bad types/versions/correlation, non-finite values, unexpected EOF, maximum high-escape public code, and one-byte-over Adapter rejection.

### Environment, package, and public MCP surface

24. Verify the absolute-but-not-realpathed `sys.executable` launcher, Python version, valid cwd changes/reset, environment kind, and deleted/inaccessible cwd fatal mapping against reported diagnostics.
25. Seed every parent environment key with unique sentinels. Verify the child contains exactly declared forwarded keys plus derived `VIRTUAL_ENV`; reject every `PYTHON*`, all proxy/provider/cloud examples, and a random arbitrary key; observe isolated user-site, unbuffered output, and UTF-8 mode while accounting for documented CPython locale normalization.
26. Install the wheel in a clean venv whose `bin/python` is a symlink; use that installed `amkernel` with official `Client(StdioServerParameters(...))`, verify Runner import and `project_venv` diagnostics preserve the launcher path, discover exactly `python_exec`, assert complete schemas and non-sandbox/managed-cleanup description clauses, call every public status path, and close cleanly.
27. Verify the default server opens no network listener, performs no privilege elevation, and emits no non-MCP byte on stdout.

Every process test has an outer test timeout and teardown that records process IDs/groups before cleanup. A skipped lifecycle scenario is not a pass for that platform.

## 7. Risk traceability

| Risk | Plan decision | Required evidence |
| --- | --- | --- |
| R-001 user output corrupts control | Separate MCP, control, diagnostic, stdout, and stderr channels; framed control; fork hooks plus PID observation | Scenarios 18, 20, 23, 26-27 |
| R-002 public kernel state is false | Runner reports neutral outcomes; Supervisor alone maps interruption/death; no auto-recreate | Scenarios 4, 9, 11-19, 24 |
| R-003 managed descendants leak | persistent owned process group; destructive-path bounded cleanup and verification | Scenarios 10, 13-19 |
| R-004 platform lifecycle diverges | POSIX target only; no support claim before native S1-080 matrix | Scenarios 12-19 and 24-25 on every candidate OS |
| R-005 concurrent calls race | one FIFO Runtime worker; explicit cancellation commit point and shutdown priority | Scenarios 6-9, 19 |
| R-006 blocking Python defeats escalation | execute-ack deadline and SIGINT/TERM/KILL with fixed grace | Scenarios 12-14, 18-19 |
| R-007 output exhausts memory or loses evidence | per-channel 256 KiB tail, raw counts, RSS plateau evidence, truthful no-artifact state | Scenarios 20-22 |
| R-008 wrong interpreter/environment leaks credentials | exact `sys.executable`, captured cwd, allowlist-complement environment test | Scenarios 24-25 |
| R-009 platform semantics enter core | dependency and path exclusions; architecture review | dependency audit and independent review |
| R-010 MCP SDK churn breaks behavior | `mcp>=2.3,<3` plus exact lock; installed official-client E2E | Scenarios 19 and 26 on every lock update |
| R-011 canonical contracts drift | ADR authority, one shared-file owner, clean cutovers, exact schema assertions | ADR/index review and scenarios 23, 26 |
| R-012 mocks hide broken package | clean wheel install and actual stdio client subprocess | Scenarios 19 and 26; Gate 5 package smoke |
| R-013 cleanup claims exceed ownership | managed group definition and explicit external-resource non-claim | Scenarios 13, 15, 17, and 26 |

R-014 is handled by enabling CI and branch protection only after S1-010 commands exist and pass with stable job names.

## 8. Review and completion evidence

Each implementation handoff names changed paths, frozen contracts, focused commands and observed results, process/kernel state after failures, downstream requirements, and any mechanism informed by the discarded sibling spike. No wholesale spike copy is permitted.

Review order is protocol/cell semantics, Supervisor lifecycle, Runtime state/queue, MCP mapping, environment/security, then installed stdio behavior. S1-001 and every load-bearing implementation item require an independent reviewer with no unresolved Blocker or Major finding.

Stage 1 is complete only when all canonical commands pass, the installed official-client scenario passes, every destructive lifecycle path proves its cleanup or truthful failure mapping on each claimed platform, S1-080 approves a bounded compatibility range, S1-085 publishes only that evidence, and all blocking risks have an accepted final state.

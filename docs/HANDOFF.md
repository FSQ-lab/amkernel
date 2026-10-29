# AMKernel Handoff

## Task

Finalize and accept the Stage 1 implementation plan required by `docs/development.md` before coding. Then build the smallest correct persistent Python execution MCP, with behavior-first tests.

## Context

AMKernel stands for **Automation MCP Kernel**.

Its product thesis is:

```text
Coding Agent
  → MCP
  → persistent Python kernel
  → official automation library
  → external system
```

Python execution is the primary Agent interface. AMKernel does not expose a growing set of browser, desktop, or mobile action tools and does not wrap official automation libraries.

Mobile/Appium is the first experimental vertical. It is intended to validate persistent live objects, interruption, screenshots, large element trees, artifacts, test execution, and external-session cleanup. It must not introduce mobile semantics into the generic kernel.

The formal repository was intentionally created design-only. A sibling spike exists, but its files were not copied because the implementation should follow the accepted architecture rather than inherit prototype structure accidentally.

## Relevant files

- `README.md` — product identity, principles, current Stage 1 status, and canonical document links.
- `docs/architecture.md` — accepted generic AMKernel architecture, core interface, invariants, execution result, runner protocol, output system, security posture, and delivery stages.
- `docs/development.md` — required agent roles, ownership rules, development workflow, quality gates, and definition of done.
- `docs/project-management.md` — milestones, Kanban states, work-item contracts, decision management, risk management, and repository-governance rollout.
- `docs/stage-1-implementation-plan.md` — accepted Stage 1 cross-module contracts, dependency/toolchain policy, path ownership, black-box scenarios, and risk traceability.
- [GitHub Project #2](https://github.com/orgs/FSQ-lab/projects/2) and [repository Issues](https://github.com/FSQ-lab/amkernel/issues) — sole live project status, queue, work contracts, blockers, risks, and verification evidence.
- `docs/decisions/` — accepted durable decisions for the implementation stack, GitHub project management, public execution contract, private Runner protocol, and Runtime lifecycle.
- `.github/workflows/ci.yml` — pinned-action hosted CI with stable `quality` and `package-smoke` checks; `tests/package_smoke.py` installs the built wheel in a clean environment and invokes its real entry point.
- `.omp/AGENTS.md` — project context; imports the architecture, development process, project-management policy, accepted decisions, and mobile experiment, and requires agents to inspect the active GitHub work item before changing code.
- `.omp/config.yml` — project-local memory (`memory.backend: local`).
- `../omp/` — discarded prototype/evidence only. It contains a TypeScript MCP demo, Python runner, persistence/reset/timeout smoke tests, and an Appium connectivity smoke. Read narrowly if an experiment needs evidence; do not copy wholesale.

## Current state

- Public GitHub repository: `https://github.com/FSQ-lab/amkernel` with local `origin` configured.
- Public organization Project: `https://github.com/orgs/FSQ-lab/projects/2`; GitHub Issues and Project fields are the sole live project-status source.
- ADR-0001 selects a single Python implementation, the official MCP Python SDK, and a uv-managed packaged toolchain. ADR-0003 through ADR-0005 and `docs/stage-1-implementation-plan.md` freeze the complete Stage 1 public contract, private protocol, lifecycle, ownership, test matrix, and evidence plan.
- S1-010 establishes `pyproject.toml`, `.python-version`, a committed `uv.lock`, the `src/amkernel/` package, typed console/module entry points, and package behavior tests. The lock uses the Tsinghua PyPI mirror because the development network restricts direct PyPI access. Runner/Supervisor/Runtime/MCP execution behavior is intentionally not part of this bootstrap.
- GOV-002/GOV-003 establish hosted CI and protected-branch governance. Run `40724547935` passed both stable checks for commit `6089615`; `main` strictly requires `quality` and `package-smoke`, the pull-request path, conversation resolution, and protection for administrators, while owner-approved continuous execution requires zero human approvals. Independent Agent review remains mandatory process evidence.
- S1-020 implements `src/amkernel/protocol.py` and `src/amkernel/runner.py`: exact bounded/correlated frames, isolated bootstrap descriptors, persistent cell state, compile-before-execute trailing expressions, detached structured results, bounded repr/errors, safe SIGINT finalization, fork descriptor closure, and truthful runtime diagnostics. This is a private process seam, not yet an MCP tool.
- S1-030 implements `src/amkernel/supervisor.py`: exact Runner spawn/environment, independent PID observation, nonblocking command acknowledgement, bounded stdout/stderr capture, deadline/cancellation precedence, SIGINT→TERM→KILL escalation, idempotent cancellation-safe shutdown, managed-descendant cleanup, retained startup-cleanup ownership, bounded graceful-shutdown delivery, host-only infrastructure diagnostics, and truthful cleanup failures. Supervisor native tests pass 33 scenarios. Windows remains unclaimed.
- S1-040 implements `src/amkernel/runtime.py`: one FIFO worker, lazy startup, strict single-flight dispatch, queued/active cancellation stabilization, destructive reset ordering, explicit dead-kernel recovery, closed-state shutdown priority, retained cleanup ownership, stable public infrastructure errors, and bounded Supervisor diagnostic propagation. Runtime native tests pass 22 scenarios; its delivery suite passed 120 on the development macOS/Python 3.11 environment.
- S1-050 implements `src/amkernel/server.py` and cuts `src/amkernel/cli.py` over to the official MCP Python SDK's public low-level `Server` and stdio transport. `python_exec` publishes strict, non-nullable input validation and one exact nested output model; completed/failed/timed-out/killed executions remain successful MCP results, while validation/unknown-tool/Adapter defects remain tool errors. JSON text and `structuredContent` match, absent result differs from explicit null, user output cannot corrupt MCP stdout, host diagnostics stay on stderr, and transport close waits for Runtime cleanup with a nonzero cleanup-failure exit. Official Client Adapter/stdio delivery tests passed 19 scenarios; its delivery suite passed 139 on the development macOS/Python 3.11 environment.
- S1-060 adds 30 bounded `tests/integration/` scenarios spanning real Runner, Supervisor, Runtime, Adapter, official Client, raw stdio, and private wire seams. Evidence covers deterministic FIFO/cancellation, real deadline races, reset/death recovery, every managed-descendant destructive path, cleanup-failure diagnostics and exit status, escaped-resource non-ownership, first-byte/full-delivery protocol deadlines, malformed/coalesced/truncated/EOF frames, maximum NUL-expanded code, 16/256 MiB output memory plateau, deterministic output attribution, exact environment complement, raw stdout accounting, and default no-network/no-elevation behavior. The resulting fixes record/replay SIGTERM across transport cleanup and reject missing/duplicate Runner descriptor arguments. Integration tests pass 30 scenarios; the full suite passes 171 on the development macOS/Python 3.11 environment.
- S1-070 adds `tests/e2e/installed_stdio.py` and extends `tests/package_smoke.py` so a clean project `.venv` installs the built wheel and the official MCP Client launches only its installed `amkernel` entry point. The black-box scenario asserts exact discovery schemas and warnings; persistent state; ordinary failure and retained mutation; reset; handled timeout survival; forced death, non-recreation, and explicit recovery; symlinked `project_venv` diagnostics; identical structured/text results; and managed-child cleanup after death and transport close. The macOS arm64/Python 3.11.16 delivery run passed against wheel SHA-256 `9b9ac0c8e3a55888b2baec9dd5c6084e6da4f06fb3883f32a757de549b5d1926`; the repository suite passed 171 scenarios, and independent review found no remaining Blocker or Major issue. No production contract changed; S1-080 remains responsible for native compatibility claims.
- S1-080 approves the bounded contiguous CPython 3.11–3.13 range on GitHub-hosted Ubuntu and macOS. Candidate run `40830237588` passed every Ubuntu/macOS 3.11–3.13 lifecycle, build, and installed-stdio job plus Ubuntu 3.14; macOS 3.14 timed out in the lifecycle suite, and a local macOS 3.14.7 reproduction blocked in CPython's asyncio child reaper after a stopped Runner, so 3.14 remains unclaimed. After restricting the permanent matrix to the approved range, run `40833053864` passed all six compatibility jobs plus quality and package smoke. Independent review found no remaining Blocker or Major issue.
- S1-085 publishes the approved `>=3.11,<3.14` package requirement and exact Python classifiers, constrains lock resolution to the same range, and documents only the qualified hosted Ubuntu/macOS support claim. Local closure gates passed 172 scenarios and installed wheel SHA-256 `e1b6e97aefedbae3fb5b34467f450c98b6b53a1e2ff6822f47d437621bee21c2`; hosted run `40834514852` passed quality, package smoke, and all six compatibility jobs. R-001 through R-014 have resolved or explicitly accepted final Stage 1 states, and independent closure review found no remaining finding.
- Global OMP memory is disabled; this project uses local project-scoped memory.
- The sibling `/Users/qunmi/Documents/FSQ_LAB/omp` remains untouched as historical discussion/prototype material.

## What was tried

- A small MCP v2/TypeScript + Python subprocess spike was built in `../omp`.
  - It demonstrated persistent namespace, trailing expression values, failed-cell survival, reset, timeout with SIGINT recovery, workspace confinement, and Appium Python Client connectivity.
  - It was rejected as production scaffolding because it was intentionally minimal and the formal module/interfaces had not yet been agreed.
- A conventional Mobile Use architecture was drafted around `MobileSession`, structured mobile actions, device brokers, and flow runners.
  - It was rejected because it displaced the central idea: the Agent directly generates and executes Python against official automation libraries.
- A mobile-only project identity was considered.
  - It was rejected because the same kernel can later support Playwright, Selenium, pywinauto, PyAutoGUI, macOS Accessibility, and other Python automation ecosystems.

## Decisions

- **Name:** AMKernel — Automation MCP Kernel.
- **Tagline:** Persistent Python execution for agentic automation.
- **Primary interface:** one Python cell execution tool.
- **Initial lifetime:** one stdio MCP process owns one persistent Python kernel.
- **No runtime ID initially:** process lifetime already scopes ownership.
- **Execution semantics:** state persists; calls serialize; ordinary cell errors do not kill the kernel; mutations before an error may remain.
- **Timeout semantics:** interrupt first, escalate only when necessary, and always report whether the kernel survived.
- **Result semantics:** typed status, stdout/stderr, trailing value, traceback, execution count, duration, kernel state, output metadata, and artifacts.
- **Output:** structured JSON, images, and artifact-backed large output are first-class requirements.
- **Automation libraries:** use official libraries directly; do not build replacement wrappers.
- **Platform knowledge:** begin in skills, experiments, and integration tests.
- **First experiment:** Mobile/Appium, covering iOS simulator and Android emulator.
- **Large trees:** raw values initially; cap/spill output and use local Python reduction. Normalization/diffs are deferred until measured need.
- **Appium server:** managed externally by the Coding Agent’s process/shell facilities during the first experiment.
- **Security:** local stdio, same-user Python code execution; not a sandbox.
- **Memory:** project-scoped only; no global memory.

## Recommended first implementation slice

Implement execution correctness only. Do not add image/artifact/Appium behavior until the execution contract is defended.

Suggested observable contracts:

1. MCP exposes one execution tool with `code`, optional `title`, optional `timeout`, and optional `reset`.
2. Separate calls share one Python namespace.
3. A trailing JSON-compatible expression is returned structurally.
4. A normal Python exception returns a typed traceback and leaves the kernel alive.
5. State changes before an exception remain observable.
6. Calls are serialized.
7. `reset` replaces the kernel and clears prior state.
8. An interruptible timeout reports `timed_out` with a live kernel.
9. A non-settling timeout escalates and reports `kernel_killed` with a dead kernel.
10. Closing the MCP process cleans up the kernel and managed descendants.
11. User stdout/stderr cannot corrupt runner frames or MCP JSON-RPC.
12. The selected interpreter and working directory are explicit in diagnostics.

Use the smallest module structure that keeps MCP transport, kernel supervision, and Python cell execution separate. Do not pre-create packages or platform modules that the slice does not need.

## Acceptance criteria

- [ ] Implementation matches the interface and invariants in `docs/architecture.md`.
- [ ] Focused behavioral tests cover persistence, errors, reset, timeout survival/escalation, stream/protocol isolation, serialization, and shutdown.
- [ ] The actual stdio MCP server is exercised end to end by a client; unit tests alone are insufficient.
- [ ] No Appium/mobile/browser/desktop semantics appear in the core implementation.
- [ ] No code is copied wholesale from `../omp`; any reused mechanism is justified and adapted deliberately.
- [ ] No long-term platform abstraction, workflow language, multiple-runtime registry, or remote transport is introduced.
- [ ] Documentation is updated only where implementation evidence changes an accepted claim.

## Constraints

- Correctness before breadth.
- Keep the model-facing interface small.
- Use official MCP SDK behavior rather than hand-rolled JSON-RPC.
- Treat stdout as potentially hostile to protocols.
- Do not suppress failures or silently recreate state after kernel death.
- Do not claim sandboxing.
- Do not add speculative abstractions for future platforms.
- Do not delete or modify the sibling `../omp` directory without explicit user instruction.

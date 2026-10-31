# AMKernel Handoff

## Task

Advance Stage 3 Mobile/Appium experiment work in GitHub Project order without moving Appium, device, or platform semantics into AMKernel core.

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

- `README.md` — product identity, principles, completed Stage 2 status, exact support claim, and canonical document links.
- `docs/architecture.md` — accepted generic AMKernel architecture, core interface, invariants, execution result, runner protocol, output system, security posture, and delivery stages.
- `docs/development.md` — required agent roles, ownership rules, development workflow, quality gates, and definition of done.
- `docs/project-management.md` — milestones, Kanban states, work-item contracts, decision management, risk management, and repository-governance rollout.
- `docs/stage-1-implementation-plan.md` — accepted Stage 1 cross-module contracts, dependency/toolchain policy, path ownership, black-box scenarios, and risk traceability.
- [GitHub Project #2](https://github.com/orgs/FSQ-lab/projects/2) and [repository Issues](https://github.com/FSQ-lab/amkernel/issues) — sole live project status, queue, work contracts, blockers, risks, and verification evidence.
- `docs/stage-3-implementation-plan.md` — accepted M3 issue graph, skill/official-source trust seam, path ownership, fixture/evidence/measurement contracts, mandatory failure matrix, platform gates, and graduation criteria.
- `src/amkernel/distribution.py` and `src/amkernel/skill/` — one uv-managed user Runtime, transactional OMP/Pi/Codex project activation, and the packaged user-centered Agent skill with verified official Appium routes and fail-closed provenance checks.
- `docs/experiments/mobile-appium.md` — experiment hypothesis, scenario matrix, failure cases, measurements, and graduation questions.
- `docs/decisions/` — accepted durable decisions for the implementation stack, GitHub project management, public execution contract, private Runner protocol, and Runtime lifecycle.
- `.github/workflows/ci.yml` — pinned-action hosted CI with quality, clean-wheel package smoke, and six supported Python/OS compatibility jobs; every package job retains its exact evidence JSON, wheel, dependency lock, and hash.
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
- REL-001 defines the pre-1.0 version/changelog, immutable tag, evidence-qualified support, retained-artifact provenance, trusted-publishing, rollback, and yank procedure. CI retains only the exact wheel exercised by `package-smoke`; the untested sdist is explicitly excluded from release. Hosted run `40840708426` passed quality, package smoke, and all six compatibility jobs and retained `distribution-ed34c39483b3b9e45becd38c4bed1e1ecfa2f8e1` (35,222 bytes). Independent review found no remaining issue after requiring wheel-only retention and synchronizing the cleanup/output test seams.
- S2-001 accepts ADR-0006 and `docs/stage-2-implementation-plan.md`, establishing the Stage 2 milestone contract, module ownership, bounds, dependency graph, cross-cutting evidence matrix, and risks R-015 through R-020. S2-010 freezes the literal public v2 discovery schema, strict private protocol-v2 frames and sequence/transaction validator, exact malformed-frame mapping, dormant-event rejection, cancellation-safe post-terminal fatal handling, and centralized output/resource/image/package bounds. S2-020 implements the process Artifact Store, exact raw/manifest resources, collision-safe reservations, quota and whole-bundle eviction, one-read admission with leases, digest verification, descriptor-relative identity-safe cleanup, Runtime retention/shutdown ownership, and official MCP resource handlers. S2-030 adds bounded complete stream recovery, canonical stream artifacts, exact combined accounting, post-limit draining, terminal-observation attribution, and Store-failure teardown. S2-040 installs reset-restored and persistently shadowable `display`/`artifact` helpers; emits ordered strict-JSON and interrupt-atomic artifact/image protocol transactions; validates exact PNG/JPEG/GIF/WebP containers and every decoded frame in Runner and Host; publishes only complete transactions; preserves arbitrary declared MIME while promoting only validated safe content; maps ordered displays/artifacts; and bounds the compact terminal result under UTF-8 replacement expansion. S2-050 installs reset-restored and persistently shadowable `read`/`write`/`env` helpers; pins the actual launch directory handle and identity; walks relative and absolute-in-root paths descriptor-relatively without following links; restricts reads to bounded regular files with strict UTF-8; atomically replaces regular destinations with mode-`0600` files through pinned parent handles; and implements detached environment snapshots plus exact get/set/delete semantics without a sandbox claim. S2-060 validates PEP 503-normalized requested distribution names before dispatch; performs ordered selected-Runner metadata inspection after completed or failed cells inside the cell deadline; publishes only bounded control-free versions or the closed three-value error vocabulary; never inventories implicitly; and retains last-valid selected-Runner diagnostics across death and failed reset while refreshing only after successful replacement. The repository suite passes 237 scenarios; Ruff and mypy pass; independent correctness and security review found no remaining Blocker or Major issue. GitHub Project #2 advances to S2-070.
- S2-070 maps complete v2 execution output through official MCP SDK types: canonical JSON plus deterministic ImageContent/ResourceLink ordering, generated resource names and logical titles, private complete zero-TTL raw/manifest/part reads, and request-scoped one-slot progress with channel/type metadata, 8 KiB/10 Hz bounds, exact unavailable/progress/failed fallback, and terminal authority under blocked or failed reporting. The final Ruff, mypy, and 244-scenario suite passed; independent correctness and security re-review found no remaining Blocker, Major, or Minor issue. Store/result-construction fatal lifecycle integration remains deliberately owned by S2-080.
- S2-080 unifies output-limit, cancellation, deadline, shutdown, protocol/death, Store, and result-construction intervention semantics. Same-turn deadline/output-limit readiness is deterministic; earlier cancellation/limit markers retain timestamp order. Fatal paths preserve exact bounded output fields, serialize terminal construction inside Runtime FIFO, destructively clean the managed Runner, and retain failed staged/published/writer deletion progress for retry. Artifact URIs revoke before deletion, deleting bundles remain quota-charged until physical removal, reset cannot replace the Runner while output cleanup is pending, and persistent shutdown cleanup faults return truthful retryable results. Ruff, mypy, and the full 254-scenario suite pass; independent correctness and security review report no Blocker, Major, or Minor finding.
- S2-090 and PR #66 close Stage 2. The final main hosted run passed quality, package-smoke, and Ubuntu/macOS CPython 3.11–3.13 compatibility against retained evidence. M3 and Issues #68–#74 now define the ordered Stage 3 Mobile/Appium experiment; S3-001's plan passed independent review with 0 Blocker / 0 Major / 0 Minor findings.
- S3-010 pins `appium/skills` commit `e907024c210fe024c956ed9c74146fc27b1dd013` and Skills CLI 1.7.4, verifies the canonical detached Git tree plus `.agents` runtime and `.claude` selected-agent copies, and provides one project-local direct Appium Python procedure. The skill keeps server/device ownership external, reuses one persistent driver, uses explicit waits, bounds status/source/screenshot evidence, fails closed on source drift, prohibits automatic SDK bootstrap/shared ADB resets/unscoped mutations, and preserves cleanup identity until `driver.quit()` succeeds. Focused verification passed 5 tests plus Ruff, mypy, the real 134-file/copy verifier, and local Skills CLI discovery; independent security/workflow review found 0 Blocker / 0 Major / 0 Minor.
- Issue #88 and ADR-0007 replace the interim separately installed `amkernel-appium` entry with one packaged `amkernel` skill and CLI. `amkernel install` installs or reuses one global uv tool, copies the version-matched skill into the project, writes one native project MCP entry, and records only managed project references. Update, project uninstall, and global uninstall preserve explicit scope, consent, rollback, and ownership.
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

## Recommended next implementation slice

S3-020 / Issue #73 is the next ordered slice: establish deterministic mobile fixture selection plus the versioned evidence and measurement record contracts. Do not start Android or iOS vertical execution until the fixture gates are Ready.

Observable contracts:

1. Android and iOS fixtures are deterministic, locally inspectable, and pinned with exact provenance/build/install inputs; dynamic-download or environment-dependent demo targets are rejected.
2. `docs/experiments/mobile-appium.md`, `tests/fixtures/mobile-appium/`, `tests/e2e/appium/`, and `evidence/mobile-appium/` receive the sole S3-020-owned schemas/templates without Appium semantics entering AMKernel core.
3. Pre-run feasibility checks record every required environment fact before launch and classify unmet platform prerequisites truthfully as blockers rather than narrowing the experiment.
4. Sample records are schema-complete, bounded, secret-reviewed, and independently verified before S3-030/S3-040 execution begins.

## Acceptance criteria

- [x] M3 and S3-001 through S3-060 are registered in GitHub Project #2 with exact dependencies and work-item contracts.
- [x] `docs/stage-3-implementation-plan.md` maps every graduation criterion, all 19 failure cases, all 12 measurements, exact paths/owners, and retained evidence requirements.
- [x] Independent S3-001 review found 0 Blocker, 0 Major, and 0 Minor findings after synchronizing Issues #71 and #69.
- [x] S3-010 implements and independently verifies the project-local skill and immutable official-skill handoffs.
- [ ] S3-020 establishes deterministic Android/iOS fixtures and versioned evidence records before platform execution.

## Constraints

- Correctness before breadth.
- Keep the model-facing interface small.
- Use official MCP SDK behavior rather than hand-rolled JSON-RPC.
- Treat stdout as potentially hostile to protocols.
- Do not suppress failures or silently recreate state after kernel death.
- Do not claim sandboxing.
- Do not add speculative abstractions for future platforms.
- Do not delete or modify the sibling `../omp` directory without explicit user instruction.

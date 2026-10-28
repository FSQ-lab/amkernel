# AMKernel Development Process

Status: required collaboration and quality baseline for implementation work.

This document governs how changes are assigned, implemented, reviewed, and verified. It does not change the product or module contracts in [`architecture.md`](architecture.md).

## 1. Authority and scope

Use these sources in this order:

1. [`architecture.md`](architecture.md) defines core product invariants, module responsibilities, and delivery stages.
2. Experiment documents define platform-specific procedures and evidence only within their experiment.
3. [`project-management.md`](project-management.md) defines the management workflow and GitHub field semantics.
4. The [GitHub Project](https://github.com/orgs/FSQ-lab/projects/2) and linked [Issues](https://github.com/FSQ-lab/amkernel/issues) are the sole live sources for milestone, status, dependency, blocker, risk, and queue state.
5. Accepted ADRs refine implementation choices but must not silently override the architecture.
6. An accepted Issue task contract narrows the current change but must not override the architecture or ADRs.
7. This document defines team ownership, implementation workflow, and quality gates.
8. [`HANDOFF.md`](HANDOFF.md) and the repository README provide durable context; any drift must be resolved explicitly rather than interpreted silently.

The active delivery target is Stage 1, execution correctness. Image output, artifact spill, and Appium behavior are not part of a Stage 1 change unless the architecture is deliberately revised first.

## 2. Agent team

The team is role-based. Create only the roles needed for a task; do not keep idle agents or split work merely to increase concurrency. One agent may perform several roles serially, but an independent reviewer must approve load-bearing behavior.

### Contract and Integration Lead

Owns:

- task scope, observable acceptance criteria, and non-goals;
- cross-module contracts and their single source of truth;
- dependency order and exact file ownership;
- shared configuration and integration files;
- final integration, verification, and delivery evidence.

Must not introduce compatibility shims, speculative modules, platform semantics, or a structure copied from the sibling spike.

### Architecture and Security Reviewer

Owns read-only review of:

- automation-neutral boundaries and delivery-stage discipline;
- state-truth guarantees;
- protocol isolation and input/output trust boundaries;
- environment filtering, workspace confinement, process ownership, and security claims.

This reviewer blocks violations; it does not rewrite the implementation during review.

### Runtime and Supervision Owner

Owns:

- the Runtime Manager and Python Kernel Supervisor;
- call serialization, spawn, reset, shutdown, and kernel state transitions;
- timeout escalation from interrupt through termination and hard kill;
- cleanup of managed descendants and truthful cleanup failures.

Must not own Python cell evaluation, MCP content mapping, arbitrary external sessions, or platform server lifecycle.

### Runner and Protocol Owner

Owns:

- the persistent Python namespace and execution count;
- cell compilation/evaluation, trailing expressions, and typed Python errors;
- preservation of mutations completed before an exception;
- private runner protocol production and user-stream isolation;
- installation of the stage-appropriate automation-neutral prelude.

Must not read MCP transport directly, decide process death, persist artifacts, or add platform helpers.

### Output and Artifact Owner

Owns Stage 2 output aggregation, bounded previews, UTF-8-safe streaming, artifact storage, hashes, MIME metadata, and structured/image display semantics.

This role is inactive for Stage 1 except where captured stdout/stderr and protocol isolation are required by the execution contract. It must not normalize platform trees or change kernel state semantics.

### Behavior and Evidence Reviewer

Owns:

- black-box scenarios derived from accepted contracts;
- actual stdio MCP client end-to-end verification;
- lifecycle, protocol-isolation, and process-leak evidence;
- experiment failure matrices and measurements when their stage begins.

This role does not own production implementation. Unit-only or mock-only evidence cannot approve an end-to-end contract.

## 3. Ownership and parallel work

Before parallel work, the Integration Lead records:

```text
path or conceptual module | sole writer | read-only consumers | contract dependency | delivery stage
```

Rules:

- One writer per file and one owner per state machine.
- Shared schemas, build configuration, README, architecture documents, and handoff documents have one serial integration owner.
- Do not invent source paths before the implementation layout is accepted. Use the conceptual module names from the architecture until then.
- Freeze the relevant boundary before parallel consumers start. Important boundaries are the MCP input/result schema, runner frames, lifecycle results, output metadata, and prelude hooks.
- Runtime timeout, reset, shutdown, and `kernelState` logic stay under one owner.
- The Runner may emit stream frames; aggregation, truncation, and storage belong to the Output role. They communicate through a frozen schema, not shared mutable files.
- If ownership overlaps, both writers stop. The Integration Lead resolves the semantic boundary before work resumes.
- A changed contract uses a clean cutover: update every consumer and remove the obsolete form. Do not retain aliases or dual schemas.

Each delegated task must include the target symbols or conceptual module, explicit non-goals, frozen inputs/outputs, exact acceptance evidence, and the files it may modify. Subagents run only focused checks for their slice; the Integration Lead runs the integrated gates once after all slices land.

## 4. Development workflow

### 4.1 Scope

The Integration Lead ties the change to one delivery stage and one or more observable contracts. The task states non-goals and identifies architecture sections that constrain the work.

### 4.2 Freeze contracts

Before implementation, resolve public inputs/results, private frames, state transitions, ownership, and failure behavior needed by the slice. Contract decisions precede package structure and parallel implementation.

### 4.3 Define behavior

Describe the black-box scenarios that would distinguish a correct implementation from plausible failures. Tests must defend observable behavior, boundaries, invariants, and recovery—not source layout or incidental defaults.

### 4.4 Implement by seam

After contracts are frozen, independent owners may work in parallel. A Stage 1 implementation may parallelize Runner semantics and Runtime/Supervision internals, but adapter integration waits for their result contract. Stage 2 output work does not expand a Stage 1 slice.

### 4.5 Slice handoff

Every owner reports:

1. task and delivery stage;
2. architecture baseline and accepted invariants;
3. files changed and files intentionally untouched;
4. contract changes, or `none`;
5. behavior implemented;
6. exact focused checks and observed results;
7. survival, cleanup, and recoverability state after failures;
8. downstream integration requirements;
9. documentation impact;
10. any mechanism informed by `../omp`, with its justification and defending test.

### 4.6 Review and integrate

Review in dependency order:

1. core boundary and non-goals;
2. Runner execution semantics and protocol isolation;
3. Supervisor spawn, timeout, and process ownership;
4. Runtime serialization, reset, shutdown, and state truth;
5. MCP adapter validation and content mapping;
6. Stage 2 artifact/output behavior when applicable;
7. environment and security safeguards;
8. black-box stdio MCP behavior.

The Integration Lead migrates all consumers, resolves shared-file changes, and removes obsolete code before integrated verification.

### 4.7 Record evidence

Report the exact command or scenario and the observed result. Never convert an untested assumption into a support claim. Update design documents only when implementation evidence changes an accepted statement.

## 5. Quality gates

The repository has a reproducible uv-managed package toolchain and hosted GitHub Actions CI. The stable `quality` and `package-smoke` jobs have passed on `main` and are strict required checks. Branch protection requires the pull-request path and conversation resolution without per-task human approval; independent Agent review and every applicable gate below remain blocking.

### Gate 0: Scope and contract

- The delivery stage, observable behavior, and non-goals are explicit.
- Changed interfaces and all consumers are identified before editing.
- The design remains automation-neutral.
- The public result always tells the truth about kernel survival.

### Gate 1: Reproducible tooling and static checks

The accepted implementation stack must provide, from a fresh checkout:

- deterministic dependency resolution with a committed manifest and lock state;
- one canonical format check;
- one canonical lint check;
- one canonical static type check for production and test code;
- one canonical package/build check.

These commands must run in CI. Local hooks may provide fast feedback, but hooks are never the authoritative gate.

### Gate 2: Focused behavior

Every change runs the smallest tests that fail for its plausible regressions. Stage 1 coverage must include, as applicable:

- namespace and live-object persistence;
- structured trailing expression values;
- typed ordinary errors with a surviving kernel;
- mutations retained before an exception;
- serialized calls;
- destructive reset and a clean replacement namespace;
- interruptible timeout with `timed_out` and `kernelState=alive`;
- escalation with `kernel_killed` and `kernelState=dead`;
- shutdown and managed-descendant cleanup;
- JSON-looking and hostile stdout/stderr that cannot corrupt control frames;
- explicit interpreter and working-directory diagnostics.

### Gate 3: Actual stdio MCP end to end

An MCP client must launch the packaged server over stdio and exercise the changed public path. Unit tests or direct calls into implementation classes do not satisfy this gate.

The scenario verifies tool discovery/schema, multiple calls against one kernel, result mapping, error mapping, reset, timeout state, and clean transport shutdown relevant to the change.

### Gate 4: Lifecycle and security

- No managed process remains after reset, shutdown, or an escalation path that promises cleanup.
- Unknown external resources are not reported as cleaned.
- User output cannot reach MCP or runner control channels unframed.
- Dead kernels are not silently recreated.
- Default operation opens no network listener and performs no privilege elevation.
- Environment exposure and helper file access match the accepted allowlist and workspace policy when those features exist.
- Documentation describes local same-user execution and never claims sandboxing.

### Gate 5: Package and platform evidence

The distributable artifact is built, installed into a clean environment, and smoke-tested through its real entry point. Process and signal behavior is tested on every operating system claimed as supported. A platform remains unsupported until its lifecycle scenarios pass there.

Appium, simulators, emulators, Xcode, and Android SDK jobs are Stage 3 experiment gates. They do not block unrelated Stage 1 core changes.

Coverage reports may reveal missing state-machine paths, but no percentage threshold is adopted without a code baseline and evidence that the threshold protects meaningful behavior.

## 6. Blocking conditions

A change cannot be accepted with any of the following:

- unknown or incorrect `kernelState`;
- runner-frame or MCP transport corruption by user output;
- leaked managed descendants;
- automatic recreation that hides kernel death or state loss;
- a public contract changed without migrating every consumer;
- a required end-to-end path proven only by mocks or unit tests;
- skipped or flaky required checks treated as success;
- platform-specific semantics in the core without cross-experiment evidence;
- speculative runtime registries, remote transport, workflow languages, or platform wrappers;
- wholesale copying from `../omp` without mechanism-level justification and focused tests;
- placeholders, stubs, compatibility shims, or deferred work inside the claimed deliverable.

## 7. Definition of done

A change is done only when:

- the complete accepted behavior works through the real surface;
- every caller and contract consumer uses the final form;
- focused tests defend new or changed behavior;
- applicable static, build, lifecycle, security, and end-to-end gates pass;
- an independent reviewer finds no blocking architecture, correctness, or security issue;
- verification evidence names what was exercised and observed;
- documentation is updated where, and only where, the verified behavior changes project truth.

## 8. Decisions required before Stage 1 coding

ADR-0001 settles the Python implementation, official MCP SDK, package-layout direction, and canonical toolchain. The first implementation planning task must consume that decision and settle the remaining coupled contracts because downstream ownership and tests depend on them:

1. initial Python test matrix, dependency constraints, and the evidence plan for later bounded compatibility metadata;
2. exact tool name, input schema, result fields, and MCP content mapping for Stage 1;
3. runner frame encoding, version handshake, correlation, limits, and crash/EOF mapping;
4. FIFO or rejection behavior, whether queue time counts toward timeout, and reset ordering;
5. timeout units/defaults/ranges, escalation grace periods, cancellation semantics, and behavior after kernel death;
6. deterministic interpreter and working-directory resolution plus diagnostic fields;
7. the minimal Stage 1 prelude and bounded representation for non-JSON trailing values;
8. managed-process ownership and the initial operating-system support claim;
9. concrete Stage 1 population rules for the required `output` and `artifacts` fields;
10. the boundary between Stage 1 completion-time stdout/stderr capture and Stage 2 execution-time live streaming.

The result schema is not a planning option: Stage 1 keeps the architecture's required fields, using truthful empty or non-spilled values until Stage 2 behavior exists.

These decisions must be recorded in the accepted implementation plan or architecture before code is fanned out to module owners.

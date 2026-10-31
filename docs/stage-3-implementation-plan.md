# Stage 3 Mobile/Appium Experiment Implementation Plan

## Purpose

This is the execution plan for the Stage 3 Mobile/Appium experiment in `docs/experiments/mobile-appium.md`. It validates AMKernel through one Android UiAutomator2 emulator and one iOS XCUITest simulator while keeping Appium, device, and platform semantics out of the kernel.

The experiment tests a vertical, not a support matrix. Every claim is limited to the exact recorded environment.

Post-graduation Issues #84 and #85 established the user-centered `amkernel-appium` interface; Issue #88 packages that interface as the project-installed `amkernel` skill beside the Runtime. Earlier names remain only in frozen Stage 3 evidence and are not active aliases.

## Fixed scope

### Included

- one project-installed `amkernel` skill that routes the Appium procedure from a user goal;
- reviewed handoffs to Appium's official setup and troubleshooting skills;
- direct use of the official Appium Python Client through `python_exec`;
- one deterministic logical fixture workflow on Android and iOS;
- one Android emulator / UiAutomator2 vertical;
- one iOS simulator / XCUITest vertical;
- persistent driver reuse, explicit waits, screenshots, bounded page-source analysis, artifacts, narrow project automation, error recovery, reset, shutdown, and explicit Appium session cleanup;
- exact environment, package, server, driver, device, fixture, artifact, duration, resource, and review evidence;
- failure and lifecycle evidence that distinguishes kernel, Appium session, device, and external server state.

### Excluded

- mobile-specific MCP tools or wrappers around the Appium Python Client;
- Appium, Selenium, Node, Android SDK, Xcode, emulator, or simulator dependencies in AMKernel core;
- automatic installation of system SDKs, Xcode, signing assets, or physical-device provisioning;
- physical devices, device farms, Espresso, web/mobile-web automation, parallel sessions, and a broad device/OS matrix;
- blocking Appium Server processes inside `python_exec`;
- automatic discovery or cleanup of unknown external Appium sessions;
- PyPI publication, Stage 4 multi-client coverage, or a general Android/iOS support claim;
- core behavior changes without a separate Issue and accepted decision.

## Milestone record

- **Delivery stage and outcome:** M3 / Stage 3. A Coding Agent follows one project-local skill to prepare, connect, reuse, inspect, diagnose, and explicitly clean up Appium Python sessions through the real AMKernel MCP surface on one recorded Android emulator and one recorded iOS simulator.
- **Entry criteria:** Stage 2 and S2-090 are complete; AMKernel's installed-wheel, output, artifact, workspace, diagnostics, timeout, reset, and shutdown contracts are accepted; M3 and S3-001 through S3-060 are registered in GitHub Project #2.
- **Exit criteria:** every criterion in the experiment document has retained evidence; all required M3 Issues are Done; no core contract changed implicitly; final independent review has no unresolved Blocker or Major finding.
- **Canonical tracking:** GitHub Project #2, milestone `M3 — Mobile/Appium experiment`, and Issues #68–#74.

## Contract prerequisites

Implementation begins only after S3-001 is reviewed and merged. Platform experiments additionally require:

1. the project-local skill contract from S3-010;
2. deterministic fixture and evidence contracts from S3-020;
3. an installed AMKernel wheel in a dedicated experiment environment;
4. the Appium Python Client and Selenium in that same Python environment;
5. an externally supervised Appium Server and reachable simulator/emulator;
6. exact version and build provenance captured before session creation;
7. destructive lifecycle cases isolated from unrelated user sessions and devices.

Missing platform software is an external blocker recorded on the owning Issue. It is not a reason to simulate evidence or weaken acceptance criteria.

## Deep module seams

### `src/amkernel/skill/SKILL.md`

Owns the user-facing AMKernel procedure: infer Android or iOS from a plain-language goal, route setup and diagnosis to reviewed official Appium skills, enforce readiness, use the official Python Client through `python_exec`, and report bounded evidence and truthful cleanup.

Its interface is a user goal. It does not define mobile action abstractions, expose internal session bookkeeping, conceal Appium APIs, run an Appium Server in a cell, or claim cleanup beyond observed actions.

### Official `appium/skills`

Appium's official `setup-uiautomator2`, `setup-xcuitest`, and `appium-troubleshooting` skills are reviewed procedural inputs from the canonical `https://github.com/appium/skills` repository. The packaged manifest records one immutable commit, every recursively consumed relative path and SHA-256, the reviewed audit result, and local restrictions at `src/amkernel/skill/references/official-skills.json`.

The only accepted acquisition form is `DISABLE_TELEMETRY=1 npx skills add https://github.com/appium/skills/tree/<commit>/skills/<name> --skill <name> --copy -a <selected-agent> -y`, with the placeholders replaced by manifest values. It installs project-local runtime copies under `.agents/skills/<name>` plus the selected agent link. Both locations are generated, excluded from source control, and must hash-match the manifest before every dry-run or use; absence or mismatch fails closed as a prerequisite blocker. S3-010 must first prove that the pinned tree URL is resolved at the named commit by the selected Skills CLI version. No branch/default-ref fallback is permitted.

These skills are not vendored production code, Python dependencies, or authority over AMKernel lifecycle truth. Updates require a manifest commit/hash change, source diff, and renewed review. Community fallback guidance is untrusted unless independently confirmed by official documentation or local evidence.

### Experiment harness

Experiment-only scripts own fixture installation, black-box MCP driving, evidence capture, measurement, and cleanup assertions. They call the public MCP surface and official platform interfaces. They do not import AMKernel private modules or become a second runtime path.

Large transcripts, screenshots, source trees, and platform logs are retained as GitHub Actions or run artifacts. Repository fixtures remain small, deterministic, reviewable, and free of credentials, local paths, signing material, and device identifiers that should not be published.

### AMKernel core

`protocol.py`, `runner.py`, `output.py`, `artifacts.py`, `supervisor.py`, `runtime.py`, and `server.py` are read-only during the planned experiment. A discovered core defect receives its own Issue, reproduction, decision if necessary, focused fix, and independent review before the experiment resumes.

## Path and sole-writer ownership

| Path | Sole writer | Consumers |
|---|---|---|
| `docs/stage-3-implementation-plan.md` | S3-001 / Contract and Integration Lead | all M3 items |
| `src/amkernel/skill/**` | #88 / Distribution and Skill Owner | installed projects and S3-020 through S3-060 |
| `tests/skills/test_amkernel_skill.py` | #88 / Distribution and Skill Owner | provenance, user-experience, and later skill changes |
| `.gitignore` entries for generated `.agents/skills` and selected agent links | S3-010 / Skill Implementation Owner | all local skill users |
| `tests/fixtures/mobile_appium/scenario.json` | S3-020 / Mobile Experiment Owner | S3-030 and S3-040 |
| `tests/fixtures/mobile_appium/evidence.schema.json` | S3-020 / Mobile Experiment Owner | S3-030 through S3-060 |
| `tests/fixtures/mobile_appium/measurement-protocol.json` | S3-020 / Mobile Experiment Owner | S3-030 through S3-060 |
| `tests/e2e/mobile_appium.py` | S3-020 / Mobile Experiment Owner | S3-030 through S3-050; later edits require S3-020 owner review |
| `.github/workflows/stage-3-mobile.yml` | S3-020 / Mobile Experiment Owner | S3-030 through S3-060 |
| `evidence/stage-3/android.json` | S3-030 / Android Experiment Owner | S3-050 and S3-060 |
| `evidence/stage-3/ios.json` | S3-040 / iOS Experiment Owner | S3-050 and S3-060 |
| `evidence/stage-3/lifecycle.json` | S3-050 / Lifecycle Verification Owner | S3-060 |
| `evidence/stage-3/index.json` | S3-060 / Contract and Integration Lead | future stages and support claims |
| `docs/HANDOFF.md` Stage 3 state/next-slice sections | active ordered M3 item owner; S3-060 final owner | next ordered item |

Large run outputs referenced by the committed evidence JSON remain retained workflow/run artifacts rather than repository blobs. No other item may edit a sole-writer path without transferring ownership visibly in its GitHub Issue first.

## Environment and provenance contract

Each platform run records at least:

- commit, installed wheel filename, SHA-256, and reported AMKernel version;
- host OS, architecture, Python implementation/version, and MCP client/protocol version;
- `Appium-Python-Client`, Selenium, Node, Appium Server, platform driver, and official-skill source revisions;
- Android SDK/emulator image/API/ABI/device identity, or Xcode/simulator runtime/device identity;
- fixture repository/release/build/package identity and SHA-256 where applicable;
- Appium base URL without credentials and the platform capability set with secrets removed;
- scenario start/end/duration, execution count, kernel state, session presence, device/app state, and cleanup result;
- screenshot/source/artifact MIME, byte size, and SHA-256;
- server, driver, device, and AMKernel logs required to explain failures;
- host RSS, open-file/task/descendant-process observations at the defined measurement points.

The baseline interpreter is CPython 3.13, the highest Stage 2 supported version. A platform item may use another supported CPython 3.11–3.13 version only when the Issue records the incompatibility evidence and updates its claim before execution.

No evidence record contains authentication tokens, signing secrets, private keys, user home paths, or unredacted capabilities with credentials.

## Delivery sequence

Each item includes focused evidence and independent review before it is Done. Platform work remains serial where it shares Appium Server, simulator/emulator, fixture, or evidence state.

### S3-001 — Accept the experiment implementation plan (#74)

**Owner:** Contract and Integration Lead.

**Deliverables**

- Register M3 and the complete ordered issue graph in GitHub Project #2.
- Accept this plan as the execution contract for `docs/experiments/mobile-appium.md`.
- Freeze skill, official-source, harness, evidence, platform, cleanup, and no-core-change seams.
- Update the handoff to name S3-010 as the next ready slice.

**Focused evidence**

- every experiment criterion maps to at least one M3 item;
- every item has dependencies, ownership, non-goals, write ownership, evidence, and reviewer requirements;
- no production schema, dependency, or support claim changes;
- independent architecture/correctness review finds no unresolved Blocker or Major issue.

**Exit**

S3-010 can implement the local skill without inventing architecture, platform claims, or evidence rules.

### S3-010 — Add the pinned Appium procedure to the AMKernel skill (#68)

**Owner:** Skill Implementation Owner.

**Depends on:** S3-001.

**Deliverables**

- Package `src/amkernel/skill/SKILL.md` with novice-oriented Android/iOS routing, readiness, persistent-driver use, bounded evidence, scenario verification, and truthful cleanup.
- Package `src/amkernel/skill/references/official-skills.json` with the canonical repository, immutable commit, consumed relative paths and SHA-256 values, exact pinned acquisition commands, generated locations, audit outcomes, and local restrictions.
- Validate the source and installed copies through `tests/skills/test_amkernel_skill.py` and the packaged fail-closed verifier.
- Keep platform setup delegated, Appium Server externally supervised, and generated `.agents/skills`/agent links out of source control through explicit `.gitignore` entries.

**Focused evidence**

- Android and iOS dry-run decision paths;
- missing Python client, server, platform driver, and device/simulator diagnoses identify the correct layer and next command;
- code examples use current options classes and `webdriver.Remote` without deprecated desired capabilities;
- screenshot uses `display()`, large source uses local reduction plus `artifact()`, and cleanup uses `driver.quit()`;
- security/source review of every external instruction path.

**Exit**

A Coding Agent can prepare either platform or produce a truthful prerequisite blocker before experiment fixture work begins.

### S3-020 — Establish deterministic mobile fixtures and evidence records (#73)

**Owner:** Mobile Experiment Owner.

**Depends on:** S3-001 and S3-010.

**Deliverables**

- Select maintained Android/iOS fixtures, or justify the smallest deterministic fixture implementation if no maintained pair meets the contract.
- Freeze stable accessibility identifiers for launch, navigation, text input, scroll, delayed state, modal handling, deterministic success, and a moderately large tree in `tests/fixtures/mobile_appium/scenario.json`.
- Add `evidence.schema.json`, the public-surface black-box harness, and the manually dispatched Stage 3 workflow at their owned paths.
- Freeze platform versions and exact fixture build/install procedures used by S3-030 and S3-040.
- Before either platform item becomes Ready, freeze `measurement-protocol.json`: instruments, clocks, warm-up, repetition counts, sampling points, baseline subtraction, every twelve required measurement fields, numeric time/resource ceilings, plateau deltas, pass/fail rules, and unavailable-measurement handling. The protocol requires three fresh-process startup trials; ten steady-state task/screenshot/source iterations sampled after warm-up and iterations 1, 5, and 10; min/median/max latency reporting; separate AMKernel/Appium/platform-driver process metrics; and independent byte/hash verification.

**Focused evidence**

- both fixture builds expose the same logical workflow and stable identifiers;
- delayed/modal/large-tree paths are deterministic across clean launches;
- a sample evidence record rejects missing provenance, hashes, state, or cleanup facts;
- fixture licenses and redistribution terms are recorded.

**Exit**

Android and iOS owners can run the same logical scenarios and produce comparable bounded records.

### S3-030 — Prove the Android UiAutomator2 emulator vertical (#72)

**Owner:** Android Experiment Owner.

**Depends on:** S3-010 and S3-020.

**Deliverables**

- Prepare one recorded Android emulator through the reviewed setup procedure.
- Drive the real MCP surface from installed AMKernel to create one UiAutomator2 session and reuse it across calls.
- Exercise navigation, text, scroll, delayed/modal state, screenshot, large source, artifact recovery, narrow project automation, ordinary Appium/Python error recovery, and explicit cleanup.
- Capture resource and process observations without claiming ownership of Appium Server or emulator processes.

**Focused evidence**

- experiment sections 7.1, 7.2, 7.5, 7.6, 7.7, and 7.8;
- stable session identity and increasing AMKernel execution count across calls;
- screenshot and source/artifact bytes independently decoded/hashed;
- final Appium session deletion and observed device/app state;
- independent Android/Appium review.

**Exit**

The exact Android environment satisfies its mapped scenarios without a mobile-specific core path.

### S3-040 — Prove the iOS XCUITest simulator vertical (#70)

**Owner:** iOS Experiment Owner.

**Depends on:** S3-010 and S3-020.

**Deliverables and focused evidence:** the S3-030 contract repeated through official XCUITest APIs on one recorded iOS simulator, including WebDriverAgent state needed for diagnosis. No physical-device signing or provisioning claim.

**Exit**

The exact iOS simulator environment satisfies its mapped scenarios without a mobile-specific core path.

### S3-050 — Exercise Appium failure and lifecycle boundaries (#71)

**Owner:** Lifecycle Verification Owner.

**Depends on:** S3-030 and S3-040.

**Deliverables**

- Exercise and retain every failure listed in the failure-coverage table below; no representative subset may substitute for an enumerated case.
- For every case independently determine kernel state, Appium session state, device/app state, external server state, required recreation, and cleanup outcome.
- Detect possible orphan sessions after kernel death without claiming AMKernel automatically cleans external resources.
- Prove reset starts a clean namespace and new Runner while retained artifacts follow the accepted core contract.

**Focused evidence**

- experiment sections 7.3, 7.4, and 7.8 plus all nineteen failure cases with the required platform coverage;
- isolated destructive cases with before/after process, session, and device observations;
- bounded outputs and recoverable artifacts for large-error paths;
- independent lifecycle/security review.

**Exit**

The experiment can state exactly which failures preserve or destroy each layer and what cleanup remains external.

### S3-060 — Graduate the Mobile/Appium experiment (#69)

**Owner:** Contract and Integration Lead; final reviewer independent from all implementation owners.

**Depends on:** S3-030, S3-040, and S3-050.

**Deliverables**

- Index every experiment criterion, all nineteen failure cases, and all twelve measurements to exact retained evidence, versions, artifacts, measurements, cleanup outcomes, and reviewer dispositions; missing or unmapped evidence is a graduation failure.
- Answer the experiment's module-seam, timeout, reset, shutdown, output, artifact, workspace, diagnostics, and resource questions.
- Keep Appium procedure in the skill unless evidence from another independent vertical justifies a separate core decision.
- Narrow documentation claims to observed environments, update the handoff, close all M3 issues, and close the milestone.

**Focused evidence**

- final focused/integrated gates on the reviewed commit;
- independently reproducible evidence hashes and provenance;
- no unresolved Blocker or Major architecture, correctness, lifecycle, security, or evidence finding.

**Exit**

Stage 3 is complete and Stage 4 remains blocked until a separately ordered GitHub item is Ready.

## Cross-cutting behavioral matrix

| Behavior | S3-010 | S3-020 | S3-030 | S3-040 | S3-050 | S3-060 |
|---|---:|---:|---:|---:|---:|---:|
| Setup/doctor routing | X |  | X | X | X | X |
| Persistent driver/session | X |  | X | X | X | X |
| Deterministic UI workflow |  | X | X | X |  | X |
| Explicit waits and async state | X | X | X | X | X | X |
| Screenshot image/artifact | X | X | X | X | X | X |
| Large page source/output bounds | X | X | X | X | X | X |
| Python/Appium error recovery | X |  | X | X | X | X |
| Timeout/cancel/reset/shutdown | X |  |  |  | X | X |
| External session cleanup truth | X |  | X | X | X | X |
| Exact provenance/measurements |  | X | X | X | X | X |

## Failure-coverage matrix

Every row from the experiment failure matrix is mandatory. “Both” means one retained Android and one retained iOS occurrence; “Shared” means one Android occurrence is sufficient because the injected failure is wholly inside the automation-neutral AMKernel/Python seam, while both normal platform paths remain covered by S3-030/S3-040.

| Required failure | Owning item | Platform coverage |
|---|---|---|
| Appium endpoint unavailable | S3-010 preflight, S3-050 evidence | Both |
| Incompatible Python client/Selenium versions | S3-010 preflight, S3-050 evidence | Shared |
| Missing Appium driver | S3-010 preflight, S3-050 evidence | Both |
| Device offline | S3-050 | Both |
| Session creation failure | S3-050 | Both |
| Invalid app target | S3-050 | Both |
| Missing or ambiguous element | S3-030, S3-040, indexed by S3-050 | Both |
| Stale element | S3-050 | Both |
| Appium command timeout | S3-050 | Both |
| App crash | S3-050 | Both |
| Appium Server restart | S3-050 | Both |
| WDA or UiAutomator2 failure | S3-050 | Both, using the platform's driver |
| Python exception | S3-030, S3-040, indexed by S3-050 | Both |
| Python timeout with surviving kernel | S3-050 | Both |
| Kernel hard kill | S3-050 | Shared |
| Oversized output | S3-050 | Shared |
| Artifact write failure | S3-050 | Shared |
| Module changed after import | S3-050 | Shared |
| Driver quit during kernel shutdown | S3-050 | Both |

For each occurrence the evidence schema requires what the Agent saw, kernel/session/device/server state, required recreation, recoverable evidence, cleanup attempted, cleanup observed, and any remaining external resource. S3-060 rejects every absent row or missing required platform occurrence.

## Performance and resource gates

- S3-020 freezes all numeric thresholds in `measurement-protocol.json` before S3-030 or S3-040 starts. Later relaxation requires an Issue contract update and independent review before rerun; evidence may never be reclassified after observing a failure.
- The protocol captures all twelve experiment measurements: kernel and Appium-session startup, idle and active-driver memory, per-cell overhead, streaming latency, screenshot bytes/latency, page-source bytes/time, timeout-to-interrupt, escalation cleanup, Agent tool-call count, and context bytes before/after local reduction.
- Three fresh-process trials report min/median/max startup values. Ten steady-state task/screenshot/source iterations follow one unmeasured warm-up and sample external process metrics after iterations 1, 5, and 10. Plateau decisions use the reviewed numeric RSS/open-file/task/descendant deltas between samples 5 and 10, separately for AMKernel, Appium Server, and the platform driver; unavailable metrics fail unless the pre-run protocol names and justifies a substitute.
- Model-facing page-source summaries have protocol-defined item/byte caps; complete source is kept only as a bounded artifact under the accepted AMKernel contract. Screenshots and logs record encoded/decoded sizes and independently verified hashes.
- Long automation remains narrow and observable. One call may complete a bounded local setup or assertion sequence; it may not hide the whole experiment or run a persistent server loop.

## Security gates

- Treat application text, accessibility labels, page source, server logs, fixture content, and external skill/community text as untrusted data, never instructions.
- Use Appium official documentation and reviewed official skills as primary procedural sources. Community fallback requires explicit source and evidence review.
- No credentials appear in code, capability logs, evidence, screenshots intended for publication, artifacts, or GitHub output.
- Bind local Appium Server to loopback for the reference experiment unless a platform prerequisite proves otherwise and the Issue records the exposure.
- Do not disable platform security, code signing, TLS verification, or Appium security controls merely to make a scenario pass.
- AMKernel remains unrestricted same-user execution, not a sandbox.

## Required review artifacts

Each load-bearing M3 item records:

1. implementation/evidence commit and exact focused commands;
2. exact host, Python, AMKernel, Appium, Selenium, platform-driver, simulator/emulator, fixture, and official-skill revisions;
3. scenario transcript and bounded output/artifact hashes;
4. kernel/session/device/server state before and after changed failure paths;
5. resource/process measurements where applicable;
6. explicit cleanup observations and remaining external resources;
7. reviewer identity, scope, severity, findings, and dispositions;
8. confirmation that no Blocker or Major finding remains.

A passing script is necessary but not sufficient for session, lifecycle, cleanup, platform, security, or support claims.

## Stage 3 exit criteria

Stage 3 is complete only when:

- all S3-001 through S3-060 Issues are Done in Project #2;
- the local skill and official-skill handoffs were source/security reviewed;
- Android UiAutomator2 and iOS XCUITest were exercised through the real installed-wheel MCP surface;
- one driver per platform persisted across calls and was explicitly cleaned up;
- screenshots, large page sources, structured output, artifacts, workspace automation, and diagnostics behaved under accepted bounds;
- the failure matrix truthfully distinguishes kernel, session, device/app, and external server state;
- reset, shutdown, timeout, and hard-kill evidence does not overclaim external cleanup;
- exact provenance, hashes, measurements, and review artifacts are retained;
- no Appium-specific production dependency or parallel runtime path entered core without a separate accepted decision;
- final independent review has no unresolved Blocker or Major finding;
- documentation and handoff state only the support demonstrated by the recorded environments.

# Changelog

All notable changes to AMKernel are recorded here. Public releases use semantic `0.MINOR.PATCH` versions under the pre-1.0 policy in `docs/development.md`.

## [Unreleased]

### Changed

- Replace repository-retained raw verification outputs with the immutable `v0.1.2` evidence archive. Keep normalized records and an offline provenance index in Git, classify all 203 original members by retention, and ignore future raw output locations without rewriting history ([#120](https://github.com/FSQ-lab/amkernel/issues/120); [ADR-0008](docs/decisions/0008-release-evidence-retention.md)).
- Deepen the installed `amkernel` Skill around a plain-language outcome: infer one minimal platform route, perform safe discovery without technical questionnaires, avoid duplicate approval for explicitly requested effects, continue from readiness through the requested action, and keep provenance, lifecycle, and cleanup truth intact. The Android behavior prompt now exercises this route from a nontechnical-user request ([#98](https://github.com/FSQ-lab/amkernel/issues/98)).
- Separate unrestricted host setup/MCP diagnostics from Appium execution through `python_exec`. Give the installed Skill a complete non-interactive installer command and a bounded launcher/configuration repair path, preserve diagnosis-only approval boundaries, and distinguish configured/reload-required from actual Agent execution without platform detours or redundant probes.
- Correct Appium locator constants and distinguish native Android package/activity liveness from explicitly selected Web-context APIs. Executable synthetic Client regressions reject Selenium-only constants, native title probes and stale local session identity; real Android qualification remains separate ([#124](https://github.com/FSQ-lab/amkernel/issues/124)).
- Preserve bounded actionable messages for explicitly recognized Selenium/Appium exception shapes without calling third-party rendering or dynamic attributes. Read only inert string `msg`; omit sensitive/oversized data and external traceback paths/source, retain fail-closed custom `__str__` behavior and truthful kernel survival. Adversarial field, namespace, credential, size and exception-chain regressions defend this boundary ([#125](https://github.com/FSQ-lab/amkernel/issues/125)).
- Make Android Skill provisioning target-scoped: reuse verified Runtime/JDK/SDK installations, evaluate exact Node and driver constraints, execute component-level installations after scoped approval, and distinguish physical/emulator prerequisites from live session proof. Preserve raw official doctor results, task-scoped environments and external service ownership. Add bounded synthetic native-Agent approval/readiness scenarios and packaged-reference integrity regressions ([#129](https://github.com/FSQ-lab/amkernel/issues/129)); no real dependency/device or platform qualification is claimed.
- Deduplicate Android Skill setup/readiness guidance: keep Android procedures in `android-setup.md`, retain routing in the main Skill, and centralize shared Appium service ownership in the execution seam. Preserve the existing rules and tests without changing Apple branches, pinned official source or core behavior ([#130](https://github.com/FSQ-lab/amkernel/issues/130)).
- Correct strict typing in the Android setup experiment's JSON narrowing, version evidence and regression annotations without changing approval/readiness decisions. The full production-and-test Mypy gate now passes alongside the existing protocol/oracle smoke ([#133](https://github.com/FSQ-lab/amkernel/issues/133)).
- Add target-scoped physical-iPhone setup to the packaged `amkernel` Skill: reuse applicable Runtime/Xcode/Appium/WDA assets, disclose dependency and security changes, guide native account/passcode/keychain actions, and distinguish profile/runner identity repair from connection failures. Preserve official Appium guidance, setup-only no-launch/no-session, shared-resource ownership and required prepared artifacts. Extend managed-reference integrity coverage; core interfaces and platform qualification remain unchanged ([#131](https://github.com/FSQ-lab/amkernel/issues/131)).

## [0.1.2] - 2026-11-04

Backward-compatible reliability, installation and release-evidence corrections. Runtime, MCP and qualified platform contracts are unchanged.

### Changed

- Build the complete pre-migration evidence corpus into a deterministic, content-addressed archive from authoritative CI and require the exact archive and manifest beside the tested wheel in the immutable GitHub Release. Keep normal tests offline and defer raw-evidence removal until the published assets verify independently ([#120](https://github.com/FSQ-lab/amkernel/issues/120); [ADR-0008](docs/decisions/0008-release-evidence-retention.md)).
- Ignore every generated official-Skill copy, installer receipt and transient lock while preserving authored project content. Remove the obsolete `amkernel-appium` unignore rule after the clean cutover ([#120](https://github.com/FSQ-lab/amkernel/issues/120)).

### Fixed

- Prompt for one Coding Agent during interactive project installation when detection is ambiguous or empty, while keeping non-interactive installation fail-closed without an explicit `--client`. Label the shared user Runtime and project-local Skill/source/MCP activation separately in the install plan ([#119](https://github.com/FSQ-lab/amkernel/issues/119)).
- Make ready-stream settlement cancellation-safe so a queued zero-delay timer cannot raise an unhandled `InvalidStateError` after its waiter is cancelled. Preserve terminal ordering, cancellation propagation and storage-failure cleanup ([#114](https://github.com/FSQ-lab/amkernel/issues/114)).
- Replace the scheduling-dependent 32 MiB/1 ms artifact deadline test with controlled real transaction boundaries. Verify complete consumer-readable artifacts and truthful `timed_out/alive` versus `kernel_killed/dead` outcomes without requiring survival after forced termination ([#115](https://github.com/FSQ-lab/amkernel/issues/115)).
- Keep Stage 4 Codex evaluation pinned to the published wheel with separate harness provenance; preserve bounded, redacted diagnostics and stop without replay or false blocked/pass classification after observed client execution. Retain the actual provider-blocked attempts and separate server-only validation without claiming either client layer passed ([#81](https://github.com/FSQ-lab/amkernel/issues/81)).
- Add the frozen cross-OS process evidence runner and hosted Ubuntu/macOS matrix, with pinned wheel/source provenance, invocation-bound aggregation, truthful managed cleanup and failed-report retention. Reject self-approved review, altered matrix metadata and contradictory lifecycle observations; no Runtime or Windows support change ([#79](https://github.com/FSQ-lab/amkernel/issues/79)).

## [0.1.1] - 2026-11-03

Backward-compatible Skill, installation and evaluation corrections from
[PR #110](https://github.com/FSQ-lab/amkernel/pull/110), published under
[Release #111](https://github.com/FSQ-lab/amkernel/issues/111).
The public `python_exec` contract, dependency baseline and qualified Ubuntu/macOS
CPython 3.11–3.13 support are unchanged. Mobile integrations remain experimental;
Windows support is not claimed. Exact hosted CI and wheel provenance are recorded
in the GitHub Release.

### Fixed

- Classify Appium dependency warnings and unverified matrix coverage separately from proven incompatible constraints, using the actual `python_exec` interpreter and package metadata. Remove the Skill's arbitrary Appium 6.x requirement and scope approved repairs to the observed Runtime ([#102](https://github.com/FSQ-lab/amkernel/issues/102)).
- Route native macOS automation explicitly to pinned `setup-mac2`/Mac2 guidance, reject unsupported Windows targets without fallback, and resolve official helper paths from the verified source checkout ([#103](https://github.com/FSQ-lab/amkernel/issues/103)).
- Install the main Skill, every referenced official Appium Skill, and the complete pinned source snapshot for GitHub Copilot CLI. Verify archive, receipt, runtime version, and exact file digests; preserve the active MCP file's unrelated entries, reject linked managed paths, and roll back file/directory-shape upgrades without losing owned or foreign data ([#104](https://github.com/FSQ-lab/amkernel/issues/104)).
- Keep short Appium flows compact while separating meaningful long-operation, recovery, restoration, and cleanup boundaries. Inspect actual `status`/`kernelState`, verify remote session liveness, and reconcile ambiguous irreversible actions through the existing `python_exec` interface. Preserve the requested end state and respect explicit action limits across execution and cleanup ([#98](https://github.com/FSQ-lab/amkernel/issues/98)).
- Discover and execution-validate existing Java, Android, and Apple capabilities before repairs; keep selections task-scoped, physical and simulator inventories separate, and development/XCUITest readiness explicit rather than inferred from listings ([#106](https://github.com/FSQ-lab/amkernel/issues/106)).
- Keep conversation activity distinct from nested-message recency; search before filtering, normalize temporal evidence, re-locate after list changes, and verify returned identity after opening. Require approval for user-visible changes, restore only task-owned reversible state before session deletion, and report restoration/session/server outcomes separately ([#107](https://github.com/FSQ-lab/amkernel/issues/107)).
- Qualify recovered native Appium execution through later timestamp-bound live target observations, not an error-free history or final no-op. Keep identity, restoration-before-quit, owned cleanup and canonical report checks separate; preserve the historical failed classification and retain a new real Calculator/Mac2 recovery baseline ([#108](https://github.com/FSQ-lab/amkernel/issues/108)).
- Correct experiment-only TextEdit/Finder save/dialog and owned-restoration checks; retain source review, isolated behavioral smoke evidence and failed actual M1 attempts. A visible retry demonstrates real Mac2 actions but exposes a remaining Major query-local identity verifier defect and duplicate-window ambiguity; lock is not an established exclusive failure cause. No Runtime or platform-support change ([#109](https://github.com/FSQ-lab/amkernel/issues/109)).
- Apply the locked Ruff formatter to the Appium remediation files so PR #110 passes the canonical formatting gate; Python ASTs are unchanged. Document the complete pre-push quality commands, including formatting separately from lint.

### Changed

- Defer complex Mac/TextEdit/Finder scenarios and their verifier development to later evaluation at the owner's direction; prioritize ordinary app operations without adding a Mac qualification gate. Historical failed/unexercised results remain unchanged ([#109](https://github.com/FSQ-lab/amkernel/issues/109)).
- Record owner-supervised ordinary Android and physical-iPhone app smoke observations, task-owned data cleanup and temporary RemoteXPC tunnel teardown, with recovery, privacy and restoration limits explicit; no formal platform qualification or Runtime change.

## [0.1.0] - 2026-11-02

### Breaking

- Replace the Stage 1 execution result with the exact Stage 2 `python_exec` schema and private protocol v2. Callers must consume bounded output metadata, displays, artifacts, and the expanded runtime diagnostics from the new shape; no compatibility alias is retained.

### Added

- Stream output from byte one into bounded previews and recoverable stdout/stderr artifacts, with optional rate-limited MCP progress and explicit hard output-limit intervention.
- Add strict JSON display, fully decoded PNG/JPEG/GIF/WebP display, explicit artifact, requested-package diagnostics, and descriptor-rooted `read`, `write`, and `env` helpers.
- Add process-scoped Artifact Store resources with raw or manifest/part recovery, digest verification, whole-bundle quota eviction, tamper detection, and identity-safe cleanup refusal.
- Extend clean-wheel official-client evidence across CPython 3.11–3.13 on hosted Ubuntu and macOS; CI retains each job's exact wheel hash, dependency set, interpreter/OS identity, scenario output, and lockfile.
- Install one uv-managed user Runtime, one project-local `amkernel` Agent Skill, and native OMP, Pi, or Codex project MCP configuration through `amkernel install`.
- Add pinned Android and iOS Appium fixtures, equivalent versioned workflows, a strict evidence schema, and a manual self-hosted mobile-lab runner through AMKernel's public MCP interface.
- Freeze one client-neutral Codex CLI/GitHub Copilot CLI scenario and executable evidence contract with privacy-safe request projection, exact byte accounting, resource reconstruction, lifecycle truth, and mutation coverage.

### Changed

- Unify deadline, cancellation, output-limit, Runner death, Store failure, reset, shutdown, and terminal result-construction ordering under the Runtime lifecycle authority.
- Lock Pillow as the cross-platform raster decoder. CPython 3.11–3.13 on current GitHub-hosted Ubuntu and macOS remain the only supported environment claim; CPython 3.14 and Windows remain unsupported.
- Document ephemeral resource retention: clients must read and verify every manifest part before another large-output call or server shutdown.
- Replace the implementation-centered `appium-python` and interim `amkernel-appium` entries with the packaged, user-centered `amkernel` skill. The skill prioritizes verified official Appium guidance, leaves contextual judgment to the LLM, adds only AMKernel-specific knowledge, and is installed with the Runtime's project activation instead of a separate skill command.

### Security

- Workspace helpers traverse from pinned descriptors without following symlinks, and Artifact Store reads revalidate identity and content digests.
- AMKernel remains unrestricted same-user local code execution, not a sandbox. Random resource identifiers do not provide confidentiality or integrity against another same-user process.

Governed by [ADR-0006](docs/decisions/0006-stage-2-output-and-artifact-contract.md), [ADR-0007](docs/decisions/0007-global-runtime-project-activation.md), the [Stage 2 implementation plan](docs/stage-2-implementation-plan.md), [S2-090](https://github.com/FSQ-lab/amkernel/issues/51), and [Release #90](https://github.com/FSQ-lab/amkernel/issues/90).

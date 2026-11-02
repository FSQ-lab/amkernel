# Changelog

All notable changes to AMKernel are recorded here. Public releases use semantic `0.MINOR.PATCH` versions under the pre-1.0 policy in `docs/development.md`.

## [Unreleased]

### Fixed

- Classify Appium dependency warnings and unverified matrix coverage separately from proven incompatible constraints, using the actual `python_exec` interpreter and package metadata. Remove the Skill's arbitrary Appium 6.x requirement and scope approved repairs to the observed Runtime ([#102](https://github.com/FSQ-lab/amkernel/issues/102)).
- Route native macOS automation explicitly to pinned `setup-mac2`/Mac2 guidance, reject unsupported Windows targets without fallback, and resolve official helper paths from the verified source checkout ([#103](https://github.com/FSQ-lab/amkernel/issues/103)).
- Install the main Skill, every referenced official Appium Skill, and the complete pinned source snapshot for GitHub Copilot CLI. Verify archive, receipt, runtime version, and exact file digests; preserve the active MCP file's unrelated entries, reject linked managed paths, and roll back file/directory-shape upgrades without losing owned or foreign data ([#104](https://github.com/FSQ-lab/amkernel/issues/104)).
- Keep short Appium flows compact while separating meaningful long-operation, recovery, restoration, and cleanup boundaries. Inspect actual `status`/`kernelState`, verify remote session liveness, and reconcile ambiguous irreversible actions through the existing `python_exec` interface. Preserve the requested end state and respect explicit action limits across execution and cleanup ([#98](https://github.com/FSQ-lab/amkernel/issues/98)).
- Discover and execution-validate existing Java, Android, and Apple capabilities before repairs; keep selections task-scoped, physical and simulator inventories separate, and development/XCUITest readiness explicit rather than inferred from listings ([#106](https://github.com/FSQ-lab/amkernel/issues/106)).

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

# Changelog

All notable changes to AMKernel are recorded here. Public releases use semantic `0.MINOR.PATCH` versions under the pre-1.0 policy in `docs/development.md`.

## [Unreleased]

### Breaking

- Replace the Stage 1 execution result with the exact Stage 2 `python_exec` schema and private protocol v2. Callers must consume bounded output metadata, displays, artifacts, and the expanded runtime diagnostics from the new shape; no compatibility alias is retained.

### Added

- Stream output from byte one into bounded previews and recoverable stdout/stderr artifacts, with optional rate-limited MCP progress and explicit hard output-limit intervention.
- Add strict JSON display, fully decoded PNG/JPEG/GIF/WebP display, explicit artifact, requested-package diagnostics, and descriptor-rooted `read`, `write`, and `env` helpers.
- Add process-scoped Artifact Store resources with raw or manifest/part recovery, digest verification, whole-bundle quota eviction, tamper detection, and identity-safe cleanup refusal.
- Extend clean-wheel official-client evidence across CPython 3.11–3.13 on hosted Ubuntu and macOS; CI retains each job's exact wheel hash, dependency set, interpreter/OS identity, scenario output, and lockfile.
- Install one uv-managed user Runtime, one project-local `amkernel` Agent Skill, and native OMP, Pi, or Codex project MCP configuration through `amkernel install`.

### Changed

- Unify deadline, cancellation, output-limit, Runner death, Store failure, reset, shutdown, and terminal result-construction ordering under the Runtime lifecycle authority.
- Lock Pillow as the cross-platform raster decoder. CPython 3.11–3.13 on current GitHub-hosted Ubuntu and macOS remain the only supported environment claim; CPython 3.14 and Windows remain unsupported.
- Document ephemeral resource retention: clients must read and verify every manifest part before another large-output call or server shutdown.
- Replace the implementation-centered `appium-python` and interim `amkernel-appium` entries with the packaged, user-centered `amkernel` skill. The skill prioritizes verified official Appium guidance, leaves contextual judgment to the LLM, adds only AMKernel-specific knowledge, and is installed with the Runtime's project activation instead of a separate skill command.

### Security

- Workspace helpers traverse from pinned descriptors without following symlinks, and Artifact Store reads revalidate identity and content digests.
- AMKernel remains unrestricted same-user local code execution, not a sandbox. Random resource identifiers do not provide confidentiality or integrity against another same-user process.

Governed by [ADR-0006](docs/decisions/0006-stage-2-output-and-artifact-contract.md), the [Stage 2 implementation plan](docs/stage-2-implementation-plan.md), and [S2-090](https://github.com/FSQ-lab/amkernel/issues/51).

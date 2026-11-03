# ADR-0007: Global Runtime and Project Activation

- Status: Accepted
- Date: 2026-10-31
- Deciders: Project owner; Contract and Integration Lead
- Supersedes: None
- Related: [`../architecture.md`](../architecture.md), [ADR-0001](0001-stage-1-implementation-stack.md), [ADR-0005](0005-stage-1-runtime-lifecycle.md), [Issue #88](https://github.com/FSQ-lab/amkernel/issues/88)

## Context

AMKernel needs one novice-facing installation and activation model before it can be distributed as a product. The Stage 1 package currently runs its Runner with the exact Python executable that launched the MCP Server. Installing a separate copy into every project duplicates the Runtime and exposes Python environment decisions to users. Installing into system Python creates permission and dependency conflicts. A global daemon would share lifecycle and state across projects, contradicting the one-Server/one-Runner ownership model.

Coding Agents also discover instructions and MCP servers at different scopes. The open Agent Skills path is project-local, and each supported Agent has a native project MCP configuration. Prompt-based setup and direct CLI setup must not implement different state transitions.

## Decision

### Product and scope

AMKernel is a local automation Runtime exposed to Coding Agents through MCP. It is installed once per user in an isolated environment managed by `uv`. The Runtime and automation Python libraries use that environment's interpreter. Stage 1 does not select or mutate project `.venv` environments.

The installed executable is shared, but every project MCP attachment starts an independent AMKernel Server, Runner process group, Python namespace, and artifact lifecycle. No global daemon or cross-project kernel exists.

### Project activation

A project activation contains:

- one copied Skill at `.agents/skills/amkernel`;
- every official Skill selected by the pinned manifest under `.agents/skills/<name>`;
- the complete pinned Appium Skills source tree at `.agents/vendor/appium-skills/<commit>`;
- one idempotent AMKernel entry in the selected Agent's native project MCP configuration;
- the canonical project path as the MCP process working directory.

The official source is distributed as a wheel resource archive with a pinned sha256, repository, and commit. Activation verifies the archive digest and every member hash before extracting it, then writes a project receipt and exact per-file ownership. Receipt identity is not trusted alone: status and the packaged verifier must also match every source and Skill hash against the trusted manifest. The verifier requires that managed receipt and binds its runtime version to the installed main Skill metadata; a missing or drifted receipt fails closed and is repaired by the installer. Legacy checkouts are adopted only by exact-content reinstall, not by a second provenance backend. The installer does not require a git checkout or network access.

Project activation never installs Appium, starts external services, or creates automation sessions. Ambiguous Agent detection does not modify multiple clients.

### Installer

`uv` is the only initial bootstrap and installation backend. The direct entry is:

```text
uvx --from amkernel amkernel install
```

A prompt-based installation discloses changes, obtains consent, and calls the same CLI. The CLI is the sole installation implementation.

The lifecycle interface is:

```text
amkernel install
amkernel status
amkernel update
amkernel uninstall
amkernel uninstall --global
```

`install` repairs the user-level Runtime and activates the current project. A fresh managed Runtime installs a compatible official Appium Python SDK selected at install time; it does not invent a narrower or older-SDK-incompatible constraint. `status` is read-only. `update` is explicit, updates the global Runtime and current project integration, and discloses the cross-project Runtime impact. Plain `uninstall` removes only the current project Skill and MCP entry. `uninstall --global` requires explicit confirmation, removes the user-level Runtime, reports known project references, and does not delete project files or external automation resources.

Human output and bounded JSON output describe paths, versions, changes, restart requirements, and failures without credentials. Noninteractive mutation requires explicit client, project scope, consent, and JSON options.

### Initial client and platform boundary

Small adapters own project configuration for OMP, Pi, Codex, and GitHub Copilot. OMP, Pi, and Copilot use JSON project configuration; Codex uses TOML. Copilot discovers Skills from the shared `.agents/skills` path, so activation does not create a second Skill copy. Copilot applies exactly one project MCP file at a time with whole-file precedence: the adapter uses an existing `.mcp.json`, otherwise an existing `.github/mcp.json`, otherwise it creates `.mcp.json`. It preserves every unrelated entry in the selected file, never creates both files or migrates between them, and leaves the inactive file untouched when both exist. Status verifies only the active file rather than claiming an inactive entry is loaded. Copilot also requires explicit folder trust before project MCP servers load, so status and human output carry a trust notice rather than claiming readiness. The Runtime remains subject to the native platform evidence and support policy; distribution does not broaden Stage 1 support claims.

## Consequences

### Positive

- A user installs one Runtime and activates only chosen projects.
- Prompt and CLI setup converge on one idempotent implementation.
- System Python and project dependency files remain untouched.
- Project kernels retain independent ownership and truthful cleanup.
- One `amkernel` Skill becomes the stable user-facing interface; automation verticals remain internal routes.

### Costs and constraints

- Global Runtime updates affect every activated project and require explicit disclosure.
- Automation Python dependencies share one initial managed environment and may eventually require profiles.
- The installer must maintain client-specific project configuration adapters.
- A copied project Skill can be older than the Runtime; status and update must report and repair version drift.
- Project interpreter selection, alternative package managers, standalone binaries, and global daemons remain unsupported.

## Alternatives considered

### Install AMKernel into every project `.venv`

Rejected for the initial product. It duplicates the Runtime, mutates project environments, and exposes package management to nontechnical users.

### Install into system Python

Rejected. It creates permission, dependency, and externally-managed-environment failures.

### Run the Runtime only through `uvx`

Rejected as the steady-state MCP command. Bootstrap may use `uvx`, but project MCP activation requires one persistent user-level installation and stable executable.

### Global MCP configuration or daemon

Rejected. It activates unselected projects and obscures independent process, namespace, cwd, and cleanup ownership.

### Separate prompt and CLI installers

Rejected. Two implementations drift in paths, consent, idempotency, and failure recovery.

## Verification

1. A clean supported host installs through the direct CLI and through an Agent prompt that invokes the same CLI.
2. Repeated installation leaves one unchanged Skill and one MCP entry.
3. Two projects use the same installed executable but distinct Server, Runner, namespace, cwd, and lifecycle state.
4. Ambiguous client detection performs no mutation.
5. Status is read-only and reports Runtime, Skill, MCP, version, provenance, content verification, and restart state.
6. Update discloses global impact and repairs the current project integration.
7. Project uninstall leaves the global Runtime and other projects usable, removing only files whose recorded hashes still match.
8. Global uninstall requires explicit confirmation, removes only managed global resources, and reports remaining project references.
9. A clean external project installs from the pinned archive without a source checkout or network fetch.
10. Modified or unowned official files survive uninstall; a failed activation restores prior files and removes only directories it created.
11. Focused adapter, transaction, output-bound, and end-to-end tests pass on every claimed platform.

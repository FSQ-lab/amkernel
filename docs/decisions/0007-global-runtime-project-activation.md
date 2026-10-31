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
- one idempotent AMKernel entry in the selected Agent's native project MCP configuration;
- the canonical project path as the MCP process working directory.

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

`install` repairs the user-level Runtime and activates the current project. `status` is read-only. `update` is explicit, updates the global Runtime and current project integration, and discloses the cross-project Runtime impact. Plain `uninstall` removes only the current project Skill and MCP entry. `uninstall --global` requires explicit confirmation, removes the user-level Runtime, reports known project references, and does not delete project files or external automation resources.

Human output and bounded JSON output describe paths, versions, changes, restart requirements, and failures without credentials. Noninteractive mutation requires explicit client, project scope, consent, and JSON options.

### Initial client and platform boundary

Small adapters own project configuration for OMP, Pi, and Codex. The standard Skill path is shared. The Runtime remains subject to the native platform evidence and support policy; distribution does not broaden Stage 1 support claims.

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
5. Status is read-only and reports Runtime, Skill, MCP, version, and restart state.
6. Update discloses global impact and repairs the current project integration.
7. Project uninstall leaves the global Runtime and other projects usable.
8. Global uninstall requires explicit confirmation, removes only managed global resources, and reports remaining project references.
9. Focused adapter, transaction, output-bound, and end-to-end tests pass on every claimed platform.

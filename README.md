# AMKernel

**Automation MCP Kernel**

> Persistent Python execution for agentic automation.

AMKernel is an exploration project that gives Coding Agents a persistent local Python execution environment through MCP. Agents can use ordinary Python automation libraries while keeping live objects, imports, and state across tool calls.

```text
Coding Agent
  → MCP
  → persistent Python kernel
  → automation library
  → external system
```

The first experimental vertical is mobile automation through Appium:

```text
Coding Agent
  → AMKernel
  → Appium Python Client
  → Appium Server
  → XCUITest / UiAutomator2
  → mobile device
```

Future experiments may apply the same kernel to Playwright, Selenium, pywinauto, PyAutoGUI, macOS Accessibility, and other Python automation ecosystems. Those platforms do not belong in the core until experiments establish shared requirements.

## Project principles

- Python execution is the primary Agent interface.
- State persists across MCP calls.
- The Agent uses official automation libraries directly.
- The kernel reports truthful execution and survival state.
- Text, structured values, images, and large artifacts are first-class outputs.
- Platform knowledge starts in project skills and experiments, not core abstractions.
- AMKernel is local stdio code execution first, not a remote multi-tenant sandbox.
- The core grows from measured experimental needs, not hypothetical platform unification.

## Current phase

This repository begins design-first. The earlier runtime spike remains outside this project and is not treated as production scaffolding.

Canonical documents:

- [`docs/architecture.md`](docs/architecture.md) — generic AMKernel core architecture.
- [`docs/development.md`](docs/development.md) — agent roles, change ownership, development workflow, and quality gates.
- [`docs/project-management.md`](docs/project-management.md) — GitHub-backed workflow, Kanban semantics, task contracts, ADR, and risk governance.
- [GitHub Project](https://github.com/orgs/FSQ-lab/projects/2) — canonical milestone, workflow state, stage, type, priority, and queue.
- [GitHub Issues](https://github.com/FSQ-lab/amkernel/issues) — canonical work-item, dependency, blocker, risk, and verification records.
- [`docs/decisions/`](docs/decisions/) — accepted architecture and implementation decisions.
- [`docs/experiments/mobile-appium.md`](docs/experiments/mobile-appium.md) — first Appium/mobile experiment and success criteria.

Implementation starts only from interfaces and invariants accepted in these documents.

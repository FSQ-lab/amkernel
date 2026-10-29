# AMKernel

**AMKernel — Automation MCP Kernel**

> Persistent Python execution for agentic automation.
>
> 面向 Agent 自动化的持久 Python Execution MCP。

AMKernel is a persistent Python execution MCP for agentic automation. Mobile automation through Appium is its first experimental vertical.

AMKernel 是一个面向 Agent 自动化的持久 Python Execution MCP。基于 Appium 的移动自动化是它的第一个实验方向。

Agents use ordinary Python automation libraries while retaining live objects, imports, and state across tool calls.

## Why the name

- **Automation** — Appium, Playwright, Windows, macOS, and other automation environments. / Appium、Playwright、Windows、macOS 等自动化场景。
- **MCP** — the standard interface that attaches AMKernel to different Coding Agents. / 挂载到不同 Coding Agent 的标准接口。
- **Kernel** — a persistent Python namespace with object reuse, incremental execution, and interrupt recovery. / 持久 Python namespace、对象复用、增量执行和中断恢复。

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

Stage 1 execution correctness is active. The reproducible package/toolchain, protected CI, private protocol, persistent Runner, POSIX Kernel Supervisor, and serialized Runtime Manager are implemented and native-tested; public MCP execution wiring follows the accepted plan. No Python execution behavior is public until the MCP Adapter is integrated. The earlier runtime spike remains outside this project and is not production scaffolding.

Canonical documents:

- [`docs/architecture.md`](docs/architecture.md) — generic AMKernel core architecture.
- [`docs/development.md`](docs/development.md) — agent roles, change ownership, development workflow, and quality gates.
- [`docs/stage-1-implementation-plan.md`](docs/stage-1-implementation-plan.md) — accepted Stage 1 contracts, dependency order, ownership, behavior scenarios, and risk traceability.
- [`docs/project-management.md`](docs/project-management.md) — GitHub-backed workflow, Kanban semantics, task contracts, ADR, and risk governance.
- [GitHub Project](https://github.com/orgs/FSQ-lab/projects/2) — canonical milestone, status, stage, type, priority, and queue.
- [GitHub Issues](https://github.com/FSQ-lab/amkernel/issues) — canonical work-item, dependency, blocker, risk, and verification records.
- [`docs/decisions/`](docs/decisions/) — accepted architecture and implementation decisions.
- [`docs/experiments/mobile-appium.md`](docs/experiments/mobile-appium.md) — first Appium/mobile experiment and success criteria.

Implementation follows the interfaces, invariants, and delivery order accepted in these documents.

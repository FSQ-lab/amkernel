# AMKernel — Automation MCP Kernel

> Persistent Python execution for agentic automation.
>
> 面向 Agent 自动化的持久 Python Execution MCP。

AMKernel is a persistent Python execution MCP for agentic automation. Mobile automation through Appium is its first experimental vertical.

AMKernel 是一个面向 Agent 自动化的持久 Python Execution MCP。基于 Appium 的移动自动化是它的第一个实验方向。

The name encodes the product boundary:

- **Automation** — Appium, Playwright, Windows, macOS, and other automation environments.
- **MCP** — the standard interface that attaches AMKernel to different Coding Agents.
- **Kernel** — a persistent Python namespace with object reuse, incremental execution, and interrupt recovery.

Before changing architecture or implementation, read:

@../docs/architecture.md
@../docs/development.md
@../docs/project-management.md
@../docs/decisions/README.md
@../docs/decisions/0001-stage-1-implementation-stack.md
@../docs/decisions/0002-github-project-management.md
@../docs/decisions/0003-stage-1-execution-contract.md
@../docs/decisions/0004-stage-1-runner-protocol.md
@../docs/decisions/0005-stage-1-runtime-lifecycle.md
@../docs/stage-1-implementation-plan.md

@../docs/experiments/mobile-appium.md

Before starting work, inspect the active item in https://github.com/orgs/FSQ-lab/projects/2 and its linked repository Issue. GitHub is the sole source for live status, dependencies, blockers, risks, and queue order.

Ready and unblocked work advances continuously in GitHub Project order without per-task owner approval. Pause only for an unreachable external prerequisite or an unresolved decision with materially different product, architecture, security, or support tradeoffs; required quality gates and independent review still apply.

Keep the core automation-neutral. Platform-specific procedures begin in skills, experiments, and integration tests until evidence from multiple verticals justifies moving behavior into the kernel.

The repository is design-first. Do not treat code from the earlier sibling `omp` spike as production scaffolding; reuse only mechanisms that are justified by the accepted architecture and covered by focused tests.

# AMKernel project context

AMKernel is a persistent Python execution MCP for agentic automation. Mobile/Appium is the first experimental vertical, not a platform-specific boundary around the core.

Before changing architecture or implementation, read:

@../docs/architecture.md
@../docs/development.md
@../docs/project-management.md
@../docs/decisions/README.md
@../docs/decisions/0001-stage-1-implementation-stack.md
@../docs/decisions/0002-github-project-management.md

@../docs/experiments/mobile-appium.md

Before starting work, inspect the active item in https://github.com/orgs/FSQ-lab/projects/2 and its linked repository Issue. GitHub is the sole source for live status, dependencies, blockers, risks, and queue order.

Keep the core automation-neutral. Platform-specific procedures begin in skills, experiments, and integration tests until evidence from multiple verticals justifies moving behavior into the kernel.

The repository is design-first. Do not treat code from the earlier sibling `omp` spike as production scaffolding; reuse only mechanisms that are justified by the accepted architecture and covered by focused tests.

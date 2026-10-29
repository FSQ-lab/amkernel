# AMKernel — Automation MCP Kernel

> Persistent Python execution for agentic automation.

AMKernel exposes one persistent local Python kernel to Coding Agents through a stdio MCP server. Stage 1 execution correctness is the completed implementation baseline; the core remains automation-neutral.

## Non-negotiable invariants

- Report kernel survival truthfully; never recreate a dead kernel implicitly.
- Keep MCP transport, private Runner control, diagnostics, and user output isolated.
- Serialize one persistent namespace; reset is destructive process replacement.
- Clean only managed process-group resources and never overclaim external cleanup.
- Treat AMKernel as unrestricted local same-user execution, not a sandbox.
- Do not add Stage 2 output/artifact behavior or platform-specific wrappers unless the active Project item explicitly owns that scope.

## Sources of truth

Durable contracts live in `docs/architecture.md`, `docs/development.md`, accepted records under `docs/decisions/`, and `docs/stage-1-implementation-plan.md`. GitHub Project #2 and linked Issues are the sole live sources for status, dependencies, blockers, risks, and queue order. `docs/HANDOFF.md` records current implementation state.

Before architecture, implementation, verification, or project-status changes:

1. inspect the active GitHub Project item and linked Issue;
2. read `docs/HANDOFF.md` and only the architecture, development, plan, and accepted ADR sections relevant to that item;
3. run the focused behavioral check for the changed contract and obtain independent review for load-bearing behavior.

For configuration advice and other questions that do not change repository behavior or project status, do not fetch GitHub state or load implementation contracts unless the answer requires them.

Ready and unblocked work advances continuously in GitHub Project order without per-task owner approval. Pause only for an unreachable external prerequisite or an unresolved decision with materially different product, architecture, security, or support tradeoffs.

Keep platform procedures in skills, experiments, and integration tests until evidence from multiple verticals justifies core behavior. Do not use the earlier sibling `omp` spike as production scaffolding; reuse only justified mechanisms covered by focused tests.

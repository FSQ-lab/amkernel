# ADR-0001: Stage 1 Implementation Stack

- Status: Accepted
- Date: 2026-10-28
- Deciders: Project owner; Contract and Integration Lead
- Supersedes: None
- Related: [`../architecture.md`](../architecture.md), [`../development.md`](../development.md), [ADR-0002](0002-github-project-management.md), [S1-010](https://github.com/FSQ-lab/amkernel/issues/6)

## Context

AMKernel exposes persistent Python execution through MCP. The Runner must execute real Python in an isolated subprocess, while the MCP Adapter and Runtime/Supervisor coordinate requests, lifecycle, timeouts, and state truth.

The accepted architecture deliberately did not select the host implementation language. The discarded spike used a TypeScript MCP host and a Python runner, but it was evidence rather than production scaffolding. Keeping that split would impose two production languages, two dependency graphs, cross-language model duplication, and two build/test toolchains without an established product requirement.

The official MCP Python SDK is maintained by the Model Context Protocol project. Its current package is `mcp`, it supports servers and clients including stdio, and its published project metadata requires Python 3.11 or newer. The development workstation already provides Python 3.11 and uv, but repository metadata and the lockfile—not workstation state—will define reproducibility.

## Decision

### Language and process model

All Stage 1 production code will use Python:

- MCP Adapter;
- Runtime Manager;
- Python Kernel Supervisor;
- private protocol types and codecs;
- Runner;
- command-line entry point.

The host and Runner remain separate operating-system processes. A single language does not weaken protocol isolation, timeout escalation, crash detection, or hostile stdout/stderr containment.

The official SDK imposes a Python 3.11 floor. AMKernel does not yet publish a `requires-python` compatibility range: dependency acceptance is not AMKernel lifecycle evidence. S1-001 defines the initial test matrix, S1-080 independently records the passing contiguous range, and S1-085 applies that reviewer-approved compatibility metadata under the Integration Lead's shared-configuration ownership.

### MCP implementation

Use the official MCP Python SDK from the `mcp` distribution. Runtime dependencies use the plain SDK unless an observed requirement justifies an extra; the `mcp[cli]` development convenience extra is not a production requirement.

AMKernel will use SDK transport and protocol behavior rather than implementing MCP JSON-RPC by hand. AMKernel's private host/Runner protocol remains project-owned and independent from MCP.

### Project and packaging toolchain

Use:

- `uv` as the canonical environment, dependency, lockfile, and command runner;
- one PEP 621 `pyproject.toml` as project metadata and tool configuration;
- a committed `uv.lock` for deterministic development and CI resolution;
- a packaged `src/amkernel/` layout;
- `uv_build` as the initial pure-Python build backend;
- an `amkernel` console entry point for the stdio server;
- Ruff for formatting and linting;
- mypy in strict mode for static type checking;
- pytest for focused behavior and real-process integration tests;
- coverage reporting without an arbitrary percentage gate until a meaningful baseline exists.

The canonical quality commands established by S1-010 will be equivalent to:

```text
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

CI must call repository-defined commands rather than reimplementing their logic in workflow YAML.

### Dependency policy

Direct runtime and development dependencies are declared in `pyproject.toml`; resolved versions and hashes are committed in `uv.lock`. Runtime code may not depend on tools that exist only in the development group.

Dependency additions require an observable need in the active delivery stage. Platform automation packages such as Appium, Playwright, or Selenium do not enter the Stage 1 core dependency set.

## Consequences

### Positive

- One production language and one project toolchain.
- Host, protocol, result, and test types can be shared without cross-language duplication.
- The project can exercise both MCP server and real stdio client through the same official SDK.
- Python environment and interpreter diagnostics remain native to the implementation domain.
- Contributors can reproduce the package and gates from `pyproject.toml` and `uv.lock`.

### Costs and constraints

- Process boundaries remain mandatory; an in-process `exec` implementation is not acceptable.
- Python signal and process-tree behavior still differs by operating system and requires platform evidence.
- A synchronous or blocking Runner operation must not block MCP request orchestration in the host.
- The official SDK is an external dependency whose API and protocol-version changes must be reviewed and locked deliberately.
- Selecting Python for the host does not make arbitrary executed Python safe or sandboxed.

## Alternatives considered

### TypeScript MCP host with Python Runner

Rejected for Stage 1. It repeats the discarded spike's dual-language boundary, requires duplicated result/protocol models, and adds Node packaging without evidence that the TypeScript SDK provides a required capability unavailable from the official Python SDK.

### Hand-written MCP JSON-RPC in Python

Rejected. The project explicitly requires official SDK behavior; custom JSON-RPC would create protocol maintenance and conformance risk without differentiating AMKernel.

### In-process Python execution

Rejected. It cannot provide the required protocol isolation, reliable escalation to hard kill, truthful dead-kernel state, or controlled replacement of a destroyed namespace.

### `pip` and requirements files as the canonical development workflow

Rejected as the canonical project workflow because they do not by themselves provide the selected lock and command model. Built distributions may still be installed by standards-compliant Python installers.

### Copying the sibling spike

Rejected. Individual mechanisms may inform tests or a new implementation only when justified against the architecture; the spike's file structure and TypeScript host are not inherited.

## Verification

S1-010 must prove that a fresh checkout can:

1. resolve the committed environment with `uv sync --frozen`;
2. run format, lint, strict type, and focused test commands;
3. build an sdist and wheel;
4. install the built artifact into a clean environment;
5. invoke the packaged `amkernel` entry point.

Until S1-080 records the evidence and S1-085 adds bounded `requires-python` metadata, built artifacts are internal verification artifacts and must not be published as compatible releases.

Stage 1 integration must additionally prove that the official MCP Python client can launch the packaged entry point over stdio, discover the execution tool, call it repeatedly against one kernel, observe typed failures and kernel state, and shut down cleanly.

## Sources

- Official MCP Python SDK repository: <https://github.com/modelcontextprotocol/python-sdk>
- Official MCP Python SDK documentation: <https://py.sdk.modelcontextprotocol.io/>
- SDK project metadata and Python requirement: <https://github.com/modelcontextprotocol/python-sdk/blob/main/pyproject.toml>
- uv packaged-project guidance: <https://docs.astral.sh/uv/concepts/projects/init/>

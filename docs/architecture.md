# AMKernel Core Architecture

Status: design baseline for the formal project.

## 1. Product definition

AMKernel is an Automation MCP Kernel: a persistent local Python execution environment exposed to Coding Agents through MCP.

```text
Coding Agent
  → execute Python through MCP
  → persistent Python kernel
  → official automation libraries
  → external systems
```

AMKernel does not define browser, desktop, or mobile actions. It lets the Agent use the corresponding Python ecosystems directly.

Examples of potential verticals:

```text
Appium Python Client → iOS / Android
Playwright            → browsers
Selenium              → browsers
pywinauto             → Windows UI
PyAutoGUI             → desktop input and screenshots
macOS Accessibility   → macOS UI
```

The initial mobile experiment is evidence for the core, not a permanent boundary around it.

## 2. Design thesis

The main model-facing interface is Python execution, not a growing catalog of automation tools.

A traditional tool interface constrains the Agent to one predefined operation per call. Persistent Python allows the Agent to construct a local program containing:

- imports and reusable objects;
- data transformations;
- branching and loops;
- explicit waits;
- calls into official libraries;
- project helper functions;
- structured summaries of large external state.

This moves short-horizon computation out of model context and into a local runtime while preserving the Agent’s ability to inspect results and choose the next step.

The project succeeds by making this execution path reliable, observable, and pleasant for Coding Agents—not by wrapping every automation library.

## 3. Scope

### Core responsibilities

- serve a local stdio MCP interface;
- own one persistent Python kernel;
- execute one Python cell per call;
- serialize calls into one namespace;
- preserve imports, variables, functions, and live objects;
- report trailing expression values;
- stream and retain stdout/stderr;
- capture structured values and images;
- spill large output into recoverable artifacts;
- resolve a predictable project Python environment;
- interrupt timed-out code and report whether the kernel survived;
- reset or shut down without leaving managed descendants;
- expose exact interpreter, execution count, duration, and kernel state;
- provide concise model-facing usage guidance.

### Explicit non-goals for the first project phase

- platform-specific action tools;
- wrappers replacing official automation libraries;
- multiple kernels in one MCP process;
- distributed or remote execution;
- multi-tenant isolation;
- a workflow language or test framework;
- device, browser, or desktop farms;
- long-term memory;
- automatic unification of different automation platforms;
- autonomous installation of arbitrary dependencies;
- a security claim stronger than local same-user code execution.

## 4. MCP interface

The first interface should be one deep execution tool:

```ts
type PythonExecInput = {
  code: string;
  title?: string;
  timeout?: number;
  reset?: boolean;
};
```

### Semantics

- `code` is one Python cell.
- The kernel namespace survives later calls.
- `title` is presentation metadata and does not affect execution.
- `timeout` bounds active cell work.
- `reset` replaces the Python kernel before executing this cell.
- Calls are exclusive within one MCP process.
- A failed cell does not automatically destroy the kernel.
- Mutations completed before an exception may remain in memory.

### Why there is no runtime ID initially

The initial lifecycle is already scoped:

```text
one Coding Agent MCP attachment
=
one stdio server process
=
one persistent Python kernel
```

A runtime registry would enlarge the interface before the project has evidence that one Agent must control multiple concurrent kernels. The mobile experiment begins with one active automation context. Later platform experiments can test whether this assumption holds.

## 5. Execution result

The result must be useful to a model without requiring it to parse terminal decoration.

```ts
type PythonExecResult = {
  status: "completed" | "failed" | "timed_out" | "kernel_killed";
  stdout: string;
  stderr: string;
  result?: unknown;
  error?: {
    type: string;
    message: string;
    traceback: string[];
  };
  executionCount: number;
  durationMs: number;
  kernelState: "alive" | "dead";
  output: {
    totalBytes: number;
    totalLines: number;
    truncated: boolean;
    artifact?: ArtifactRef;
  };
  artifacts: ArtifactRef[];
};
```

The central invariant is state truth. After every call, the Agent must know whether objects from earlier cells can still be used.

## 6. Persistent kernel semantics

### 6.1 Namespace

Each call executes in the same user namespace until reset or process shutdown.

```python
client = create_client()
```

A later call can use `client` without recreating it.

Definitions and mutations before an exception remain, as they would in a normal Python interpreter. The runtime never promises transactional rollback.

### 6.2 Trailing expression

The final expression is evaluated separately and returned:

```python
{
    "type": type(client).__name__,
    "ready": client.is_ready(),
}
```

JSON-compatible values become structured MCP content. Other values receive a safe, bounded representation.

### 6.3 Reset

Reset is destructive to Python memory. It must:

1. stop the previous kernel and managed descendants;
2. report cleanup failures;
3. start a new kernel with the same project configuration;
4. load the standard prelude;
5. execute the supplied cell.

External resources created by arbitrary user code may outlive the kernel. AMKernel may track resources created through optional helpers, but it cannot guarantee discovery of every external session or child process created by unrestricted Python.

### 6.4 Cancellation and timeout

A timeout uses the least destructive mechanism first:

```text
deadline
→ SIGINT / equivalent interrupt
→ grace period
→ graceful termination
→ final hard kill
```

If Python handles the interrupt, the result is:

```json
{
  "status": "timed_out",
  "kernelState": "alive"
}
```

If escalation destroys the process:

```json
{
  "status": "kernel_killed",
  "kernelState": "dead"
}
```

The implementation must test blocking Python code, subprocesses, native extensions, and operating-system differences.

### 6.5 Input

Interactive `input()` is unsupported initially. User stdin cannot share a control channel with the runner protocol. Agents pass data through generated code, files, environment helpers, or subsequent MCP calls.

### 6.6 Concurrency

Only one cell executes at a time in one kernel. Calls queue in arrival order or fail explicitly when the host requests non-blocking behavior. Two cells must never race mutations in the same namespace.

## 7. Runner protocol

The Python runner is a subprocess controlled by the MCP host. Its private protocol is independent from MCP JSON-RPC.

```text
MCP transport stdin/stdout     Client ↔ MCP server
runner request channel         MCP host → Python runner
runner frame channel           Python runner → MCP host
user stdout/stderr             captured execution streams
```

User code and inherited subprocesses must not be able to corrupt protocol frames by printing JSON-looking lines.

Every request/frame includes a correlation ID. The protocol supports at least:

```text
Host → Runner
  initialize
  execute
  reset-related initialization
  shutdown

Runner → Host
  ready
  started
  stdout
  stderr
  display
  artifact
  error
  done
```

The protocol is versioned before external compatibility matters. Host and runner ship together; compatibility across arbitrary versions is not required initially, but version mismatches must fail clearly.

## 8. Output system

### 8.1 Streaming text

Requirements:

- stream stdout and stderr while execution is active when supported by the MCP host;
- preserve valid UTF-8 boundaries;
- retain a bounded live tail;
- count complete bytes and lines;
- avoid unbounded memory use;
- make full recoverable output available through artifacts when limits are exceeded;
- distinguish user stderr from runner diagnostics.

### 8.2 Structured display

The prelude provides an explicit display path for JSON-compatible objects:

```python
display({
    "status": "ready",
    "items": results,
})
```

Structured values remain typed in the MCP result. Text rendering is a secondary representation for clients that do not expose structured content.

### 8.3 Images

Automation frequently produces screenshots. Images are first-class execution outputs:

```python
display(image_bytes, mime_type="image/png")
```

The result may include both an MCP image block and an artifact reference. Metadata includes MIME type, dimensions when detectable, size, and hash.

Common Python image objects can be supported through explicit display hooks without making a specific image library mandatory.

### 8.4 Artifacts

```ts
type ArtifactRef = {
  uri: string;
  mimeType: string;
  size: number;
  sha256: string;
};
```

Artifacts support:

- long stdout/stderr;
- screenshots;
- page sources and DOM dumps;
- videos;
- traces;
- logs;
- reports;
- arbitrary files explicitly exported by the cell.

Artifact storage is scoped to one MCP process. Model-facing results contain bounded previews and resource references rather than silently losing omitted bytes. Resource URIs remain valid only while their whole bundle is retained; capacity pressure, eviction, tamper detection, or server shutdown can revoke them. Artifacts above one resource part use a manifest whose bounded parts must all be read, hash-verified, and concatenated before another large-output call. Random resource identifiers do not protect Store files from unrestricted same-user code, and every read revalidates the stored bytes.

## 9. Python environment

Interpreter resolution should be deterministic and reported to the Agent. Initial priority:

1. explicit project/runtime configuration;
2. project virtual environment;
3. active virtual environment;
4. managed environment if introduced later;
5. compatible Python on `PATH`.

The runtime reports:

- resolved executable;
- Python version;
- working directory;
- environment kind;
- relevant package versions on request.

Environment variables use an allowlist. Common model/provider credentials are excluded. Project-specific credentials are not injected implicitly.

AMKernel does not claim to sandbox Python. Generated code runs with the permissions of the local user that launched the MCP server.

## 10. Prelude

The standard prelude should remain small and automation-neutral:

```python
display(value, ...)
artifact(name, content, mime_type=None)
read(path, ...)
write(path, content)
env(key=None, value=None)
```

Potential additional helpers must earn their place across experiments. Platform-specific connection, action, selector, or test helpers begin in skills and project code.

The prelude must not shadow common user names unnecessarily or make ordinary Python imports behave differently.

## 11. Skills and experiments

Platform knowledge belongs outside the core until repeated experiments reveal shared runtime requirements.

Initial skill:

```text
appium-python
```

Possible future skills:

```text
playwright-python
windows-automation
macos-automation
```

A skill can guide the Agent through setup, external process lifecycle, library usage, waits, large-output reduction, debugging, and cleanup. A skill is procedural knowledge, not an executable capability or security mechanism.

Each experiment produces evidence about the kernel:

- which live objects need persistence;
- which outputs are too large;
- which image formats matter;
- how timeouts behave;
- which external resources become orphaned;
- whether one kernel is sufficient;
- what belongs in the universal prelude.

Only cross-experiment evidence should deepen the core.

## 12. Security posture

Initial security statement:

> AMKernel is a local same-user Python execution MCP, not a sandbox.

Required safeguards:

- stdio transport by default;
- visible code in tool calls;
- host-controlled approval policy;
- workspace confinement for helper file operations;
- environment-variable filtering;
- output, artifact, time, and process limits;
- child-process cleanup where ownership is known;
- no network listener in the default configuration;
- no automatic privilege elevation;
- no remote multi-user mode.

Remote transport or untrusted code execution requires a separate threat model and isolation design.

## 13. Module ownership

Target conceptual modules:

```text
MCP Adapter
  validates calls and converts execution results to MCP content

Runtime Manager
  owns one kernel, serialization, reset, and shutdown

Python Kernel Supervisor
  spawns the interpreter and controls cancellation/escalation

Runner
  owns the persistent namespace and cell evaluation

Output Pipeline
  streams, counts, truncates, and spills output

Artifact Store
  persists recoverable large/binary outputs

Prelude
  injects small automation-neutral helpers
```

Platform experiments and skills consume these modules but do not modify their responsibilities without demonstrated need.

## 14. Current implementation stance

The repository implements the Stage 2 automation-neutral core through one packaged stdio MCP server. The public surface remains one `python_exec` tool; private Runner frames, Runtime lifecycle authority, output aggregation, Artifact Store retention, resource reads, and MCP content mapping stay isolated behind their module interfaces.

The earlier spike proved selected mechanics but was not copied as production scaffolding. Implemented behavior is defended through focused module tests, real Runner/Supervisor/Runtime integration tests, and an installed-wheel scenario that launches the installed entry point through the official MCP client.

## 15. Delivery stages

### Stage 1: execution correctness — delivered

- one-tool MCP surface;
- stable execution-result shape and truthful kernel survival;
- persistent namespace, trailing expressions, and typed errors;
- isolated completion-time stream capture;
- reset, shutdown, timeout escalation, and managed-process cleanup;
- explicit interpreter and working-directory identity.

### Stage 2: Agent-quality output — delivered

- bounded live stdout/stderr progress with authoritative terminal results;
- strict structured JSON and fully decoded PNG/JPEG/GIF/WebP displays;
- recoverable stream spill and explicit artifacts through ephemeral MCP resources;
- bounded previews, item/result/store quotas, whole-bundle eviction, and tamper detection;
- descriptor-rooted workspace helpers and requested-package diagnostics;
- explicit output-limit, Store, cleanup, and result-construction failure semantics.

### Stage 3: mobile/Appium experiment

Defined in [`experiments/mobile-appium.md`](experiments/mobile-appium.md).

### Stage 4: cross-client evidence

- attach to representative Coding Agent hosts;
- measure tool clarity and context use;
- harden process behavior across supported operating systems;
- decide whether another automation vertical should be explored.

## 16. Success criteria

AMKernel core succeeds when a Coding Agent can:

1. attach a local MCP server;
2. execute Python incrementally;
3. retain complex live library objects across calls;
4. recover from ordinary cell errors;
5. distinguish surviving and destroyed kernels after timeout;
6. receive compact text, structured values, images, and recoverable artifacts;
7. use project automation libraries without AMKernel wrapping them;
8. shut down without known managed process leaks;
9. understand the runtime from a concise tool description;
10. apply the same core to more than one automation vertical without adding platform semantics to the kernel.

## 17. Open questions for experiments

- Does one kernel per MCP process remain sufficient in real Coding Agent workflows?
- Which output/progress features are portable across target MCP clients?
- How should process-tree interruption work consistently across operating systems?
- Which external-session cleanup hooks are genuinely cross-platform?
- How much package/environment provisioning belongs in the core?
- Which display protocols cover the important automation libraries without dependency-specific code?

These questions are resolved with focused experiments, not speculative abstraction.

## References

- [MCP tools](https://modelcontextprotocol.io/specification/latest/server/tools)
- [MCP resources](https://modelcontextprotocol.io/specification/latest/server/resources)
- [MCP Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview)

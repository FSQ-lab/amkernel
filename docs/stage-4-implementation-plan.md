# Stage 4 Cross-Client Evidence Implementation Plan

Status: active implementation contract for milestone `M4 — Cross-client evidence`.

Stage 4 validates the installed AMKernel interface through representative Coding Agent hosts. It does not add client-specific production behavior. GitHub Project #2 and Issues #78, #81, #80, #79, and #77 remain the live sources for order, ownership, blockers, and review state.

## 1. Governing constraints

- Preserve every invariant in `architecture.md`, ADR-0003, ADR-0004, and ADR-0006.
- Exercise a clean installed wheel only through the public stdio MCP interface.
- Use the same frozen scenario for every Coding Agent client. Client adapters may configure or launch a client; they may not change scenario semantics.
- AMKernel remains unrestricted local same-user execution, not a sandbox.
- Record kernel, process, resource, and cleanup state truthfully. Clean only managed resources.
- Do not modify persistent client configuration. Every client run uses an isolated temporary configuration or a per-invocation additional MCP configuration.
- Do not retain credentials, unrestricted model prose, absolute home paths, or raw chain-of-thought. Evidence retains bounded normalized tool events and measurements only.
- Exact client, model, operating-system, Python, AMKernel revision, wheel, scenario, schema, and runner identities are mandatory.
- A client or operating-system discrepancy blocks graduation. It never becomes a special case in the shared contract.

## 2. Active milestone

### Entry criteria

- Stage 3 graduated with a source-derived index and no open Blocker/Major review findings.
- At least two representative Coding Agent clients are locally available.
- The installed-wheel stdio scenario and package-smoke behavior pass before client evidence is collected.

Observed entry clients:

- Codex CLI `0.163.0`;
- GitHub Copilot CLI `1.0.105`.

Versions are observations, not durable pins. Each retained run records its actual version and must be repeated when the client changes before Stage 4 closes.

### Ordered work

| ID | Issue | Work | Depends on | Sole write ownership |
| --- | --- | --- | --- | --- |
| S4-001 | #78 | Freeze scenario, evidence schema, process matrix, and privacy contract | Stage 3 | this plan; `tests/fixtures/cross_client/**`; contract tests |
| S4-005 | #82 | Freeze one naturalistic dependency-graph challenge | S4-001 | GitHub Issue #82 only; no repository writes |
| S4-010 | #81 | Codex CLI reference run | S4-001, S4-005 | `tests/e2e/cross_client/codex.py`; `evidence/stage-4/codex/**` |
| S4-020 | #80 | GitHub Copilot CLI reference run | S4-001, S4-005 | `tests/e2e/cross_client/copilot.py`; `evidence/stage-4/copilot/**` |
| S4-030 | #79 | Linux/macOS process and cleanup matrix | S4-001 | Stage 4 workflow/process harness; `evidence/stage-4/process/**` |
| S4-040 | #77 | Source-derived index and next-vertical decision | S4-010, S4-020, S4-030 | `evidence/stage-4/index.json`; decision report; Stage 4 handoff/status |

S4-010 and S4-020 begin after S4-005 is independently accepted; S4-030 depends only on S4-001.
These items may then run concurrently because they do not share writable files.

### Two-layer client evaluation

Every client reference run executes two complementary layers. The frozen S4-001 scenario remains
the deterministic lifecycle and interface conformance gate. GitHub Issue #82 is a naturalistic,
outcome-specified dependency investigation: the client receives the same issue text and chooses its
own `python_exec` decomposition. The runner starts the client in an empty temporary workspace with
ephemeral configuration, no task-specific Skill or custom instruction, and only AMKernel enabled
where the client supports a tool allowlist. A bounded complete client event log records every tool
attempt; any non-AMKernel work-tool attempt, native repository read, or repository mutation forces
`failed`. AMKernel itself starts with the repository as its working directory. An independent oracle
verifies the graph fields, JSON artifact, and digest. The displayed PNG is retained by digest; its
embedded canonical chart-data text must equal the oracle and independent review must confirm that
the visible labels, order, and bar values represent that data. Naturalistic success never compensates
for a failed deterministic gate, and client-specific prompting or contract relaxation is prohibited.

## 3. Frozen client-neutral scenario

`tests/fixtures/cross_client/scenario.json` is the canonical machine-readable definition. Its SHA-256 identifies the scenario in every run.

The client must:

1. discover exactly one public tool, `python_exec`, and observe its complete model-facing lifecycle/security description;
2. create persistent state;
3. reuse that state in a later tool call;
4. observe an ordinary Python exception after a mutation;
5. prove that the mutation and kernel survived;
6. receive bounded stdout and stderr with exact byte accounting;
7. receive a strict structured JSON value;
8. receive a fully decoded display through MCP rich content;
9. create an artifact whose bytes stay behind an ephemeral resource URI;
10. read and hash every manifest/part resource without copying raw artifact bytes into conversation evidence;
11. observe a timed-out execution whose kernel survives;
12. prove continuation after the timeout;
13. destructively reset and prove the prior namespace is absent.

The final client response is restricted to the scenario's declared summary fields. It must not reproduce code, stdout/stderr bodies, display bytes, artifact bytes, or unrestricted reasoning.

### Outcome rules

A passed run requires every step exactly once and in order, zero clarification requests, zero wrong-tool selections, no more than two schema-retry calls, resource integrity verification, ordinary-error continuation, timeout continuation, reset isolation, and completed cleanup.

A client inability, authentication failure, unsupported MCP feature, or environment prerequisite is `blocked`, not `failed`. A scenario/tool/state/cleanup mismatch after ready preflight is `failed`. Neither state may be rewritten as `passed`.

## 4. Tool clarity and context measurements

Each run records:

- public tool count and exact selected tool name;
- client-issued AMKernel tool-call count;
- schema-retry call count;
- wrong-tool selection count;
- clarification-request count;
- normalized MCP request bytes;
- normalized MCP result bytes;
- largest normalized tool result;
- total raw resource bytes read outside conversational content;
- resource-reference bytes exposed to conversational content;
- context reduction ratio, calculated as `1 - resourceReferenceBytes / rawResourceBytes` when raw bytes are nonzero;
- bounded final-response bytes;
- per-step and whole-run duration.

Normalized byte counts use the shared `tests/e2e/cross_client_normalizer.py` implementation: compact UTF-8 JSON with sorted object keys and no client-private envelope fields. Each tool attempt records an executable-derived canonical request byte count; each final response records an executable-derived byte count and semantic digest. Resource observations retain only hashed URI identity plus scheme, MIME type, and size. Evidence records SHA-256 identities for both the declarative policy and executable normalizer.

The contract measures interface use; it does not score model intelligence. Client names are dimensions, not rankings.

## 5. Evidence and privacy contract

`tests/fixtures/cross_client/evidence.schema.json` defines one run record. Required evidence includes:

- exact client executable/version/model and invocation mode;
- host OS/release/architecture and Python version;
- AMKernel revision, wheel name/size/SHA-256, entry point, MCP protocol version, and runner protocol version;
- scenario/schema/normalizer-policy/executable-normalizer identifiers and SHA-256 digests;
- persistent-config existence and SHA-256 observations before and after, plus `persistentMutation: false`;
- an outcome-sensitive frozen step prefix: all thirteen normalized step records for `passed`, a mismatch-bearing prefix for `failed`, and no scenario steps for a preflight `blocked` run;
- clarity/context measurements;
- hash-linked bounded artifacts;
- final kernel state, server/runner exit observations, and remaining external resources;
- limitations and independent-review disposition.

Strings reject home-directory paths, bearer credentials, credential-bearing URLs, and common secret assignments. The same privacy scan and excluded-field policy apply inside retained JSON artifact payloads. Artifact paths are relative, cannot escape the evidence root, and include size and SHA-256. Each artifact is bounded to 16 MiB; the complete normalized event record is bounded to 1 MiB. Larger raw client logs are not retained.

The semantic validator additionally enforces:

- exact scenario step order/action and equality of every structured expected semantic, plus result and semantic digests;
- exact scenario/schema/normalizer-policy/executable-normalizer hashes;
- normalized-attempt and exact final-summary structure, including separately classified and measured schema retries;
- artifact existence, size, hash, root containment, multipart manifest/part integrity, scenario payload identity, and URI-safe resource observations;
- equality and truthful existence/hash pairing of persistent-configuration observations;
- tool-call index ordering/ownership, executable-derived request/response measurements, reduction ratio, and ordered step/run chronology;
- readiness/outcome/state/cleanup consistency, including a concrete mismatch for `failed` and readiness failure for `blocked`;
- accepted zero-Blocker/zero-Major review for a passed retained reference.

## 6. Cross-OS process matrix

`tests/fixtures/cross_client/process-matrix.json` is executed from the built wheel on Ubuntu and macOS, using CPython 3.11 and 3.13 (the oldest and newest supported minors). It covers:

- installed entry-point startup and initialization;
- normal client/server shutdown;
- destructive reset process replacement;
- timeout with surviving kernel;
- timeout escalation with dead kernel;
- runner response-channel death;
- output-limit intervention and drain;
- artifact read/tamper/expiry behavior;
- cancellation and managed-process cleanup.

Windows is not claimed: the Runtime contract is POSIX-only. Adding Windows requires a separate accepted platform decision and implementation item.

## 7. Verification gates

### S4-001

- JSON Schema Draft 2020-12 metaschema validation;
- positive fixture validation;
- negative mutations for missing/reordered steps, identity/hash drift, secret/path leakage, result/state drift, call-index drift, resource-link drift, timing/arithmetic drift, readiness contradictions, false cleanup, and missing review;
- independent architecture/correctness/privacy review with 0 Blocker and 0 Major.

### Reference runs

- actual non-interactive client invocation;
- fresh temporary workspace and per-run MCP configuration;
- clean wheel installation;
- schema and semantic validation;
- recurrence run against the same client version;
- no persistent configuration mutation;
- no managed process remains;
- unchanged GitHub Issue #82 naturalistic task completed through `python_exec` only;
- bounded complete client event log proves no non-AMKernel work-tool attempt;
- independent dependency-graph oracle matches every report and JSON artifact field;
- displayed PNG is digest-retained, embeds the oracle chart data, and passes semantic review;
- one digest-verified `dependency-investigation.json` artifact;
- independent evidence review with 0 Blocker and 0 Major.

### Process matrix

- hosted Ubuntu and macOS observations for every matrix cell;
- exact wheel and environment identity;
- no ignored or expected-failure cell;
- independent lifecycle review with 0 Blocker and 0 Major.

### Graduation

- one source-derived portable index linking every client step, process row, artifact, identity, limitation, and review;
- all source schema, semantic, hash, state, and cleanup checks rerun from the index;
- explicit support claim and next-vertical decision bounded to observed evidence;
- final independent review with 0 Blocker and 0 Major.

## 8. Exit criteria

Stage 4 exits only when both real clients complete the frozen scenario, the claimed POSIX operating-system matrix passes, all retained evidence validates, every blocking risk has an evidence-backed disposition, and S4-040 records the justified support/next-vertical decision. Production `src/amkernel/` remains unchanged unless a separate defect Issue and accepted contract authorize a fix.

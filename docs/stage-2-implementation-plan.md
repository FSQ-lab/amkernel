# Stage 2 Agent-Quality Output Implementation Plan

## Purpose

This is the execution plan for the Stage 2 contract accepted by ADR-0006. It turns bounded Stage 1 completion output into live advisory text, structured displays, images, recoverable artifacts, workspace helpers, and requested package diagnostics without weakening persistent-kernel, lifecycle, transport, or security invariants.

Live status, dependencies, blockers, risks, owners, and queue order live in GitHub Project #2 and linked Issues. This document defines durable scope, interfaces, sequencing, evidence, and exit criteria.

## Fixed scope

### Included

- one `python_exec` tool with optional requested distribution versions;
- version-2 private Runner output frames;
- strict JSON display and explicit supported-image display;
- explicit text, binary, and JSON artifacts;
- complete stdout/stderr spooling behind bounded tails;
- per-execution hard output and artifact bounds;
- process-scoped Artifact Store with whole-bundle pressure eviction;
- MCP progress previews, structured content, images, resource links, and resource reads;
- `display`, `artifact`, `read`, `write`, and `env` prelude helpers;
- extended runtime identity and requested package diagnostics;
- installed-wheel black-box evidence on every supported Python/OS pair.

### Excluded

- multiple kernels, concurrent execution, notebook compatibility, remote transports, durable cross-process artifacts, user accounts, ACLs, cloud stores, workflow DSLs, platform actions, dependency-specific rendering adapters, arbitrary host cleanup, and sandboxing;
- MCP logging as a user-output channel;
- a claim that client progress is complete, durable, or rendered;
- dynamic artifacts in `resources/list`;
- output beyond the hard limit or retention after an artifact URI expires.

## Milestone record

- **Delivery stage and outcome:** M2 / Stage 2. One installed `python_exec` surface produces truthful bounded live previews, typed displays, images, recoverable ephemeral artifacts, workspace helpers, and requested runtime diagnostics while preserving Stage 1 execution/lifecycle correctness.
- **Entry criteria:** M1 and REL-001 are complete; ADR-0001 through ADR-0005 are Accepted; the supported baseline is CPython 3.11–3.13 on GitHub-hosted Ubuntu and macOS; S2-001, ADR-0006, this plan, follow-up work, and risks are registered in Project #2; no production item starts before ADR-0006 acceptance.
- **Ordered work and dependency edges:** `S2-010 -> S2-020 -> S2-030 -> S2-040 -> S2-050 -> S2-060`; `(S2-020, S2-030, S2-040, S2-060) -> S2-070`; `(S2-030, S2-040, S2-070) -> S2-080`; `(S2-050, S2-070, S2-080) -> S2-090`. Project order is the tie-breaker where dependency-ready items have disjoint writers and files.
- **Required ADRs:** ADR-0001 through ADR-0006. A later semantic change to an accepted contract requires a new superseding ADR.
- **Required risks:** R-015 unbounded output/store pressure, R-016 artifact/resource disclosure or active content, R-017 live-progress backpressure, R-018 output-limit/lifecycle races, R-019 workspace-helper escape/race, and R-020 ephemeral resource expiry. Each linked work item states which risks it mitigates; none closes before its evidence is observed.
- **Exit scenarios and quality gates:** the cross-cutting matrix, performance/resource gates, security gates, S2-090 installed-wheel matrix, canonical `ruff format --check`, `ruff check`, `mypy`, full `pytest`, and independent reviews defined below all pass on the final integration commit.
- **Allowed support claims after completion:** CPython 3.11–3.13 on GitHub-hosted Ubuntu and macOS; one serialized persistent local kernel; advisory live text only when the official client supplies progress; complete recoverable stream bytes only through the hard limit and only while the execution bundle is retained; explicit typed JSON and supported raster images; process-local ephemeral resource links; workspace-confined convenience helpers that are not a sandbox.
- **Explicitly deferred:** every item under Excluded, durable artifact retention, protocol-level partial tool-result streaming, SVG/active-content display, dependency-specific rich representations, configurable public quotas, remote/multi-user authorization, and support beyond the evidence-qualified Python/OS range.

## Contract prerequisites

Production work starts only after:

1. ADR-0006 is Accepted;
2. this complete plan is linked from S2-001;
3. implementation, evidence, and risk Issues exist in dependency order in Project #2;
4. each Issue names one writer for each shared state machine or schema it changes;
5. an independent reviewer reports no remaining Blocker or Major architecture/security finding.

## Target module seams

Stage 2 deepens existing modules rather than adding parallel execution paths.

### `protocol.py`

Owns the exact version-2 frame models, strict parser/encoder, correlation, logical sequence/transaction state, canonical base64, hashes, declared sizes, frame/item/chunk bounds, and fatal violations. It does not know storage paths, MCP classes, or lifecycle policy.

### `runner.py`

Owns prelude installation, user-facing validation before frame emission, locked Pillow image validation, requested package inspection, ordered event production, and complete/incomplete artifact transactions. It does not persist artifacts or make kernel-survival decisions.

### `output.py` (new)

Owns one execution-scoped Output Pipeline. It accepts observed stdout/stderr chunks and validated logical events, maintains bounded tails/counters/discard counts/latest-value snapshots, enforces all per-call byte/item/result bounds, and finalizes an immutable bundle. It is the only module that combines streams with explicit output facts.

### `artifacts.py` (new)

Owns the process Artifact Store: identity-pinned temporary root, charged reservations, 8 MiB parts/manifests, atomic publication, SHA-256, metadata index, read leases, whole-bundle eviction, exact URI lookup, tamper verification, and identity-safe cleanup. It never sends MCP messages or signals the Runner.

### `supervisor.py`

Continues to own pipe readers, execution windows, intervention markers, pipe discard draining, process signals, Runner response validation, timeout/cancellation/death precedence, and destructive cleanup. It feeds the Output Pipeline and translates typed output-limit/store failures through one lifecycle state machine. It does not format MCP content or implement storage.

### `runtime.py`

Owns serialization, reset/shutdown orchestration, last-valid diagnostics, Artifact Store lifetime, and the narrow resource-read method used by the Adapter. Reset replaces only the Runner; shutdown stabilizes execution before store cleanup.

### `server.py`

Owns exact public schemas/descriptions, request-scoped progress, deterministic current-protocol MCP content mapping, resources capability/list/read handlers, and bounded protocol errors. It never reads store files directly or mutates lifecycle state.

## Delivery sequence

Each increment includes focused behavior checks and an independent review before its Project item is Done. Canonical full-suite and installed-wheel matrices run once at the integration/evidence gates, not after every internal increment.

### S2-010 — Freeze public and private schema fixtures

**Owner:** Contract and Integration Lead.

**Deliverables**

- Accept ADR-0006, add it to the ADR index, and lock Pillow as the justified Stage 2 raster-validation runtime dependency.
- Add the exact version-2 request/response frame models and literal schema fixtures without enabling Runner emission.
- Update `python_exec` input/output schemas, closed package-error values, descriptions, and typed models in one clean cutover.
- Remove the dormant singular `output.artifact` shape; no aliases or deprecated paths.
- Define reusable JSON-value, package-name, MIME/name, safe-MIME, ID/hash, byte/count/frame/result, resource-part, and image-pixel constants once.

**Focused evidence**

- literal equality for every public/private required/optional field, closed value, and `additionalProperties` rule;
- version mismatch; unknown/extra/missing field; correlation/sequence/transaction/chunk/base64/hash/count/integer/result-bound rejection; and exact fatal mapping;
- official client discovery exposes exactly one updated tool and resources capability under the current negotiated protocol.

**Exit**

Every later Issue imports these constants/models; no competing schema literals exist.

### S2-020 — Implement Artifact Store lifecycle and resource reads

**Owner:** Output and Artifact Owner.

**Depends on:** S2-010.

**Deliverables**

- Identity-pinned randomized temporary root and collision-safe server/artifact IDs with explicit same-user limitations.
- Charged 544 MiB reservation/staging/abort/atomic publication, 8 MiB parts/manifests, read leases, whole-bundle eviction, and identity-safe shutdown cleanup.
- Mode `0700` directories / `0400` published files; descriptor-relative no-follow operations; aggregate/part SHA-256; exact 66-item/128-part byte/index/file accounting.
- Narrow Runtime read interface; one global read admission; atomic lookup/lease/bounded load/reverification; raw/manifest/part URI mapping.
- Exact current-protocol empty list and read `cacheScope`, `resultType`, `ttlMs`; Blob parts; generic resource-not-found/integrity errors.

**Focused evidence**

- exact raw and 8 MiB boundary/manifest/32-part recovery, aggregate/part hashes, safe versus declared MIME, generated names, and no path disclosure;
- malformed, unknown, expired, tampered, hash/size-mismatched, and cross-process URI behavior with no partial response;
- zero-byte/item/file/index floods, 544 MiB reservation arithmetic, charged quota, three-collision exhaustion, and whole-oldest-bundle pressure eviction;
- resource-read versus eviction/execution/shutdown races; reset retention; normal cleanup; substituted-root/entry refusal; crash residue truth;
- permissions, descriptor/symlink/rename races, and RSS/encoded-response plateaus on Linux/macOS.

**Exit**

A synthetic producer can publish/read/evict bundles through the public Runtime seam without a Runner.

### S2-030 — Add Output Pipeline and complete stream recovery

**Owner:** Output and Artifact Owner.

**Depends on:** S2-020.

**Deliverables**

- Per-call tails, accepted/discarded raw byte/line counts, spools from byte one, UTF-8-safe tails, and one-slot observer snapshots.
- Stream artifact parts/manifests only when a returned preview omits accepted bytes.
- Exact `truncated`, `limitBytes`, `limitExceeded`, `discardedBytes/Lines`, channel references, and canonical artifact order.
- First byte beyond 256 MiB atomically marks the limit after accepting only the in-bound prefix; exact-bound completion remains valid; both pipes then discard-drain and progress suppresses.
- Temporary cleanup on completion, abort, timeout, cancellation, limit, death, publication failure, and transport shutdown.

**Focused evidence**

- empty, boundary-1/exact/+1 tails, invalid UTF-8, no trailing newline, long line, both channels, and background overlap;
- 16 MiB and 256 MiB producers with bounded RSS, exact resource recovery, and item/file/index plateaus;
- concurrent Python/native/child writers ending exactly at the limit or crossing by one/chunk while Runner returns, ignores SIGINT, or dies: no blocked pipe, exact accepted/discarded counts, correct state;
- no leftover unpublished file/task/descriptor after every terminal path and unchanged Stage 1 execution-window attribution.

**Exit**

Supervisor tests consume immutable output results; no Stage 1-only tail collector remains.

### S2-040 — Add structured display, images, and explicit artifacts

**Owner:** Runner and Protocol Owner for event production; Output and Artifact Owner for validation/publication. Changes to shared models are serialized through the S2-010 owner.

**Depends on:** S2-010, S2-020, S2-030.

**Deliverables**

- Fresh-Runner `display` and `artifact` helpers with per-kind, aggregate, event, frame, and encoded-result cardinality bounds.
- Exact version-2 begin/chunk/end frames, noninterleaved transactions, canonical base64, incremental hashes, and 64 KiB decoded chunks.
- Strict JSON value/size/count validation with no implicit `repr`.
- Exact container-end checks plus locked Pillow open/seek/`load()` of every frame in Runner and host; width/height, 256-frame, 40-million cumulative pixel-frame, warning/error, MIME, artifact, and inline rules.
- Text/bytes/JSON inference, validated duplicate logical names, declared-versus-safe MIME, and opaque active-content mapping.
- Partial transactions withheld; completed pre-error items preserved; forged host-side mismatch is fatal.

**Focused evidence**

- helper signatures, shadowing persistence, reset restoration, and public/runtime order identity;
- exact event/frame/transaction/item/chunk boundaries, zero-byte floods, 4 MiB structured result limit, and fatal forged-frame cases;
- JSON cycles/nonfinite/keys/sizes/counts and every image valid/truncated/trailing/polyglot/compressed-malformed/frame-count/cumulative-pixel/decompression/parser/MIME case;
- exact max/aggregate artifact bytes/items, duplicate/control names, partial transactions, chunk crash, collision, Store failure, safe MIME and active-content opacity;
- descendants cannot inherit/forge private frames; host revalidation detects a compromised Runner mismatch.

**Exit**

Runtime results expose complete ordered `displays`/`artifacts` but the Adapter may still render only canonical JSON.

### S2-050 — Add workspace and environment prelude helpers

**Owner:** Runner and Protocol Owner.

**Depends on:** S2-040.

**Deliverables**

- Launch-time canonical workspace directory pinned by handle/device/inode identity.
- Descriptor-relative no-follow `read`, strict text decoding, binary mode, regular-file and one-byte-over-limit checks.
- Descriptor-relative atomic `write`, pinned existing parent, regular-destination rule, mode `0600`, and byte count.
- Exact `env()`/`env(key)`/`env(key,value)`/`env(None)` semantics.
- Explicit docstrings/reprs: helper confinement is safe default, not sandboxing.

**Focused evidence**

- relative and absolute-in-root component mapping; empty/`..` rejection;
- root/parent rename, symlink substitution at every segment, dangling links, directories/devices/FIFOs/sockets, destination races, permissions, and atomic failure;
- UTF-8 error and zero/exact/exceeded read limit with no returned prefix; text/bytes writes;
- environment copy isolation, omitted key versus `None`, missing/set/replace/delete, invalid key/value, and direct `os.environ` coexistence;
- persistence/reset and explicit refusal when descriptor-relative no-follow primitives are unavailable.

**Exit**

Prelude tests use only the Runner public execution path; no test reaches helper internals to assert behavior.

### S2-060 — Add package and extended runtime diagnostics

**Owner:** Runner and Protocol Owner for inspection; Contract and Integration Lead for public mapping.

**Depends on:** S2-050.

**Deliverables**

- Input validation, PEP 503 normalization/duplicate detection, and exact package count/name bounds.
- Runner-side `importlib.metadata` inspection in requested order within the cell deadline.
- Control-free bounded version strings, closed three-value error vocabulary, no raw metadata exception disclosure, and bounded implementation/platform identity.
- Last-valid diagnostics after death and deterministic reset refresh.

**Focused evidence**

- installed/absent distributions, case/separator normalization, request order, and empty list;
- duplicate/invalid/count/length and control/oversized/invalid metadata;
- unavailable metadata maps to one closed error and does not change a completed cell; inspection obeys timeout;
- project/active/system identity plus death/reset behavior, with no host-interpreter substitution.

**Exit**

No implicit package inventory or host-interpreter answer is possible.

### S2-070 — Map official MCP content, resources, and live progress

**Owner:** Contract and Integration Lead.

**Depends on:** S2-020, S2-030, S2-040, S2-060.

**Deliverables**

- Current-protocol `resultType="complete"`, bounded `structuredContent`, and canonical JSON `TextContent`.
- Fixture-locked ImageContent/ResourceLink ordering, safe generated resource names, titles, declared/safe MIME, raw/manifest mapping, and stdout/stderr suffix order.
- Exact resources list/read `cacheScope="private"`, `resultType="complete"`, `ttlMs=0`, Blob/Text behavior, generic errors, and one-read admission.
- Request-scoped one-slot progress reporter with monotonic revisions, generic 8 KiB messages, and 10 Hz maximum.
- Exact `output.live` unavailable/progress/failed semantics; reporter latency/failure never backpressures output or changes execution.

**Focused evidence**

- official client calls with/without progress and with forced local progress-send failure;
- literal content/list/read fields, content block/data/MIME/name/title/URI order, manifests/parts, and `isError=false` across all statuses;
- monotonic revision/rate/message/privacy bounds, truthful `live`, and terminal-result authority;
- blocked/failing reporter proves one-slot observer memory and unaffected 16 MiB completion;
- cancellation/transport close/read-lease/eviction leave no reporter, publication, or read race.

**Exit**

No private MCP model construction bypasses the official SDK types, and final output remains complete when progress is absent.

### S2-080 — Integrate output-limit and lifecycle failure semantics

**Owner:** Runtime and Supervision Owner.

**Depends on:** S2-030, S2-040, S2-070.

**Deliverables**

- Exact 256 MiB marker, continued discard drain, generic progress suppression, safe-return and escalation behavior.
- One implemented precedence table for valid done, deadline, output limit, cancellation, transport shutdown, Store/result failure, protocol failure, Runner death, reset FIFO, and simultaneous deadline/limit readiness.
- Typed `ArtifactStoreError` with active-bundle abort, destructive cleanup, bounded retained fields, and host-only diagnostics.
- Complete task/future/descriptor/pipe/lease cleanup under repeated failures.

**Focused evidence**

- cooperative and ignored limit interruption produce exact accepted/discarded counts and `failed/alive` versus `kernel_killed/dead` without pipe deadlock;
- every table row and pairwise race fixes status/state/count/error/output and first-marker precedence;
- write/hash/verify/part/fsync/rename/quota/result-construction failures never return an active artifact reference;
- retry cleanup remains honest after injected group and Store identity/entry cleanup failures;
- existing deadline, cancellation, reset/death, transport-close, diagnostics, and idle-output suites retain their accepted meaning.

**Exit**

Independent lifecycle review reports no duplicated authority or survival overclaim.

### S2-090 — Installed-wheel black-box evidence and documentation cutover

**Owner:** Verification and Release Owner; independent reviewer separate from implementation owners.

**Depends on:** S2-050, S2-070, S2-080.

**Deliverables**

- Extend the clean-project-venv official-client scenario through discovery, progress/no-progress/failure, strict displays, fully verified images, item floods, raw/manifest artifacts and resource reads, package diagnostics, descriptor-rooted helpers, failure/timeout/limit/death/reset, shutdown, eviction, tamper, and cleanup refusal.
- Exercise the exact built wheel and locked Pillow dependency; no source-tree import or private-seam substitution.
- Update architecture, development, README, tool description, Handoff, and changelog to accepted behavior, exact support claims, ephemeral manifest recovery, same-user limitations, and no-sandbox truth. Remove superseded wording.
- Retain wheel SHA-256, dependency versions, interpreter/OS matrix, exact scenario output, byte/hash/count/RSS/file/index/task measurements, and review on the final commit.

**Focused evidence**

- canonical static checks, full suite, exact schema/content fixtures, and dependency audit;
- clean-wheel official-client jobs on Ubuntu/macOS for every supported Python minor;
- Linux/macOS process RSS/open-file/store/index/result measurements for empty-item floods, 16/256 MiB streams, 64+2 logical artifacts, 128 parts, 8 MiB reads, and 32-part manifests;
- fresh-process URI invalidation, tamper/read failure, pressure eviction, read race, normal root removal, and substituted-root cleanup refusal;
- independent architecture/correctness/security/behavior review with no Blocker or Major finding.

**Exit**

Every claimed public behavior is covered through the installed public surface, Stage 2 Project items are Done, and the Handoff names the next ready item or explicitly states that the queue is empty.

## Cross-cutting behavioral matrix

Every implementation Issue selects the relevant cells below; S2-090 covers the full matrix.

| Dimension | Required cases |
| --- | --- |
| Cell result | expression, statement, ordinary exception, syntax error |
| Terminal path | completed; failed/alive; timed_out alive/dead; killed/dead; cancel safe/dead; reset; shutdown |
| Stream | none, stdout, stderr, both, invalid UTF-8, native/child writers, background overlap, discard drain |
| Size/count | 0, boundary-1/exact/+1, empty-item flood, 16 MiB, 256 MiB, hard-limit+1, terminal-result bound |
| Display | strict JSON errors/count; four fully decoded raster formats; malformed/polyglot/pixel/MIME; inline/fallback |
| Artifact | text/bytes/JSON, duplicate/control name, safe/active MIME, byte/item/part quota, partial, collision, I/O failure |
| MCP client | progress token/no token/local failure, current result/list/read fields, ignored content type |
| Store/resource | raw/manifest/parts, retained/leased/expired/tampered/foreign URI, eviction/read race, cleanup substitution/crash |
| Helper path | pinned root/parent, relative/absolute, traversal, rename, every-level symlink, special file, replacement race |
| Diagnostics | empty, present/absent, normalized duplicate, invalid, control/oversized metadata, closed errors |
| Platform | Ubuntu, macOS; every supported Python minor |

## Performance and resource gates

- Supervisor/Runner RSS plateaus under repeated empty-item floods and 16/256 MiB stream/artifact calls; no result retains full stream bytes.
- One active observer holds at most one 8 KiB snapshot plus fixed metadata; item/frame/result cardinality remains fixed.
- Artifact write/hashing is incremental; Store files are at most 8 MiB parts; one resource read loads/encodes at most one part and stays within a recorded RSS ceiling.
- Base64 allocation is allowed only for one 64 KiB private chunk, one bounded inline image, or one 8 MiB resource part. No full large artifact enters one response.
- Tail, exact-bound/first-excess split, accepted/discarded line counting, UTF-8 boundary selection, hashing, parting, and manifest generation are incremental.
- Charged bytes, item/part/file/index counts, result bytes, descriptors, leases, tasks, and managed processes plateau and return to the documented baseline after eviction/shutdown.

## Security gates

- No result, URI, block, exception, progress message, or resource error reveals a Store path, workspace path, traceback, PID/group, private frame, or executable path beyond ADR-0003's runtime contract.
- Validated logical titles and declared MIME are untrusted metadata; generated names select resources; only the safe MIME allowlist is advertised/renderable.
- Random exact URI lookup protects remote MCP access, not a hostile same-user process; every bounded read revalidates loaded bytes and documents this limitation.
- Workspace operations use pinned descriptor-relative no-follow traversal and refuse unsupported primitives; unrestricted Python remains explicitly not sandboxed.
- Progress carries user stream text or generic bounded type/size metadata, never raw logical names or host diagnostics.
- Cleanup verifies root identity, renames to a tombstone, unlinks descriptor-relatively without following links, and reports/refuses any substitute rather than removing it.

## Required review artifacts

Each load-bearing Issue records:

1. implementation commit and exact focused commands;
2. relevant environment/interpreter/platform;
3. behavioral evidence, including byte/hash/RSS/store values where applicable;
4. fault-injection result for changed failure paths;
5. reviewer name/agent, scope, severity, and final disposition;
6. explicit confirmation that no Blocker or Major finding remains.

A passing test suite is necessary but not sufficient for lifecycle, storage, security, or resource-bound claims.

## Stage 2 exit criteria

Stage 2 is complete only when:

- ADR-0006 is implemented without compatibility shims or duplicate paths;
- all S2-010 through S2-090 Issues are Done in Project #2;
- every normal preview omission is recoverable while its documented artifact bundle is retained;
- every hard limit, eviction, unavailable progress path, and cleanup failure is explicit and truthful;
- official-client installed-wheel evidence passes across the claimed Python/OS matrix;
- canonical static and full-suite gates pass on the final commit;
- documentation and Handoff describe the implemented behavior, not planned behavior;
- independent architecture, correctness, security, and behavior review has no remaining Blocker or Major finding.

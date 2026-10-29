# ADR-0006: Stage 2 Output and Artifact Contract

- Status: Accepted
- Date: 2026-10-29
- Deciders: Project owner; Contract and Integration Lead
- Supersedes: None
- Related: [`../architecture.md`](../architecture.md), [`../development.md`](../development.md), [S2-001](https://github.com/FSQ-lab/amkernel/issues/46), [MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), [MCP resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources), [MCP progress](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress)

## Context

Stage 1 returns bounded completion-time stdout/stderr tails and truthful counts but deliberately cannot recover omitted bytes. Stage 2 must add live text when the client requests it, structured displays, images, recoverable artifacts, bounded previews and storage, a complete automation-neutral prelude, and requested package diagnostics without changing kernel-survival semantics.

The official MCP tool result can carry text, images, resource links, embedded resources, and a JSON `structuredContent` value. MCP progress is optional, client-requested, advisory, monotonically increasing, and not a durable content channel. Logging notifications are not user stdout/stderr and are deprecated in the current protocol. Resource links returned by a tool need not be listed by `resources/list`, but a server advertising resources must answer resource-list and resource-read requests.

Unrestricted user code can emit unbounded output. Full recovery, bounded storage, and unlimited execution cannot all be guaranteed simultaneously. Stage 2 therefore needs explicit per-execution hard limits, process-wide retention pressure, and truthful failure behavior rather than silent loss.

## Decision

### Scope and non-goals

Stage 2 keeps one `python_exec` tool and one serialized persistent Runner. It adds output and artifact behavior behind the existing Runner, Supervisor, Runtime, and Adapter seams. It does not add another execution tool, a notebook protocol, remote transport, multi-user storage, a workflow language, platform actions, dependency-specific display code, arbitrary external-session cleanup, or a sandbox claim.

Execution status, `kernelState`, execution counting, timeout precedence, reset, cancellation, and managed-process cleanup remain governed by ADR-0003 through ADR-0005. Output-limit escalation uses the same survival-truth machinery but has the distinct public error `OutputLimitExceeded`.

### Public tool input and requested diagnostics

`python_exec` adds one optional field:

```ts
type PythonExecInput = {
  code: string;
  title?: string;
  timeout?: number;
  reset?: boolean;
  packages?: string[];
};
```

`packages` requests installed distribution versions from the selected Runner environment. It accepts at most 64 unique names. Each name is 1–128 ASCII characters and must be a valid normalized Python distribution name: ASCII letters or digits separated by `.`, `_`, or `-` runs. Matching is case-insensitive under PEP 503 normalization. Duplicate normalized names and unknown input fields are rejected before Runtime dispatch.

Requested versions are resolved by the Runner after the cell and are reported even when the named distribution is absent. A returned version is valid only when it is 1–1,024 UTF-8 bytes and contains no Unicode `Cc`/`Cf` code point. Package inspection remains inside the cell deadline. No full environment inventory is produced implicitly.

`runtime` becomes:

```ts
type RuntimeInfo = {
  executable: string;
  pythonVersion: string;
  workingDirectory: string;
  environmentKind: "project_venv" | "active_venv" | "system";
  implementation: string;
  platform: string;
  packages: Array<{
    name: string;
    version?: string;
    error?: "not installed" | "metadata unavailable" | "invalid metadata";
  }>;
};
```

`packages` is always present and preserves request order; it is empty when none were requested. Exactly one of `version` or `error` is present for each requested name. Raw metadata exception types, messages, paths, and tracebacks remain bounded host diagnostics only. A per-name metadata error does not change a completed cell into a failed cell. `implementation` and `platform` are nonempty, control-free strings of at most 256 UTF-8 bytes. Existing path/version bounds remain those of ADR-0004. Runtime identity fields retain ADR-0003's last-valid-diagnostics behavior after kernel death.

### Prelude interface

A fresh Runner injects exactly these five automation-neutral helpers in addition to normal Python execution globals:

```python
display(value, *, mime_type=None)
artifact(name, content, *, mime_type=None)
read(path, *, binary=False, limit=1_048_576)
write(path, content)
env(key=<missing>, value=<missing>)
```

The helpers are ordinary synchronous Python functions and return `None` except `read`, `write`, and `env` as described below. Reset installs fresh helper instances. User reassignment is ordinary namespace mutation and persists until reset.

`display(value)` accepts a strict JSON-compatible value. Its compact JSON encoding is limited to 1 MiB per item and 4 MiB per execution. At most 64 JSON displays are accepted per execution. It emits one ordered structured display and returns `None`. Non-JSON values, cycles, non-string object keys, NaN/infinity, or an exceeded bound raise `DisplayError` in user code; they are not implicitly converted with `repr`.

`display(data, mime_type="image/...")` accepts bytes-like PNG, JPEG, GIF, or WebP. Runner and host independently apply the same complete validator: a format-specific container parser proves the terminal marker/declared RIFF length ends exactly at EOF; Pillow opens the claimed format; every frame is sought and `load()`ed; and all decoder warnings/errors are fatal. Width and height are each at most 32,768, frame count at most 256, and cumulative decoded pixel-frames at most 40,000,000. Truncated, trailing/polyglot, MIME/format-mismatched, malformed compressed, oversized, decompression-warning, or parser-error input raises `DisplayError` in Runner validation; a host mismatch is fatal. Each image is limited to 256 MiB, counts against artifact byte/item quotas, and is one ordered display item. At most 16 images are accepted. Full bytes are stored as an artifact. A verified image no larger than 4 MiB may also become MCP `ImageContent`; aggregate inline images are at most 8 MiB. A larger verified image remains a first-class image display/resource link without base64 inline. SVG and unsupported formats can only use `artifact` as opaque bytes.

`artifact(name, content, mime_type=None)` accepts `str`, bytes-like data, or a strict JSON-compatible value. Text defaults to `text/plain; charset=utf-8`, bytes to `application/octet-stream`, and JSON values to `application/json`. The logical name is 1–255 Unicode code points and contains neither `/` nor `\\`, NUL, `Cc`, or `Cf`; duplicate logical names are accepted as distinct artifacts. A MIME value is 1–255 printable ASCII bytes, syntactically valid as one media type with optional parameters, and contains no control character. Arbitrary caller MIME is preserved as `declaredMimeType` but never automatically promoted to client-renderable MIME. Each artifact and the combined explicit artifact/image bytes per execution are limited to 256 MiB. At most 64 stored artifact items, including images, are accepted per execution. The helper streams bounded chunks to the host, emits one ordered artifact item, and returns `None`. Runner-side validation or quota failure raises `ArtifactError` before a transaction begins; an impossible host-side mismatch is a fatal protocol/store failure and never publishes a partial artifact.

`read` and `write` are convenience helpers confined to the launch-time workspace directory identity. Initialization opens and pins the canonical workspace directory. Each operation converts an accepted relative or absolute-in-root path to workspace-relative components, rejects empty components, `..`, and symlinks at every level, then walks with directory-relative no-follow opens. `read` opens the final handle before `fstat` verifies a regular file and returns strict UTF-8 text or bytes. `limit` is 0 through 64 MiB; the helper reads at most one detection byte beyond the bound and raises `ReadLimitError` without returning a prefix when the file is larger, including a nonempty file at limit zero. `write` accepts text or bytes, requires an existing pinned regular-directory parent, creates a mode-`0600` temporary file through that parent handle, and atomically replaces a regular-file destination through the same handle. It returns the byte count. Workspace root/parent rename and symlink substitution cannot redirect the held directory identities; a platform lacking the required descriptor-relative no-follow primitives is unsupported rather than using a path-check fallback. These helpers are confined; unrestricted user Python remains able to use `open`, `os`, and network libraries directly.

`env()` returns a detached copy of the Runner's current environment. `env(key)` returns one value or `None`. `env(key, value)` sets a string value, or deletes the key when value is `None`, and returns the previous value or `None`. Omitting `key` is distinct from passing `None`; `env(None)` is invalid. Keys must be nonempty portable environment names and values may not contain NUL. This helper is convenience, not a credential boundary; the Runner starts with ADR-0005's filtered environment, but user code can mutate `os.environ` directly.

### Ordered output events and private protocol

The private protocol advances to version 2 as one clean cutover while retaining ADR-0004's envelope, 8,388,608-byte encoded-frame cap, correlation rule, request states, and fatal behavior. `execute.payload` becomes exactly `{"code": string, "packages": string[]}`; `packages` is present even when empty and already host-validated. `ready`, `started`, `done`, and `protocol_error` retain their transitions, with the expanded `RuntimeInfo`. Between `started` and `done`, version 2 adds these exact response payloads:

| Type | Exact payload |
| --- | --- |
| `display_json` | `{"executionCount": integer, "sequence": integer, "value": JSONValue}` |
| `artifact_begin` | `{"executionCount": integer, "sequence": integer, "transactionId": string, "kind": "artifact" | "image", "name": string, "declaredMimeType": string, "size": integer}` |
| `artifact_chunk` | `{"executionCount": integer, "sequence": integer, "transactionId": string, "chunkIndex": integer, "data": string}` |
| `artifact_end` | `{"executionCount": integer, "sequence": integer, "transactionId": string, "chunkCount": integer, "sha256": string}` |

`executionCount` equals the active `started` count. `sequence` is the next integer in `1..128` for each logical `display` or `artifact` call; a JSON display consumes one sequence, and one complete artifact transaction shares one sequence across its begin, all chunks, and end. Artifact transactions cannot interleave. `transactionId` is a Runner-generated UUIDv4 in the same 32-lowercase-hex form as `correlationId` and is unique within the call. `kind="image"` is valid only for the image overload. `size` is `0..268435456`. Names/MIME/JSON values obey the public bounds before frame encoding.

`chunkIndex` begins at zero and increases by one. `data` is canonical RFC 4648 base64 with padding, no whitespace, and at most 87,384 encoded ASCII bytes representing at most 65,536 decoded bytes. The concatenated decoded length must equal `size`; `chunkCount` equals the number of chunks; `sha256` is exactly 64 lowercase hexadecimal characters and must match the host's incremental hash. A zero-byte artifact has begin/end with `chunkCount=0`. Across one call, at most 4,288 Stage 2 output frames, 64 artifact transactions, 64 JSON displays, 16 image transactions, 4,096 chunks, 256 MiB decoded artifact bytes, and 4 MiB compact JSON display bytes are valid.

Any unknown/extra/missing field, wrong type/bound/base64, duplicate ID, sequence gap, illegal transition, interleaving, count/hash/size mismatch, bound excess, incomplete transaction, or output frame after `done` is `RunnerProtocolError`: the host aborts the unpublished bundle, destroys the managed group, and returns `kernel_killed/dead`. A Runner-side helper validation error occurs before `artifact_begin` and remains an ordinary user exception. Descendants never inherit private descriptors.

Stdout and stderr remain separate raw process pipes because inherited descendants legitimately write them. The Output Pipeline, not the Runner, assigns observed stream chunks to the active execution window, retains bounded tails, spools accepted per-channel bytes, counts observed raw bytes and lines, and emits nonblocking observer snapshots. The Runner protocol never carries stdout/stderr.

The Output Pipeline exposes one deep execution-scoped interface to the Supervisor: accept stream chunks and validated Runner output events, finalize one immutable output result, or abort and remove unpublished temporary data. Artifact Store mechanics, hashes, retention, MCP models, and paths do not leak into the Runner.

### Bounds and output-limit behavior

The fixed Stage 2 defaults are:

| Limit | Value |
| --- | ---: |
| Returned stdout tail | 262,144 raw bytes |
| Returned stderr tail | 262,144 raw bytes |
| Accepted combined stdout/stderr per execution | 268,435,456 raw bytes |
| One / combined explicit artifacts and images | 268,435,456 / 268,435,456 raw bytes |
| Stored explicit/image items / stream items / total | 64 / 2 / 66 per execution |
| Total explicit logical events / version-2 output frames | 128 / 4,288 per execution |
| Compact terminal `structuredContent` JSON | 4,194,304 encoded bytes |
| Total execution bundle reservation | 570,425,344 charged bytes |
| Process Artifact Store quota | 2,147,483,648 charged bytes |
| Artifact resource part / one admitted resource read | 8,388,608 raw bytes / 1 globally |
| JSON display item / execution | 1,048,576 / 4,194,304 encoded bytes |
| Inline MCP image item / execution | 4,194,304 / 8,388,608 raw bytes |
| Live update message / rate | 8,192 UTF-8 bytes / at most 10 per second |

The Output Pipeline spools each stream from its first byte. Before the hard limit, a channel exceeding its returned tail publishes all accepted channel bytes as a logical artifact. Thus `truncated=true && limitExceeded=false` implies every omitted observed byte is recoverable while that bundle remains retained.

When the first stream byte beyond 256 MiB combined arrives, the Supervisor accepts only the in-bound prefix of that read, atomically records `OutputLimitExceeded`, and sends the group signal. A call ending at exactly the limit is not limited. After the marker, the Supervisor drains both pipes only to a discard sink until valid `done` or destructive cleanup, so buffered Python/native/child writes cannot deadlock finalization. Discarded chunks are never spooled or sent as progress, but observed discarded bytes/lines are counted. Safe Runner return maps to `failed/alive`; escalation maps to `kernel_killed/dead`. Accepted prefixes remain recoverable; AMKernel never claims unobserved attempted bytes.

Every logical artifact is divided into immutable parts of at most 8 MiB and consumes its raw bytes plus at least 4 KiB logical/index/inode charge; every part adds at least 4 KiB. One call can publish 64 explicit/image artifacts plus two stream artifacts and at most 128 physical parts. Before execution, the Store locks and reserves 570,425,344 charged bytes (544 MiB), covering both 256 MiB raw maxima plus all fixed per-item/part/manifest/index overhead with margin. It evicts oldest complete bundles until that exact reservation fits. One active read lease prevents bundle eviction; admission waits for the single bounded read. Active bundles and individual retained files are never evicted.

Reset does not delete artifacts. Pressure evicts only completed whole bundles. Normal shutdown removes the identity-pinned owned root; abnormal server death leaves only operating-system temporary-directory policy. A resource URI can expire under pressure before a later call or at shutdown, so the tool description requires callers needing durable evidence to read/copy all parts before further large calls.

Generated server and artifact storage IDs use UUIDv4 lowercase hex and exclusive creation. A collision retries with a fresh ID at most three times; exhaustion is `ArtifactStoreError`. Existing index entries/files are never overwritten. Duplicate user logical names remain distinct artifacts.

Artifact-store reservation, write, hash, image revalidation, publication, or terminal-result bound failure is host infrastructure failure. The active bundle is aborted, the Runner/group is destructively cleaned because the public output cannot be completed truthfully, and the call returns `kernel_killed/dead` with `ArtifactStoreError` plus host-only diagnostics.

### Failure precedence

The Supervisor assigns one monotonic intervention marker per active call. A validated terminal `done` closes the intervention window. Exact precedence is:

| First decisive fact before public response | Public outcome | Retained output | Lifecycle action/state |
| --- | --- | --- | --- |
| Valid `done` before any intervention | Existing ADR-0003 completed/failed mapping | All completed items and accepted streams | Reuse Runner; `alive` |
| Deadline marker before valid `done` | `timed_out` / `TimeoutError` if Runner returns in grace | Completed items and all observed streams | Existing SIGINT→TERM→KILL; `alive` only after valid safe `done`, otherwise `kernel_killed/dead` |
| Output-limit marker before deadline and valid `done` | `failed` / `OutputLimitExceeded` if Runner returns in grace | Completed items, accepted stream prefixes, observed discard counts | Same escalation; `alive` only after valid safe `done`, otherwise `kernel_killed/dead` |
| Caller cancellation after `started` | No result is promised to that caller | State retained for the next caller when publication succeeds | Same first-marker and escalation rules; safe `done` leaves `alive`, otherwise `dead` |
| Transport shutdown | No tool result; adapter state `closed` | No recovery claim to disconnected client | ADR-0005 priority shutdown; clean group, then Store; never return to `alive` |
| Store or terminal-result construction failure before response | `kernel_killed` / `ArtifactStoreError` when transport remains | Only bounded stream tails/JSON displays that require no failed publication; no active artifact reference | Abort active bundle, destroy group, `dead` |
| Runner exit, protocol violation, lost response channel, or TERM/KILL escalation | `kernel_killed` with existing exact error mapping | Completed published items and observed streams unless Store failure also occurred | Destroy/verify group; `dead` |

If timeout and output limit become ready in the same event-loop turn, the Supervisor processes the already-scheduled cell deadline before pipe-limit notification; otherwise the first recorded marker wins. A later marker cannot replace it. Store/protocol/death failure is always fatal regardless of a prior nonfatal marker. A `done` validated first wins and later signals are handled by the idle handler. Reset requests are FIFO commands and never overlap an active call; active transport shutdown is the sole priority close path. Execution count remains the validated `started` count on every post-start outcome.

### Public result

Stage 2 replaces the dormant singular `output.artifact` field with per-channel references and adds ordered displays:

```ts
type ArtifactRef = {
  uri: string;
  name: string;
  declaredMimeType: string;
  mimeType: string;
  representation: "raw" | "manifest";
  size: number;
  sha256: string;
};

type DisplayItem =
  | {
      sequence: number;
      kind: "json";
      value: unknown;
    }
  | {
      sequence: number;
      kind: "image";
      mimeType: "image/png" | "image/jpeg" | "image/gif" | "image/webp";
      size: number;
      sha256: string;
      width: number;
      height: number;
      inline: boolean;
      artifact: ArtifactRef;
    }
  | {
      sequence: number;
      kind: "artifact";
      artifact: ArtifactRef;
    };

type OutputInfo = {
  totalBytes: number;
  totalLines: number;
  discardedBytes: number;
  discardedLines: number;
  truncated: boolean;
  limitBytes: number;
  limitExceeded: boolean;
  live: "progress" | "failed" | "unavailable";
  stdoutArtifact?: ArtifactRef;
  stderrArtifact?: ArtifactRef;
};

type PythonExecResult = {
  // ADR-0003 fields remain
  runtime: RuntimeInfo;
  output: OutputInfo;
  displays: DisplayItem[];
  artifacts: ArtifactRef[];
};
```

`sequence` orders explicit helper calls. The `artifacts` array has one total order: completed explicit image/artifact calls by ascending `sequence`, then `stdoutArtifact`, then `stderrArtifact`. Nested references are equal JSON objects, not separate stored copies. JSON displays never enter `artifacts`. A failed/timed-out/limited cell retains transactions completed before interruption. An incomplete transaction is never published. Stdout/stderr remain aggregates; Stage 2 does not claim deterministic cross-pipe ordering or origin attribution.

`totalBytes`/`totalLines` count all stream bytes/lines the host observed before terminal drain or cleanup, including discard-sink observations. `discardedBytes`/`discardedLines` are zero unless the hard limit was enforced and are subsets of those totals. `truncated` retains ADR-0003 preview meaning. `limitExceeded` identifies hard-limit enforcement. The compact encoded `structuredContent` must remain within 4 MiB after all fields are populated; exceeding any item/count/result bound is rejected at the producing helper, while a forged frame or host construction excess is fatal.

### Live text and client fallback

When the request has a syntactically valid MCP progress token, the Adapter activates one request-scoped reporter and attaches a bounded latest-value observer. Progress is the strictly increasing output-event revision; total is omitted. Messages identify `stdout` or `stderr`, contain at most the latest 8,192 UTF-8 bytes, and coalesce to at most 10 sends per second. Display/artifact completion uses generic type/size metadata and never interpolates a user logical name. Progress never contains binary bytes, artifacts, host diagnostics, paths, PIDs, or private-frame data.

The observer queue holds one replaceable snapshot. A slow/disconnected client cannot backpressure stream draining, execution, spooling, or the terminal result. The Adapter cancels and awaits the reporter before returning. `output.live="unavailable"` means no progress token was supplied; `"progress"` means a token activated the reporter and no local SDK send raised; `"failed"` means a local send raised and the bounded exception stayed in host diagnostics. Client receipt/rendering has no acknowledgement and never changes the value. A reporter failure is not an execution/store failure.

The terminal structured result and artifacts are authoritative. AMKernel does not use MCP logging for user streams and does not claim a durable partial-content stream.

### MCP content and resources

For the current negotiated MCP protocol, terminal `CallToolResult` is exactly `resultType="complete"`, `isError=false`, complete `structuredContent`, and content blocks in this deterministic order:

1. one canonical compact-JSON `TextContent` equal to `structuredContent`;
2. explicit display/artifact calls by ascending `sequence`: a JSON display adds no block; an inline image adds `ImageContent` then its `ResourceLink`; a non-inline image or explicit artifact adds only its `ResourceLink`;
3. the stdout artifact `ResourceLink`, then stderr artifact `ResourceLink`, when present.

ResourceLink `name` is generated ASCII `artifact-<artifact-id>`, `title` is the validated logical name, and `mimeType` equals the safe representation MIME in `ArtifactRef`. No raw logical name enters progress. This block order and the `artifacts` array order are fixtures.

The safe advertised MIME allowlist is `text/plain; charset=utf-8`, `application/json`, and the four fully verified raster MIME types. Any other caller declaration, including HTML, SVG, XML, or scriptable/unknown types, is preserved only as `declaredMimeType` and advertised as `application/octet-stream`. Artifact content remains untrusted even when verified as a raster image.

Artifact URIs use `amkernel://artifact/<server-id>/<artifact-id>`. A logical artifact no larger than 8 MiB has `representation="raw"` and that URI returns one base64 `BlobResourceContents`. A larger artifact has `representation="manifest"`, `mimeType="application/vnd.amkernel.artifact-manifest+json"`, and its URI returns strict UTF-8 compact JSON:

```json
{
  "version": 1,
  "name": "validated logical name",
  "declaredMimeType": "caller declaration",
  "size": 123,
  "sha256": "64 lowercase hex",
  "parts": [
    {"uri": "amkernel://artifact/<server-id>/<artifact-id>/part/0", "offset": 0, "size": 123, "sha256": "64 lowercase hex"}
  ]
}
```

Parts are contiguous, ordered, at most 8 MiB, and reproduce the logical bytes/hash. Part URIs return base64 `BlobResourceContents` with `application/octet-stream`. One artifact has at most 32 parts; one execution bundle has at most 66 logical artifacts and 128 physical part files (95 across the 64 explicit/image items, plus 33 across the two combined-limit stream artifacts). The server-generated manifest contains no path and is below 64 KiB. Callers recover it by concatenating every verified part and checking the aggregate hash.

The server advertises resources but returns a stable empty list: `resources=[]`, no cursor, `cacheScope="private"`, `resultType="complete"`, `ttlMs=0`. A successful retained read returns one content object with `cacheScope="private"`, `resultType="complete"`, and `ttlMs=0`. Exactly one resource read is admitted process-wide. Index lookup, a bundle read lease, bounded file load, and expected size/SHA-256 verification occur atomically with eviction; the Store loads at most 8 MiB, verifies the loaded bytes, then may release the lease. Unknown/malformed/evicted/cross-process URIs return resource-not-found. A size/hash mismatch returns a generic resource-integrity protocol error and bounded host diagnostics before any content response. No partial resource response exists.

### Artifact Store threat model and cleanup

The Store creates a randomized root under an operating-system temporary parent, pins parent/root directory handles and device/inode identity, uses mode `0700` directories and `0400` published files, and performs create/read/evict traversal relative to pinned handles without following links. Publication is atomic after exact size, aggregate/part hash, quota, and repeated host image validation. Random URI/storage IDs prevent remote MCP guessing; they and POSIX modes do **not** provide confidentiality or integrity against deliberately hostile same-user Runner code, which can enumerate and tamper with accessible host files. Resource reads therefore reverify loaded bytes, and the public security claim excludes same-user filesystem secrecy.

For cleanup, the Store compares the temporary-parent entry to its pinned root device/inode, atomically renames that exact entry to a generated tombstone through the pinned parent, then unlinks only descriptor-relative known regular files/directories without following links. A missing/substituted identity, unexpected entry type, or traversal failure stops cleanup and reports residue; it never follows or recursively removes the substitute. Reset does not clean the Store. Runtime shutdown first stabilizes/cancels execution and cleans the managed process group, then performs this Store cleanup. Store cleanup never traverses a caller path, workspace, source export, or external resource.

### Ownership

The Runner and Protocol Owner owns helper validation, Pillow validation, and version-2 event production, but never chooses storage paths, URIs, retention, or MCP content.

The Output and Artifact Owner owns aggregation, observers, stream limits/discard accounting, Pillow host revalidation, the Artifact Store, hashes, parts/manifests, quotas, leases, retention, and resource reads. This owner returns typed facts/failures to the Supervisor and never changes lifecycle state directly.

The Runtime and Supervision Owner owns intervention precedence and escalation. The Contract and Integration Lead owns public schemas, negotiated official-SDK result/resource/progress mapping, and serial integration. One owner writes each state machine and shared schema at a time.

## Consequences

### Positive

- Every byte omitted from a normal bounded stream preview is recoverable while its bundle is retained.
- Final results remain authoritative across clients that ignore progress, images, resource links, or structured content.
- Large/binary outputs do not enter `structuredContent`; bounded images use official MCP content.
- Quotas, eviction, and hard limits make memory and storage claims testable.
- Artifact references expose no workspace paths and are served through the official resource interface.
- The five-helper prelude stays automation-neutral; Pillow is the one justified Stage 2 runtime dependency for full per-frame raster decoding after exact container-boundary validation.
- Existing kernel survival and cleanup semantics remain centralized in the Supervisor/Runtime modules.

### Costs and constraints

- Artifact URIs are intentionally ephemeral and may expire before a later large call.
- Every execution that emits stream bytes performs temporary disk I/O even when no final stream artifact is needed.
- MCP progress is only a live preview; hosts may omit or coalesce it.
- Inline image data can still add up to 8 MiB to a tool response.
- A cell that attempts more than 256 MiB of stdout/stderr is interrupted rather than allowed to run with unrecoverable output.
- The public input/output schema and private protocol change together and require an exact installed-client cutover.
- Helper confinement improves safe defaults but cannot constrain unrestricted Python.
- Resource recovery is multi-read for artifacts above 8 MiB; callers must verify a manifest and concatenate its bounded parts.
- Same-user unrestricted code can tamper with host-visible temporary files; AMKernel detects tampering on read but makes no same-user storage confidentiality/integrity claim.

## Alternatives considered

### Use MCP logging notifications for stdout/stderr

Rejected. Logging is not user output, is client-gated, and is deprecated in the current protocol. It also does not provide final recoverability.

### Treat progress messages as the authoritative stream

Rejected. Progress is optional, lossy, rate-limited, and human-readable. It cannot replace final content or artifacts.

### Buffer all output in memory and spill only after the tail limit

Rejected. It recreates Stage 1's unrecoverable prefix problem or unbounded memory use. Spooling from byte one keeps memory bounded and recovery exact.

### Keep unlimited execution and discard bytes after a disk quota

Rejected. It would make `truncated` lie about recoverability and violate the architecture. A hard output limit is explicit and testable.

### Return artifact `file://` paths

Rejected. Paths disclose host layout, couple clients to local filesystem access, and make retention and authorization bypass the Artifact Store.

### List dynamic artifacts in `resources/list`

Rejected. Tool-produced resource links need not be listed, and a stable empty list avoids making resource discovery depend on prior calls on one connection.

### Embed every artifact in the tool result

Rejected. Base64 expands binary data, inflates model context, and defeats bounded response memory. Resource links are the narrow MCP seam.

### Add dependency-specific display adapters beyond raster validation

Rejected. Playwright, Appium, pandas, notebook display protocols, and implicit rich-repr discovery expand core policy without cross-vertical evidence. Stage 2 accepts explicit strict JSON or bytes/MIME only. Pillow is admitted solely as the locked cross-platform raster decoder; exact container boundaries, every-frame `load()`, frame count, and cumulative decoded pixels must all pass before MCP image MIME is used.

### Put artifact storage in the Runner

Rejected. It would mix untrusted evaluation, filesystem retention, URI policy, and MCP mapping. The Runner emits bounded logical events; the host owns persistence.

## Verification

Stage 2 implementation and installed-wheel evidence must prove:

1. exact public schemas, exact version-2 frame schemas/bounds/transitions, prelude signatures, clean reset behavior, and malformed/forged frame fatality;
2. strict JSON ordering, count/encoded-result bounds, zero-byte item floods, mutation retention, and no implicit `repr` conversion;
3. independent Runner/host exact-container and full Pillow frame decoding for valid, truncated, trailing/polyglot, malformed-compressed, MIME-mismatched, dimension, 256-frame, 40-million cumulative pixel-frame, warning, and parser-failure PNG/JPEG/GIF/WebP; exact inline/fallback mapping;
4. text, binary, JSON, maximum-size, duplicate/control-name/MIME, 64+2 item and 128-part bounds, byte quota, partial transaction, collision, and Store-I/O behavior;
5. spooling from byte one; exact-bound success and first-byte/chunk excess; exact accepted/discarded hashes, bytes, and lines; both-channel Python/native/child producers without pipe deadlock; cooperative/ignored interruption; 16/256 MiB plateaus;
6. progress-token/no-token calls through the official client; monotonic revision, bounds/rate, generic metadata, slow-consumer isolation, local reporter failure and truthful `live`, cancellation, and terminal-result authority;
7. exact negotiated `resultType`, `cacheScope`, `ttlMs`, `ResourceLink`, `ImageContent`, canonical `TextContent`, `structuredContent`, and content ordering fixtures;
8. raw and 8 MiB boundary/manifest/32-part recovery; at most one admitted resource read; read-versus-eviction/shutdown races; retained/expired/malformed/cross-process/integrity-failed URIs; bounded encoded-response RSS;
9. 544 MiB reservation arithmetic, charged quota, 66-item/128-part/index/file/result plateaus, whole-bundle eviction, reset retention, ID collision, normal cleanup, substituted-root/entry refusal, crash residue, permissions, tamper detection, and no path disclosure;
10. pinned-descriptor `read`/`write` behavior across relative/absolute, root or parent rename, every-level symlink substitution, traversal, special file, encoding, zero/exact/exceeded bound, replacement race, and unsupported-primitive refusal while preserving the non-sandbox claim;
11. exact `env` missing-versus-`None` behavior and requested package diagnostics for present, absent, normalized duplicate, malformed, oversized/control metadata, closed error vocabulary, and metadata failure;
12. every row and pairwise race in the failure-precedence table, including valid-done boundary, timeout/output simultaneous readiness, cancellation, transport shutdown, store failure, protocol violation, death, reset FIFO behavior, and last-valid diagnostics;
13. canonical static/full-suite gates and a clean-wheel official-client scenario on every claimed Python/OS pair;
14. independent architecture, correctness, security, and behavior review with no remaining Blocker or Major finding.

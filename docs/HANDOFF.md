# AMKernel Handoff

## Task

Resolve the separately scoped post-release core CI defects #114/#115, then continue the owner-authorized ordered real-platform acceptance, real Windows Android verification, and installed-wheel Codex/cross-OS Stage 4 evaluation without changing the public interface or support claims.

## Context

AMKernel stands for **Automation MCP Kernel**.

Its product thesis is:

```text
Coding Agent
  → MCP
  → persistent Python kernel
  → official automation library
  → external system
```

Python execution is the primary Agent interface. AMKernel does not expose a growing set of browser, desktop, or mobile action tools and does not wrap official automation libraries.

Mobile/Appium is the first experimental vertical. It is intended to validate persistent live objects, interruption, screenshots, large element trees, artifacts, test execution, and external-session cleanup. It must not introduce mobile semantics into the generic kernel.

The formal repository was intentionally created design-only. A sibling spike exists, but its files were not copied because the implementation should follow the accepted architecture rather than inherit prototype structure accidentally.

## Relevant files

- `README.md` — product identity, principles, completed Stage 2 status, exact support claim, and canonical document links.
- `docs/architecture.md` — accepted generic AMKernel architecture, core interface, invariants, execution result, runner protocol, output system, security posture, and delivery stages.
- `docs/development.md` — required agent roles, ownership rules, development workflow, quality gates, and definition of done.
- `docs/project-management.md` — milestones, Kanban states, work-item contracts, decision management, risk management, and repository-governance rollout.
- `docs/stage-1-implementation-plan.md` — accepted Stage 1 cross-module contracts, dependency/toolchain policy, path ownership, black-box scenarios, and risk traceability.
- [GitHub Project #2](https://github.com/orgs/FSQ-lab/projects/2) and [repository Issues](https://github.com/FSQ-lab/amkernel/issues) — sole live project status, queue, work contracts, blockers, risks, and verification evidence.
- `docs/stage-3-implementation-plan.md` — accepted M3 issue graph, skill/official-source trust seam, path ownership, fixture/evidence/measurement contracts, mandatory failure matrix, platform gates, and graduation criteria.
- `src/amkernel/distribution.py` and `src/amkernel/skill/` — one uv-managed user Runtime, transactional OMP/Pi/Codex project activation, and the packaged user-centered Agent skill with verified official Appium routes and fail-closed provenance checks.
- `docs/experiments/mobile-appium.md` — experiment hypothesis, scenario matrix, failure cases, measurements, and graduation questions.
- `docs/decisions/` — accepted durable decisions for the implementation stack, GitHub project management, public execution contract, private Runner protocol, and Runtime lifecycle.
- `.github/workflows/ci.yml` — pinned-action hosted CI with quality, clean-wheel package smoke, and six supported Python/OS compatibility jobs; every package job retains its exact evidence JSON, wheel, dependency lock, and hash.
- `.omp/AGENTS.md` — project context; imports the architecture, development process, project-management policy, accepted decisions, and mobile experiment, and requires agents to inspect the active GitHub work item before changing code.
- `.omp/config.yml` — project-local memory (`memory.backend: local`).
- `../omp/` — discarded prototype/evidence only. It contains a TypeScript MCP demo, Python runner, persistence/reset/timeout smoke tests, and an Appium connectivity smoke. Read narrowly if an experiment needs evidence; do not copy wholesale.

## Current state

- Public GitHub repository: `https://github.com/FSQ-lab/amkernel` with local `origin` configured.
- Public organization Project: `https://github.com/orgs/FSQ-lab/projects/2`; GitHub Issues and Project fields are the sole live project-status source.
- ADR-0001 selects a single Python implementation, the official MCP Python SDK, and a uv-managed packaged toolchain. ADR-0003 through ADR-0005 and `docs/stage-1-implementation-plan.md` freeze the complete Stage 1 public contract, private protocol, lifecycle, ownership, test matrix, and evidence plan.
- S1-010 establishes `pyproject.toml`, `.python-version`, a committed `uv.lock`, the `src/amkernel/` package, typed console/module entry points, and package behavior tests. The lock uses the Tsinghua PyPI mirror because the development network restricts direct PyPI access. Runner/Supervisor/Runtime/MCP execution behavior is intentionally not part of this bootstrap.
- GOV-002/GOV-003 establish hosted CI and protected-branch governance. Run `40724547935` passed both stable checks for commit `6089615`; `main` strictly requires `quality` and `package-smoke`, the pull-request path, conversation resolution, and protection for administrators, while owner-approved continuous execution requires zero human approvals. Independent Agent review remains mandatory process evidence.
- S1-020 implements `src/amkernel/protocol.py` and `src/amkernel/runner.py`: exact bounded/correlated frames, isolated bootstrap descriptors, persistent cell state, compile-before-execute trailing expressions, detached structured results, bounded repr/errors, safe SIGINT finalization, fork descriptor closure, and truthful runtime diagnostics. This is a private process seam, not yet an MCP tool.
- S1-030 implements `src/amkernel/supervisor.py`: exact Runner spawn/environment, independent PID observation, nonblocking command acknowledgement, bounded stdout/stderr capture, deadline/cancellation precedence, SIGINT→TERM→KILL escalation, idempotent cancellation-safe shutdown, managed-descendant cleanup, retained startup-cleanup ownership, bounded graceful-shutdown delivery, host-only infrastructure diagnostics, and truthful cleanup failures. Supervisor native tests pass 33 scenarios. Windows remains unclaimed.
- S1-040 implements `src/amkernel/runtime.py`: one FIFO worker, lazy startup, strict single-flight dispatch, queued/active cancellation stabilization, destructive reset ordering, explicit dead-kernel recovery, closed-state shutdown priority, retained cleanup ownership, stable public infrastructure errors, and bounded Supervisor diagnostic propagation. Runtime native tests pass 22 scenarios; its delivery suite passed 120 on the development macOS/Python 3.11 environment.
- S1-050 implements `src/amkernel/server.py` and cuts `src/amkernel/cli.py` over to the official MCP Python SDK's public low-level `Server` and stdio transport. `python_exec` publishes strict, non-nullable input validation and one exact nested output model; completed/failed/timed-out/killed executions remain successful MCP results, while validation/unknown-tool/Adapter defects remain tool errors. JSON text and `structuredContent` match, absent result differs from explicit null, user output cannot corrupt MCP stdout, host diagnostics stay on stderr, and transport close waits for Runtime cleanup with a nonzero cleanup-failure exit. Official Client Adapter/stdio delivery tests passed 19 scenarios; its delivery suite passed 139 on the development macOS/Python 3.11 environment.
- S1-060 adds 30 bounded `tests/integration/` scenarios spanning real Runner, Supervisor, Runtime, Adapter, official Client, raw stdio, and private wire seams. Evidence covers deterministic FIFO/cancellation, real deadline races, reset/death recovery, every managed-descendant destructive path, cleanup-failure diagnostics and exit status, escaped-resource non-ownership, first-byte/full-delivery protocol deadlines, malformed/coalesced/truncated/EOF frames, maximum NUL-expanded code, 16/256 MiB output memory plateau, deterministic output attribution, exact environment complement, raw stdout accounting, and default no-network/no-elevation behavior. The resulting fixes record/replay SIGTERM across transport cleanup and reject missing/duplicate Runner descriptor arguments. Integration tests pass 30 scenarios; the full suite passes 171 on the development macOS/Python 3.11 environment.
- S1-070 adds `tests/e2e/installed_stdio.py` and extends `tests/package_smoke.py` so a clean project `.venv` installs the built wheel and the official MCP Client launches only its installed `amkernel` entry point. The black-box scenario asserts exact discovery schemas and warnings; persistent state; ordinary failure and retained mutation; reset; handled timeout survival; forced death, non-recreation, and explicit recovery; symlinked `project_venv` diagnostics; identical structured/text results; and managed-child cleanup after death and transport close. The macOS arm64/Python 3.11.16 delivery run passed against wheel SHA-256 `9b9ac0c8e3a55888b2baec9dd5c6084e6da4f06fb3883f32a757de549b5d1926`; the repository suite passed 171 scenarios, and independent review found no remaining Blocker or Major issue. No production contract changed; S1-080 remains responsible for native compatibility claims.
- S1-080 approves the bounded contiguous CPython 3.11–3.13 range on GitHub-hosted Ubuntu and macOS. Candidate run `40830237588` passed every Ubuntu/macOS 3.11–3.13 lifecycle, build, and installed-stdio job plus Ubuntu 3.14; macOS 3.14 timed out in the lifecycle suite, and a local macOS 3.14.7 reproduction blocked in CPython's asyncio child reaper after a stopped Runner, so 3.14 remains unclaimed. After restricting the permanent matrix to the approved range, run `40833053864` passed all six compatibility jobs plus quality and package smoke. Independent review found no remaining Blocker or Major issue.
- S1-085 publishes the approved `>=3.11,<3.14` package requirement and exact Python classifiers, constrains lock resolution to the same range, and documents only the qualified hosted Ubuntu/macOS support claim. Local closure gates passed 172 scenarios and installed wheel SHA-256 `e1b6e97aefedbae3fb5b34467f450c98b6b53a1e2ff6822f47d437621bee21c2`; hosted run `40834514852` passed quality, package smoke, and all six compatibility jobs. R-001 through R-014 have resolved or explicitly accepted final Stage 1 states, and independent closure review found no remaining finding.
- REL-001 defines the pre-1.0 version/changelog, immutable tag, evidence-qualified support, retained-artifact provenance, trusted-publishing, rollback, and yank procedure. CI retains only the exact wheel exercised by `package-smoke`; the untested sdist is explicitly excluded from release. Hosted run `40840708426` passed quality, package smoke, and all six compatibility jobs and retained `distribution-ed34c39483b3b9e45becd38c4bed1e1ecfa2f8e1` (35,222 bytes). Independent review found no remaining issue after requiring wheel-only retention and synchronizing the cleanup/output test seams.
- S2-001 accepts ADR-0006 and `docs/stage-2-implementation-plan.md`, establishing the Stage 2 milestone contract, module ownership, bounds, dependency graph, cross-cutting evidence matrix, and risks R-015 through R-020. S2-010 freezes the literal public v2 discovery schema, strict private protocol-v2 frames and sequence/transaction validator, exact malformed-frame mapping, dormant-event rejection, cancellation-safe post-terminal fatal handling, and centralized output/resource/image/package bounds. S2-020 implements the process Artifact Store, exact raw/manifest resources, collision-safe reservations, quota and whole-bundle eviction, one-read admission with leases, digest verification, descriptor-relative identity-safe cleanup, Runtime retention/shutdown ownership, and official MCP resource handlers. S2-030 adds bounded complete stream recovery, canonical stream artifacts, exact combined accounting, post-limit draining, terminal-observation attribution, and Store-failure teardown. S2-040 installs reset-restored and persistently shadowable `display`/`artifact` helpers; emits ordered strict-JSON and interrupt-atomic artifact/image protocol transactions; validates exact PNG/JPEG/GIF/WebP containers and every decoded frame in Runner and Host; publishes only complete transactions; preserves arbitrary declared MIME while promoting only validated safe content; maps ordered displays/artifacts; and bounds the compact terminal result under UTF-8 replacement expansion. S2-050 installs reset-restored and persistently shadowable `read`/`write`/`env` helpers; pins the actual launch directory handle and identity; walks relative and absolute-in-root paths descriptor-relatively without following links; restricts reads to bounded regular files with strict UTF-8; atomically replaces regular destinations with mode-`0600` files through pinned parent handles; and implements detached environment snapshots plus exact get/set/delete semantics without a sandbox claim. S2-060 validates PEP 503-normalized requested distribution names before dispatch; performs ordered selected-Runner metadata inspection after completed or failed cells inside the cell deadline; publishes only bounded control-free versions or the closed three-value error vocabulary; never inventories implicitly; and retains last-valid selected-Runner diagnostics across death and failed reset while refreshing only after successful replacement. The repository suite passes 237 scenarios; Ruff and mypy pass; independent correctness and security review found no remaining Blocker or Major issue. GitHub Project #2 advances to S2-070.
- S2-070 maps complete v2 execution output through official MCP SDK types: canonical JSON plus deterministic ImageContent/ResourceLink ordering, generated resource names and logical titles, private complete zero-TTL raw/manifest/part reads, and request-scoped one-slot progress with channel/type metadata, 8 KiB/10 Hz bounds, exact unavailable/progress/failed fallback, and terminal authority under blocked or failed reporting. The final Ruff, mypy, and 244-scenario suite passed; independent correctness and security re-review found no remaining Blocker, Major, or Minor issue. Store/result-construction fatal lifecycle integration remains deliberately owned by S2-080.
- S2-080 unifies output-limit, cancellation, deadline, shutdown, protocol/death, Store, and result-construction intervention semantics. Same-turn deadline/output-limit readiness is deterministic; earlier cancellation/limit markers retain timestamp order. Fatal paths preserve exact bounded output fields, serialize terminal construction inside Runtime FIFO, destructively clean the managed Runner, and retain failed staged/published/writer deletion progress for retry. Artifact URIs revoke before deletion, deleting bundles remain quota-charged until physical removal, reset cannot replace the Runner while output cleanup is pending, and persistent shutdown cleanup faults return truthful retryable results. Ruff, mypy, and the full 254-scenario suite pass; independent correctness and security review report no Blocker, Major, or Minor finding.
- S2-090 and PR #66 close Stage 2. The final main hosted run passed quality, package-smoke, and Ubuntu/macOS CPython 3.11–3.13 compatibility against retained evidence. M3 and Issues #68–#74 now define the ordered Stage 3 Mobile/Appium experiment; S3-001's plan passed independent review with 0 Blocker / 0 Major / 0 Minor findings.
- S3-010 pins `appium/skills` commit `e907024c210fe024c956ed9c74146fc27b1dd013` and Skills CLI 1.7.4, verifies the canonical detached Git tree plus `.agents` runtime and `.claude` selected-agent copies, and provides one project-local direct Appium Python procedure. The skill keeps server/device ownership external, reuses one persistent driver, uses explicit waits, bounds status/source/screenshot evidence, fails closed on source drift, prohibits automatic SDK bootstrap/shared ADB resets/unscoped mutations, and preserves cleanup identity until `driver.quit()` succeeds. Focused verification passed 5 tests plus Ruff, mypy, the real 134-file/copy verifier, and local Skills CLI discovery; independent security/workflow review found 0 Blocker / 0 Major / 0 Minor.
- Issue #88 and ADR-0007 replace the interim separately installed `amkernel-appium` entry with one packaged `amkernel` skill and CLI. `amkernel install` installs or reuses one global uv tool, copies the version-matched skill into the project, writes one native project MCP entry, and records only managed project references. Update, project uninstall, and global uninstall preserve explicit scope, consent, rollback, and ownership.
- Issue #119 keeps ADR-0007's single-client ownership while improving interactive installation: one detected client remains automatic, ambiguous candidates open a single-choice prompt, no candidates offer all supported clients, and non-interactive installation still requires explicit `--client`. Install plans distinguish the shared user Runtime from project-local Skill, official-source, and native MCP activation.
- S3-020, S3-030, and S3-040 are complete: frozen fixture/evidence contracts and passing Android
  and iOS reference records are retained under `evidence/mobile-appium/`. Independent review
  findings on baseline provenance, fresh-start identities, post-transport kernel state, and portable
  artifact paths were fixed; both retained records validate in place.
- S3-050 exercises all 19 frozen lifecycle failures as 33 platform-tagged occurrences. The aggregate
  `evidence/stage-3/lifecycle.json` validates against the frozen evidence definitions, hash-links every
  bounded transcript and both platform reference manifests, preserves failure-time state separately
  from cleanup, and reports no remaining external resources. Exact semantic guards cover live-session
  Runner death/reset, actual UiAutomator2/WebDriverAgent termination, genuine stale elements, observed
  offline devices, and injected endpoint state. Focused verification passed 29 tests plus Ruff and
  mypy; final independent rereview found 0 Blocker / 0 Major / 0 Minor findings. Production
  `src/amkernel/` remains unchanged.
- S3-060 graduates the Mobile/Appium experiment through the portable, schema-validated
  `evidence/stage-3/index.json`. The index hash-links the selected Android, iOS, and lifecycle
  records; maps all 10 criteria, 12 measurements, 19 failure cases, 33 required occurrences, and
  6 canonical review dispositions; and rejects missing mappings, modified identities, or lifecycle
  evidence tied to different platform runs. `evidence/stage-3/decision-report.md` recommends Stage
  4 cross-client validation while retaining an experimental/unsupported claim, external Appium and
  device supervision, and no mobile-specific core interface. Focused verification passed 37 tests
  plus Ruff and mypy; final independent review found 0 Blocker / 0 Major / 0 Minor findings.
- S4-001 freezes one client-neutral installed-wheel scenario and executable evidence contract under
  `tests/fixtures/cross_client/` and `tests/e2e/`. The contract binds per-step semantics, request/result
  measurements, retry attribution, resource reconstruction, readiness/outcome/cleanup truth, and
  privacy-safe normalized evidence without retaining raw code, model prose, credentials, or local
  paths. Focused verification passed 39 tests plus Ruff and mypy; final independent review found
  0 Blocker / 0 Major / 0 Minor findings and certified S4-010, S4-020, and S4-030 Ready.
- S4-005 adds the independently certified GitHub Issue #82 naturalistic dependency investigation
  without weakening S4-001. Codex CLI and GitHub Copilot CLI receive identical outcome-based text,
  choose their own `python_exec` decomposition, and run from empty ephemeral client workspaces with
  complete tool-attempt auditing. An independent oracle verifies graph results and JSON artifacts;
  retained PNG data plus semantic review verify the visible chart. Final independent review found
  0 Blocker / 0 Major / 0 Minor findings.
- Global OMP memory is disabled; this project uses local project-scoped memory.
- The sibling `/Users/qunmi/Documents/FSQ_LAB/omp` remains untouched as historical discussion/prototype material.

## Release 0.1.1 and post-release verification

PR #110 merged the completed remediation and retained evidence. Release PR #112
merged through protected `main` at `e16f42727b32a30fd431e4504712a5f31c28b408`;
its PR and exact-main CI run `41612230439` each passed all eight jobs. Release
Actions run `41613732304` published the unchanged main-CI wheel to the immutable
GitHub `v0.1.1` release and PyPI. Wheel SHA-256:
`a72cacb0de33335026e0b03e0686d115c8366c4e012f84fe6f4973e1ebcc608f`.
Release Issue #111 is closed. Qualified support remains Ubuntu/macOS CPython
3.11–3.13; mobile remains experimental and Windows remains unqualified.

`evidence/appium-skill/published-011-install-20261103.json` retains the actual
published-wheel external-directory stdio/persistence smoke, complete Copilot
installation, and parent-observed receipt/MCP/native-interpreter/cwd linkage.
Private paths and raw events are withheld; this is not an independent installation
replay or byte-for-byte verification of installed package files.

The next actual native Copilot Mac2 attempt is **not-qualified**, retained in
`published-011-mac2-20261103.json`. No successful session or live Calculator/window
query occurred. Failed/alive calls remain visible. Desktop restoration is false;
owned server/group/ports/Runner disappearance was observed separately. A later
read-only host observation explicitly returned a locked session and loginwindow
foreground. Further UI work needs manual owner unlock; do not unlock automatically
or change settings. This current prerequisite does not establish the cause of the
earlier Mac2 process-not-running error. Historical qualified `mac2-m0-20261103.json`
is unchanged. Independent artifact review has 0 Blocker/Major/Minor findings in
`published-011-review-20261103.json`; review does not make the failed run pass.

Keep the fixed sequence: install smoke → Mac2 → Android → iOS simulator → physical
iOS → independent review. Downstream formal platform runs have not started.
Current simulator discovery returned zero available/booted devices; physical Apple
discovery returned one connected development-enabled target, not XCUITest readiness.
Existing task-local Java 17 and Android SDK/adb were found and execution-validated;
no new dependency installation or shared ADB startup was performed in this attempt.

Windows prerequisite discovery found no authorized reachable Windows/Android host
or repository self-hosted runner. No actual Windows command or failure was
observed. `published-011-windows-readiness-20261103.json` distinguishes those facts
from static shipped-code POSIX requirements: Artifact Store startup, Supervisor
spawning/control and Runner signal initialization lack native Windows support.
Windows needs the separate accepted platform design required by #100/ADR-0005;
do not remove guards or weaken file-identity/owned-cleanup contracts as a shortcut.
A new authorized hosted Windows job can supply lifecycle-only evidence, not the
required Android-device scenario. Missing existing jobs do not prove hosted
execution impossible. Issue #100 records the investigated limits and dependencies.

Issues #102, #103, #104, #106, #107 and #108 are closed against their completed,
merged and independently reviewed defect contracts. #98 and #105 remain open for
the outstanding actual-platform sequence; #100 still requires real Windows evidence.
The latest read-only Project #2 check has #81 Planning and #79/#82 Ready.
Available credentials have `read:project`, not board-write scope; issue updates do not imply board changes.
Complex Mac #109, dynamic-list #97 and Gmail privacy expansion #99 stay deferred.

## Stage 4 Codex blocked reference

`evidence/stage-4/codex/evidence.json` records two real supplementary Codex
`0.162.0-alpha.17.2` launches using the published 0.1.1 wheel above. The configured
model-provider route at `http://127.0.0.1:23333/api/openai/v1` was unreachable.
Both launches timed out near 180 seconds with null recorded exit codes. Client
`turn.started` events exist, but no completed model turn, model-generated response
or tool call was observed. Neither frozen client layer was entered; outcome stays
`blocked`. Cleanup flags describe only those unentered layers, not independently
observed supplementary process-tree cleanup. Historical launch logs are unchanged.

The separate `validation/` report records 21 server-level MCP checks. It is not
Codex execution or naturalistic #82 evidence. Omitted multipart payloads prevent
replaying historical part reads from the retained directory alone; the executable
digest identifies the launch file, not independently the native binary behind it.
Independent blocked-record review found 0 Blocker/Major/Minor findings.

A later real harness rerun aborted after approximately 360 seconds because its
source snapshot changed while the isolated harness was being edited. It emitted
no evidence record and is not included in the retained reference; its client
events cannot be replayed from this directory. Do not count it as a valid client
evaluation or infer additional execution/cleanup outcomes from its abort.

The runner now verifies exact published-wheel bytes, keeps wheel source identity
separate from harness identity, and stops supplementary launches at the first
observed item execution. It retains prose-free, bounded diagnostics before raising
mutation, incomplete-audit or execution failures; it never silently relaunches or
labels those failures blocked/passed. Independent static harness review found
0 Blocker/Major/Minor findings; no real-model positive-path execution was observed.
A separate actual external-wheel installation/stdio smoke verified the inferred
interpreter, distinct source/harness provenance, persistence and exact artifact
resource reads. A synthetic external CLI process verified a late tool event is
retained, only one launch occurs and no raw model prose/arguments or false
blocked/pass record is retained. Synthetic checks are not client qualification.
Issue #81 remains open until the configured provider and client can execute the
unchanged deterministic and naturalistic layers; no alternate provider, credential
or persistent configuration was silently introduced.

These corrections and blocked-reference evidence merged through PR #117 at
`771397f96fb0d3c2d2d0278443c0a9d4cb1fe0dc` after all eight PR CI jobs passed
in `41623314474`. The merge does not qualify either Codex evaluation layer.

## Post-release core CI defects

Exact-main CI `41618289181` at `43114989275d6e287dc506c2cc2fd614d1f383da`
failed independently of PR #113's eight passing jobs. Ubuntu/Python 3.11 reported
an asynchronous `InvalidStateError` during storage-failure cleanup (#114);
macOS/Python 3.13 returned `kernel_killed` in the 1 ms artifact deadline test,
whose assertion only allowed a live Runner (#115). Do not rerun these away or
fold production fixes into Stage 4 evidence-only ownership.

#114 has a deterministic failing-before/passing-after cancellation regression.
The zero-delay timer now reuses the existing cancellation-safe Future resolver;
its ordering and task cancellation remain unchanged. The regression and existing
storage-failure consumer test passed. A separate actual Runtime/spawned-Runner
smoke first returned 42, then an injected Store failure returned
`kernel_killed/dead` with `ArtifactStoreError`, no active artifact references,
successful shutdown cleanup and no event-loop errors. Independent source/test
review found 0 Blocker/Major/Minor findings.

#115 replaces the scheduling-dependent 32 MiB/1 ms test with two controlled
real transaction-boundary cases. Cooperative interruption must report
`timed_out/alive` and retain both complete artifacts; forced termination must
report `kernel_killed/dead`, discard the incomplete transaction, preserve the
earlier complete artifact and reject subsequent execution without replacement.
Both cases passed; exact bytes, sizes and SHA-256 digests are checked through
consumer resource reads. A separate actual stdio MCP smoke from a temporary
external workspace observed the same outcomes with natural one-second deadlines,
including a live subsequent result of 42 versus `KernelUnavailable` after death.
Independent source/test review found 0 Blocker/Major/Minor findings. This is
transaction atomicity/lifecycle evidence, not wall-clock deadline accuracy or
published-wheel/platform qualification.

Both fixes merged through PR #116 at
`fd2c3041cb8efc17974284efcea0d54d33ca0135`. All eight PR CI jobs passed in
`41621336861`; the separate local quality gate passed 595 tests, Ruff formatting
and lint, mypy (63 files) and wheel build. The original failed-main run was not
rerun. The fixes are unreleased. Fresh exact-main CI `41623110888` passed all
eight jobs after the merge; this is separate from the original failed run.

## Stage 4 cross-OS process evidence

The S4-030 runner executes the unchanged nine-row matrix through an installed
wheel in isolated workspaces. The hosted workflow covers Ubuntu/macOS with
CPython 3.11/3.13, retains existing failed reports, emits validation summaries, and
combines only records bound to the exact workflow invocation and wheel identity.
An optional published wheel requires its digest and a separate pinned source
checkout; package bytes are compared with that source rather than the newer
harness checkout. No production Runtime behavior or frozen matrix was changed.

A parent-run macOS/CPython 3.11 smoke observed nine passed rows using published
0.1.1 wheel `a72cacb0de33335026e0b03e0686d115c8366c4e012f84fe6f4973e1ebcc608f`
and source `e16f42727b32a30fd431e4504712a5f31c28b408`; independent validation
reported no problems. This remains local evidence, not hosted four-environment
qualification. Full-record negative checks reproduced three pre-fix acceptances
and post-fix rejections: self-approved review, altered frozen matrix metadata,
and contradictory timeout transition status. Those mutations are synthetic
validator checks, not platform observations.

Hosted run `41625606905`, attempt 1, observed all 36 cells passing across the four
environments. Original reports, the unchanged pending-review index and selected
actual matrix/validation/aggregation logs are retained under
`evidence/stage-4/process/source-41625606905/`. Parent aggregation reproduced
index hash `3a3199a9bab97f715554318b9bb7e17cba4041cac331c9b03cb54a4b6daa3fbc`.
This run built current source at PR merge SHA
`46495b43522b99d23b77125cd0a8ecfb304086d2`, not head-branch SHA
`737bbd09a5874d1b0131b9dafaa4ab6f4db4dc9e`. Its wheel digest is
`4c3029c083fecef50871636ce2d90670c5b54738a93aa141a83f558e3c6f1e77`;
this includes unreleased fixes and is not published-0.1.1 qualification.

Independent static Runner and validator reviews found 0 Blocker/Major/Minor findings. The
normal-shutdown bound excludes the SDK's later escalation path by elapsed time,
not signal tracing. Cancellation's final count derives from its single executing
request; no terminal response is received after disconnect. Descendant reset
ordering, live malformed-control injection, and separate MCP cancellation
notifications remain outside this frozen matrix. Windows, Android and iOS are
not claimed. Independent lifecycle and provenance/privacy evidence reviews each
found 0 Blocker/Major/Minor findings; `review.json` records acceptance separately
without rewriting the original pending-review reports/index. The retained
`sourceRootKind=pinned-release-source` denotes a separate source directory, not
verified publication. The actual digest and source revision above control claims.

## What was tried

- A small MCP v2/TypeScript + Python subprocess spike was built in `../omp`.
  - It demonstrated persistent namespace, trailing expression values, failed-cell survival, reset, timeout with SIGINT recovery, workspace confinement, and Appium Python Client connectivity.
  - It was rejected as production scaffolding because it was intentionally minimal and the formal module/interfaces had not yet been agreed.
- A conventional Mobile Use architecture was drafted around `MobileSession`, structured mobile actions, device brokers, and flow runners.
  - It was rejected because it displaced the central idea: the Agent directly generates and executes Python against official automation libraries.
- A mobile-only project identity was considered.
  - It was rejected because the same kernel can later support Playwright, Selenium, pywinauto, PyAutoGUI, macOS Accessibility, and other Python automation ecosystems.

## Decisions

- **Name:** AMKernel — Automation MCP Kernel.
- **Tagline:** Persistent Python execution for agentic automation.
- **Primary interface:** one Python cell execution tool.
- **Initial lifetime:** one stdio MCP process owns one persistent Python kernel.
- **No runtime ID initially:** process lifetime already scopes ownership.
- **Execution semantics:** state persists; calls serialize; ordinary cell errors do not kill the kernel; mutations before an error may remain.
- **Timeout semantics:** interrupt first, escalate only when necessary, and always report whether the kernel survived.
- **Result semantics:** typed status, stdout/stderr, trailing value, traceback, execution count, duration, kernel state, output metadata, and artifacts.
- **Output:** structured JSON, images, and artifact-backed large output are first-class requirements.
- **Automation libraries:** use official libraries directly; do not build replacement wrappers.
- **Platform knowledge:** begin in skills, experiments, and integration tests.
- **First experiment:** Mobile/Appium, covering iOS simulator and Android emulator.
- **Large trees:** raw values initially; cap/spill output and use local Python reduction. Normalization/diffs are deferred until measured need.
- **Appium server:** managed externally by the Coding Agent’s process/shell facilities during the first experiment.
- **Security:** local stdio, same-user Python code execution; not a sandbox.
- **Memory:** project-scoped only; no global memory.

## Implementation record and superseded execution queue

The owner previously authorized sequential first-release Appium remediation before Stage 4 runs. The release/status section above supersedes this historical execution queue.
Separate defects own the work: [#102](https://github.com/FSQ-lab/amkernel/issues/102) compatibility,
[#103](https://github.com/FSQ-lab/amkernel/issues/103) Mac2 routing,
[#104](https://github.com/FSQ-lab/amkernel/issues/104) complete Copilot installation,
[#105](https://github.com/FSQ-lab/amkernel/issues/105) external-project installation verification,
then [#98](https://github.com/FSQ-lab/amkernel/issues/98) real Agent behavior. Environment discovery
[#106](https://github.com/FSQ-lab/amkernel/issues/106) and owned-state/conversation behavior
[#107](https://github.com/FSQ-lab/amkernel/issues/107) remain separate contracts. Gmail privacy
expansion #99 remains post-v1; Windows Android #100 still requires real Windows evidence.

#102 now distinguishes constraints, tested coverage, observed failures, and proven incompatibility.
`evidence/appium-skill/compatibility-20261102.json` retains bounded real Copilot CLI 1.0.105 /
gpt-6.1-sol calls: actual Python 3.11.16, Appium 5.2.5, Selenium 4.52.0, satisfied installed
requirements, no session or dependency mutation. Both baseline and updated audits classified the
pairing as unverified; this prompt did not reproduce a baseline hard-block. Independent Skill
review found 0 Blocker/Major/Minor. Three focused provenance-verifier tests and Ruff passed.

#103 adds the pinned Mac2 Skill and explicit host/target routing. Real Copilot route probes in
`evidence/appium-skill/mac2-routing-20261102.json` chose `setup-mac2`, observed `Mac2Options`
defaults (`Mac`/`Mac2`) through `python_exec`, and rejected XCUITest fallback and Windows Mac2.
Both added official files matched the existing pinned source digests. These are route/options
checks, not a Calculator session or a platform support claim. The separate new
actual M0 Calculator baseline is recorded below; it does not relabel these probes.

#104 now installs the main Skill, every referenced official Skill, and the complete pinned
source archive without a development checkout or runtime network fetch. Copilot edits only
its active project MCP file, preserves unrelated entries, and still requires explicit folder
trust. Exact archive/source/copy hashes, receipt/runtime version, linked-path rejection,
transactional upgrades, foreign-file preservation, and rollback file/directory permissions
are checked. Focused installation/verifier/CLI checks: 59 passed; Ruff, mypy (53 source files),
and wheel build passed. Final independent review has zero surviving findings. A clean external
project and actual GitHub Copilot CLI 1.0.105 / gpt-6.1-sol passed 12 installation checks,
including native Skill/MCP discovery, native loading of the fifth official Skill
`xcuitest-real-device-config`, two persistent `python_exec` calls, fail-closed tamper
and missing-copy repair, and native MCP coexistence in both existing-file layouts.
This is installation evidence, not physical Mac2/Android/iOS or Windows qualification.
Retained installation evidence is `evidence/appium-skill/copilot-install-20261102.json` (#105).

#98 now has observed native installed-Skill/MCP behavior for all 16 synthetic
scenarios through Copilot CLI 1.0.105 / gpt-6.1-sol. Retained evidence is
`evidence/appium-skill/agent-behavior-20261103.json`; earlier failed runs remain
unchanged beside it. The initial matrix also exposed a real Mac2 action-limit
violation hidden by its old oracle: cleanup clicked a second time. Skill guidance
and the final oracle preserve requested end state and enforce action limits across
execution and cleanup. Exact report controls replace prose-based status inference;
ambiguous-submit reconciliation requires a later successful completed/alive call
observing the actual result. Global cleanup claims are checked against observed
session, server and restored state. User configuration hashes remained unchanged;
owned Runner exits are observed without claiming external-session cleanup after
kernel death or deliberate DELETE failure. Full pytest: 443 passed; final focused
checks: 38 passed; Ruff, mypy (55 source files), and wheel build passed. These are
synthetic behavior results, not physical Mac2/Android/iOS or Windows qualification.
Independent final source/protocol/guidance and all-scenario evidence review found
0 Blocker / 0 Major / 0 P2; the retained review and source/evidence digests are in
`evidence/appium-skill/agent-behavior-review-20261103.json`.

#106 now has four passing native installed-Skill/MCP discovery cases: read-only
actual-host discovery and synthetic explicit-Java preference, bundled-JBR fallback,
and missing-capability environments. Final evidence is
`evidence/appium-skill/environment-discovery-20261103.json`; the first run and the
second run's two contract/oracle failures remain separately retained. Executable
journals cross-check candidate existence, exit codes, actual version/home facts,
and separate physical/simulator inventories against both printed and final facts.
Approval flags concern the current request; readiness counts concern listed targets,
so an independently observed empty population permits zero without qualifying the
host. Nonempty unverified readiness remains unknown. Actual user configuration,
profiles, active Xcode selection and observed service state remained unchanged;
owned Runner exits were observed. Full pytest: 469 passed; Ruff, mypy (58 source
files), and wheel build passed. No Appium session was created, and no physical
platform or Windows support is established by these discovery results.
Independent final source and four-case evidence review found 0 Blocker / 0 Major /
0 P2; exact source/evidence digests and review limits are retained in
`evidence/appium-skill/environment-discovery-review-20261103.json`.

#107 now has completed Skill guidance and synthetic native-client verification
for conversation/thread selection and task-owned visible-state restoration.
Thread activity is distinct from nested-message recency; search/local filtering,
timezone/precision evidence, refresh relocation and returned post-open identity
are checked. Context/unknown fields cannot manufacture identity, semantics and
precision metadata cannot stand in for timestamps, and narrowed searches do not
erase unresolved earlier ties. Later disjoint normalized time intervals can
resolve them. Approval, restoration-before-quit and separate cleanup outcomes
remain observed contracts, not Runtime workflow APIs.

#107 final verification at its recorded revision: **514 pytest passed**, Ruff passed, mypy passed
(60 source files), wheel build passed, and the full installed-wheel/native Copilot
matrix **18/18 passed** with unchanged recorded user configuration and observed
owned Runner exits. Independent final source/artifact review: **0 Blocker / 0
Major / 0 P2**. Final evidence, failed/intermediate iterations, source digests and
review limits live in `evidence/appium-skill/conversation-final-20261103.json`,
`conversation-review-20261103.json` and `final-provenance-20261103.json`. The final
native uncertainty case covers coarse timestamps; other temporal/incomplete-search
branches have regression coverage, not an additional physical-platform claim.

The original ordered platform run is retained unchanged: external Copilot
installation passed; initial Calculator/Mac2 created no successful session;
Android discovery found no working Java/SDK/adb with unknown target counts;
simctl returned zero runtimes/devices and devicectl returned zero physical targets.
No dependency/runtime installation, pairing, permission, signing, simulator boot
or global Xcode change was silently performed. Windows #100 still lacks a
reachable host/Android target.

The owner-authorized Mac2 retry subsequently created one real Calculator/Mac2
session, observed foreground state `4` and one window, restored the initial
Calculator/frontmost-app state, deleted the session, observed an empty session
listing before server shutdown, and observed owned server/group/ports/Runner exit.
Unchanged retry evidence is `evidence/appium-skill/mac2-retry-20261103.json`.
Its original overall result remains `not-qualified`: the historical
`nativeMcpCompletedAlive` predicate requires every call to complete successfully
despite observed recovery with live kernels. The original evidence is unchanged.

[#108](https://github.com/FSQ-lab/amkernel/issues/108) now replaces that blanket
predicate with timestamp-bound recovery, independent target/restoration/cleanup
checks, and four canonical report checks. Focused behavioral regressions: 79
passed; full pytest: 593 passed. Ruff and mypy (63 files) passed. New actual
external-project/native Copilot
M0 evidence is `evidence/appium-skill/mac2-m0-20261103.json`: failed/alive execution
2 is retained, and both actual Mac2/Calculator live queries occur inside later
successful execution 6. One session, restoration before DELETE, empty session
listing before server stop, and owned server/group/ports/Runner exit were observed.
All 24 flags pass; the final report is completed/restored/cleaned/not-owned.
Independent source and actual-evidence review: 0 Blocker / 0 Major / 0 Minor.
Review record: `evidence/appium-skill/mac2-recovery-review-20261103.json`.
Source/wheel/client identities and frozen verifier source are retained in
`mac2-recovery-source-20261103.json`. This is not a Runtime, dependency-conflict or
tablet finding; the preparation error's exact cause remains unestablished.
See `docs/experiments/appium-agent-behavior.md` §13 for evidence boundaries.

**Deferred by owner:** complex Mac scenarios under
[#109](https://github.com/FSQ-lab/amkernel/issues/109), including TextEdit
multi-window identity, edit/save/reopen, collision handling, Finder relocation,
cross-app continuity and interruption/partial cleanup, belong to later evaluation.
Mac is not the highest current priority. Stop M1–M7 execution and associated
verifier development; they are not current delivery or ordinary-app gates.
#108/M0 remains qualified. All three M1 attempts remain not-qualified; M2–M7 have
not run. The retained evidence below is historical, not an instruction to resume
this supplement. Earlier 57 isolated boundary checks and a clean source review
missed the Major verifier defect later exposed by actual execution.

The owner-observed unchanged-procedure retry is retained in
`evidence/appium-skill/mac2-m1-visible-20261103.json`, with source/preflight in
`mac2-m1-visible-source-20261103.json` and independent review in
`mac2-m1-visible-review-20261103.json` (0 Blocker / 1 Major / 0 Minor).
Unlike the earlier empty-window attempt, it observed actual Mac2 window clicks
and scoped descendant-content reads. Its four failed flags share a predicate
that incorrectly requires a query-local window ID to survive re-query. However,
startup already exposed two target-title windows; later three target-title
windows had indistinguishable synthetic text. Underlying paths and same-logical-
window continuity remain unproved. Do not remove the ID comparison and promote
this ambiguous result to passing. All 16 Python executions reported live kernels;
synthetic files were unchanged, TextEdit was absent and Ghostty foreground after
cleanup, with owned session/server/group/ports/Runner exit observed. This does not
prove startup-window ownership or preservation of unrecorded application history.

The earlier post-run lock observation remains historical evidence, not the
established cause of its empty-window failure. The owner reported disabling lock;
latest preflight observed Ghostty foreground, an active console, no TextEdit, and
no returned lock key (not an explicit false). Do not require another lock-setting
change or attribute the current identity failures to lock. Original failed and
diagnostic records remain unchanged; regression order and deferred #97/#99 remain.


Next: focus on ordinary Appium app operations—opening an app, finding an element,
clicking, entering synthetic text and checking a simple visible result—with
proportionate identity, approval and owned-cleanup checks. Resume the existing
first-release platform priorities; do not extend the already-qualified cheap Mac2
baseline into another complex Mac campaign. Re-discover available Android/iOS
prerequisites rather than treating older discovery as current readiness.

Keep #109 for later evaluation, with no deadline or release gate inferred. The
unresolved verifier/identity issues are retained, not repaired or waived by this
deferral. Subsequent task-only isolation and identity work stopped as unverified
temporary drafts; no new UI run, source qualification or permanent setting change
followed. Retained procedure/reviews remain in `mac2-applications-source-20261103.json`
and `mac2-applications-review-20261103.json`. No Runtime, public tool or support
claim changes.

Owner-supervised ordinary mobile operations subsequently completed on Android
(Calculator, Clock and Edge; Notes explicitly skipped) and a physical iPhone
(Calculator, Clock, Notes and Edge). See
`docs/experiments/appium-agent-behavior.md` §15 for observed results, approved
task-local preparation, RemoteXPC recovery and verified tunnel cleanup. These are
simple functional observations, not retained raw mobile evidence, independent
platform acceptance, or completion of the fixed regression sequence. Android's
initial tab-selection restoration and iOS's initial Settings foreground were not
verified; browser history, approved pairing/permission choices and installed
toolchains remain. No production code, public interface or support claim changed.

Project #2 still lists S4-010 as In Progress and S4-030/#82 as Ready. The current credential has
`read:project`, not board-write scope; the execution override and dependencies are recorded in
Issues #102 and #81 rather than falsely claiming a board update. S4-001/#82 stay frozen and
evidence-only items do not own these production changes. After remediation, resume S4-010 with
both client-neutral layers through the installed wheel; preserve the experimental mobile support
boundary and external Appium/device ownership.

## Acceptance criteria

- [x] M3 and S3-001 through S3-060 are registered in GitHub Project #2 with exact dependencies and work-item contracts.
- [x] `docs/stage-3-implementation-plan.md` maps every graduation criterion, all 19 failure cases, all 12 measurements, exact paths/owners, and retained evidence requirements.
- [x] Independent S3-001 review found 0 Blocker, 0 Major, and 0 Minor findings after synchronizing Issues #71 and #69.
- [x] S3-010's official Appium inputs are pinned and independently verified before use.
- [x] S3-020 establishes deterministic Android/iOS fixtures and versioned evidence records before platform execution.
- [x] S3-030 and S3-040 retain schema-valid passing Android and iOS reference evidence.
- [x] S3-050 retains all 33 required failure occurrences with explicit lifecycle and cleanup state.
- [x] S3-060 independently reviews graduation evidence and records the Stage 4 recommendation.
- [x] S4-001 freezes and independently certifies the client-neutral scenario, normalizer, evidence
  schema, executable validator, and mutation coverage before either client run begins.
- [x] S4-005 independently certifies GitHub Issue #82 as the identical, outcome-based naturalistic
  task for both client runs, with auditable tool restrictions and oracle-verified deliverables.

## Constraints

- Correctness before breadth.
- Keep the model-facing interface small.
- Use official MCP SDK behavior rather than hand-rolled JSON-RPC.
- Treat stdout as potentially hostile to protocols.
- Do not suppress failures or silently recreate state after kernel death.
- Do not claim sandboxing.
- Do not add speculative abstractions for future platforms.
- Do not delete or modify the sibling `../omp` directory without explicit user instruction.

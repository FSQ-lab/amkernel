# Agent Behavior Experiment: Appium Skill

Status: native installed-Skill/MCP behavior observed for all 16 synthetic scenarios
with GitHub Copilot CLI 1.0.105 / gpt-6.1-sol. No physical-platform qualification.

Issue: #98. Related contracts: #102 (compatibility behavior), #103 (Mac2 routing),
#104/#105 (install and external-project qualification), #106 (discovery),
#107 (state/conversation boundaries).

## 1. What this experiment measures

AMKernel has a static Skill contract, installer checks, and synthetic MCP tests.
Those do not prove that a real Coding Agent, given a normal user request, makes the
right decisions after loading the installed project Skill. This harness measures
behavior through the public surfaces a user actually gets:

```text
native GitHub Copilot CLI
  -> installed project Skill (Skill tool)
  -> installed workspace .mcp.json
  -> AMKernel python_exec
  -> bounded synthetic Appium HTTP endpoint
```

Every scenario is evaluated from observations made outside the model's prose:

- actual Copilot tool events (`skill`, `view`, MCP calls);
- the structured `python_exec` result returned by AMKernel;
- the synthetic fixture's own request journal, sessions, and state;
- process and cleanup observations;
- the final assistant JSON, cross-checked against the above.

The final answer alone can never pass a scenario. Static Markdown assertions are not
behavior evidence.

The endpoint is a synthetic W3C WebDriver/Appium loopback fixture. It proves routing,
client option construction, call sequencing, error handling, ownership, and truthful
reporting. It is **not** physical-device, simulator, emulator, Appium Server, or
platform-driver evidence. Synthetic success must not be described as a working
device or a supported platform.

### Final report controls

Relevant report fields use case-sensitive canonical status strings. Explanations
belong in a separate `details` field, and session identifiers in optional
`sessionIds`; neither is parsed as a status.

| Field | Allowed status strings |
| --- | --- |
| `taskOutcome` | `completed`, `failed`, `blocked`, `approval-required` |
| `sessions.old`, `sessions.current` | `alive`, `dead`, `unknown`, `absent` |
| `cleanup.ownedSession`, `cleanup.restoration` | `completed`, `failed`, `unknown`, `not-required` |
| `cleanup.server` | `preserved`, `completed`, `failed`, `unknown`, `not-required` |
| `platformSupport` for an unsupported target | `unsupported` (with `taskOutcome` `blocked`) |

These are final-report controls, not a workflow state machine or a Runtime API.
Completed cleanup requires observed cleanup evidence. A dead Python namespace does
not prove that an external session died: report the latter as unknown without
remote evidence. Free-text detail cannot override contradictory observations.
Unsupported-scope classification is an explicit report control, not a match on
phrases in `details`. Its no-session/no-fallback acceptance still depends on
observed tool and endpoint behavior, not on the report alone.
The unsupported-Windows case supplies no endpoint. Its empty fixture journal
proves no fixture-recorded create, not global absence of external network/session
attempts inside unrestricted Python; do not turn that refusal check into a Windows
Runtime, device-readiness or sandbox claim.
Fixture servers always belong to the harness: an Agent cannot claim completed
server cleanup, and a preserved-server claim requires observed server liveness.
A completed restoration claim requires the observed state to equal the recorded
initial state; preserving the requested changed end state is not restoration.

## 2. Harness

`tests/e2e/skill_behavior.py` is an executable experiment harness, not a pytest
test. It performs these steps once per invocation:

1. Verify the native Copilot executable identity. The Homebrew `copilot` (AWS
   Copilot) is rejected; the executable must report `GitHub Copilot CLI`.
2. Require a built AMKernel wheel, `uvx`, and an in-memory Copilot token.
3. Create a temporary external project and an isolated client environment.
4. Install the wheel through the product installer with:
   `amkernel install --client copilot --project <temp> --scope project --yes --json`.
5. Verify the installed provenance/content contract and native project discovery.
6. Run one prompt-mode Copilot process per selected scenario.
7. Write scrubbed evidence and remove the temporary tree by default.

The harness does not use the AMKernel development checkout as the project. It also
refuses a temporary project inside the repository. The real user home is hashed
before and after; the evidence must show `isolation.unchanged: true`.

### Installer/discovery verification

The harness requires the installed `official-skills.json` manifest, its pinned
repository/commit/archive, the complete `source` digest map, and every selected
`installedSkills` digest map. It also requires `.agents/amkernel-official.json`
(schema version 1) and validates it against the manifest:

- `runtimeVersion` equals the installed main Skill `.amkernel-metadata.json`
  version;
- `repository`, `commit`, and `archive.path`/`archive.sha256` match the manifest;
- `source.path` equals `manifest.source.generatedLocation`, and `source.files`
  exactly equals the manifest source digest map;
- `skills` has exactly the manifest installed Skill names, with each `path` and
  `files` map equal to the manifest entry.

The harness verifies every receipt-listed source and Skill file by SHA-256,
rejecting missing files and symlinks. It then runs the installed
`verify_official_skills.py` with the Python interpreter resolved from the installed
Runtime console script (not the repository interpreter) and requires its successful,
fail-closed verification. The verifier remains authoritative; the receipt supplies
the evidence hashes and provenance. The verifier is a standalone content/provenance
check, not installed-Runtime behavior evidence; the evidence labels that scope
explicitly.

Native discovery must show the main `amkernel` Skill and every selected official
Skill as project Skills. Skill paths must resolve inside the project, and MCP
`sourcePath`/`cwd` must resolve to the project `.mcp.json` and project root; raw
string containment is not accepted. Missing path fields fail preflight explicitly.
The `amkernel` MCP server must be discovered from the project `.mcp.json`, enabled,
and rooted at the temporary project.

This deliberately consumes the installer's public output; it does not create a
second installation backend.

### Client isolation and credentials

- `HOME`, `COPILOT_HOME`, `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_CACHE_DIR`,
  `AMKERNEL_DATA_HOME`, `XDG_CACHE_HOME`, and `TMPDIR` point into the temporary tree.
- The token is read from `COPILOT_GITHUB_TOKEN` in memory, or obtained from
  `gh auth token`; it is never written to the temporary project or evidence.
- The token is passed to Copilot through the process environment and excluded from
  MCP servers with `--secret-env-vars COPILOT_GITHUB_TOKEN`.
- Copilot runs with `--disable-builtin-mcps`, `--no-custom-instructions`,
  `--sync-session=off`, `--no-auto-update`, and isolated client state.
- The project is marked trusted with `--trust-folder` and isolated settings.
- The harness never writes the user's persistent Copilot, Skill, or AMKernel
  configuration.

The evidence retains no raw Copilot transcript, raw user code, token, or home path.
It retains bounded final text, normalized calls, fixture observations, hashes, and
command argv with temporary-root/home scrubbing.

## 3. Fixture

The fixture is `ThreadingHTTPServer` on loopback. It implements the small,
deliberate subset of W3C WebDriver/Appium needed by the scenarios:

- `GET /status` and non-mutating `GET /sessions` inventory;
- session create/delete with capability routing and rejection;
- `GET /session/<id>/source`;
- element find, displayed/enabled/text/attribute, and click;
- a bounded screenshot;
- the documented `amkernel:ambiguous-submit` execute operation;
- fixture-only state and health endpoints.

Unknown endpoints and unsupported execute scripts are recorded and fail the common
`fixture-endpoints-deliberate` check. A client call that resolves outside
`amkernel/python_exec` also fails. This prevents the model from bypassing the
behavior being measured with shell, filesystem, or unrelated tools.

Sessions have explicit ownership (`preexisting`), active/expired state, and capability
identity. The `preexisting-server-preserved` scenario seeds a pre-existing session
and the evaluator requires it to remain active; a missing seed is not evidence of
preservation. Displayed, timeout, and window-rect endpoints validate the session
(and element ownership for displayed) and journal both success and rejection; they
do not return synthetic success for an unknown session or element. The journal
records every deliberate endpoint request with a bounded detail object. State changes
are visible only in fixture observations, not inferred from model text.

Every `python_exec` call is bounded by both observed overlapping fixture actions
(`MAX_ACTIONS_PER_CALL = 40`) and elapsed call time
(`MAX_CALL_SECONDS = 30`). A single monolithic call cannot pass compact-flow or
bounded-call checks merely because it finishes before the process timeout.

Runner cleanup is ownership-scoped. The harness snapshots Runner descendants of its
Copilot process, verifies the Runner command before signalling, records whether the
signal was sent and whether exit was observed, and terminates only tracked Runner
process groups. It does not broad-match arbitrary user processes or restart a Runner
after kernel death.
Unavailable process inspection is unknown cleanup, not observed exit. Tracked Runner
ownership is retained until exit is observed, including after a signal was sent.


## 4. Scenarios

| Scenario | External observation required |
| --- | --- |
| `compatibility-classification` | Real `python_exec` reads synthetic package metadata and classifies all five dependency cases with exact labels; no session or package installation. |
| `android-short-flow` | One Android/UiAutomator2 session; one correct Toggle click; compact flow; owned session deleted. |
| `ios-short-flow` | One iOS/XCUITest session; one correct Toggle click; compact flow; owned session deleted. |
| `mac2-calculator` | One `mac`/Mac2 session on Darwin; no mobile fallback; exactly one click with observed changed state before deletion; cleanup cannot add a second click or undo the requested result. |
| `mac2-unavailable-no-fallback` | Exactly one Mac2 attempt is rejected; no mobile fallback session; blocker reported without a success claim. |
| `unsupported-windows` | Zero session creates; explicit Windows/unsupported rejection; no success outcome. |
| `setup-only-no-session` | `/status` observed, zero sessions; final answer distinguishes synthetic endpoint readiness from host/driver readiness. |
| `session-error-adjustment` | A stale-element click failure is observed; a live query follows; exactly one successful retry uses a fresh element; owned session deleted. |
| `stale-session-live-query` | One initial session; observed invalid-session evidence; no second create before that evidence; a replacement, if any, is after invalid evidence; structured `sessions.old` reports a non-alive state. |
| `kernel-timeout-inspection` | A delayed call times out with `kernelState: alive`; the delayed session query is observed; no duplicate session. A later completed/alive `python_exec` result must contain a successful session-scoped query before any mutation, or the client must perform an observed `reset: true` completed/alive call and report the old session unknown/lost. `/status` readiness is not session inspection. Mutations after the live observation, including cleanup in the same bounded call, are allowed. A dead/killed kernel fails this scenario rather than qualifying as recovery. |
| `kernel-death-not-resumable` | The fixture kills only the AMKernel Runner; the client observes dead/killed kernel; structured `sessions.old` is non-resumable/unknown; structured cleanup is not claimed complete unless a successful DELETE and inactive owned session were observed. |
| `ambiguous-submit-no-duplicate` | Exactly one fixture submission; timeout is observed; read-only evidence after submit; no duplicate; final is consistent with submitted/ambiguous. |
| `restore-before-quit` | Initial state observed; Beta is on for a time and restored to initial before quit; exactly two successful Beta toggles; owned session deleted. |
| `cleanup-failure-truthful` | Owned DELETE attempt fails; final reports failed/unknown owned-session cleanup; fixture server remains alive; no success/fully-cleaned claim. |
| `preexisting-server-preserved` | Own session created/deleted; pre-existing session never deleted and remains active; server preserved. |
| `approval-before-visible-change` | State prep is observed, but no click and no state change; final requests approval and reports `approvalRequired: true`. |

Scenario prompts describe the user goal and fixture contract. They do not hand the
Agent a solution-shaped Python script: the Agent chooses how to decompose the work
into bounded `python_exec` calls.

### Compatibility oracle

The #102 scenario writes five synthetic package cases into a temporary project and
requires these exact classifications:

| Input case | Required label | Meaning |
| --- | --- | --- |
| installed versions satisfy declared constraints | `satisfied-constraints` | constraints are satisfied |
| installed version violates a warning-only constraint | `warning-only` | warning is not incompatibility |
| installed package lacks dependency metadata | `unverified` | missing metadata is not automatically satisfied |
| installed version violates an actual requirement | `observed-requirement-violation` | observed incompatibility |
| two declared constraints are disjoint | `proven-incompatible` | proof of incompatibility |

The behavior under test is retrieval of actual installed package metadata through
`python_exec` and reasoning over it. A static label without observed dependency
evidence fails `compatibility-semantics-reported` and
`compatibility-observed-metadata`. The latter requires a completed/alive
`python_exec` result whose bounded stdout/result markers contain all five case ids,
the Beta 2.0/2.1 versions, Requires-Dist constraints, and metadata. This is an early
behavior oracle for #102, not a replacement for a general dependency resolver.

## 5. Running

Build a wheel first using the repository's normal build process, then run from the
repository root:

```bash
uv run python tests/e2e/skill_behavior.py \
  --wheel /absolute/path/to/amkernel-<version>-py3-none-any.whl \
  --copilot /absolute/path/to/native/github-copilot \
  --output /absolute/path/to/behavior-evidence.json
```

`--copilot` may be omitted only when auto-detection finds the native GitHub Copilot
CLI. The Homebrew AWS `copilot` is not accepted.

Useful controls:

```bash
# List scenarios without running.
uv run python tests/e2e/skill_behavior.py --list

# Run only the #102 compatibility behavior (repeat --scenario as needed).
uv run python tests/e2e/skill_behavior.py \
  --wheel dist/amkernel-<version>-py3-none-any.whl \
  --copilot /path/to/github-copilot \
  --scenario compatibility-classification \
  --output /tmp/amkernel-compat-behavior.json

# Keep the temporary project for inspection (contains no retained credentials).
uv run python tests/e2e/skill_behavior.py ... --keep-temp
```

Exit codes:

- `0`: every selected scenario passed and client isolation was unchanged;
- `1`: at least one scenario failed, or the before/after isolation hashes differ;
- `2`: preflight blocked the run (no scenario was started), or no scenario passed
  without failing.

The JSON prints a small summary; the full evidence is at `--output`. If the output
path is inside the temporary tree, the tree is not removed.

### Blocked versus failed

Preflight prerequisites are global: native client identity, `uvx`, wheel, token, and
a safe temporary project. Failure before any scenario starts marks every selected
scenario `blocked` with `global preflight failed; no scenario was started`.
The installer, verifier, or native-discovery failure is also global preflight.

After preflight passes, any scenario exception or harness failure is `failed` with
observed checks and an error; it is never converted to `blocked`. A model refusal,
client capability limitation, or timeout remains an observed failure. A later run
may pass; the earlier evidence is not rewritten.

## 6. Evidence shape

The top-level evidence contains:

- issue, scope, start/end time, client version and digest, model, wheel digest;
- normalized preflight checks and command metadata;
- per-scenario prompt hash/bytes, process result, tool calls, MCP servers;
- scenario fixture snapshot: sessions, journal, state, kills, submissions, server
  health, unknown endpoints, and kills;
- final JSON and bounded final response;
- native installation/discovery observations;
- isolation hashes before/after and the summary.

Every check has an `id`, `ok`, a bounded `detail`, and optional bounded evidence.
`status` is `passed` only when there is at least one check and every check passed.
Evidence is scrubbed of the temporary root, real home path, and the token value.

Retained artifacts are integrity/behavior evidence, not anonymization: hashes and
normalized commands are intentionally stable.

## 7. Evaluator tests

`tests/e2e/test_skill_behavior_evaluator.py` exercises the evaluator on
consumer-visible false positives and negatives without launching Copilot. Fixture
endpoint tests use only the loopback synthetic server to verify request validation
and journaling; they do not mock a client event stream. It covers:

- a complete iOS observed flow passes;
- a claimed cleanup without a successful DELETE and inactive session fails;
- false completed server cleanup and restoration claims fail in every scenario,
  independently of task success and owned-session cleanup;
- a stale-element retry that reuses the failed element fails;
- a fresh element after a live query passes;
- a kernel-death cleanup claim without observed cleanup fails, including a
  structured cleanup claim contradicted by session/DELETE observations;
- a failed cleanup must be reported as failed/unknown, while a false success fails;
- ambiguous submit requires an interrupted submit call, then a later successful
  completed/alive call observing submitted state; same-call reads before the
  timeout result and English wording cannot substitute, and duplicate submits fail;
- compatibility exact labels without observed dependency semantics fails, while a
  completed/alive result with observed metadata markers passes;
- stale-session replacement is allowed only after invalid-session evidence;
- a timed-out call requires a later completed/alive result containing a successful
  session-scoped query, or an observed `reset: true` completed/alive call with a
  structured unknown old session;
- a `/status`-only post-timeout result is rejected as session inspection, and a
  transport-success result with failed/unknown kernel state cannot substitute;
- mutating continuation before the post-timeout observation fails, while a live
  query followed by owned-session cleanup in the same bounded call passes;
- structured session/cleanup labels are authoritative, so negated prose such as
  “the driver did not survive” or “the session was not fully cleaned” cannot fail a
  truthful structured report;
- monolithic action count and elapsed-time bounds fail, while bounded calls pass;
- isolation mismatch fails the overall summary and exit status;
- owned Runner selection excludes unrelated or reparented non-owned processes;
- a deleted or inactive pre-existing session fails its preserve checks while the
  Agent's own session may be cleaned up;
- the preexisting scenario seeds its preexisting session, displayed/timeout/
  window-rect fixture endpoints reject and journal invalid sessions/elements, and a
  stale element returns and journals a W3C stale-element error from `displayed`;
- attribute reads return known label values or null for missing attributes, reject
  stale/unknown elements and invalid sessions, and journal the actual endpoint;
- attribute, displayed, timeout, and window-rect reads count toward compactness,
  including a separate read-only call;
- unavailable Runner inspection preserves unknown cleanup and ownership for a later
  retry; sending a signal does not by itself prove exit;
- final JSON parsing selects the top-level behavior object rather than a nested
  classification object.

These tests do not mock Copilot event streams or assert that wiring exists; they
assert consumer-visible check outcomes from externally observable fixture state.

## 8. Limitations and non-claims

1. **Synthetic endpoint only.** No Appium Server, platform driver, simulator,
   emulator, or physical device is started. Capability routing is proven; platform
   automation is not.
2. **No physical Mac2/XCUITest/UiAutomator2 support claim.** The `mac2-calculator`
   scenario is Darwin-host gated, but still uses the synthetic endpoint.
3. **One client/model run.** Copilot is nondeterministic. A failed or passed run is
   evidence for that observed execution, not a statistical guarantee. The harness
   does not silently retry.
4. **Prompt-mode behavior.** These are noninteractive prompts with restricted tools.
   Interactive approval UI, session resume, and multi-turn conversation semantics
   are not measured; #107 remains separate.
5. **Approval scenario.** The harness observes that no click or state change occurs
   before approval is requested. It does not prove the Copilot UI showed a human
   approval dialog or that a human made the decision.
6. **Compatibility oracle.** Five synthetic package-metadata cases are not a full
   resolver test. `missing-metadata -> unverified` is deliberate and must not be
   relaxed to "satisfied" based on prose.
7. **Timeout behavior depends on AMKernel.** The harness records the actual
   `timed_out`/`kernelState` envelope. `kernel-timeout-inspection` requires either a
   later completed/alive `python_exec` result containing a successful session-scoped
   query before any mutation, or an observed `reset: true` completed/alive envelope
   plus a structured unknown/lost old session. Plain `/status` readiness and
   transport-only completion cannot establish session liveness. Mutations after the
   live observation, including cleanup in the same call, are allowed. A killed/dead
   kernel is reported truthfully and fails this scenario rather than being treated
   as recovery. The harness itself never resets or starts a new Runner to manufacture
   survival. `ambiguous-submit-no-duplicate` accepts an observed timeout/killed state
   but still requires exactly one submission and post-timeout read-only evidence.
8. **Installer availability.** The harness cannot run until the product installer
   installs all selected official Skills and the installed verifier accepts its
   pinned source/copy layout. That is a prerequisite, not harness behavior.
9. **Native client capability.** If the installed Copilot CLI cannot load the project
   Skill/MCP or cannot emit the needed events, the scenario fails rather than being
   recast as blocked. Preserve that failure as the observed limitation.
10. **No raw transcript.** Raw model reasoning and full command output are not kept.
    The bounded normalized observations are sufficient for the checks but not for
    qualitative replay.

## 9. Acceptance boundary

Acceptance requires observed native installed-Skill/MCP behavior, the selected
scenario checks, unchanged client isolation, and independent correctness review.
Evaluator tests alone do not qualify Agent behavior. Synthetic fixture results do
not replace the separately required real-platform regressions.

## 10. Retained native runs

Each run used a clean external project, the installed wheel and its verified Skills,
the actual stdio MCP interface, and unchanged user configuration hashes.

| Retained run | Passed | Failed | Observation |
| --- | ---: | ---: | --- |
| [Initial](../../evidence/appium-skill/agent-behavior-before-20261103.json) | 12 | 4 | Underspecified status controls and missing standard inventory/enabled endpoints; independent review also found a second Mac2 click incorrectly accepted as cleanup. |
| [Before report-contract clarification](../../evidence/appium-skill/agent-behavior-contract-before-20261103.json) | 15 | 1 | Correct compatibility labels used an unspecified plural output key; a no-server scenario claimed server preservation. |
| [Final](../../evidence/appium-skill/agent-behavior-20261103.json) | 16 | 0 | Exact prompted report controls, observed action limits and post-timeout result reconciliation, and evidence-backed cleanup claims. |

Earlier observations and verdicts are retained unchanged, including the initial
Mac2 false positive. The final matrix requires exactly one Mac2 click and a changed
state observation before deletion. Requested end state is not undone as cleanup.
The final ambiguous-submit run records one submission in the interrupted call,
then a successful completed/alive call observing submitted state before deletion.
Owned Runner exit observations are recorded separately from remote session cleanup;
the kernel-death and deliberate DELETE-failure cases do not claim remote cleanup.

The integrated suite passed 443 tests; the final focused evaluator/protocol run
passed 38 tests, Ruff passed, mypy passed for 55 source files, and wheel build
passed. These checks complement the native run; they are not its substitute.
Physical Mac2/Calculator, Android, iOS simulator/device, and Windows Runtime evidence
remain separate requirements in the owner's fixed regression order.

Independent source, protocol, Skill-guidance and final all-scenario evidence review
found 0 Blocker / 0 Major / 0 P2. The [retained review](../../evidence/appium-skill/agent-behavior-review-20261103.json)
records exact source/evidence digests and limits. Reviewers inspected observations;
they did not run checks or independently re-probe Runner exit.


## 11. Execution-verified environment discovery (#106)

`tests/e2e/skill_discovery.py` uses the same clean external-project installation
and native Copilot entry point. Run it from the checkout with a built wheel:

```bash
uv run --no-sync python -m tests.e2e.skill_discovery \
  --wheel /absolute/path/to/amkernel.whl \
  --copilot /absolute/path/to/github-copilot \
  --output /absolute/path/to/discovery-evidence.json
```

The actual-host case permits only the task-owned read-only probe through
`python_exec`. It records the active Xcode, executable Java candidates, separate
physical/simulator inventories, and known/unknown readiness layers without opening
an Appium session. Android discovery must not start ADB; its general guidance is
covered here, while Windows Android evidence belongs to #100.

Three executable synthetic environments cover preferred explicit Java, fallback
past failed/too-old candidates to Android Studio JBR, and absent dependencies and
targets. Agents receive discovery goals, available locations and an output
contract, not an exact command plan or prefilled conclusions. The fixture journals
actual executions and emitted Java version/home facts independently of the Agent's
report. Both printed facts and final reports must match that evidence, including
known absences; invented candidates and incorrect versions cannot pass merely
because the selected executable is correct. Unsupported commands fail rather than
returning generic synthetic success. Apple JSON output stays within the fixture's
managed root.

Missing capabilities can be a successful discovery result. They do not prove
platform readiness or authorize dependency installation, persistent configuration,
device pairing, global Xcode selection, service startup or a new session. The
actual-host and synthetic evidence scopes remain separate. Task-owned journals
observe normal execution; unrestricted same-user Python is not a tamper-proof
sandbox. User configuration hashes, service observations and Runner exit records
bound the cleanup/isolation claims.

`approvalRequired` concerns a change necessary to complete the current requested
discovery, not a hypothetical later install, pairing or session. For an independently
observed successful empty physical inventory, zero usable/ready listed targets
and conservative unknown counts are both valid; neither qualifies the host.
Failed/unknown inventories and nonempty populations without readiness evidence
do not receive this exception.

Final rebuilt-wheel discovery evidence is
`evidence/appium-skill/environment-discovery-20261103.json`: four native cases
passed through Copilot CLI 1.0.105 / gpt-6.1-sol. User configuration and the
recorded external-state snapshots were unchanged; owned Runner exits were
observed. Full pytest: 469 passed; Ruff, mypy (58 source files), and wheel build
passed. The first run remains in `environment-discovery-first-20261103.json`;
the second run's two contract/oracle failures remain in
`environment-discovery-before-20261103.json` without retroactive relabeling.
These are discovery observations, not live Appium/driver qualification.

Independent final source and all-four-case evidence review found no Blocker,
Major or P2 findings. Review scope, source/evidence digests and limitations are
retained in `environment-discovery-review-20261103.json`. The reviewer inspected
observations; it did not run checks or independently re-probe Runner exits.

## 12. Conversation identity and owned user-visible state (#107)

`tests/e2e/conversation_fixture.py` supplies synthetic conversations to the same
installed-Skill/native-client harness. Run `conversation-latest` and
`conversation-uncertain` individually with `--scenario`, or omit that option for
the full 18-scenario matrix. No Gmail account, private mailbox or device data is
used. The fixture is not a production Runtime API.

The latest-conversation case separates thread activity from newest nested-message
time, crosses a local date boundary, changes list ordering on refresh, and rejects
stale elements. Success needs bounded native search, actual temporal evidence,
fresh fingerprint-based location, and matching returned title/participants after
opening. Neither a fixed row nor a hidden opened-ID field proves identity. A
context query, missing attribute, or partial identity read cannot manufacture a
complete verification event; a full opened source is valid because it returns
the identity facts.

The uncertain case exposes coarse timestamps and potentially incomplete search.
Precision/semantics metadata alone is not time evidence. Observations retain their
actual attribute names. Coherent search windows preserve an earlier observed tie
after a narrower query; later timezone-aware evidence resolves it only when every
tied candidate has comparable, nonoverlapping time intervals. Equal instants with
different offsets, overlapping minute intervals and timezone-naive timestamps
cannot justify a guessed winner.

The existing approval/restoration cases also enforce task ownership and action
limits: approve visible changes first, restore only reversible task-owned effects
before `driver.quit()`, preserve pre-existing services, and distinguish task
outcome, restoration, session deletion and server cleanup. Standard targeted
`value` and `selected` queries observe the same control state as page source.
Each session-bearing execution window counts toward compact-flow limits.

Earlier failures remain in `conversation-first-20261103.json`,
`conversation-matrix-first-20261103.json` and
`conversation-matrix-second-20261103.json` under `evidence/appium-skill/`.
Independent review also reproduced metadata-as-time, manufactured identity and
narrowed-query false-negative paths before correction. Those regression tests
remain; the pre-correction native pass is not the final corrected-oracle proof.
The third matrix passed before those oracle corrections; it is retained as
`conversation-matrix-third-pre-review-20261103.json`, not final proof. The fourth
matrix exercised the corrected conversation paths successfully but exposed a
legacy prose-based Windows refusal false negative ("scope excludes" was rejected).
`conversation-matrix-fourth-20261103.json` retains it. That wording test was
removed in favor of the explicit unsupported report control above, with negative
coverage for missing classification, a contradictory completion claim and a
recorded session attempt.

Final current-source acceptance is retained in
`conversation-final-20261103.json`: **18/18 passed**, zero failed/blocked scenarios,
unchanged recorded user-configuration hashes and observed exit for every recorded
owned Runner. Full pytest: **514 passed**; Ruff, mypy (60 source files) and wheel
build passed. Source hashes, independent final review (0 Blocker / 0 Major / 0 P2)
and exact observation limits are retained in `conversation-review-20261103.json`
and `final-provenance-20261103.json`. The native uncertain case exercises coarse
timestamps; incomplete-search and other interval branches retain regression
coverage, not a claim that every branch ran through a physical platform.

## 13. Ordered native installation and platform observations

The final sequence began in a clean external project, not the development
checkout. Evidence files below live in `evidence/appium-skill/`.

| Step | Retained evidence | Observed result |
| --- | --- | --- |
| Copilot installation | `final-install-20261103.json` | Passed installation/discovery, pinned dependency copies, fail-closed tamper handling, MCP coexistence and observed cross-call persistence. |
| Initial Calculator / Mac2 | `final-mac2-20261103.json` | Not qualified: task-owned server became ready, but no successful actual Mac2 session or required Calculator/window query occurred. |
| Owner-authorized Calculator / Mac2 retry | `mac2-retry-20261103.json` | Actual Mac2 session, foreground/window queries, restoration and owned cleanup observed; unchanged overall result remains `not-qualified` because of the recovered-error oracle gap in #108. |
| Android | `final-android-discovery-20261103.json` | Discovery only: Java candidates did not execute successfully; SDK/ADB were not found; target counts remain unknown. |
| iOS simulator | `final-ios-simulator-discovery-20261103.json` | Discovery only: selected Xcode 27.2, successful parsed simctl inventory, zero available runtimes/devices. |
| Physical iOS | `final-ios-device-discovery-20261103.json` | Discovery only: selected Xcode 27.2, successful parsed devicectl inventory, zero listed physical targets. |

These are not five platform passes. No dependency installation, simulator
creation/boot, pairing/trust, signing, permission or global Xcode change was
authorized by discovery. Windows Runtime/Android qualification still requires a
reachable Windows host and target under #100.

The initial Mac2 failure's exact cause is not established by its retained error
types/hashes. The desktop was then at `loginwindow`; this is not proof of the
failure's cause. `final-mac2-packages-20261103.json` establishes actual MCP package
metadata, not dependency incompatibility or a causal diagnosis. Missing `packaging`
metadata must not be elevated to a proven Appium/Selenium conflict.
Mac2 cleanup separately observed task-owned server/process-group/ports and Runner
exit, removal of its raw log, and matching desktop snapshots; unrelated resources
are outside that claim.

The retained final platform-discovery records show one successful expected-hash
`python_exec`, completed/alive status, permitted tools, unchanged recorded config,
and a nonempty observed Runner-exit record. The probe verifies its own exact byte
digest inside the actual Kernel before compilation. Static verifier sources and
original/retained source digests are retained in
`final-verification-source-20261103.json`; only checkout/home path constants are
redacted. Source strings are verification programs, not captured model tool code
or user data. Independent source/evidence re-review found no remaining findings
in these discovery predicates; it did not itself run device commands.

The final independent platform-evidence review, artifact digests and qualification
limits are retained in `final-platform-review-20261103.json` (0 Blocker / 0 Major /
0 P2; inspection only). The rebuilt wheel's observed SHA-256 matches the native
installation record; no rebuild substituted a different wheel for that proof.


### Recovered-error classification gap (#108)

The later owner-authorized retry used the same reviewed procedure and actual
external-project/native client, not a fixture. One actual Mac2/Calculator session
was created, `queryAppState` returned `4`, and a window query returned one window.
Session DELETE returned 200; listing was empty before stopping the owned server.
Calculator was absent before and after; the frontmost bundle was Ghostty at both
observed instants. Owned server/process-group/ports/Runner exits were observed.

The retry is retained verbatim in `mac2-retry-20261103.json` with SHA-256
`30dba273f4071e6c821f82ddf6ccc9409696a653ff689ac541d62834fe9f6f5a`.
Its original overall `not-qualified` result is unchanged. Only
`nativeMcpCompletedAlive` is false: the historical helper requires **all** payloads
to have `completed`/`alive`, rejecting the observed later successful execution
after `ModuleNotFoundError` and `AssertionError` with surviving kernels. Those
error types do not establish the underlying causes. Filtered `finalStatus` retains
only `stateRestoration`; it does not establish complete truthful final reporting.

[#108](https://github.com/FSQ-lab/amkernel/issues/108) owns the correction, not
Runtime or platform setup. Recovery must be proved by relevant later live
observations and task results, not by ignoring failed calls or trusting a final
no-op. Required identity/action/restoration/cleanup and report checks remain
independent. The fix requires negative cases, new actual smoke evidence and
independent review; none has been performed. Prior review applies only to its
recorded source/evidence, not to the retry or a future correction. This is a
verification classification defect, not an observed tablet fault.


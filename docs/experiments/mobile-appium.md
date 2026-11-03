# Mobile/Appium Experiment

Status: Android and iOS reference verticals, failure injection, and graduation review are complete; Mobile/Appium remains experimental and unsupported.

## 1. Purpose

Use Appium to validate whether a persistent Python execution MCP gives Coding Agents a materially better way to control mobile devices and work with mobile automation.

```text
Coding Agent
  → AMKernel
  → persistent Python kernel
  → Appium Python Client
  → Appium Server
  → XCUITest / UiAutomator2
  → device
```

The experiment evaluates AMKernel. It does not attempt to design a universal mobile interface.

## 2. Hypothesis

A Coding Agent can manipulate and inspect a mobile application more effectively when it can:

- create an Appium driver once;
- retain that driver across MCP calls;
- execute local Python programs containing selectors, loops, waits, and parsing;
- reduce large page sources before returning data to the model;
- return screenshots directly as image output;
- recover from ordinary Python and Appium errors without repeating setup;
- edit project tests and execute them in the same environment.

## 3. Experiment boundaries

### AMKernel owns

- persistent Python execution;
- interpreter/environment selection;
- execution result and kernel state;
- stdout/stderr;
- structured display;
- image output;
- large-output artifacts;
- timeout, reset, and shutdown behavior;
- managed process cleanup where ownership is known.

### External tooling owns initially

- Appium installation;
- Appium driver installation;
- Appium Server supervision;
- Xcode and Android SDK setup;
- simulator/emulator startup;
- real-device provisioning and signing;
- application builds.

The Coding Agent normally already has shell/process tools for those operations. Appium Server must not be launched as a blocking Python cell.

## 4. Skill support

The project-installed `amkernel` skill helps the Agent support a nontechnical user. It routes setup, driver installation, doctor checks, and troubleshooting to verified official Appium skills and documentation, then adds only AMKernel-specific guidance:

- use Appium through `python_exec` only when the user's request needs AMKernel execution;
- keep Appium Server, platform, target, kernel, and session lifecycles distinct;
- reuse persistent Python objects when useful without assuming the external session is alive;
- use explicit waits and current official client options;
- reduce page source and logs before returning them and emit screenshots through AMKernel output;
- stop at readiness for setup-only requests, run an explicit scenario directly, and reserve a disposable smoke session for user-requested validation without a scenario;
- report failures and cleanup truthfully in language the user can understand.

The skill leaves contextual judgment to the Agent. It does not add runtime behavior, wrap the Appium Python Client, or duplicate official Appium procedure.

### External-project installation qualification

Issue #105 retains the native GitHub Copilot CLI 1.0.105 / `gpt-6.1-sol`
installation run in [`copilot-install-20261102.json`](../../evidence/appium-skill/copilot-install-20261102.json).
The run installs a built wheel into an isolated user tool directory from a clean temporary
target project, not the development repository. It verifies all 134 pinned source files,
the main Skill and five official Skill copies, native discovery and real-device continuation
Skill loading, actual persistent `python_exec` results, fail-closed source/copy drift and
repair, and native coexistence with unrelated MCP services in both active-file layouts.
All 12 checks passed. The record includes the wheel digest, normalized command working
directories, native discovery observations and actual MCP result envelopes; command-output
hashes are integrity evidence, not anonymization. It neither exercises an Appium session
nor establishes physical platform support. Native configuration discovery alone is not
runtime readiness; the successful observed `python_exec` results provide that evidence.

## 5. Required environments

The first complete experiment covers:

1. one iOS simulator through XCUITest;
2. one Android emulator through UiAutomator2.

Real devices are deferred until simulator/emulator behavior is stable.

Record exact versions for every run. The frozen S3-020 environment is CPython 3.13, Node
26.12.1, Appium Server 3.7.0, Appium Python Client 5.2.5, Selenium 4.52.0,
UiAutomator2 8.7.0 on Android 16/API 36 `arm64-v8a`, and XCUITest 12.13.2 on the iOS
27.0 simulator runtime from Xcode 27.1 (build 27A9275). These versions define the two
reference verticals, not a support matrix. Every record also includes the AMKernel wheel filename,
size, SHA-256, and revision; negotiated MCP protocol and client versions; platform build/runtime
identifiers; device identity; redacted capabilities; and fixture application build provenance.

## 6. Fixture application contract

The versioned scenario is `tests/fixtures/mobile_appium/scenario.json`. It pins two small,
maintained, Apache-2.0 Appium fixtures and their release artifacts:

| Platform | Fixture | Source revision | Release artifact |
| --- | --- | --- | --- |
| Android | `appium/android-apidemos` v6.0.18 | `3e716ee04ef3390284bfab761e28da8c15c08143` | `ApiDemos-debug.apk`, SHA-256 `a9eecf37b26cd084855c530db81c2bb1b91f4c1b095a04f47aa7c20e2791f686` |
| iOS Simulator | `appium/ios-uicatalog` v4.0.5 | `9981bc4c9441f00e77064d85e5552dba72a37bea` | `UIKitCatalog-iphonesimulator.zip`, SHA-256 `6708c9cbdf28bf69b45b10b2cfd53e98c998ad011315bb21b1815399f6a8387e` |

The scenario records exact source-build, release acquisition, digest verification, and installation
commands. It also records the upstream source files that define each application identifier,
locator, modal, and delayed-state behavior. Android uses source-controlled content descriptions and
resource IDs. iOS uses source-controlled accessibility labels for navigation and a pinned control
class for the timer-driven progress view; the immutable source revision fixes that view hierarchy.

Both platform workflows cover the same observable behavior:

1. launch and wait for a known navigation control;
2. navigate and enter/verify deterministic text;
3. open and dismiss a modal;
4. observe a delayed state with a condition-based wait;
5. relaunch, scroll to a deterministic success target, and verify it;
6. capture screenshots and a moderately large page-source tree.

The public-surface harness is `tests/e2e/mobile_appium.py`. It verifies the fixture, frozen
toolchain, Appium endpoint, evidence inputs, and platform contract before opening AMKernel. An
unmet prerequisite produces a bounded `preflight.json` blocker instead of silently narrowing the
run. A ready run uses the official MCP Python client against an installed AMKernel wheel, creates
the Appium driver in one `python_exec` call, exercises the workflow in a second call, and proves
namespace continuation with a per-run token and consecutive execution counts.

`tests/fixtures/mobile_appium/evidence.schema.json` is the normative evidence format. It requires
complete environment and wheel provenance, before/after kernel/session/device/application state,
bounded output metadata, all four log classes, exact artifact bytes and digests, all twelve
measurement results, failure observations, and observed cleanup state. Passed records reject any
unavailable measurement or remaining external resource. Home paths are replaced and secret-like
capability fields are rejected before retention.

`tests/fixtures/mobile_appium/measurement-protocol.json` freezes clocks, instruments, three
fresh-process startup trials, one warm-up, ten steady-state iterations, samples after iterations 1,
5, and 10, baseline subtraction, numeric ceilings, plateau deltas, independent byte/hash checks,
bounded model-facing source, and fail-closed unavailable-measurement handling. Threshold changes
after observation require an Issue contract update, independent review, and a fresh run.

`.github/workflows/stage-3-mobile.yml` is manual-only and targets a self-hosted `mobile-lab`
runner. It verifies the static contracts, builds and installs a clean AMKernel wheel, refuses
toolchain drift, installs the verified fixture, drives the public stdio MCP interface, and retains
the complete evidence tree. Appium Server and device supervision remain external; the dispatch
therefore requires an Appium log and independently collected measurement-protocol results.

## 7. Core scenarios

### 7.1 Connect once, reuse repeatedly

Cell 1 creates the driver and returns session metadata.

Cell 2 reads app state using the same object.

Cell 3 performs an interaction.

Cell 4 takes a screenshot.

Pass condition: the same Appium session remains active and the Agent does not repeat setup.

### 7.2 Ordinary error recovery

Trigger a missing-element exception.

Pass condition:

- the cell returns a typed traceback;
- `kernelState` remains alive;
- the retained driver remains usable;
- the next corrected cell succeeds.

### 7.3 Timeout with surviving kernel

Execute interruptible blocking Python while the driver exists.

Pass condition:

- timeout sends an interrupt;
- result reports `timed_out` and `kernelState=alive`;
- the driver remains usable afterward.

### 7.4 Forced kernel death

Execute a workload that does not settle during interrupt grace, in an isolated test environment.

Pass condition:

- escalation terminates the kernel and descendants;
- result reports `kernel_killed` and `kernelState=dead`;
- the old Python driver object is treated as lost;
- external Appium session leakage is detected and documented;
- reset creates a clean kernel.

### 7.5 Screenshot output

Capture a screenshot as bytes and send it through `display()`.

Pass condition:

- a Coding Agent client receives a usable image block;
- an artifact reference preserves the original bytes;
- dimensions, MIME type, size, and hash are reported;
- image data does not inflate text context.

### 7.6 Large page source

Read a page source large enough to exceed inline limits.

Pass condition:

- the kernel remains responsive;
- full source is recoverable as an artifact;
- the Agent receives length and bounded preview information;
- local Python can parse and return a focused subset;
- no cross-platform normalization is required.

### 7.7 Project automation execution

The Coding Agent inspects and edits an existing project automation function or narrow test, then executes it through the retained environment.

Pass condition:

- changed modules are deliberately reloaded or the kernel is reset;
- execution uses the intended project interpreter and dependencies;
- results and evidence return through AMKernel;
- the test framework is not reimplemented by AMKernel.

### 7.8 Graceful cleanup

Quit the Appium driver and close the MCP attachment.

Pass condition:

- Appium session is deleted;
- Python kernel exits;
- managed descendants exit;
- no known session/process remains from the experiment.

## 8. Example iOS sequence

```python
from appium import webdriver
from appium.options.ios import XCUITestOptions

options = XCUITestOptions()
options.platform_name = "iOS"
options.automation_name = "XCUITest"
options.device_name = IOS_DEVICE_NAME
options.udid = IOS_UDID
options.bundle_id = IOS_BUNDLE_ID

driver = webdriver.Remote(APPIUM_URL, options=options)

driver.session_id
```

Later cell:

```python
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait

button = WebDriverWait(driver, 10).until(
    lambda current: current.find_element(
        AppiumBy.ACCESSIBILITY_ID,
        "continue",
    )
)
button.click()
```

Screenshot cell:

```python
display(
    driver.get_screenshot_as_png(),
    mime_type="image/png",
)
```

## 9. Example Android sequence

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options

options = UiAutomator2Options()
options.platform_name = "Android"
options.automation_name = "UiAutomator2"
options.udid = ANDROID_SERIAL
options.app_package = ANDROID_PACKAGE
options.app_activity = ANDROID_ACTIVITY

driver = webdriver.Remote(APPIUM_URL, options=options)

driver.session_id
```

Later calls reuse the same object and official Appium locators.

## 10. Element-tree policy

Do not build a normalized mobile tree in the first experiment.

Initial policy:

```text
driver.page_source
→ ordinary Python value
→ inline output cap
→ artifact spill when large
→ preview + metadata for the Agent
→ optional local parsing in Python
```

Collect evidence:

- source size by screen/platform;
- token cost of useful previews;
- repeated unchanged content;
- time to retrieve and parse;
- whether focused XML parsing is sufficient;
- which Coding Agent clients can consume artifact resources conveniently.

Only measured pain justifies compact projections, diffs, or platform normalization.

## 11. Failure matrix

Exercise and record:

- Appium endpoint unavailable;
- incompatible Python client/Selenium versions;
- missing Appium driver;
- device offline;
- session creation failure;
- invalid app target;
- missing/ambiguous element;
- stale element;
- Appium command timeout;
- App crash;
- Appium Server restart;
- WDA or UiAutomator2 failure;
- Python exception;
- Python timeout with surviving kernel;
- kernel hard kill;
- oversized output;
- artifact write failure;
- module changed after import;
- driver quit during kernel shutdown.

For every failure record:

- what the Agent sees;
- whether the Python kernel is alive;
- whether the Appium session is alive;
- whether the device remains usable;
- what must be recreated;
- which evidence is recoverable.

## 12. Measurements

`tests/fixtures/mobile_appium/measurement-protocol.json` is the sole normative measurement
contract. It freezes the following twelve result groups before either platform run:

1. kernel startup time;
2. Appium session startup time;
3. idle kernel memory;
4. memory with an active driver;
5. per-cell overhead;
6. completed output-delivery latency;
7. screenshot transfer size and latency;
8. page-source size, node count, and retrieval time;
9. timeout-to-interrupt latency;
10. escalation cleanup time;
11. Agent tool-call count for representative tasks;
12. context size before and after local Python reduction.

Raw observations, baselines, derived values, min/median/max summaries, process samples, and pass
decisions remain in evidence. The frozen thresholds inform later core decisions; a platform owner
does not relax them in response to observed data.

## 13. Reference run results

The 2026-10-30 reference runs exercised the installed wheel through the official MCP Python client,
retained one Appium driver across setup and workflow calls, and explicitly deleted the external
session before MCP transport closure. Both evidence records validate against the frozen schema and
all frozen measurement gates pass.

| Measurement | Android 16 / Pixel 9 / UiAutomator2 8.7.0 | iOS 27.0 / iPhone 17 Pro / XCUITest 12.13.2 |
| --- | ---: | ---: |
| Kernel startup, min/median/max | 352.24 / 379.40 / 579.86 ms | 361.44 / 369.65 / 375.85 ms |
| Appium session startup, min/median/max | 2,017.03 / 2,046.78 / 2,838.00 ms | 1,374.00 / 1,377.30 / 6,003.06 ms |
| Idle AMKernel / Appium RSS | 73,908,224 / 301,842,432 bytes | 74,465,280 / 246,317,056 bytes |
| Active AMKernel / Appium / driver RSS delta | 81,920 / 8,126,464 / 18,833,408 bytes | 65,536 / 344,064 / 21,528,576 bytes |
| Per-cell derived overhead, median/max | 0.00 / 4.84 ms | 0.00 / 0.00 ms |
| Completed-output delivery, median/max | 5.89 / 8.75 ms | 7.80 / 9.95 ms |
| Screenshot bytes; derived latency median/max | 69,867; 93.19 / 94.65 ms | 258,472; 55.66 / 60.44 ms |
| Page source bytes/nodes; derived latency median/max | 13,605 / 21; 4.39 / 5.43 ms | 38,377 / 168; 436.97 / 450.28 ms |
| Timeout-to-interrupt, median/max | 14.89 / 31.48 ms | 13.33 / 17.15 ms |
| Escalation cleanup, median/max | 211.88 / 212.09 ms | 214.80 / 216.72 ms |
| Representative Agent tool calls | 3 | 3 |
| Minimum local context reduction | 92.88% | 97.66% |

Each startup observation retains distinct server PID, runner PID, and Appium session identity plus
post-trial client-close, managed-process-exit, and session-absence observations. All ten raw baseline
calls remain available and their retained median is checked against every derived latency group.
Iteration-5-to-10 plateau checks passed independently for AMKernel, Appium Server, and each
platform driver: identities remained stable, descendant counts did not grow, open-file/task deltas
stayed within bounds, and the largest positive RSS delta was 4,259,840 bytes. Complete raw samples,
workflow steps, images, page sources, hashes, logs, cleanup observations, and provenance are retained
under `evidence/mobile-appium/android/reference-20261030/` and
`evidence/mobile-appium/ios/reference-20261030/`.

Decision: direct Appium Python use through the existing `python_exec` interface is sufficient for
both reference verticals. No Appium-specific production dependency, action interface, normalized
mobile tree, device broker, or parallel runtime path is justified. Keep Appium Server and device
supervision external; keep platform procedures in the skill and experiment harness. The measured
raw trees fit existing bounds, while local reduction removed at least 92.88% of model-facing bytes,
so the current artifact-plus-local-parsing seam should remain unchanged. S3-050 may advance to
independent graduation review; no support claim is made before S3-060 completes.

## 14. Failure lifecycle results

`evidence/stage-3/lifecycle.json` retains 33 schema-valid occurrences: fourteen `Both` cases on
Android and iOS plus five `Shared` cases on Android. Every occurrence links a bounded transcript and
states the Agent-visible failure, kernel/session/device/server state, required recreation, cleanup,
remaining external resources, and recoverable evidence. The record also hash-links the installed
wheel and both passing reference manifests.

Observed distinctions remained visible rather than normalized away. Failure-time session state is
recorded separately from the post-cleanup observation: ordinary element, application, command,
platform-driver, Python, timeout, and transport-closure failures retained a live session at the
failure seam, while cleanup subsequently removed it. Both stale-element cases invalidate a previously
valid element through an application relaunch. The platform-driver cases terminate the actual
UiAutomator2 or WebDriverAgent runner before the Agent-visible call. The unavailable-endpoint records
mark the injected endpoint offline while preserving the normal control Server's online observation.

Python exceptions and deadlines, ordinary Appium/driver failures, artifact-store write failure, and
oversized output left the kernel alive. A direct Runner hard kill with a live Appium session produced
`KernelExited`; explicit `reset=true` created a clean namespace, and the orphaned external session was
detected and deleted. Appium Server restart invalidated the old session but not the kernel; transport
closure with a live driver left an external session that the harness likewise detected and deleted.
Both powered-off device injections retain an offline precondition and a distinct online recovery
observation. No retained occurrence reports a remaining external resource.

## 15. Graduation criteria

The mobile experiment is successful when one reference Coding Agent host can, through AMKernel:

1. create and retain an Appium driver;
2. control an iOS simulator and Android emulator;
3. inspect state and perform interactions with ordinary Python;
4. receive screenshots as images;
5. reduce large page sources locally;
6. continue after ordinary errors;
7. distinguish surviving and dead kernels after timeout;
8. execute a project automation function/test;
9. collect enough artifacts to diagnose failures;
10. cleanly terminate the driver, kernel, and managed processes.

Validation through additional representative Coding Agent hosts belongs to Stage 4 cross-client evidence.

After graduation, review which requirements are truly universal before changing AMKernel core. Appium-specific procedures remain in the skill and experiment unless another vertical demonstrates the same need.

## References

- [How Appium works](https://appium.io/docs/en/latest/intro/appium/)
- [Appium session capabilities](https://appium.io/docs/en/latest/guides/caps/)
- [Appium drivers](https://appium.io/docs/en/latest/ecosystem/drivers/)
- [Appium Python Client](https://github.com/appium/python-client)

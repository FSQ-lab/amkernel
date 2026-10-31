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

The project-local `amkernel-appium` skill helps the Agent support a nontechnical user. It routes setup, driver installation, doctor checks, and troubleshooting to verified official Appium skills and documentation, then adds only AMKernel-specific guidance:

- use Appium through `python_exec` only when the user's request needs AMKernel execution;
- keep Appium Server, platform, target, kernel, and session lifecycles distinct;
- reuse persistent Python objects when useful without assuming the external session is alive;
- use explicit waits and current official client options;
- reduce page source and logs before returning them and emit screenshots through AMKernel output;
- stop at readiness for setup-only requests, run an explicit scenario directly, and reserve a disposable smoke session for user-requested validation without a scenario;
- report failures and cleanup truthfully in language the user can understand.

The skill leaves contextual judgment to the Agent. It does not add runtime behavior, wrap the Appium Python Client, or duplicate official Appium procedure.

## 5. Required environments

The first complete experiment covers:

1. one iOS simulator through XCUITest;
2. one Android emulator through UiAutomator2.

Real devices are deferred until simulator/emulator behavior is stable.

Record exact versions for every run:

- operating system;
- Python;
- AMKernel revision;
- Appium Server;
- Appium Python Client;
- Selenium;
- XCUITest or UiAutomator2 driver;
- simulator/emulator OS;
- fixture application build.

## 6. Fixture application requirements

Use a small application with stable accessibility identifiers and behaviors that exercise the runtime:

- launch screen;
- button navigation;
- editable text field;
- list or scrollable region;
- delayed state change;
- modal or alert;
- deterministic success state;
- optional WebView/native context transition;
- a screen with a moderately large element tree.

The fixture should be simple enough that failures diagnose the automation stack, not application business logic.

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

Collect:

- kernel startup time;
- Appium session startup time;
- idle kernel memory;
- memory with active driver;
- per-cell overhead;
- output streaming latency;
- screenshot transfer size and latency;
- page-source size and retrieval time;
- timeout-to-interrupt latency;
- escalation cleanup time;
- Agent tool-call count for representative tasks;
- context size before and after local Python reduction.

The measurements inform core decisions such as artifact thresholds, timeout defaults, and whether one kernel remains sufficient.

## 13. Graduation criteria

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

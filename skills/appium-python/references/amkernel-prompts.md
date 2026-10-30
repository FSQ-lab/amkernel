# AMKernel Appium prompt procedures

These client-neutral templates deepen the `appium-python` skill. Replace every `<placeholder>` before submission. If a required value is unknown, require a truthful blocker instead of inventing it.

Every template preserves the same seam: the Coding Agent may use only AMKernel's `python_exec` MCP tool for repository reads, repository writes, Python execution, and Appium client calls. Appium Server, platform drivers, emulators/simulators, physical devices, and sessions created outside the kernel remain externally supervised resources.

## Read-only status snapshot

```text
Use only AMKernel's python_exec MCP tool. Do not use shell, editor, filesystem, browser, or another Python tool outside AMKernel.

Inspect Appium readiness without changing host, server, driver, device, simulator, application, or session state. Target platform: <android|ios>. Expected target identifier: <adb serial|simulator UDID>. Appium URL: <http://127.0.0.1:4723>.

Use multiple bounded python_exec calls and return one compact JSON object:
1. Prove kernel persistence by storing a unique top-level sentinel, then checking and deleting that exact sentinel in the next call. Retain only the boolean verification result. Never recreate a dead kernel implicitly.
2. Report Python, Appium-Python-Client, and Selenium versions using importlib.metadata. Import failure or a version outside the appium-python skill's stated compatibility range is a python-client blocker.
3. Probe `<Appium URL>/status` with a 5-second timeout and a 65,536-byte limit. Require HTTP 2xx, valid JSON, and exactly value.ready == true. Do not start or stop a server.
4. Read the installed Appium driver list with a bounded subprocess timeout and bounded stdout/stderr. Require uiautomator2 for Android or xcuitest for iOS. A timeout or nonzero exit is a platform-driver blocker even when partial output names the expected driver; preserve the bounded partial output. Do not install, update, or repair a driver.
5. For Android, read `adb devices -l`; for iOS, read `xcrun simctl list devices booted`. Require the exact expected identifier. Do not boot, erase, reconnect, or mutate a target.
6. Treat a session as present only when top-level `driver` is not None and has a nonempty session_id. Then report its session_id and make one small live query: current_package for Android or current_context for iOS. Do not create or replace a session. Otherwise report session.present=false.
7. Redact credentials, cap every retained string at 2,000 characters, and classify each blocker as kernel, python-client, server, platform-driver, target, or session. Include exact evidence and one safe next action.

Return only this shape:
{"kernel": {...}, "pythonClient": {...}, "server": {...}, "platformDriver": {...}, "target": {...}, "session": {...}, "blockers": [...]}
```

## Connect and retain one session

```text
Use only AMKernel's python_exec MCP tool. Do not use shell, editor, filesystem, browser, or another Python tool outside AMKernel.

Follow the appium-python skill. First run its read-only status procedure for <android|ios>. Stop on any blocker. Use these user-supplied values without inventing replacements:
- Appium URL: <url>
- target identifier: <serial-or-udid>
- app/package/bundle: <absolute-app-path-or-existing-package>
- remaining capabilities: <redacted JSON>

If a live top-level `driver` already exists, reuse it; do not create a second session or claim ownership. Otherwise create exactly one session with UiAutomator2Options or XCUITestOptions and assign it to the top-level name `driver`. Never use desired_capabilities. After successful creation, store `_amkernel_appium_owned_session_id = driver.session_id`; do not set the marker before success. Report the redacted options, session_id, current context/package, and an exception string capped at 2,000 characters if creation does not complete. Do not start or stop Appium Server or the target.
```

## Perform one bounded Appium operation

```text
Use only AMKernel's python_exec MCP tool. Reuse the existing top-level `driver`; do not create a session. Before acting, require driver.session_id and one successful live query.

Perform exactly this requested behavior: <behavior>.
Use only these stable locators supplied by the user or repository fixture: <locators>.
Use WebDriverWait and semantic locators; never use time.sleep. Assert the observable result: <assertion>.

On success, display one PNG screenshot with display(..., mime_type="image/png") and return a compact result containing session_id, action, locator, assertion, and elapsed milliseconds. On failure, preserve exception and context/activity strings capped at 2,000 characters, one screenshot when available, and a page-source summary capped at 500 elements, 500 characters per retained field, and 262,144 serialized UTF-8 bytes. Stop adding elements before the byte limit. Never print base64 image data, an unbounded XML tree, or full device logs.
```

## Inspect or write a focused Appium test

```text
Use only AMKernel's python_exec MCP tool for all repository inspection, code writing, and execution. Work only inside the current checkout. Confirm Path.cwd(), the repository marker files, and the exact target path before writing.

Task: <test change>.
Target file: <relative path>.
Focused command or callable: <exact test selector or callable>.

Read only the bounded source sections needed to match the repository's existing Appium test conventions. Do not change dependencies, global configuration, generated evidence, or unrelated files. Require the supplied target path itself to be relative before resolution. Resolve the checkout and target, require the resolved target to remain inside the checkout, and reject a symlink at the target or any checkout-relative ancestor. Refuse a path that was not explicitly supplied. Write the complete intended content atomically, preserving UTF-8 and the existing newline convention.

The test must use current Appium options classes, explicit waits, stable semantic locators, bounded screenshot/source evidence, and cleanup in finally. A test-created driver must be quit by that test; an externally supplied driver must not be claimed as cleaned. Run only the supplied focused selector with a bounded timeout and return bounded stdout/stderr plus the process exit code. On failure, diagnose the failing layer; do not install packages, start services, reset devices, or broaden the test command.
```

## Diagnose a failed live command

```text
Use only AMKernel's python_exec MCP tool. Do not retry yet and do not replace the top-level driver.

Classify the observed failure using retained evidence in this order: kernel, python-client, server, platform-driver, target, session creation, live command/locator. Preserve exception and context/activity strings capped at 2,000 characters. For a live session, collect only session_id, current context/activity when available, one PNG screenshot, a page-source summary capped at 500 elements, 500 characters per retained field, and 262,144 serialized UTF-8 bytes, plus the matching log slice capped at 65,536 UTF-8 bytes only if its externally supervised path was explicitly supplied. Redact capabilities and credentials.

Return one compact diagnosis with failingLayer, evidence, safeNextAction, sessionState, and cleanupState. Do not install, restart, reset, erase, reconnect, or create a replacement session without explicit approval.
```

## Explicit cleanup and reconciliation

```text
Use only AMKernel's python_exec MCP tool. Clean up only when top-level `driver` is not None, its session_id is nonempty, and `_amkernel_appium_owned_session_id == driver.session_id`. Otherwise refuse cleanup and report the session as externally owned or ownership unknown.

Capture session_id before cleanup. Call driver.quit() exactly once. If it returns, set driver=None, set `_amkernel_appium_owned_session_id = None`, and report that the HTTP session deletion returned. If it raises, preserve the driver handle, ownership marker, session_id, server URL, and exception string capped at 2,000 characters; report cleanup unknown and do not claim success.

Do not stop Appium Server, emulator/simulator, physical device, ADB, WebDriverAgent, or unrelated sessions. List those external resources as still externally owned and requiring observation by their owning supervisor.
```

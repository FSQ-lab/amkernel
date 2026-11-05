# Android execution through AMKernel

Read this reference for an Android scenario, including an already-running session. It owns
Android execution decisions, not environment preparation. Use `android-setup.md` only for missing
prerequisites and `amkernel-appium.md` for the shared Runtime, service ownership, bounded output,
recovery and cleanup contract. All session creation, live queries, actions, verification, recovery
and `driver.quit()` use the official Appium Python Client through `python_exec`.

## Work toward the requested final state

Use the user's request to determine the goal, authorized effects and the state that would prove
completion. Start from the current app surface, not a remembered sequence or example task.
Follow the shared control-first, visual-fallback policy in `amkernel-appium.md`: sufficient
control evidence needs no screenshot or image analysis. Android-specific decisions below do
not establish a second observation order or require repeated setup.

Use Appium to operate the app's supported UI. For a UI task, do not replace interaction with
database edits, internal business/save handlers or manufactured completion evidence. Group
known actions and their checks; return an observation when another decision is needed. Finish
only when the requested result is verified, or report the concrete blocker and remaining
uncertainty. A completed execution or a confident final answer alone is not task success.

## Understand the current surface

Keep these facts separate; establish only those needed for the next action and reuse evidence
while it remains valid. They are not a mandatory checklist before every command:

| Evidence | What it proves | What it does not prove |
| --- | --- | --- |
| Completed live session query | The queried remote operation works now | The requested app, page or object is selected |
| Current package/activity | The reported application/Android activity | The correct business page or result; one activity may host multiple views |
| Current native/Web context | Which automation surface is selected | That another context exists or the desired content is exposed there |
| Relevant element attributes and nearby structure | A current candidate and its observed semantics | Stable identity after navigation, scrolling or refresh; complete search results |
| Observed post-action business state | The specific result inspected | Persistent saving or submission unless that state actually demonstrates it |

A different package can be an expected system picker or authorized cross-app step, not necessarily
an app crash. Compare observed app/page identity with the requested flow before acting. A successful
package query alone is not permission to click the next remembered element. Wait boundedly for an
expected launch transition; do not repeatedly relaunch an app whose current page has not been checked.

## Connect to the selected app

Use the reviewed loopback server and observed target identity. For an explicitly selected APK:

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options

options = UiAutomator2Options().load_capabilities({
    "platformName": "Android",
    "appium:automationName": "UiAutomator2",
    "appium:udid": "<observed adb serial>",
    "appium:app": "<selected absolute app path>",
})
driver = webdriver.Remote("http://127.0.0.1:4723", options=options)
```

The APK example is not an instruction to install or replace an app for an existing-app request.
For an installed app, obtain its package and any needed launch activity from observed evidence;
use the observed client's supported options/activation API. Preserve existing app data. Do not
invent identifiers or uniformly enable `fullReset`, `noReset`, or `autoGrantPermissions` as a fix.

## Locate from current evidence

Native Android is not a Web page. Choose a locator from current, bounded evidence: a stable
resource-id or accessibility description (`content-desc`), then an appropriate Android UIAutomator
selector. Text can depend on locale and state; an accessibility label is not necessarily a visible
text value. Use XPath only when the observed structure makes it necessary; do not guess indices.

Use Appium's locator constants, not Selenium-only `By` attributes:

```python
from appium.webdriver.common.appiumby import AppiumBy

accessibility_element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, accessibility_id)
uiautomator_element = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, uiautomator_selector)
```

Supply both values from the current UI; do not run both searches automatically. Selenium `By`
has no `ACCESSIBILITY_ID` or `ANDROID_UIAUTOMATOR` constants. A successful find is only a candidate:
use relevant attributes, container or nearby labels to disambiguate before acting when needed.

A page-source tree is an accessibility/automation view, not a complete equivalent of the screen.
A missing node may mean the wrong page/context, an off-screen item or content not exposed there,
not merely a bad selector. Reduce source locally to relevant fields and candidates, then use
the shared visual-fallback decision only if needed. Android does not require a tree walk before
known canvas/custom-drawn content, nor permit guessed coordinates after an unrelated timeout.

## Keep native and Web contexts distinct

Never use `driver.title` as a native state or session probe. When a live native query is needed:

```python
if not driver.session_id:
    raise RuntimeError("No local session identity; reconcile before replacement")
native_state = {"package": driver.current_package, "activity": driver.current_activity}
```

A nonempty local `session_id` is not remote liveness proof. A failed live query leaves no verified
usable session; preserve its known identity for reconciliation under the shared lifecycle contract.
Compare `native_state` with the expected flow rather than treating any returned package as correct.

Use Web APIs only after observing and explicitly selecting an available Web context. A browser
app does not imply an available WebView. For a selected context, starting from the native surface:

```python
available_contexts = driver.contexts
if web_context not in available_contexts or not (
    web_context.startswith("WEBVIEW") or web_context == "CHROMIUM"
):
    raise RuntimeError("Requested Web context is not available")
native_context = driver.current_context
if native_context != "NATIVE_APP":
    raise RuntimeError("Observe the native context before this native-to-Web transition")
driver.switch_to.context(web_context)
if driver.current_context != web_context:
    raise RuntimeError("Web context selection was not verified")
web_title = driver.title
```

Here `web_context` is an observed user-relevant choice, not an invented context name. Selenium
Web locators such as `By.CSS_SELECTOR` apply only on the selected Web surface. Return to the
retained observed native context and verify selection before native operations. Context/navigation
changes invalidate previous element assumptions; reacquire relevant elements on the new surface.
Use verified official troubleshooting only when an actual context/transport problem needs it;
do not add WebView/Chromedriver setup to every native task.

## Navigate, scroll and handle system UI

Keep locators and minimal target identity, not long-lived element handles or row numbers. After
navigation, refresh, context changes or scrolling, reacquire affected elements and check the
intended identity. Repeated labels require container or item-specific evidence, not the first match.

For a list, prefer an available app search/filter when it matches the goal. Otherwise identify the
relevant scroll container and direction, inspect bounded candidates after each scroll, and stop
when the target is found or fresh observations show no progress/end of the relevant range. Do not
repeat the same swipe indefinitely. A partial viewport or incomplete search cannot prove global
absence or a superlative such as "latest". Use the shared conversation rules when ranking threads.

Before acting on a blocked field or missing control, inspect whether a keyboard, dialog, system
picker or permission prompt owns focus or obscures it. Do not assume Back always hides a keyboard:
it may navigate away or discard edits. Choose a supported, scoped action from observed state,
then verify the intended page and focus before continuing. Follow existing approval boundaries
for permissions, trust, lock screens and security choices; do not accept them to manufacture progress.

## Input, submit and verify the requested result

Determine whether the user wants replacement or appended text. Select the intended editable field,
change only its authorized content and read back the relevant value. Do not clear an entire form
or use blind repeated input to compensate for an unknown focus or a failed command.

Input, submission and persistence are separate outcomes. If the task is only to fill a field,
verify that field and leave it filled. If the task is to create/save something, observe the saved
object or relevant business state; reopen/read back only when needed to establish the requested
persistence. Do not restart every app just to verify ordinary input. A button click or disappearing
dialog is not by itself proof of a save. After an ambiguous submit, inspect the existing result
before deciding whether another submission is safe.

Before changing incidental state that must be restored, retain only the minimal relevant baseline,
such as the selected task view or identities of task-owned objects. Preserve the user's requested
end state. Do not claim restoration of an unobserved baseline or clear personal history/app data
as generic cleanup. Shared restoration, session and server outcomes remain separate.

## Recover from the observed failure, not a generic retry recipe

Inspect the actual `python_exec` status, `kernelState`, exception type and bounded actionable
message. A failed call does not imply a dead Kernel, dead session or failed overall task.

| Observation | Next decision |
| --- | --- |
| `StaleElementReferenceException` | Discard the affected handle; obtain current page/target evidence and locate it again. Do not repeat a command on the old handle or recreate a session merely for stale. |
| `NoSuchElementException` | Check relevant page/context, visible range and locator evidence. Resolve ambiguity or scroll only when justified; do not cycle through guessed selectors. |
| Locator/wait timeout | Obtain bounded fresh applicable package/activity and relevant UI facts. Decide whether the expected transition is pending, the page/locator is wrong, or another surface intervened. No equivalent wait without new evidence. |
| `AttributeError` or unsupported command | Correct the observed Client API/context mismatch. Do not classify it as device loss or repair the environment without evidence. |
| Action may have succeeded before an error | Inspect the external/business result first, especially before repeating create/save/send/delete. |
| Session error, interruption or Kernel death | Apply the shared live-query/reconciliation contract; local `session_id` alone proves nothing, and a dead Kernel cannot resume its Python objects. |

Use explicit bounded waits only for state expected to change, not a longer timeout as a universal
fix. After an ordinary Appium error with a surviving Kernel, establish current remote state with
one relevant live query before continuation; fold that query into the observation needed for the
next decision rather than adding a separate generic health-check loop. Host setup and diagnostics
do not authorize replacing Appium execution with shell/ADB actions. Official troubleshooting
steps that reset shared ADB, uninstall helpers or clear app data are not automatic retries; apply
the existing ownership and approval boundaries before any such repair.

## Choose useful call boundaries

- When the page, target and low-risk action are already known, keep locate, action and direct
  result verification together in one bounded `python_exec` call; include owned cleanup only
  when it has no independent wait or recovery decision.
- When the next action depends on interpreting unknown candidates or a changed page, return a
  bounded observation first, choose from that evidence, then act and verify. Do not pre-script
  an entire unknown flow or split every WebDriver command into its own call.
- An expected long wait, ambiguous irreversible action or independent cleanup failure needs an
  observable boundary. Keep naturally persistent `driver` and useful locals, not a workflow
  engine or task-state wrapper.

Optimize away repeated no-progress observations and equivalent failed waits, not necessary
verification. Call count is diagnostic telemetry, not a correctness threshold. These rules are
generic Android guidance: benchmark task steps, target answers and evaluator predicates do not
belong in this reference.

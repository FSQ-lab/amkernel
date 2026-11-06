# Native macOS setup and readiness through AMKernel

This reference owns dependency discovery, scoped installation approval, privacy handoff, and
readiness reporting for native macOS automation with Appium Mac2. Read it before the verified
`setup-mac2` skill. The official skill still owns its version-scoped environment checker, direct
doctor command, and bounded server smoke; this reference supplies the AMKernel Runtime seam,
reuse and installation decisions, target scope, and user-interaction contract.

Native macOS execution still uses the official Appium Python Client through `python_exec`. This
reference adds no driver wrapper, permission helper, desktop-specific MCP tool, or AMKernel core
surface. iOS/tvOS uses XCUITest, not Mac2. Android uses UiAutomator2.

## Boundary

Follow the supported-host and official-source verification boundaries in `SKILL.md`. This is
AMKernel-owned guidance, not pinned official Appium content. Do not edit the verified official
source, manifests, environment checker, doctor interpretation, or smoke verifier to make a host
pass.

Setup-only and status-only requests create no Appium session and do not launch the target app.
Read-only discovery may inspect executable/package metadata, selected Xcode, app identity, raw
available doctor evidence and task-owned server state. Installation, Xcode license or first-launch
work, persistent environment changes, server startup and privacy/security changes use the one
authorization record in `readiness-contract.md`. An explicitly requested app outcome authorizes
its visible launch/action sequence; do not ask again for the same effect.

## Scope the request before acting

| User request | May proceed to | Completion requires |
| --- | --- | --- |
| “What is missing for Mac2?” | Read-only discovery and static checks | Existing, missing, incompatible, not-applicable, and unknown layers reported separately; no install, app launch, server, or session |
| “Set up Mac2 on this Mac” | Disclosed dependency installation and official readiness checks | Applicable prerequisites pass; privacy and live session remain unverified unless separately exercised; no session |
| “Set it up and verify it can control this Mac app” | Setup plus one disclosed minimal live connection validation | Actual Client session through `python_exec`, one harmless target query, `driver.quit()`, and separate restoration/cleanup report |
| “Automate this Mac app” | Preparation, then the requested scenario | The requested outcome is verified; do not insert an unrelated smoke scenario first |

“Set up and let me use it” is not by itself authorization to open the app, trigger macOS privacy
prompts, grant permissions, enable system-wide Automation Mode, or create a session. Explain that a
live check is available after preparation and ask once whether to perform it. Do not require a live
Appium server merely to report installed/prepared dependency readiness.

## Guide a nontechnical user

Keep commands, paths, package names, bundle identifiers, and diagnosis Agent-owned. The user
handles only macOS actions that require their identity, password, physical confirmation, or privacy
choice.

For each human step, name the observed System Settings or system dialog, the one action needed now,
and the visible result that means it is complete. Do not send a checklist of hypothetical prompts.
If the expected prompt did not appear, ask whether it is visible or absent; do not guess that the
permission was granted. A reply of “done” authorizes a bounded recheck but is not evidence that the
setting took effect.

Never request the user's password, Touch ID approval, recovery key, or a screenshot containing
private desktop content. Password and biometric confirmation stay in the native macOS interface.

## Shared setup contract

Read `readiness-contract.md` before this adapter. Use its one authorization record, native-macOS
profile, canonical layer states, official-guidance ownership and cleanup rules. This reference adds
only selected Xcode/app identity and operation-specific macOS privacy applicability.

## Required layers

| Layer | Prepared setup evidence | Not proved by that evidence |
| --- | --- | --- |
| AMKernel Runtime and Python Client | Actual Runtime interpreter, package metadata, imports, compatible requirements | Appium server, Mac2, Xcode, target app, or permissions |
| Node/npm and Appium | Executed versions, executable paths, selected backend and Appium home | Compatible Mac2 driver or privacy authorization |
| Mac2 driver | Installed-list metadata, install path, exact driver metadata, direct doctor output | Successful WDA launch or target control |
| macOS and Xcode | Host version, selected Xcode/`DEVELOPER_DIR`, `xcodebuild` and SDK/tool execution | Xcode Helper privacy authorization |
| Target app | Observed app path and bundle identifier when relevant | Launchability, current foreground state, or safe mutation scope |
| Privacy/security | Current session/doctor evidence or user-visible system state for the actual process identity | Future prompts, another launcher identity, Screen Recording when no visual capture was requested |
| Live validation | Explicit session, harmless query, deletion, and restoration evidence | Broader app/task coverage or durable future readiness |

Keep privacy readiness `unknown` when static discovery cannot prove it. Do not report the machine
fully ready for a requested live validation while an applicable permission remains unknown or
blocked. Installed/prepared setup may still be ready with live proof explicitly pending.

## Shared Runtime and official driver seam

Use the actual managed Runtime identified by `python_exec` or verified AMKernel metadata; never
substitute the project `.venv`. Runtime/client applicability and repair authorization use
`readiness-contract.md`. Current Node, Appium, Mac2, dependency, doctor and server-smoke procedure
belongs to verified `setup-mac2`. Do not copy its version ranges or prerequisite checklist here.

Bind official checks to the selected Xcode, target app and task-scoped environment below. Preserve
an existing working backend and `APPIUM_HOME`; changing global/local mode or home is a disclosed
effect, not an automatic repair.

## macOS, selected Xcode, and target identity

Confirm the host and execute the selected tools rather than trusting directories or environment
variables:

```bash
sw_vers -productVersion
uname -m
printf '%s\n' "${DEVELOPER_DIR:-<unset>}"
xcode-select -p
xcodebuild -version
xcrun --sdk macosx --show-sdk-version
xcrun --find xcodebuild
```

Current official Mac2 guidance requires a supported macOS host and Xcode; the verified official
skill supplies its current version gate. Command Line Tools alone are not sufficient when the
selected driver needs the Xcode-bundled XCTest and helper assets. A successful `xcode-select -p`
does not prove that `xcodebuild` works, the license is accepted, first-launch components are ready,
or the selected path matches the intended Xcode.

Prefer a task-scoped `DEVELOPER_DIR` for an existing alternate Xcode. Do not run `sudo xcode-select
--switch` or modify global Xcode selection merely because the default is unsuitable. Xcode license
acceptance, first-launch installation, Apple downloads, and administrator confirmation are separate
disclosed changes.

When a target app matters, resolve its actual bundle identity without launching it. Reuse an
observed installed app or exact user-provided build; do not substitute Finder, Calculator, or a
different app as a setup shortcut. Multiple matching apps or builds require a short user choice.
Setup readiness does not establish that the target app is safe to mutate.

## Bind official checks to the selected native-macOS environment

After selecting Xcode and target-app evidence, verify and consume `setup-mac2`. Run its current
Node/Appium/driver discovery, doctor and bounded server smoke with the same task-scoped
`DEVELOPER_DIR`, backend mode and `APPIUM_HOME`. Preserve raw required fixes and warnings before
applying this adapter's target and privacy applicability rules.

Do not independently require a version, reinstall a listed driver, switch global/local mode or
create a second Appium home. A verified official warning is evidence, not permission to repair.
Only an observed applicable incompatibility or failed required operation can block the layer.

## Privacy and security seam

macOS privacy approval is process-identity-specific. Xcode Helper, Terminal, a Coding Agent app,
Appium, or a spawned helper may not share authorization. Reinstalling, relocating, re-signing, or
launching from another parent can trigger a new decision. Do not infer permission from an unrelated
process or an old successful run.

For Accessibility or other requested privacy access:

1. Let the official doctor or an explicitly authorized live session identify the missing permission
   and relevant process/helper.
2. Tell the user the exact visible System Settings path and observed process identity.
3. Ask the user to make the single native choice; never click the privacy control for them.
4. Re-run the bounded affected check. Preserve unknown if the check cannot prove the result.

Do not read or edit the TCC database, run `tccutil reset`, copy another process's entries, disable
SIP, or weaken system security. Do not run `automationmodetool
enable-automationmode-without-authentication` by default: it changes system-wide authentication
behavior and needs a separate security disclosure and explicit approval when current official
guidance establishes it as necessary. Prefer the normal user-visible Automation prompt.

Screen Recording is applicable only when the requested validation or task captures the rendered
screen. Accessibility does not imply Screen Recording, and Screen Recording does not imply
Accessibility or Automation. Do not request every privacy category as a generic checklist.

## Verification and completion

After approved changes, rerun only affected discovery, then the verified `setup-mac2` checks:

1. its environment checker with top-level `summary.requiredOk: true`;
2. direct `appium driver doctor mac2` with zero required fixes;
3. its bounded Appium server smoke with required server/driver/cleanup evidence.

Use the same command mode, `APPIUM_HOME`, Node executable, and selected `DEVELOPER_DIR` throughout.
A server smoke proves endpoint and driver loading, not target control or privacy readiness. Stop the
task-owned server; preserve a compatible pre-existing server and report its ownership separately.

Only an explicitly requested live validation may create a session. Use `Mac2Options` with
`platformName=mac` and `automationName=mac2`, the observed target identity, and the ownership,
restoration, timeout, cancellation, and cleanup contract in `amkernel-appium.md`. Perform one
harmless query, restore only task-owned reversible state, call `driver.quit()`, and report target,
session, server, and Kernel cleanup separately.

## Report truthfully

Return the canonical `readiness-contract.md` result with `target.platform=macos` and
`target.profile=native-desktop`. Include selected Xcode/app identity and only privacy layers required
by the requested operation. Setup-only creates no session. Authorized live validation additionally
requires an actual Mac2 session, a relevant query and truthful cleanup. `/status`, driver lists,
doctor warnings and historical sessions are not current target-control proof.

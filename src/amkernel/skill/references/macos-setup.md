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
Read-only discovery may inspect executable and package metadata, selected Xcode, app identity, raw
doctor evidence already available without a session, and task-owned server state. Installation,
Xcode license or first-launch work, persistent environment changes, server startup, application
launch, and privacy/security changes require the scoped approval below.

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

## One disclosure, one approval

Before the first mutation, explain what observed prerequisite is missing or incompatible and why an
existing candidate cannot satisfy it. Then disclose the complete proposed batch:

- **Component and exact target:** Runtime client, Node, Appium, Mac2 driver, Xcode or Command Line
  Tools component, with exact versions resolved from current metadata; never “latest”.
- **Source and backend:** existing uv tool source/extras, existing Node/version-manager or npm
  backend, Appium extension source, and Apple/Xcode source where applicable.
- **Install location and environment:** uv tool environment, npm prefix, selected `APPIUM_HOME`,
  selected Xcode and task-scoped `DEVELOPER_DIR`, driver install path, and temporary directories.
- **Impact:** other projects using the shared Runtime, Appium home, Node installation, Xcode, server,
  or privacy identity; whether the MCP connection or Kernel must be replaced.
- **State-changing effects:** package installation, Xcode license or first launch, server startup,
  target app launch, Accessibility/Automation/Screen Recording prompts, administrator
  authentication, and persistence beyond this task.
- **Rollback:** prior versions and paths, the command that removes only the task addition or restores
  the selected version, and effects that are not mechanically reversible such as accepted licenses
  or user-granted privacy decisions.
- **Secrets and elevation:** the user enters credentials only in native interfaces. Prefer
  user-level installation; a privileged or global change needs a separate explicit reason.

One approval covers exactly the disclosed batch. A different version, source, Appium home, global
Xcode selection, privacy action, persistent profile edit, privileged command, or newly required
component needs another disclosure. After approval, perform and verify the technical work in this
task; do not hand installation commands back to the user.

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

## Runtime Python and Client

Use `python_exec` to inspect the actual Runtime:

```python
import importlib.metadata as md
import sys
from appium import webdriver
from appium.options.mac import Mac2Options

print(sys.executable, sys.version)
for name in ("amkernel", "Appium-Python-Client", "selenium"):
    print(name, md.version(name))
print(md.metadata("Appium-Python-Client")["Requires-Python"])
print(md.requires("Appium-Python-Client"))
print(md.requires("selenium"))
```

If only host inspection is available, identify the uv-managed AMKernel installation with `uv tool
list --show-version-specifiers --show-with --show-extras --show-paths --show-python`. Preserve the
observed AMKernel source/version, Python selection, package indexes, extras, and every other
`--with` requirement. Never use system Python, the project `.venv`, or `pip` inside the uv-managed
tool environment.

Repair only a proven missing or incompatible Client layer. Recreate the same uv tool environment
with `--force` only when recreation is actually required, adding the resolved Client constraint and
retaining every recorded option. A shared Runtime replacement affects all activated projects;
disclose it and reconnect affected Kernels before use.

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

## Node, Appium, Appium home, and Mac2 driver

Discover the active backend and every relevant path before changing it:

```bash
node -v
node -p "process.execPath"
npm -v
npm config get prefix
printf '%s\n' "${APPIUM_HOME:-<unset>}"
command -v appium
appium -v
appium driver list --installed --json
```

An unset `APPIUM_HOME` or missing `appium` on one `PATH` is not proof of absence. Inspect the
selected executable, its package-manager ownership, effective Appium home, and existing driver
install path. Reuse a compatible installation. Do not install a second global Appium, silently
switch between global and local mode, or create another Appium home to bypass a conflict.

Resolve an exact candidate from current registry metadata before approval:

```bash
npm view "appium@$APPIUM_VERSION" engines --json
npm view "appium-mac2-driver@$DRIVER_VERSION" engines peerDependencies dist.integrity --json
```

Evaluate the complete declared Node/npm engine and Appium peer range. Do not reduce compatibility
to major versions, infer it from a successful package download, or upgrade every driver. The current
Mac2 major line may require Appium 3 while older lines supported Appium 2; use the selected version's
actual declarations and official documentation.

For the default global Appium route, install only the approved exact driver into the same selected
Appium home:

```bash
APPIUM_HOME="$SELECTED_APPIUM_HOME" appium driver install "mac2@$DRIVER_VERSION"
APPIUM_HOME="$SELECTED_APPIUM_HOME" appium driver list --installed --json
APPIUM_HOME="$SELECTED_APPIUM_HOME" appium driver doctor mac2
```

Use local `npx --no-install appium` only when the user explicitly selected the existing local mode.
Do not use `sudo npm`, change the global npm prefix, or run a broad driver update as a repair. Keep
the raw doctor result. A required failure blocks prepared readiness; a warning remains a warning
unless current official guidance makes it applicable to the selected target.

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

Report these layers independently:

- Runtime/client: satisfied, incompatible, repaired, or unknown;
- Node/Appium/Mac2: exact observed versions, selected home/mode, doctor status;
- Xcode: selected path/version and executable readiness;
- target app: observed identity or unresolved choice;
- privacy: verified for the relevant identity, blocked on one user action, not applicable, or
  unknown;
- prepared setup: ready or blocked, with exact blockers;
- live control: not requested, not attempted, passed, failed, or unknown;
- cleanup: session, target restoration, server, and Kernel reported separately.

Never convert “installed”, a passed `/status`, a doctor warning, a user's “done”, or a historical
session into proof of current target control. Prepared setup is not macOS platform qualification,
and a successful synthetic or minimal validation does not qualify arbitrary desktop tasks.

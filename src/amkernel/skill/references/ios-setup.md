# iPhone setup and readiness through AMKernel

This reference owns physical iPhone discovery, dependency ownership, scoped approval, signing
route selection, WebDriverAgent reuse, and the human-interaction seam. Read it before the verified
`setup-xcuitest` skill for a physical iPhone target. That skill still owns the shared Xcode, Node, Appium,
driver, doctor, and server checks; the verified `xcuitest-real-device-config` skill still owns its
trust, Developer Mode, signing, provisioning, and WDA procedure. This reference does not replace
those steps or restate them as a second tutorial.

A simulator or tvOS request keeps its existing route. This reference is iOS physical-device
guidance only, and no iPhone task requires simulator inventory, a simulator runtime, or a booted
simulator. Android setup remains in `android-setup.md`; nothing here requires Android SDK
discovery.

The execution, evidence, service, and cleanup contract is in `amkernel-appium.md`. This reference
adds no server, driver, signing helper, device wrapper, MCP tool, or AMKernel core surface.

## Boundary

Follow the supported-host and official-source verification boundaries in `SKILL.md`. This
reference is AMKernel-owned guidance, not pinned official content. Do not change official source,
archive, manifest, or verifier content to make a route pass.

Setup-only and status-only requests create no session and do not launch WDA. Discovery is
read-only. Installation, Xcode first-launch or license changes, device trust, Developer Mode,
signing, provisioning, device registration, WDA installation, tunnel or developer-service changes,
and service startup require the scoped approval described below.

## Scope the request before acting

| User request | May proceed to | Completion requires |
| --- | --- | --- |
| "What is missing for this iPhone?" | Read-only discovery and static checks | Existing, missing, not-applicable, and unknown layers reported separately; no install, launch, or session |
| "Set up this iPhone" | Disclosed installation, account/device setup, signing preparation, official readiness checks | Applicable prerequisites pass; WDA live launch remains explicitly unverified unless separately authorized; no session |
| "Set it up and verify it can control this phone" | The setup above, plus one disclosed minimal connection validation | Actual Client session through `python_exec`, one harmless live query, `driver.quit()`, and separate cleanup report |
| "Operate this phone for a task" | Preparation, then the requested scenario | The requested outcome is verified; do not insert an extra smoke scenario first |

"Set up and let me use it" is not by itself authorization to start WDA or create a session. State
that a real connection check is possible after preparation, and ask once whether to perform it.
Every installation or security change still receives its own scoped disclosure.

Installed/prepared environment readiness in setup-only scope does not require a running Appium
server or WDA. Report them as not started or launch-unverified, not as missing dependencies solely
because they are stopped. A requested live endpoint or connection validation does require the
appropriate reachable service and actual session evidence. Check prerequisites for the requested
scope rather than quietly widening it to service startup.

"Configured" does not promise durable readiness: disconnection, signature expiry, driver or Xcode
updates, and device trust changes can invalidate earlier evidence.

## Guide a nontechnical user

Use the user's language. Keep commands, paths, identifiers, and diagnosis Agent-owned; do not make
the user understand Appium, WDA, provisioning, or Runtime details before they can proceed. Describe
WDA, when relevant, as the helper that lets automation communicate with the iPhone.

For each human step, say where to act (iPhone or Mac, and the observed app/dialog), the single
action needed now, and the visible result that means it is complete. Explain why only when it
affects the user's decision or security. Do not send a checklist of future screens or assume a
dialog appeared. If its location is unclear, ask whether it is on the phone, on the Mac, or absent;
never ask for the code or a screenshot of an authentication dialog.

Wait for the user to finish, then perform the relevant bounded check yourself. A reply of "done"
is permission to re-check, not evidence that the prerequisite passed. If the check still fails,
name the observed remaining blocker and give only its next action; do not repeat the entire setup.
For example, when the phone is currently locked: "请在 iPhone 上解锁，看到主屏幕后告诉我。密码只在手机输入，不要发给我；我会重新检查连接。"

## One disclosure, one approval

Before the first mutation, explain the decision in plain language: what is missing, why the
observed existing tools cannot satisfy it, and what the Agent proposes to do. Follow with compact
details covering every planned change below, then ask for approval. Keep exact versions, sources,
locations, shared impact, and rollback visible; plain language must not hide material effects.
If evidence is incomplete, report what is unknown and obtain the next relevant read-only
observation instead of treating uncertainty as permission to install or re-sign. If that
observation cannot be obtained, pause at that blocker rather than proposing a speculative repair.

- **Component and exact target:** distribution or package name and the exact version resolved from
  current metadata; never "latest" or a guessed version.
- **Source and backend:** uv tool with its source and extras; npm/Appium extension source; Apple or
  Xcode source for Xcode and signing assets; existing host tunnel or developer-service mechanism if
  one is required.
- **Install location and environment:** uv tool environment; npm prefix and `APPIUM_HOME`; selected
  Xcode and task-scoped `DEVELOPER_DIR`; selected driver install path; temporary artifact
  directories.
- **Impact:** which other projects, shared Appium homes, drivers, sessions, devices, or running
  services are affected; whether the Kernel connection must be replaced or reconnected; which
  existing compatible components are preserved.
- **State-changing effects:** Apple Account sign-in, Xcode license or first launch, device trust,
  Developer Mode and restart, device registration, provisioning-profile or bundle-ID change,
  WDA installation or replacement, keychain access confirmation, administrator authentication, and
  whether the effect persists after the task.
- **Rollback:** the exact prior version, source specification, install path, and task-scoped
  environment recorded before the change; the command or action that removes only this task's
  addition; what cannot be rolled back, such as an accepted license, a registered device, a
  generated profile, or a changed trust setting.
- **Secrets:** the user enters passwords, PINs, two-factor codes, and keychain confirmations only in
  native interfaces. Never request, capture, print, or store them.

One approval covers exactly the disclosed batch. Newly discovered scope, a different version,
additional device registration, a persistent environment edit, or an additional privileged action
requires a new disclosure. A broad "set up my iPhone" request does not authorize unrelated
drivers, updates, simulator components, or device erasure.

After approval, perform the disclosed technical work in this task and verify each layer. Do not
hand installation commands or Xcode configuration back to the user. The user handles only actions
that require their account, body, or local security confirmation.

## Dependency ownership and required layers

| Dependency | Owner | Discovery or reuse evidence | Change boundary |
| --- | --- | --- | --- |
| Python, AMKernel, Appium Python Client, Selenium | Shared `uv tool` Runtime | Current MCP/CLI interpreter, tool source/extras, package metadata, actual imports | Keep AMKernel version/source and all extras; never use system Python or the project `.venv` |
| Node/npm and Appium Server | Existing package manager or user-level Node installation | Executable paths, exact versions, Appium entry point, declared engine constraints | Reuse the existing backend; do not reinstall for a `PATH` miss or a newer release |
| XCUITest driver | Appium extension CLI in one `APPIUM_HOME` | `driver list --installed --json`, install path, driver metadata, raw doctor output | Install only the selected driver version; do not update every driver or write another Appium home |
| WDA source and artifacts | Selected driver and Xcode | WDA version/path inside the driver installation, artifact platform/architecture/signature, target coverage | Do not install a separate WDA; driver updates can invalidate a prepared artifact |
| Xcode, iOS SDK, developer tools | Xcode/Apple distribution | Selected `DEVELOPER_DIR`, `xcode-select -p`, executed versions, SDK version, device support | Prefer a task-scoped `DEVELOPER_DIR`; do not switch global Xcode or install simulator runtimes |
| Certificates, profiles, account, device trust | Xcode, keychain, iPhone | Valid signing identity, profile expiry/coverage, Team/Bundle matching, current device state | Registration, profile creation, trust, and Developer Mode are disclosed effects; never request private-key export |
| Appium Server, WDA process, tunnel or port forward | Host tools and driver | Task-owned process identity, port, logs, current service state | Reuse matching shared resources; stop only task-owned processes; no persistent daemon or launch agent |

A physical iPhone target does not require simulator tools, a simulator runtime, or a booted
simulator. A connected phone also does not make the host setup ready: report host dependency
blockers and target readiness separately.

## Runtime Python and client

Prefer `python_exec` evidence:

```python
import importlib.metadata as md
import sys
from appium import webdriver
from appium.options.ios import XCUITestOptions

print(sys.executable, sys.version)
for name in ("amkernel", "Appium-Python-Client", "selenium"):
    print(name, md.version(name))
print(md.metadata("Appium-Python-Client")["Requires-Python"])
print(md.requires("Appium-Python-Client"))
print(md.requires("selenium"))
```

If the Runtime is reachable only from the host, identify the uv-managed installation and preserve
its environment:

```text
uv tool list --show-version-specifiers --show-with --show-extras --show-paths --show-python
uv tool dir
uv tool dir --bin
```

Use the listed `amkernel` tool environment, its interpreter, and its recorded extras. Do not use
`python3` from `PATH`, the project `.venv`, or another project's environment.

Evaluate and classify the dependency layer with `SKILL.md`'s exact labels:
`satisfied-constraints`, `warning-only`, `unverified`, `observed-requirement-violation`, and
`proven-incompatible`. A successful import proves client dependency presence, not device or
session compatibility.

Repair only when the actual Runtime lacks a required client or violates an applicable requirement.
Record the current install specification and extras first, then recreate the same tool with
`--force` only when recreation is needed:

```bash
uv tool list --show-version-specifiers --show-with --show-extras --show-paths --show-python
# Resolve these values from the current tool before replacement, not from this example.
uv tool install "$OBSERVED_AMKERNEL_SPEC" --force --python "$OBSERVED_PYTHON_SPEC" \
  "${PRESERVED_UV_OPTIONS[@]}" --with "$RESOLVED_CLIENT_SPEC"
```

Reuse the observed package-index, local-path, or other source specification, its same AMKernel
version and Python selection. `PRESERVED_UV_OPTIONS` contains the recorded index/source settings,
package extras and other `--with` requirements; replace only the client requirement being repaired,
not unrelated extras. `--force` does not authorize an AMKernel version change. Do not mutate the
tool environment with `pip`. A shared Runtime replacement affects every activated project: disclose it, then
reconnect or restart affected Kernels before use. If the requested constraint conflicts with the
Runtime package's own requirements, report the conflict instead of forcing an incompatible
environment.

Offline index: verify the existing Runtime and report a missing distribution as an offline
blocker; do not invent a version or substitute an unrelated interpreter.

## Xcode and the selected toolchain

Inspect explicit settings first, then the active and other installed Xcodes. Execute only the
selected developer directory:

```bash
printf '%s\n' "${DEVELOPER_DIR:-<unset>}"
xcode-select -p
xcodebuild -version
xcodebuild -showsdks
xcrun --sdk iphoneos --show-sdk-version
xcrun --find devicectl
xcrun --find xctrace
```

If another installed Xcode is needed, validate it under a task-only `DEVELOPER_DIR`:

```bash
DEVELOPER_DIR="/Applications/Xcode-<version>.app/Contents/Developer" xcodebuild -version
```

Do not run `sudo xcode-select --switch`. Do not persist a global Xcode change merely because an
unset `DEVELOPER_DIR` looks incomplete.

Command Line Tools alone are not an XCUITest toolchain: the selected Xcode must supply the iOS SDK,
device support, `devicectl`, and `xctrace`. Check license and first-launch state with the selected
Xcode; acceptance or first-launch component installation may require administrator approval and is
a separate disclosed change. Do not install a simulator runtime to satisfy a physical-device task.

If no usable Xcode exists, that is a missing prerequisite. The approved route is the official
Apple distribution for the host: the App Store or the Apple Developer download site, selected from
current official metadata and recorded by exact version. Installation is large, requires the
user's Apple Account and often administrator authorization, and is not performed silently. After
installation, re-run the checks above under the selected `DEVELOPER_DIR`.

## Physical target discovery

Use the selected Xcode's `devicectl`, and interpret its JSON using the current local help/schema.
Keep task-owned temporary files:

```bash
TMP="$(mktemp -d)"
xcrun devicectl list devices --timeout 30 --json-output "$TMP/devices.json"
xcrun devicectl list devices --help
```

Pass a bounded `--timeout` to each `devicectl` command; do not let discovery or a device query wait
indefinitely.

For the selected target, check only the facts needed for the next decision:

```bash
xcrun devicectl device info details --device "$UDID" --timeout 30 --json-output "$TMP/details.json"
xcrun devicectl device info ddiServices --device "$UDID" --no-auto-mount-ddis --timeout 30 --json-output "$TMP/ddi.json"
xcrun devicectl device info lockState --device "$UDID" --timeout 30 --json-output "$TMP/lock.json"
xcrun devicectl device info apps --device "$UDID" --bundle-id "$TARGET_WDA_BUNDLE_ID" --timeout 30 --json-output "$TMP/apps.json"
xcrun xctrace list devices
```
Use a bounded host-tool deadline for `xctrace`, which may not expose a command-level timeout.

`device info apps` is relevant when checking an installed WDA; do not use it as a generic
inventory. `ddiServices` and `lockState` fail or report unavailable when the current development
service is not usable; preserve that result instead of treating it as a signing error. Newer
`devicectl` versions expose `properties` and deprecate older keys; read the actual JSON rather than
assuming field names from this reference. A listing can include historically paired, disconnected
devices.
The current `ddiServices` default can mount/update a developer disk image. Use
`--no-auto-mount-ddis` for read-only discovery when supported; confirm the selected version's
help before execution. If a version offers no non-mutating query, keep that service layer unknown
until an explicitly approved preparation step. Filter installed-app queries to the observed WDA
Bundle ID; do not emit unrelated application inventory.

Report physical Apple targets in separate evidence layers:

- **discovered:** the device is listed; this alone does not prove a current connection.
- **connected:** current transport/connection evidence exists in the selected tool's present
  output.
- **usable-for-development:** current pairing/trust, Developer Mode, lock state, and the required
  developer disk image or development service are usable. A historical `paired` value, a
  previously enabled Developer Mode, or an old Xcode test does not override current unavailability.
- **ready-for-xcuitest:** the selected driver, signing/provisioning assets, and WDA route are
  verified for this target.

Preserve unknown and not-checked states with their reasons. Do not promote an earlier layer into a
later one. Live XCUITest proof belongs to an explicitly requested validation or scenario.

If several current targets match, offer one short choice using familiar device names; include a
UDID only when needed to distinguish them. Do not require the user to find a UDID. If the phone is
locked or disconnected, guide the user to connect and unlock it; do not unlock it remotely, dismiss
security prompts, or claim readiness from the user's verbal confirmation alone. Re-check current
connection and development-service evidence afterward.

### Developer services, disk image, and tunnels

Opening the selected Xcode after connecting normally mounts the developer disk image. Some
iOS/driver combinations need an additional developer-service, RemoteXPC, or tunnel mechanism before
WDA can launch. Treat that mechanism as driver/version-dependent:

- confirm from the selected driver's installed version, metadata, help, and current official docs
  that it is required;
- preserve and reuse the host mechanism the user already has, if it is current and applicable;
- disclose administrator authentication, port, process lifetime, and cleanup before starting it;
- keep it task-owned and stop it after an authorized validation unless the user requested it as a
  lasting part of their setup;
- do not install `pymobiledevice3`, `tidevice`, `ios-deploy`, `go-ios`, or another device tool by
  default, and do not add a launch agent or daemon.

If a tunnel or image service fails, that is a connection/developer-service diagnosis, not evidence
that signing or the certificate is invalid. Do not replace the user's working mechanism with a new
one without a disclosed reason.

## Node, Appium, and the XCUITest driver

Discover the existing installation before changing anything:

```bash
node -v
node -p "process.execPath"
npm -v
command -v appium
appium -v
appium driver list --installed --json
```

For generic Node discovery, version managers, official archive checksums, npm prefix rules, and
exact engine/peer evaluation, reuse
[`android-setup.md#node-npm-appium-and-the-selected-driver`](android-setup.md#node-npm-appium-and-the-selected-driver).
Do not run Android SDK, JDK, ADB, emulator, or system-image discovery for an iPhone task.

Resolve the XCUITest driver's exact version and constraints from current metadata; do not reduce
compatibility to a "latest" install or a major-version floor:

```bash
npm view "appium-xcuitest-driver@$DRIVER_VERSION" engines peerDependencies --json
appium driver list --installed --json
```

The installed-driver JSON reports the driver version, `installPath`, and peer Appium range. Inspect
the driver package metadata, and compare the active Node/Appium versions with its `engines` and
`peerDependencies`. Preserve an existing compatible driver; do not update other drivers to match a
newer release.

Use one `APPIUM_HOME` consistently for extension commands, doctor, and the server:

```bash
export APPIUM_HOME="${APPIUM_HOME:-$HOME/.appium}"
appium driver doctor xcuitest
```

Run the doctor with the same task-scoped `APPIUM_HOME`, `DEVELOPER_DIR`, Node, and Appium entry
point the server will use. Preserve its raw stdout/stderr and exit status. Classify each required
fix and warning by applicability using the same three categories as Android setup:

- **applicable-blocking:** the requested iPhone target needs this layer now; resolve and re-run.
- **not-applicable-to-this-target:** simulator, tvOS, FFmpeg, or another component this physical
  target does not need.
- **optional-unrequested:** an explicitly optional capability the user did not request.

Report the raw findings and the classification together. Never filter the official output or
present a filtered subset as the raw result. Official helper summaries follow the same rule; a
sandbox or Appium-home permission failure is evidence, not proof that a target or package is
absent.

The official `check-xcuitest-env.mjs` summary includes simulator inventory in its aggregate
`requiredOk`. For a physical iPhone target, simulator inventory is
`not-applicable-to-this-target`: do not install a simulator runtime, create a simulator, or report
the physical setup as blocked solely because simulator inventory failed. Preserve the raw helper
result, name the failing component and its applicability, and use the applicable Xcode, Node,
Appium, driver-doctor, `/status`, and selected-driver gates for the phone. This applicability seam
does not relax those applicable official checks.

Only after approval, install the missing selected driver into the same Appium home:

```bash
appium driver install "xcuitest@$DRIVER_VERSION"
appium driver list --installed --json
```

Do not install with a bare latest version when its peer range does not include the active Appium.
If a shared Appium home has a real conflict, first check whether the task can safely use an
isolated task-owned Appium home and port without colliding with existing sessions or devices;
disclose any extra installation. Do not overwrite or remove a shared driver to make room. Record
the previous state and roll back only this task's addition:

```bash
# Only when this task added it:
appium driver uninstall xcuitest
```

An existing compatible Appium/driver pair is reused without upgrading merely to silence a warning.

## Signing, provisioning, and WDA reuse

### Prefer reusable evidence

Check these in order and stop at the first route that satisfies the target:

1. **Existing running WDA endpoint.** Confirm reachability and target/transport binding with a
   small `/status` request and the selected driver's documented attachment method. Do not take
   over another user's active session. Attach only when an Appium session is explicitly authorized.
2. **Installed WDA or prepared signed artifact.** Treat it as a reuse candidate only after checking
   version, platform/architecture, Bundle ID, signature, provisioning-profile coverage, Team, and
   target coverage. Always confirm the actual installed identity; do not infer it from an icon or a
   stale build directory.
3. **Build from the selected driver's WDA source.** Use the verified official preparation route and
   task-scoped build/signing settings. Do not edit the npm-installed WDA project as the durable
   configuration; a driver update can overwrite it.
4. **Fix the observed blocker.** A missing or expired profile, invalid certificate, missing private
   key, Bundle/Team mismatch, or uncovered device needs the corresponding signing repair. An
   unreachable endpoint, locked phone, permission prompt, port conflict, or transport error does
   not.

Static artifact candidacy is independent of endpoint reachability: an artifact with verified
identity/signature/profile/target coverage can remain a candidate after a transport timeout.
That timeout still blocks the requested connection route and proves neither attachment nor launch.
Keep the endpoint failure and live-readiness uncertainty; do not invalidate the artifact or re-sign
it merely to make the transport result pass.

Do not use `appium:useNewWDA=true` as a default repair; it removes and rebuilds WDA. Use
`appium:webDriverAgentUrl` only for a confirmed existing instance. Use
`appium:usePreinstalledWDA` or `appium:prebuiltWDAPath` only when the installed driver version,
device OS, bundle identity, and artifact meet the conditions documented for that mode.

For WebDriverAgent v13+ prebuilt/preinstalled flows, the pinned official guidance requires
iOS/tvOS 17.0 or newer. For older iOS/tvOS, use the default Appium-managed `xcodebuild` flow, an
applicable `.xctestrun`/bootstrap path, or attach to an already running WDA. A preinstalled runner
without the expected `.xctrunner` relationship needs the driver-documented bundle identifier and
suffix, not a blind reinstall. Confirm these conditions from the selected driver's installed
capability reference before choosing a mode.

### Concrete local observations

Resolve the actual driver `installPath` from `driver list --installed --json`; never assume the
default Appium home layout. Resolve its WDA dependency using that path:

```bash
DRIVER_PATH="<observed driver installPath>"
WDA_PKG="$(node -e 'console.log(require.resolve("appium-webdriveragent/package.json", {paths: [process.argv[1]]}))' "$DRIVER_PATH")"
node -e 'console.log(require(process.argv[1]).version)' "$WDA_PKG"
```

List available signing identities and profile directories, but return only counts, validity, and
match/no-match results. Never print a full identity, private key, `.p12`, profile content, or full
UDID in shared evidence.

```bash
IDENTITIES="$(security find-identity -v -p codesigning)"
printf 'valid-identities=%s\n' "$(printf '%s\n' "$IDENTITIES" | awk '/valid identities found/{print $1}')"
find "$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles" \
  "$HOME/Library/MobileDevice/Provisioning Profiles" \
  -name '*.mobileprovision' 2>/dev/null | wc -l
```

For a candidate local artifact, check its code signature and identity:

```bash
WDA_APP="<absolute path to WebDriverAgentRunner-Runner.app>"
codesign --verify --deep --strict --verbose=2 "$WDA_APP"
codesign -dv --verbose=4 "$WDA_APP" 2> "$TMP/wda-signature.txt"
```

Inspect the profile embedded in the actual candidate artifact, not an unrelated profile with a
similar name. Decode into task-owned scratch and use the verified Runtime's standard library;
report match booleans only. Do not parse dates with a guessed shell format or treat every wildcard
as covering every Bundle ID:

```bash
security cms -D -i "$WDA_APP/embedded.mobileprovision" > "$TMP/profile.plist"
"$RUNTIME_PYTHON" - "$TMP/profile.plist" "$RUNNER_BUNDLE_ID" "$TEAM_ID" "$UDID" <<'PY'
import datetime as dt
import fnmatch
import json
import plistlib
import sys

with open(sys.argv[1], "rb") as source:
    profile = plistlib.load(source)
target_bundle, target_team, target_device = sys.argv[2:]
expiry = profile.get("ExpirationDate")
if isinstance(expiry, dt.datetime) and expiry.tzinfo is None:
    expiry = expiry.replace(tzinfo=dt.timezone.utc)
app_id = profile.get("Entitlements", {}).get("application-identifier", "")
prefix, separator, pattern = app_id.partition(".")
print(json.dumps({
    "unexpired": isinstance(expiry, dt.datetime) and expiry > dt.datetime.now(dt.timezone.utc),
    "teamMatches": target_team in profile.get("TeamIdentifier", []),
    "bundleCovered": bool(separator) and prefix in profile.get("ApplicationIdentifierPrefix", [])
        and fnmatch.fnmatchcase(target_bundle, pattern),
    "deviceCovered": target_device in profile.get("ProvisionedDevices", [])
        or profile.get("ProvisionsAllDevices") is True,
    "revocation": "not-checked-locally",
}))
PY
```

This probe checks only the profile fields shown. Separately verify certificate validity and
membership in the profile's signing certificates, the corresponding private key, artifact
platform/architecture and signed entitlements, and their Team/Bundle relationship. A profile's
App ID prefix can differ from its Team ID; compare both with their actual roles. Do not print full
profiles or identities in shared evidence.

An uncovered device remains a blocker until approved registration/profile regeneration completes
and coverage is rechecked. The account's ability to register the device does not prove existing
coverage. Local signature/profile checks cannot prove revocation, current device trust, online
validation, or launchability. Preserve those unknowns, and never call WDA launch-verified before
an actual authorized start.

### Shortest signing path

1. **Reuse a valid WDA or signed artifact.** If it already matches the target, do not require an
   Apple Account login, certificate export, or rebuild.
2. **Use an existing local signing identity and profile.** Keep the build/base Bundle ID distinct
   from the actual runner `CFBundleIdentifier`: normal Xcode runners append `.xctrunner`.
   Observe `WDA_BUILD_BUNDLE_ID` from the selected project/build settings and `RUNNER_BUNDLE_ID`
   from the resulting artifact; do not pass an already suffixed runner ID back as the base.
   Match the embedded profile against the final runner, then map driver Bundle ID/suffix
   capabilities to that observed identity. Prefer invocation-level settings over npm source edits.
   Choose a disclosed user-owned `WDA_DERIVED_DATA` location outside temporary cleanup when a
   prepared `.app`/`.xctestrun` is a setup deliverable. Preserve its required products and layout
   until the user no longer needs that route; recheck paths after any move. Provisioning updates
   and device registration change external state and need explicit approval. The argument shape is:

   ```bash
   WDA_PROJECT="$(dirname "$WDA_PKG")/WebDriverAgent.xcodeproj"
   WDA_DERIVED_DATA="<approved retained build directory, or task scratch for a disposable build>"
   DEVELOPER_DIR="$DEVELOPER_DIR" xcodebuild clean build-for-testing \
     -project "$WDA_PROJECT" \
     -scheme WebDriverAgentRunner \
     -destination "generic/platform=iOS" \
     -derivedDataPath "$WDA_DERIVED_DATA" \
     -allowProvisioningUpdates \
     PRODUCT_BUNDLE_IDENTIFIER="$WDA_BUILD_BUNDLE_ID" \
     DEVELOPMENT_TEAM="$TEAM_ID" \
     CODE_SIGN_IDENTITY="$SIGN_ID"
   ```

   Use the verified official preparation command for the selected target when it differs. Include
   `-allowProvisioningUpdates` only when those updates are approved; add
   `-allowProvisioningDeviceRegistration` only when approved registration is required. Verify the
   generated runner's actual Bundle ID/profile/capability relationship. Stop after applicable
   build/signature checks in setup-only scope; retain products required by the selected route.
3. **Configure or renew with Xcode's normal account and automatic signing.** A free Apple Account
   is sufficient by default; do not require a paid membership. For a free account, use a Bundle ID
   Xcode has already accepted. For a paid team, use the user's approved Team and Bundle ID. If the
   account is not signed in, point to the current Xcode Accounts interface; the user completes
   sign-in and two-factor authentication there. Ask which Team only when observed evidence cannot
   determine it: show the observed account or organization labels as a short choice, not Team IDs
   for the user to look up. Do not silently choose the first of several eligible Teams.
4. **Create the minimum missing asset when needed.** A temporary Xcode project, profile, device
   registration, or signing-setting change is a disclosed effect. The Agent provides identifiers
   and performs the technical configuration; the user handles the account and native confirmations.
   Prefer invocation-level settings; do not leave a modified WDA source tree as a hidden dependency.
5. **Avoid the `.p12` + `resigner` route by default.** Use it only when an existing artifact and
   available signing material make it clearly appropriate and the user authorizes that exact
   route. Do not install a resigner or extra signing helper merely to follow a generic checklist.
   The driver's `build-wda` helper is simulator-only, and `sign-wda` requires a resigner.
6. **Verify before installation, and installation is not launch.** Check profile validity, target
   coverage, Team/Bundle/entitlement matching, and the built artifact's signature. After building
   or installing, stop at the readiness layer achieved. Framework removal and re-signing apply
   only when required by the selected preinstalled/prebuilt route and device/driver version, not
   to every Appium-managed build on iOS 17+. Never modify a signed `.app` without re-signing it.

In a setup-only task, do not run a manual Xcode **Product > Test**, and do not use a build or WDA
launch as a hidden smoke test. Opening the WDA project for signing configuration is acceptable when
disclosed, but stop before launching. Launching WDA belongs to an explicitly authorized validation
or scenario and is performed through the Appium lifecycle, not a manual Xcode test.

### Human security prompts

Apply the one-action interaction above. Select only the row matching the current observed prompt;
connection, unlock, and trust are separate steps, not a single instruction:

| Prompt | User-facing guidance | Check afterward |
| --- | --- | --- |
| iPhone disconnected | "Connect this iPhone to the Mac. Tell me when it is connected; I will check whether it is detected." | Current target visibility and connection; only then handle an observed lock or trust prompt |
| iPhone locked | "Unlock the iPhone. When the home screen appears, tell me; enter the passcode only on the phone, never here." | Current lock and connection state; only then handle any observed trust prompt |
| "Trust This Computer" | "On the iPhone, tap Trust in this prompt and complete any passcode confirmation on the phone. Tell me when the prompt closes; do not send me the passcode." | Current pairing/trust and required development-service state, not the user's verbal confirmation |
| Developer Mode first enable | Explain that it lowers device security restrictions and may require a restart; after approval, point to the current Settings interface and the password confirmation. | Re-discover the device and confirm current Developer Mode/service availability |
| Developer app not trusted | Only when that actual error appears, guide trust for the matching developer in Settings and note that network validation may be required. | Target trust/launch result; do not assume every phone shows the same path |
| Mac keychain confirmation | "Confirm this prompt is for the signing tool and certificate used in this task, and complete it in the Mac dialog." | Build/signature result. Do not choose "Always Allow" by default or change keychain access control. |
| Apple Account sign-in or two-factor | Complete in the Xcode/Apple interface | Account, Team, signing identity, and profile availability; never read authentication credentials |
| Device passcode requested during a connection | Enter the passcode on the device itself; pause the dependent action | Whether the device unlocked and the current service became usable; do not treat every passcode prompt as a signing failure |

UI Automation and Safari Web Inspector/Remote Automation are target-scope settings. Enable one only
when the selected driver/iOS version or the requested web/hybrid scenario needs it, only when it is
observed disabled, and only after disclosure; do not toggle an already enabled setting or require
Safari automation for a native-app task. Re-check the current setting afterward.

Do not call every prompt a "WDA PIN". Treat a user-reported PIN or keychain block as a real blocker,
but determine its location from the current interface and logs. Never leave an unbounded launch
call waiting for the user, never run a retry storm, and never turn a timeout into a reason to
re-sign. After the user completes the action, re-check the preconditions that may have changed.

If the user cancels or is not ready, pause dependent work without repeated prompts, retries,
installation, or signing changes to bypass the wait. Say what is waiting and which earlier changes
already took effect; cancellation does not undo them. Reconcile any in-flight session or owned
resources under the existing recovery/cleanup contract. On return, re-check current target and
service state and the interrupted step's prerequisites before continuing. Preserve unchanged
approval scope; disclose and obtain approval for any newly required effects.

## Appium service and startup

Start a task-owned Appium Server outside `python_exec` with the selected `APPIUM_HOME`,
`DEVELOPER_DIR`, Node, Appium entry point, and driver. Keep its process identity, port, environment,
and log. Wait boundedly, then check `/status`. Reuse an existing server only when its environment
and driver identity match; do not restart or mutate it. If it does not match, use a disclosed
isolated task-owned server only when it will not collide with existing sessions or devices.

Check readiness with a bounded request against the task server's actual loopback URL:

```bash
curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:<port>/status"
```

A successful `/status` proves service reachability, not target readiness, WDA launch, or a session.
For setup-only and status-only requests, stop without creating a session.

### Create a session only for authorized validation or a scenario

Session creation, live queries, actions, verification, recovery, and `driver.quit()` use the
official Appium Python Client through `python_exec`:

```python
from appium import webdriver
from appium.options.ios import XCUITestOptions

options = XCUITestOptions().load_capabilities({
    "platformName": "iOS",
    "appium:automationName": "XCUITest",
    "appium:udid": "<observed device identifier>",
    # Add only the capabilities applicable to the selected WDA route.
})
driver = webdriver.Remote("http://127.0.0.1:4723", options=options)
```

Populate target identifiers and applicable signing/WDA values from observation or the user's
selection. Never invent a UDID, Team, Bundle ID, or WDA URL.

The first launch may build and install WDA and may take minutes. Bound the call and use the
driver-documented launch/connection timeouts rather than an unlimited wait. Do not put session
creation, an expected user action, and cleanup into one unobservable call. When a user prompt is
expected, stop after the creation attempt or at the observed prompt, give one action, and resume
with a separate bounded observation. Do not poll a stable precondition.

After every call, inspect `status` and `kernelState`:

- If the Kernel survived and `driver` exists, make one small relevant live query before
  continuation.
- A nonempty local `session_id` alone proves nothing; a failed live query leaves no verified usable
  session.
- A timeout does not prove that the remote session or WDA does not exist.
- Kernel death loses the Python namespace. Do not describe former objects as resumable or rebuild
  the Kernel implicitly.

For the minimal validation, perform one harmless current-screen or page query. Do not click a
business action, submit a form, or reset app data. If the home screen is needed as a launch target,
disclose that it may change the foreground view and what automation settings apply.

## Diagnose failures without collapsing causes

Read the actual logs before changing signing or rebuilding:

- **Appium Server log:** server start failure, driver load, session creation, WDA build/launch,
  endpoint forwarding, and session termination.
- **WDA/xcodebuild output:** build settings, signing identity, profile/team errors, install errors,
  launch errors.
- **`devicectl`/`xctrace` output:** current visibility, lock, connection, developer-service, and
  disk-image state.

Do not infer a cause from a single exit status:

- A non-zero `xcodebuild` exit status does not itself mean signing failed. Inspect the log for the
  actual build, deployment-target, certificate, profile, team, device, or destination error.
- `codesign --verify` failure proves a local signature problem. Success proves only local
  signature integrity, not device trust or launchability.
- `ECONNREFUSED 127.0.0.1:8100`, a port conflict, a lock, a disconnected phone, or a transport
  timeout is endpoint, process, connection, permission, or forwarding evidence, not a signing
  failure.
- `ApplicationVerificationFailed` or a missing valid provisioning profile points to profile/Bundle/
  device coverage; `No Account for Team` or missing profiles points to account/Team state.
- A device locked, Developer Mode unavailable, or a developer-disk-image/tunnel failure points to
  the device or developer service, not the certificate.

Classify dependency evidence by applicability and use the bounded relevant check instead of a
whole-environment reset. Preserve shared installations and external state.

### Reconcile ambiguous sessions and resources

- If the Appium log or current state shows an existing session that this task may not own, do not
  delete it and do not blindly create a second session. Identify ownership from the Appium service
  logs, task-created identifiers, and current endpoint state.
- If the Kernel died, external state is unknown. Reconcile through the task-owned server log and
  endpoint before deciding whether another attempt is safe.
- If the device, port, or Appium session is genuinely in use by another task, report the shared
  conflict and block. Do not preempt the device or clear all sessions.
- Create another session only after the previous attempt is confirmed ended, relevant resources are
  verified, and any required user safety action is complete.

### Cleanup

- `driver.quit()` closes the Appium session. Success does not prove the WDA process disappeared.
- Do not uninstall WDA, delete a profile, revoke trust, or disable Developer Mode to make the
  environment look "clean". Preserve the user's requested setup result.
- Stop only task-owned Appium Server, tunnel, port forward, and temporary device-service processes.
  Leave shared services and the user's existing mechanism untouched.
- Delete only task-owned disposable JSON, logs, profile scratch and build staging. Do not delete
  the `.app`, `.xctestrun`, product layout or derived-data path that the selected prepared WDA route
  still needs. Retain them in the disclosed user-owned location, report that location/lifetime and
  preserve the user's setup deliverables; keep only non-sensitive facts in the report.
- Do not add a persistent launch agent, background daemon, or auto-start service.
- Report the requested result, live-session cleanup, and server/tunnel cleanup separately. A
  successful result with failed cleanup is not fully cleaned.

## Verification and reporting

Lead with a short user-facing result in the user's language: ready for the requested scope,
waiting for a user action/approval, or blocked by an observed problem. State what was reused or
changed and, if unfinished, the single next user action (or the Agent's next check if none is
needed). Distinguish "prepared, connection not tested" from "connection verified"; a user wait
is not itself a technical failure. Follow with the compact technical evidence below rather than
making the user interpret raw tool output to discover what to do next.

A completed approved step does not clear a different unresolved prerequisite. State separately
what the Agent still needs to diagnose and which remaining installation, signing, or security
changes still need the user's approval before they can happen. An outstanding consent requirement
is not a request to approve an uncertain plan now: clarify conflicting evidence first, then
disclose the exact proposed effects and ask for approval. Do not send the user to solve technical
contradictions or describe the remaining changes as already authorized.

For an approved setup-only request, report:

- the exact components reused, installed, or repaired, with their observed versions and locations;
- the raw XCUITest doctor required fixes and warnings with their target applicability;
- Xcode/SDK and selected driver evidence, plus the current target layers
  (discovered/connected/usable-for-development/ready-for-xcuitest);
- the selected signing route and sanitized match/no-match evidence;
- the selected WDA route and whether it is merely a reuse candidate or actually launch-verified;
- that no session was created and what remains unverified.

For an authorized validation, additionally report the actual Client session creation, the harmless
live query, `driver.quit()` result, and cleanup limits. Never claim a live session from `/status`,
an import, a driver listing, a signature check, or a manual WDA icon. Keep device outcome and
cleanup truth separate.

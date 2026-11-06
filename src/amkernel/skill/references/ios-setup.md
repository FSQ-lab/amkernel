# iPhone setup and readiness through AMKernel

This reference owns physical iPhone discovery, target applicability, signing route selection,
WebDriverAgent reuse and the human-interaction seam. Read `readiness-contract.md`, then this
adapter, before verified `setup-xcuitest` guidance for a physical iPhone target. That official
Skill still owns shared Xcode, Node, Appium, driver, doctor and server checks; verified
`xcuitest-real-device-config` guidance owns current trust, Developer Mode, signing, provisioning
and WDA procedure. This adapter does not restate them as a second tutorial.

An iOS Simulator request uses `ios-simulator.md`. This reference is physical-iPhone guidance only,
and no physical task requires simulator inventory, a simulator runtime or a booted simulator. tvOS
is outside this adapter and has no AMKernel support claim. Android setup remains in
`android-setup.md`; nothing here requires Android SDK discovery.

Setup/readiness/authorization uses `readiness-contract.md`; execution, service and live cleanup use
`amkernel-appium.md`. This adapter adds no server, driver, signing helper, device wrapper, MCP tool
or AMKernel core surface.

## Boundary

Follow the supported-host and official-source verification boundaries in `SKILL.md`. This
reference is AMKernel-owned guidance, not pinned official content. Do not change official source,
archive, manifest, or verifier content to make a route pass.

Setup-only and status-only requests create no session and do not launch WDA. Discovery is
read-only. Installation, Xcode first-launch or license changes, device trust, Developer Mode,
signing, provisioning, device registration, WDA installation, tunnel, developer-service and
service-start effects use the one authorization record in `readiness-contract.md`.

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

## Shared setup contract

Read `readiness-contract.md` before this adapter. Use its one authorization record, physical-iPhone
profile, canonical layer states, official-guidance ownership and cleanup rules. This reference adds
only physical target discovery, Apple security handoffs, signing/provisioning and WDA reuse.

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

## Shared Runtime and official driver seam

Use the actual managed Runtime identified by `python_exec` or verified AMKernel metadata; never
substitute the project `.venv`. Runtime/client applicability and repair authorization use
`readiness-contract.md`. Current Node, Appium, XCUITest, dependency, doctor and server-smoke
procedure belongs to verified `setup-xcuitest`; real-device continuation belongs to verified
`xcuitest-real-device-config`. Do not copy their version ranges or prerequisite checklists here.

Bind official checks to the selected Xcode, physical target, signing/WDA route and task-scoped
environment below. Preserve an existing working backend and `APPIUM_HOME`; changing global/local
mode or home is a disclosed effect, not an automatic repair.

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

## Bind official checks to the selected physical-iPhone environment

After selecting Xcode and physical target evidence, verify and consume `setup-xcuitest`, followed by
`xcuitest-real-device-config` only after shared prerequisites pass. Run their current
Node/Appium/driver discovery, doctor and bounded smoke procedure with the same task-scoped
`DEVELOPER_DIR`, backend mode and `APPIUM_HOME`. Preserve raw required fixes and warnings before
applying this adapter's physical-target applicability rules.

Do not independently require a version, reinstall a listed driver, switch global/local mode or
create a second Appium home. A verified official warning is evidence, not permission to repair.
Only an observed applicable incompatibility or failed required operation can block the layer.

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

## Appium service and authorized connection

Read and apply `amkernel-appium.md` sections **Runtime contract**, **Run the service with the
task environment**, **Connect**, **Bound operations by observable failure states**, and
**Cleanup**. They own Client execution through `python_exec`, server supervision and reuse,
execution-result/liveness checks, interrupted-session recovery, and task-owned cleanup. The
request scope above still governs whether service startup, WDA launch, or session creation is
authorized.

For iPhone, use the selected XCUITest driver with the same `APPIUM_HOME` and `DEVELOPER_DIR`
used for discovery and doctor. Use `XCUITestOptions` with the observed device identifier and only
capabilities applicable to the selected WDA route. Derive Team, Bundle ID, and WDA URL values from
observed evidence or the user's selection, never guesses.

If the selected route requires WDA build/install, disclose those effects before launching it.
That launch can take minutes; use the driver's documented launch/connection timeouts. Keep
expected phone or Mac security prompts separate from creation and cleanup: pause at the observed
prompt, give one action, then resume with a bounded observation. Do not poll a stable precondition.

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

Apply the shared interrupted-session and cleanup rules. If the device, port, or session is in use
by another task, or ownership is unknown, stop and establish ownership from the server log and
task-created identities; do not preempt the device or clear sessions. Retry only after the previous
attempt is confirmed ended, relevant resources are verified, and any required user safety action
is complete.

### Cleanup

- `driver.quit()` closes the Appium session. Success does not prove the WDA process disappeared.
- Do not uninstall WDA, delete a profile, revoke trust, or disable Developer Mode to make the
  environment look "clean". Preserve the user's requested setup result.
- Delete only task-owned disposable JSON, logs, profile scratch and build staging. Do not delete
  the `.app`, `.xctestrun`, product layout or derived-data path that the selected prepared WDA route
  still needs. Retain them in the disclosed user-owned location, report that location/lifetime and
  preserve the user's setup deliverables; keep only non-sensitive facts in the report.
- Do not add a persistent launch agent, background daemon, or auto-start service.

## Verification and reporting

After an authorized change, rerun only affected discovery and verified official checks. Confirm the
selected Xcode, current physical target state, signing route and WDA route from live evidence; do
not trust an installer's success message, a historical pairing or a reusable-candidate label.

Return the canonical `readiness-contract.md` result with `target.platform=ios` and
`target.profile=physical`. Include applicable doctor, target, signing and WDA blockers in their
layers. Setup-only creates no session. Authorized live validation additionally requires an actual
official-client session, a relevant query and truthful cleanup. `/status`, an import, driver list,
signature check or manual WDA icon is not live proof.

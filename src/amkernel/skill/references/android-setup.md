# Android setup and readiness through AMKernel

This reference owns Android dependency provisioning and target-scoped readiness. Read it before
executing the verified `setup-uiautomator2` skill. The official skill still supplies the driver
and server checks; this reference supplies discovery, component selection, approvals, and the
applicability seam that prevents host-wide setup criteria from overriding the requested target.

Android execution still belongs to the official Appium Python Client in `python_exec`. This
reference adds no server, driver, SDK wrapper, MCP tool, or AMKernel core surface.

## Boundary

Follow the supported-host and official-source verification boundaries in `SKILL.md`; this
reference is AMKernel-owned guidance, not pinned official content. The execution and lifecycle
contract is in `amkernel-appium.md`; setup-only and status-only requests create no session.

Discovery is read-only. Installation, license acceptance, persistence, emulator work, ADB
start-up and device authorization use the shared authorization record below.

## Route

1. Establish the requested physical-device, emulator or SDK-only goal.
2. Read `readiness-contract.md`; select exactly one Android profile and discover only its relevant
   layers. Preserve working installations and the actual AMKernel Runtime identity.
3. Use this adapter for Java, SDK, target and ADB applicability; use verified official guidance for
   current Appium/driver prerequisites and procedure.
4. Resolve exact missing effects, authorize them once through the shared record, execute them in
   this task and rerun only affected checks.
5. Return the canonical result. Setup/status stops without a session; live proof remains separate.

## Shared setup contract

Read `readiness-contract.md` before this adapter. Use its one authorization record, canonical
profile/layer states, official-guidance ownership and cleanup rules. This reference adds only
Android target selection, Java/SDK applicability, ADB side effects and doctor-result interpretation.


## Target scope and required layers

| Layer | Physical device | Emulator target |
| --- | --- | --- |
| Runtime Python/client | Required. Actual Runtime, not project `.venv`. | Required. Same. |
| Java/JDK | Required. | Required. |
| Android SDK | Platform tools plus target-relevant platform. | Platform tools plus target-relevant platform. |
| Emulator package | Not applicable. | Required. |
| System image | Not applicable. | Required for selected API/ABI. |
| AVD | Not applicable. | Required. |
| Target state | Connected and authorized. | Launched, boot-complete, responsive. |
| Node/Appium/UiAutomator2 | Required through verified official guidance. | Required through verified official guidance. |

Do not install emulator components for a physical request, and do not treat a configured AVD as a
booted target. Report these layers through the shared Android physical or emulator profile.

## Shared Runtime and official driver seam

Use the actual managed Runtime identified by `python_exec` or verified AMKernel metadata; never
substitute the project `.venv`. Runtime/client applicability and repair authorization use
`readiness-contract.md`. Current Node, Appium, UiAutomator2, dependency, doctor and server-smoke
procedure belongs to the verified `setup-uiautomator2` Skill. Do not copy its version ranges or
checklist here.

Bind official checks to the Java, SDK, target and task-scoped environment selected below. Preserve
an existing working backend and `APPIUM_HOME`; changing global/local mode or home is a disclosed
effect, not an automatic repair.

## Java

### Enumerate every candidate

Missing `JAVA_HOME` or a missing `java` on `PATH` is not proof that Java is absent. Enumerate and
audit every actually considered candidate in this order, retaining its origin:

1. The task-scoped `JAVA_HOME` value.
2. `java` and `javac` found on the task `PATH`; resolve symlinks and aliases while recording the
   original location.
3. macOS registered JDKs from `/usr/libexec/java_home -V`, plus JDK homes under
   `/Library/Java/JavaVirtualMachines` and `$HOME/Library/Java/JavaVirtualMachines`.
4. Known vendor JDK homes and retained task-managed installation paths.
5. Android Studio bundled JBR: `/Applications/Android Studio.app/Contents/jbr/Contents/Home`,
   `$HOME/Applications/Android Studio.app/Contents/jbr/Contents/Home`, `$HOME/android-studio/jbr`,
   `/opt/android-studio/jbr`, `/usr/local/android-studio/jbr` when those installations exist.
6. On Linux, distribution JDK homes under `/usr/lib/jvm`, plus any JDK listed by
   `update-alternatives --list java`.

For each candidate, execute both binaries and record exit status, actual version, and
`java.home`:

```bash
"$candidate/bin/java" -XshowSettings:properties -version 2>&1
"$candidate/bin/javac" -version 2>&1
```

A macOS `/usr/bin/java` stub or an existing directory is not a working JDK. Exclude a known stub
from execution rather than letting it trigger an installer prompt; resolve its real target or
skip it. If a launcher only relays to another install, use the real home reported by the successful
execution. Choose the first candidate that actually runs and satisfies the selected driver,
`sdkmanager`, and build requirements; record why earlier candidates failed or were unsuitable. A
single failing candidate does not justify installation.

Use the selected value inline and consistently:

```bash
export JAVA_HOME="<selected candidate home>"
export PATH="$JAVA_HOME/bin:$PATH"
```

Pass the same values to discovery tools, `sdkmanager`, `appium driver doctor`, and the Appium
Server. Persist them only after the disclosed approval.

### Install only when no candidate works

Prefer an existing installation backend and user-level installation. Disclose the exact source,
version, install path, license, and rollback before proceeding. Valid routes:

- Reuse an existing version manager or user-level package manager when it already manages JDKs.
- An existing Android Studio installation may supply its bundled JBR as a candidate, but do not
  install Android Studio merely to obtain a JDK. Install Android Studio only when the user
  separately requests or approves it as the product goal.
- An official vendor JDK archive, such as the Eclipse Temurin archive served by the Adoptium API.

For an Adoptium archive, resolve the LTS feature that satisfies the observed tool requirements,
then read the exact package link and checksum from the official asset metadata rather than
hard-coding a build:

```bash
curl -fsSL "https://api.adoptium.net/v3/assets/latest/$JDK_FEATURE/hotspot?architecture=$ARCH&image_type=jdk&os=$OS&vendor=eclipse" -o "$TMP/adoptium.json"
# Read .binary.package.link and .binary.package.checksum with an available JSON parser.
curl -fL "<package link>" -o "$TMP/jdk.tar.gz"
# Compare the SHA-256 with the checksum before extraction.
mkdir -p "$HOME/.local/opt/jdk"
tar -xzf "$TMP/jdk.tar.gz" -C "$HOME/.local/opt/jdk"
```

Do not use privilege elevation for a user-level JDK, do not switch the system-wide Java, and do
not modify shell profiles without approval. Verify `java -version`, `javac -version`, and the
selected `JAVA_HOME` after installation. If the vendor archive or metadata endpoint is offline,
keep using an existing working candidate; otherwise report the exact offline blocker rather than
installing from an unverified mirror.

## Android SDK and tools

### Discover before installing

Inspect explicit SDK settings first, then existing installations and conventional user SDK roots:

- Task-scoped `ANDROID_HOME`; treat legacy `ANDROID_SDK_ROOT` as reading evidence, not as a reason
  to set both variables inconsistently.
- Installed Android Studio locations and the SDK paths they use.
- macOS `$HOME/Library/Android/sdk`; Linux `$HOME/Android/Sdk`.
- Any existing SDK root whose binaries actually execute.

A directory is not proof. Execute the selected binaries and record results:

```bash
"$ANDROID_HOME/platform-tools/adb" version
# Only when SDK management is needed and these tools are present:
"$SDKMANAGER" --sdk_root="$ANDROID_HOME" --version
# Only for an emulator route:
"$ANDROID_HOME/emulator/emulator" -version
```

If a valid SDK exists but `ANDROID_HOME` is unset, set the task-scoped value rather than
installing a second SDK:

```bash
export ANDROID_HOME="<observed valid SDK root>"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
```

Add `$ANDROID_HOME/emulator` only when the selected target is an emulator.
When command-line tools are needed, resolve and verify `SDKMANAGER` from the selected existing
revision rather than assuming `latest` exists. Set `SDK_TOOLS_BIN="${SDKMANAGER%/*}"` and add that
directory to the task PATH. For AVD management, verify `AVDMANAGER="$SDK_TOOLS_BIN/avdmanager"`
from the same selected installation before use; do not fall back to a different revision.

### Bootstrap command-line tools only when SDK management is needed

If no usable SDK exists and the task needs SDK packages, choose a user-level SDK root and
disclose it. Prefer a conventional user root such as `$HOME/Library/Android/sdk` on macOS or
`$HOME/Android/Sdk` on Linux; do not write into a system-wide location without approval.

```bash
export ANDROID_HOME="<selected user-level SDK root>"
```

Install the official command-line tools into that root. Resolve the current host archive from
Google's official repository metadata instead of pinning an old build:

1. Download `https://dl.google.com/android/repository/repository2-3.xml`.
2. Resolve a command-line-tools entry to its exact revision and archive before approval.
3. Select the matching `host-os`; honor `host-arch` if declared, without rejecting an
   architecture-neutral archive merely because that field is absent. Record URL and checksum.
4. Download `https://dl.google.com/android/repository/<archive url>` and verify the listed checksum.

```bash
# Use a fresh task-owned staging directory; verify the declared checksum before extraction.
unzip -q "$TMP/commandlinetools.zip" -d "$TMP/cmdline-tools"
# Reuse a verified existing manager rather than overwriting cmdline-tools/latest.
test ! -e "$ANDROID_HOME/cmdline-tools/latest" || exit 1
mkdir -p "$ANDROID_HOME/cmdline-tools"
mv "$TMP/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
SDK_TOOLS_BIN="${SDKMANAGER%/*}"
export PATH="$SDK_TOOLS_BIN:$PATH"
"$SDKMANAGER" --sdk_root="$ANDROID_HOME" --version
```

The installed layout is `<sdk_root>/cmdline-tools/latest/bin/{sdkmanager,avdmanager}`;
`platform-tools/adb` and `emulator/emulator` sit beside it under the same root. Always pass
`--sdk_root="$ANDROID_HOME"` so an SDK package is written to the selected root rather than to the
bootstrap directory.

### Licenses and components

License acceptance is a disclosed change. Identify the agreements required by the selected
components and include them in the approval; do not blanket-accept every license reported by
`sdkmanager --licenses`. During the approved component installation, use an interactive host
process and accept only the agreements covered by that approval. An unexpected agreement pauses
that step for disclosure. SDK license records persist in the selected root; removing a component
does not revoke the agreement.

Inspect the available and installed package identifiers before selecting components:

```bash
"$SDKMANAGER" --sdk_root="$ANDROID_HOME" --list
"$SDKMANAGER" --sdk_root="$ANDROID_HOME" --list_installed
```

Install only components required by the requested target or task:

- `platform-tools`: the base for authorized ADB access.
- Command-line tools: management; already present after bootstrap. Reuse them, or resolve a
  specific available revision when management requires installation or replacement.
- `build-tools;<version>`: when selected tools, driver auxiliary APK analysis/signing/install,
  or an actual build needs them; resolve the version from the relevant requirement.
- `platforms;android-<api>`: only when the selected tool, build, or check needs that platform;
  resolve the API from the project or the tool's output, not from an arbitrary latest value.
- `emulator` and `system-images;android-<api>;<tag>;<abi>`: only for an emulator target, selected
  from `sdkmanager --list` for the host architecture and the requested API.
- Do not install unrelated platforms, build-tools, system images, emulator packages, or
  performance/optional components merely because they appear in a list.

Never pin an API level, build-tools version, command-line tools build, or system image from this
reference. Resolve each exact package identifier from current official metadata and record it.
Package IDs such as `platform-tools` and `emulator` do not pin a revision. Record their resolved
revision before approval and compare repository metadata immediately before installation and
installed revisions afterward. Do not silently substitute an upstream revision that changed;
resolve the difference and disclose any expanded change.

```bash
"$SDKMANAGER" --sdk_root="$ANDROID_HOME" "platform-tools"
# Add only the selected applicable package identifiers to this command.
```

Verify by executing the installed tools and reading `--list_installed`; do not infer success from
the installer's exit status alone.

Offline SDK repository: use `--list_installed` and existing binaries. If a required component is
absent and the official repository is unreachable, report the blocker; do not claim an install or
substitute an unknown archive.

## Bind official checks to the selected Android environment

After selecting Java, SDK and target evidence, verify and consume `setup-uiautomator2`. Run its
current Node/Appium/driver discovery, doctor and bounded server smoke with the same task-scoped
`JAVA_HOME`, Android SDK root, executable paths, backend mode and `APPIUM_HOME`. Preserve its raw
required fixes and warnings before applying this adapter's target applicability rules.

Do not independently require a version, reinstall a listed driver, switch global/local mode or
create a second Appium home. A verified official warning is evidence, not permission to repair.
Only an observed applicable incompatibility or failed required operation can block the layer.

## Service environment

Follow `amkernel-appium.md#run-the-service-with-the-task-environment` for service supervision,
readiness evidence, shared-server reuse, ownership, and cleanup.

Pass the selected `JAVA_HOME`, `ANDROID_HOME`, `APPIUM_HOME`, and task `PATH` from discovery and
doctor. Use the exact observed Node installation and Appium entry point: include their bin
directories on `PATH` or invoke the absolute Appium path, so startup does not select a different
Node/Appium pair. In explicitly requested local mode, run `npx --no-install appium` from the
project root instead of the global executable.

## ADB and target readiness

### Do not turn discovery into a daemon or device action

`adb devices` can start the ADB daemon. Never run it, or a helper such as the official
`check-android-env.mjs` that executes it, as automatic read-only discovery. Use target inventory
only through an already authorized ADB service established in this task or confirmed from the
user's existing setup. If no authorized service exists, request approval before starting one or
before running a command that may start it. `adb version` is binary identity evidence, not a
target inventory and not readiness proof.

Distinguish target states without promoting them:

- **discovered**: listed by an authorized inventory;
- **connected**: authorized state `device`, not `offline` or `unauthorized`;
- **target-prerequisites-verified**: connected, system responsive and sufficiently booted,
  supported Android API, and task-relevant lock/app conditions plus applicable driver checks;
  physical devices also need more than an ADB `device` entry;
- **execution-verified**: a real official-client session and successful relevant live query.
  This layer stays not checked for setup/status-only requests.

Keep device state separate from readiness of the requested setup. A connected, booted phone
can be device-ready while the setup is blocked by missing Java, an incompatible Node version,
SDK tools or Runtime/client prerequisites. Report those setup blockers separately; do not
describe the requested setup as complete merely because its device is usable. Conversely, a
missing host dependency does not turn a connected phone into a disconnected device.
For a target-specific readiness request, the setup also remains blocked while the selected
target is stopped, unbooted or otherwise unusable, even if every host package is installed.
An SDK/JDK-only installation has no device requirement. State which requested prerequisites
remain unmet and which changes need authorization; that includes service/device startup, not
just package installation.

Do not start, unlock, authorize, pair, boot, or create a target as a discovery side effect. Never
accept a host or device permission prompt automatically. An `unauthorized` device needs the user's
action; an `offline` device is not usable. Do not require emulator tools, system images, or AVD
inventory for a physical-device task.

### Physical target

When an authorized physical device is connected, it is a complete target class on its own. Do not
install the emulator package or a system image, and do not create an AVD, merely because the
official host-wide checklist mentions them. Apply the selected driver's required checks to this
device; report an observed lock or permission prompt as the user action that blocks the requested
scenario rather than overriding it.

### Missing emulator target

If the requested target is an emulator and no AVD exists, installing the emulator package, a
system image, and creating an AVD are separate disclosed changes. Do this only for an emulator
target, never for a physical device, and only after approval. Select the system image from
`sdkmanager --list` for the host architecture and the requested API, then create the AVD with the
official `avdmanager` after the image is installed:

```bash
"$SDKMANAGER" --sdk_root="$ANDROID_HOME" "emulator" "system-images;android-<api>;<tag>;<abi>"
"$AVDMANAGER" list device
"$AVDMANAGER" create avd \
  -n "$AVD_NAME" -k "system-images;android-<api>;<tag>;<abi>" --device "$DEVICE_ID"
"$ANDROID_HOME/emulator/emulator" -list-avds
```

The listing after creation proves only that the AVD is configured. Launch and boot verification
follow the same approval and evidence rules below. Do not create an AVD automatically as part of
generic setup, and do not install a system image that the selected target does not use.

### Configured but stopped emulator

`emulator -list-avds` lists configured AVD names only. It proves neither a running emulator nor a
booted, usable target. Do not claim readiness from that listing.

If the requested target is that emulator, disclose the selected AVD, the launch command, the
resources it will use, and—if no authorized ADB service exists—the ADB start-up it implies. Obtain
approval before launching. Start it outside `python_exec` with task-owned logs, wait for its
authorized ADB serial to reach `device`, and verify boot completion through the existing
authorized ADB service:

```bash
"$ANDROID_HOME/emulator/emulator" -avd "<selected AVD>" -no-snapshot-save
"$ANDROID_HOME/platform-tools/adb" -s "<emulator serial>" shell getprop sys.boot_completed
```

Proceed only when the boot property reports completion and the applicable driver checks pass. If
launch was not requested or approved, report the AVD as configured but not launched or usable.
Creating an AVD or installing a system image is a separate disclosed change and is only in scope
for an emulator target; never do it automatically. Do not stop or restart an emulator this task
did not create.

## Raw doctor output and target applicability

Run the selected official doctor command with the same task environment and preserve its complete
stdout/stderr, exit status, and the exact command:

```bash
APPIUM_HOME="${APPIUM_HOME:-$HOME/.appium}" \
JAVA_HOME="$JAVA_HOME" \
ANDROID_HOME="$ANDROID_HOME" \
PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH" \
appium driver doctor uiautomator2
# local mode: npx --no-install appium driver doctor uiautomator2
```

Do not feed the official helper or doctor a filtered environment, and do not edit profiles to make
a check look satisfied. If the task-scoped environment is correct, rerun in that environment; that
is not filtering the raw result.

Classify every reported required fix and warning by applicability:

- **applicable-blocking**: the requested target needs this layer now; resolve it and rerun.
- **not-applicable-to-this-target**: the check describes a component this target does not need,
  such as emulator/system-image/AVD readiness for a physical-device task, or a platform/build-tool
  component not required by the selected tool or build.
- **optional-unrequested**: an explicitly optional capability, such as an unrequested media or
  bundletool feature.

Report the raw required-fix findings and the classification together, without presenting a
filtered subset as the raw doctor result. For example: "Raw doctor output reports three required
fixes. Two apply to this physical target and are now resolved; one concerns emulator tooling and
is not applicable because the requested target is a physical device. Raw doctor itself is not
reported as passed." Never change the official pinned source or manifest to suppress output.

The official helper scripts may also require a writable Appium home or may execute `adb`; run them
only under the same ADB and approval rules, and treat sandbox/Appium-home access failures as raw
evidence, not as proof that a package or target is absent. Apply the same applicability
classification to their summaries.

## Verification and reporting

After an authorized change, rerun only affected discovery and the verified official checks. Confirm
the selected Java home, SDK root, target state and official required checks from live evidence; do
not trust an installer's success message.

Return the canonical `readiness-contract.md` result with `target.platform=android` and exactly one
physical or emulator profile. Include raw applicable doctor blockers as layer blockers. Setup-only
creates no session. Live control requires a real official-client session and query under
`amkernel-appium.md`; `/status`, imports, driver lists and configured AVDs are not live proof.

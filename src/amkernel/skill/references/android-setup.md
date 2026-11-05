# Android setup and readiness through AMKernel

This reference owns Android dependency provisioning and target-scoped readiness. Read it before
executing the verified `setup-uiautomator2` skill. The official skill still supplies the driver
and server checks; this reference supplies discovery, component selection, approvals, and the
applicability seam that prevents host-wide setup criteria from overriding the requested target.

Android execution still belongs to the official Appium Python Client in `python_exec`. This
reference adds no server, driver, SDK wrapper, MCP tool, or AMKernel core surface.

## Boundary

- Use this route on the currently qualified AMKernel hosts: Ubuntu and macOS with CPython
  3.11–3.13. Windows is not a supported AMKernel host. Official Android guidance may include
  Windows commands, but that is not AMKernel Windows qualification; do not present a Windows
  Runtime as supported or claim Windows Android readiness.
- Keep the pinned official source, manifest, archive, and verifier unchanged. Verify official
  skills when a route is about to consume them; do not treat this reference as official content.
- A setup-only or status-only request stops at readiness and creates no Appium session. A live
  session, live query, action, or `driver.quit()` only occurs for an explicitly requested scenario
  and only through the official client in `python_exec`.
- Discovery is read-only. Installation, license acceptance, persistence, emulator work, ADB
  start-up, and device authorization require the scoped approval described below.

## Route

1. Establish the requested Android target and goal from the conversation and safe evidence:
   physical device, emulator/AVD, or an application/build task that only needs SDK tooling.
2. Identify the host; for Appium work, identify the actual AMKernel Runtime as well. Do not
   substitute system Python, the project `.venv`, or another interpreter for that Runtime.
3. Discover only relevant layers read-only. An Appium scenario needs Runtime client, Java,
   Android tools, Node/npm/Appium/driver; an SDK/JDK-only install needs only its own prerequisites.
   Preserve working installations; SDK-only requests never require Appium or an Agent Runtime.
4. Resolve exact candidates from observed metadata. Classify what is genuinely missing for this
   target; do not infer absence from one unset variable or one failed candidate.
5. If changes are needed, present one disclosure and obtain one scoped approval. After approval,
   perform the installation in this task and verify it. Do not hand the setup back to the user.
6. For an Appium target, verify the selected official driver/server checks and classify their raw
   output by applicability. For SDK/JDK-only work, verify the installed tools and stop there.
7. Report target-scoped readiness and any remaining live-session proof separately. Stop without a
   session when the request was setup-only or status-only.

## One disclosure, one approval

Before any mutation, present one concise disclosure covering every planned change. Use these
fields so the approval is exact and scoped:

- **Component and exact target**: distribution/package name and the exact version or SDK package
  identifier resolved from current metadata; never "latest" or an unverified guess.
- **Source and backend**: uv tool with its package source and extras; npm registry package spec;
  Google SDK repository package ID and archive checksum; official vendor JDK archive URL and
  checksum; existing version manager if used.
- **Install path and environment**: uv tool environment; npm prefix and `APPIUM_HOME`; Android SDK
  root and component paths; JDK directory; whether the environment value is task-scoped or
  persistent.
- **Impact**: which other projects, global sessions, Appium homes, SDK roots, or running services
  are affected; whether the current Kernel/MCP connection must be reloaded; whether existing
  compatible versions are preserved.
- **Rollback**: the exact previous version/spec/install path recorded before the change and the
  command that restores or removes only this task's addition; state what cannot be rolled back,
  such as an accepted Android SDK license.
- **Licenses**: the license or agreement to be accepted, at which step, and that acceptance is a
  separate disclosed effect of the install.
- **Elevation**: whether any privileged step is required; prefer a user-level route and obtain a
  separate approval if elevation is genuinely unavoidable.
- **Persistence**: exactly which environment variable or profile change would persist beyond this
  task and its removal line; prefer task-scoped values.

One approval covers the disclosed batch. Apply only those changes and verify them in this task;
do not hand the commands to the user. A newly discovered change, a different version, additional
SDK components, a persistent environment edit, or a privileged action requires a new disclosure
and approval.

## Target scope and required layers

| Layer | Physical device | Emulator target |
| --- | --- | --- |
| AMKernel Runtime client (`appium`, `selenium`) | required | required |
| Working JDK | required | required |
| `platform-tools` / authorized ADB service | required | required |
| `cmdline-tools` / `sdkmanager` | only for SDK management or install | only for SDK management or install |
| SDK platform | only if the selected tool, build, or driver check requires it | only if the selected tool, build, or driver check requires it |
| `build-tools` | when selected tools, driver APK handling/signing, or builds need them | when selected tools, driver APK handling/signing, or builds need them |
| `emulator` package, system image, AVD | not required | required |
| Device authorization / unlock | user action when observed | observe locks/prompts; never auto-dismiss or unlock |
| Appium session | only for an explicitly requested scenario | only for an explicitly requested scenario |

A physical target must not be gated on emulator inventory, a system image, or an AVD. Do not
install an emulator component just to satisfy a generic Android checklist. An emulator target
must not be treated as usable merely because an AVD is configured.

## Runtime Python and client

### Identify the actual Runtime

Prefer `python_exec` evidence:

```python
import sys
print(sys.executable, sys.version)
```

If the Runtime is reachable only from the host, identify the uv-managed installation and preserve
its environment:

```text
uv tool list --show-with --show-paths --show-python
uv tool list --show-version-specifiers --show-with --show-paths --show-python
uv tool dir
uv tool dir --bin
```

Use the listed `amkernel` tool environment, its interpreter, and its extra requirements. Do not
use `python3` from `PATH`, the project `.venv`, or another project's environment.

### Verify the dependency layer

In the actual Runtime:

```python
import importlib.metadata as md
import sys

print(sys.executable, sys.version)
for name in ("amkernel", "Appium-Python-Client", "selenium"):
    print(name, md.version(name))
print(md.metadata("Appium-Python-Client")["Requires-Python"])
print(md.requires("Appium-Python-Client"))
print(md.metadata("selenium")["Requires-Python"])
print(md.requires("selenium"))
```

Also exercise the actual imports and, when a driver route is selected, inspect the selected
driver's declared ranges as support evidence. Evaluate `Requires-Python` and each
environment-marker-qualified requirement only when its marker applies in this Runtime. Use the
classification labels defined in `SKILL.md`; do not upgrade or downgrade merely to silence a
warning. A successful import proves dependency presence, not full compatibility.

### Repair

Repair only if the actual Runtime lacks a required client or violates an applicable requirement.
Record the current install spec and extras first:

```text
uv tool list --show-version-specifiers --show-with --show-paths --show-python
```

Then re-create the tool environment with the same package source spec and all previously recorded
extras, adding the applicable client constraint. `uv tool install` of an already-present tool
version may otherwise leave the existing environment in place; when repair must actually recreate
it, add the documented `--force` flag. Preserve the installed AMKernel version rather than
upgrading it as a side effect; for a package-index install:

```text
uv tool install "amkernel==$AMKERNEL_VERSION" --force --with 'Appium-Python-Client<resolved applicable constraint>'
```

If the observed Runtime was installed from a local path or another non-index source, reuse that
same source spec and flag set instead of replacing it with the package-index name, adding
`--force` only to recreate the existing environment. `--force` does not authorize a version
change: keep the recorded AMKernel version/source spec. If the requested client constraint
conflicts with the Runtime package's own requirements, report the conflict rather than forcing an
incompatible environment. Do not mutate the tool environment with `pip`; the uv tool environment
is managed by `uv`. If the actual interpreter is outside AMKernel's supported CPython range,
disclose and select a supported interpreter through the same uv tool installation rather than
changing system Python. Replacing a shared Runtime affects every activated project; disclose
that scope and reconcile/reconnect affected Kernels before using the replacement.

Never install the client into the project `.venv`.

Offline index: verify the existing Runtime instead of installing. If a required distribution is
absent, report the offline index/blocker and stop that dependency repair; do not invent a version
or fall back to an unrelated interpreter.

## Java

### Enumerate every candidate

Missing `JAVA_HOME` or a missing `java` on `PATH` is not proof that Java is absent. Enumerate and
audit every actually considered candidate in this order, retaining its origin:

1. The task-scoped `JAVA_HOME` value.
2. `java` and `javac` found on the task `PATH`; resolve symlinks and aliases while recording the
   original location.
3. macOS registered JDKs from `/usr/libexec/java_home -V`, plus JDK homes under
   `/Library/Java/JavaVirtualMachines` and `$HOME/Library/Java/JavaVirtualMachines`.
4. Android Studio bundled JBR: `/Applications/Android Studio.app/Contents/jbr/Contents/Home`,
   `$HOME/Applications/Android Studio.app/Contents/jbr/Contents/Home`, `$HOME/android-studio/jbr`,
   `/opt/android-studio/jbr`, `/usr/local/android-studio/jbr` when those installations exist.
5. On Linux, distribution JDK homes under `/usr/lib/jvm`, plus any JDK listed by
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

## Node, npm, Appium, and the selected driver

### Discover the existing installation

```bash
node -v
node -p "process.execPath"
npm -v
npm config get registry
npm config get prefix
npm root -g
command -v fnm
command -v asdf
command -v volta
```

If `node` is absent from `PATH`, inspect existing version managers and their installed versions
before concluding Node is absent. Reuse an existing manager (`nvm`, `fnm`, `asdf`, `volta`, or the
platform's maintained equivalent) rather than adding a second one. Use that manager's documented
install/use command for an LTS release that satisfies the selected package engines, for example
`fnm install <version> && fnm use <version>` or `nvm install <version> && nvm use <version>`.

If no version manager exists and Node must be installed, use the official Node.js distribution
archive. Resolve the exact LTS release from `https://nodejs.org/dist/index.json` that satisfies the
selected engines, verify it against `SHASUMS256.txt`, and install it into a user-owned directory:

```bash
curl -fsSLO "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-$NODE_PLATFORM.tar.xz"
curl -fsSLO "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt"
grep " node-v$NODE_VERSION-$NODE_PLATFORM.tar.xz\$" "SHASUMS256.txt" | shasum -a 256 -c -
mkdir -p "$HOME/.local/lib"
tar -xJf "node-v$NODE_VERSION-$NODE_PLATFORM.tar.xz" -C "$HOME/.local/lib"
export PATH="$HOME/.local/lib/node-v$NODE_VERSION-$NODE_PLATFORM/bin:$PATH"
node -v
npm -v
```

Do not use `sudo` or a system-wide prefix for a user-level route. Record the exact Node/npm
versions and the resolved archive checksum. Inspect the active npm prefix and keep global installs
user-owned; do not use a system-wide prefix without approval.

### Evaluate exact engine and peer constraints

Do not reduce compatibility to a major-version floor. Read the installed packages' actual
metadata and compare the exact ranges with a semver-aware check available on the host. If no such
check exists, report the raw ranges as `unverified` instead of assuming compatibility.

```bash
appium -v                                    # or: npx --no-install appium -v
appium driver list --installed --json
```

For the selected driver, `driver list --installed --json` reports its version, `installPath`, and
`appiumVersion` peer range. Read the driver package's `engines` and `peerDependencies`:

```bash
node -e 'const p=require(process.argv[1]); console.log(JSON.stringify({version:p.version,engines:p.engines,peerDependencies:p.peerDependencies},null,2))' "$DRIVER_INSTALL_PATH/package.json"
```

Read the active Appium package metadata the same way from `$(npm root -g)/appium/package.json`
(global mode) or the project's installed Appium package (local mode). Verify:

- the active `node` and `npm` versions satisfy the selected Appium and driver `engines`;
- the selected driver's `peerDependencies.appium` range includes the active Appium version, or
  `appiumVersion` from `driver list` does;
- the selected Appium Python Client's requirements remain applicable in the Runtime;
- the constraints have a non-empty intersection. A warning, one failed resolution, or a missing
  package is not proof that no compatible combination exists.

When a version must be chosen from the registry, query exact candidates rather than selecting
latest for each package independently:

```bash
npm view "appium@$APPIUM_VERSION" engines peerDependencies --json
npm view "appium-uiautomator2-driver@$DRIVER_VERSION" engines peerDependencies --json
```

Choose an exact compatible pair that also satisfies the host. Preserve an existing compatible
pair; do not upgrade merely to match a newer release. Record the resolved versions and their
sources.

Offline registry: `npm ping` or `npm view` failure is an offline/blocker observation. Use the
installed package metadata and existing driver list; do not upgrade or install a guessed version.
If a required package is missing, report the exact blocker and stop that install path.

### Install Appium and the driver after approval

Default to the existing global mode unless the user explicitly requested local `npx` mode. Keep
the mode consistent across install, doctor, server, and smoke checks. Export the selected
`APPIUM_HOME` (default `$HOME/.appium`) for extension commands so they address the same extension
tree the server will load:

```bash
export APPIUM_HOME="${APPIUM_HOME:-$HOME/.appium}"
```

Global mode, only for missing or genuinely incompatible pieces:

```bash
npm install -g "appium@$APPIUM_VERSION"
appium -v
appium driver install "uiautomator2@$DRIVER_VERSION"
appium driver list --installed --json
```

Do not install the driver with bare latest when its peer range does not include the active
Appium. If installing over an existing driver, uninstall it first only after preserving the
previous exact version and obtaining approval; reinstall the exact compatible version.

Local mode, only when explicitly requested and only when dependency-file changes are authorized:
use the project's existing package manager and lockfile to install exact `appium` and
`appium-uiautomator2-driver` versions, then invoke `npx --no-install appium`. Never run `npm -g`
in local mode and never use the global `appium driver install` flow to satisfy a local request.
Do not mix global and local extensions in one route.

Use one `APPIUM_HOME` consistently. The default is `$HOME/.appium`; an explicit value must be the
same for extension installation, doctor, and the server. Do not install into one Appium home and
expect an already-running server with another home to load it.

Record the previous exact versions and install paths before changing anything. Roll back only
this task's changes, for example:

```bash
# Only when this task added them:
appium driver uninstall uiautomator2
npm uninstall -g appium

# Only when this task replaced a pre-existing version:
appium driver uninstall uiautomator2
npm install -g "appium@$PREVIOUS_APPIUM_VERSION"
appium driver install "uiautomator2@$PREVIOUS_DRIVER_VERSION"
```

Never remove a pre-existing shared package, and never restart a shared service. A removed
extension or package does not undo accepted SDK licenses or other external state.

## Service environment

Start a task-owned Appium Server outside `python_exec`, non-blocking, with the same environment
used for discovery and doctor:

```bash
JAVA_HOME="$JAVA_HOME" \
ANDROID_HOME="$ANDROID_HOME" \
APPIUM_HOME="${APPIUM_HOME:-$HOME/.appium}" \
PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH" \
appium --address 127.0.0.1 --port "$PORT" --log "$TASK_LOG"
```

In explicitly requested local mode, run `npx --no-install appium` from the project root instead
of the global executable. Use a reviewed loopback URL without credentials. Use the exact observed
Node installation and `appium` entry point: include their bin directories on `PATH` or invoke the
absolute `appium` path, so the server does not resolve a different Node/Appium pair than the one
installed and checked.

Retain the PID, port, log path, and environment identity. Wait boundedly for the service, then
check the status endpoint and the selected driver evidence:

```bash
curl -fsS "http://127.0.0.1:$PORT/status"
```

A successful `/status` or a server log entry proves service readiness only; it does not prove
that a target is usable or that an Appium session exists. If a server already exists, use it only when its environment and driver identity match;
do not restart or mutate a shared server. If it does not match, do not install into its
`APPIUM_HOME` or restart it to fit this task: use an isolated task-owned server only when that will
not collide with its sessions/devices, otherwise report the shared-service conflict. Stop only the
task-owned server, and remember that stopping the server does not clean a remote session or target
state.

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

After an approved installation, verify the exact result rather than the installer's message:

- Runtime: the uv tool environment, exact interpreter, and actual imports/versions.
- Java: selected `java.home`, `java -version`, `javac -version`, and origin.
- SDK: selected root, component identifiers/revisions, and applicable tool execution; use
  `sdkmanager --list_installed` when the selected management tools are available.
- Node/Appium: `node -v`, `npm -v`, active executables, exact Appium version, installed driver
  version, and the observed engine/peer relation.
- Service: task-owned identity, same environment, `/status`, and selected driver evidence.

For setup-only, report: the raw doctor required-fix findings and their target applicability; the
readiness layers established; the target's actual state (physical connected/authorized, or
emulator configured/launched/booted); and that no session was created. Do not describe a ready status,
driver listing, configured AVD, or successful import as a live-session or full-compatibility
proof. When live execution is requested, it must be a real official-client session with a live
query under the scenario rules in `amkernel-appium.md`.

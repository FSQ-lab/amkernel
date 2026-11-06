# iOS Simulator setup and readiness through AMKernel

Use this adapter only for an iOS Simulator target on a supported macOS AMKernel host. Read
`readiness-contract.md` first, then consume verified `setup-xcuitest` guidance for current
XCUITest prerequisites, doctor and server-smoke procedure. Do not apply physical-iPhone trust,
Developer Mode, signing or provisioning guidance to a Simulator.

## Select the target profile

Establish whether the user requested a named Simulator, any usable iOS Simulator, or only prepared
XCUITest tooling. Keep these scopes distinct:

- **discovery:** identify selected Xcode, installed Simulator runtimes and available devices;
- **prepared:** establish required iOS Simulator profile layers without creating a session;
- **live:** create an authorized XCUITest session, perform one relevant live query and clean up.

Use the selected Xcode's tools with a task-scoped `DEVELOPER_DIR` when needed. Do not switch global
`xcode-select` merely because another Xcode is installed. Observe Simulator inventory from the
selected toolchain's current structured output; do not infer availability from an application icon,
directory name or stale remembered device id.

If exactly one usable target satisfies the request, continue with it. If several materially
different targets match, ask the user to choose using familiar device and OS names. Never ask them
to choose a driver, capability or raw UDID.

## Distinguish the Simulator layers

Report these through the shared profile without renaming them:

- `xcode`: selected developer directory and usable current command-line tools;
- `simulator-runtime`: the requested iOS runtime is installed and available;
- `simulator-target`: a matching configured device exists and is available;
- `boot`: optional during prepared setup, required only when the requested validation needs a
  booted target;
- `runtime-client`, `appium-server`, and `driver`: shared/official layers.

An installed runtime does not prove a configured device. A configured device does not prove it is
booted. A booted device does not prove XCUITest session creation or application control. Preserve
those states independently.

For this profile, physical device connection, pairing, trust, Developer Mode, signing identity,
provisioning profile and physical WDA deployment are `not-applicable`. Do not diagnose or repair
them to make a Simulator ready.

## Mutations and authorization

Missing runtime installation, Simulator device creation, boot, erase/reset, application install and
persistent Xcode selection are distinct effects. Resolve the exact required effects, record them in
the shared authorization object and ask once. Do not request approval again after handing off to
the official Skill unless the resolved effect set changes.

Prefer an existing matching runtime and device. Never erase or recreate a Simulator as a generic
repair. Erase is destructive and requires a separately disclosed effect even when another setup
effect was already authorized.

## Verification and ownership

After authorized changes, rerun only affected discovery and the verified official checks. Prepared
completion requires every required shared profile layer to be `ready`; it creates no Appium session.
A live validation additionally requires an actual XCUITest session against the selected Simulator,
a relevant bounded query and `driver.quit()` evidence.

Do not shut down, erase or delete a pre-existing Simulator. If this task booted a Simulator only as
an incidental validation step, restore its prior shutdown state after session cleanup unless the
user requested it remain running. Preserve user-requested application state; uninstall only a
task-owned disposable application whose removal was part of the authorized plan.

Return the canonical `readiness-contract.md` result with `target.platform=ios` and
`target.profile=simulator`. Synthetic or minimal validation does not qualify arbitrary iOS apps or
real Apple platforms.

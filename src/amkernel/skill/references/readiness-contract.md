# Readiness and authorization contract

This reference is the shared interface for every AMKernel Appium setup, readiness, repair and
unsupported-platform route. Platform references are adapters: they select applicable layers and
supply platform evidence. They must not invent another result shape, approval vocabulary or copy of
official Appium prerequisites.

This is an Agent reporting contract, not an AMKernel Runtime API and not a security mechanism.
`python_exec` remains the only execution seam. A plain-language result may precede the object for a
nontechnical user.

## Canonical result

For setup, readiness, repair or unsupported-platform requests, return one `readiness` object:

```json
{
  "scope": "observed-host",
  "platformEvidence": "observed-host",
  "platformSupport": "supported",
  "taskOutcome": "completed",
  "target": {
    "platform": "ios",
    "profile": "simulator",
    "identity": "observed simulator name or id"
  },
  "readiness": {
    "scope": "prepared",
    "status": "ready",
    "layers": [
      {
        "id": "target",
        "applicability": "required",
        "state": "ready",
        "evidence": ["bounded observed fact"],
        "blockers": []
      }
    ]
  },
  "authorization": {
    "status": "not-required",
    "effects": []
  },
  "liveControl": "not-requested",
  "cleanup": {
    "ownedSession": "not-required",
    "restoration": "not-required",
    "server": "not-required"
  }
}
```

Use only these control values:

- `scope` and `platformEvidence`: `observed-host`, `synthetic-fixture`, or `none`;
- `readiness.scope`: `discovery`, `prepared`, or `live`;
- `platformSupport`: `supported` or `unsupported`;
- `taskOutcome`: `completed`, `failed`, `blocked`, or `approval-required`;
- `readiness.status`: `ready`, `blocked`, `approval-required`, or `unknown`;
- layer `applicability`: `required`, `optional`, `not-applicable`, or `unknown`;
- layer `state`: `ready`, `missing`, `incompatible`, `blocked`, `unknown`, or `not-checked`;
- `authorization.status`: `not-required`, `pending`, `granted`, or `declined`;
- `liveControl`: `not-requested`, `not-attempted`, `passed`, `failed`, or `unknown`;
- cleanup values: `completed`, `failed`, `unknown`, `not-required`, plus `preserved` for a
  pre-existing server.

`evidence` contains bounded sanitized observations, never conclusions disguised as facts.
`blockers` contains concrete unresolved facts. Put prose and identifiers in evidence, blockers or a
separate `details` field; never append prose to a control value.

A result is `ready` only when every required layer is `ready`. One missing, incompatible, blocked,
unknown or unchecked required layer prevents `ready`. `prepared` excludes session creation and live
target control. `live` requires an actual official-client session, a relevant live query and
truthful cleanup evidence. Installation, `/status`, a driver list, target inventory or historical
success alone is not live proof.

## Profile adapters

Select exactly one profile before checking layers. Do not execute another profile's checks merely
because its tools are installed.

| Profile | Required layer ids | Applicability rules |
| --- | --- | --- |
| Android physical | `runtime-client`, `java`, `android-sdk`, `appium-server`, `driver`, `target` | Emulator package, image and AVD are `not-applicable`. |
| Android emulator | Android physical layers plus `emulator-package`, `system-image`, `avd`, `boot` | A configured AVD is not a booted target. |
| iOS Simulator | `runtime-client`, `xcode`, `simulator-runtime`, `simulator-target`, `appium-server`, `driver` | Device trust, Developer Mode, physical signing and physical WDA provisioning are `not-applicable`. |
| Physical iPhone | `runtime-client`, `xcode`, `target`, `appium-server`, `driver`, `signing`, `wda` | Simulator inventory and boot are `not-applicable`. |
| Native macOS | `runtime-client`, `xcode`, `target-app`, `appium-server`, `driver` | Privacy is a separate required live layer only for the requested operation. |
| Windows host or target | none | `platformSupport=unsupported`, `readiness.status=blocked`; perform no setup mutation or session attempt. |

A platform adapter may add a layer only when the requested profile needs it. It may not rename the
shared fields or states. Preserve physical, simulator/emulator and native-desktop evidence
separately.

## One authorization record

Read-only discovery is automatic. The user's explicit requested end state authorizes the visible
actions clearly necessary to produce it. Technical mutations still require one bounded disclosure
and authorization record before the first change:

```json
{
  "status": "pending",
  "effects": [
    {
      "kind": "install",
      "target": "exact component",
      "source": "observed source",
      "version": "resolved version",
      "location": "resolved path",
      "persistence": "persistent",
      "privilege": "user",
      "consequences": ["license, trust, privacy or security effect, or none"],
      "rollback": "exact rollback"
    }
  ]
}
```
Every effect carries every field. Use the literal `not-applicable` for an inapplicable scalar and
an empty `consequences` list rather than omitting a field.


The record travels unchanged across first-party and official Skill handoffs. Do not ask again when
the resolved effect set is identical and the user already granted it in this task. Ask again only
when discovery changes the effect kind, component, source, version, location, persistence,
privilege, consequences or rollback. An unanswered request remains `pending`. An explicit rejection
sets `authorization.status=declined` and blocks those effects until the user reopens them or the
resolved effect set changes; do not ask again automatically or reinterpret a broad setup request as
approval.

Authorization is behavioral guidance, not enforcement. Never describe it as a sandbox, privilege
boundary or protection against unrestricted same-user execution.

## Guidance ownership

AMKernel first-party guidance owns target/profile selection, layer applicability, Runtime identity,
authorization continuity, resource ownership, result normalization and cleanup truth.

Verified official Appium Skills own current Node/Appium/driver prerequisites, versions, doctor
commands, helper behavior, capabilities and driver-specific setup procedure. Platform adapters add
only facts the official guidance cannot know: the user's requested target, selected local
installation, applicability and ownership. Do not copy version-sensitive official checklists into
first-party references.

Verify the routed official guidance once, immediately before consuming it:

```text
python .agents/skills/amkernel/scripts/verify_official_skills.py --project-root . --json
```

`{"status":"verified","errors":[]}` is the whole success interface. The manifest, file hashes,
receipt and source layout are implementation details. On `failed`, stop the official route and
report the exact returned errors; repair only through the AMKernel installer after authorization.
Do not fetch an unpinned replacement or rerun verification for an already-ready scenario that
consumes no official setup guidance.

## Finish and cleanup

Report the requested result first. For a blocker, give one next user action only when identity,
physical confirmation, privacy, trust or another user-native step truly requires it. Keep commands,
paths and diagnosis Agent-owned.

Stop or delete only resources this task created and can identify. Preserve compatible pre-existing
servers, targets and sessions. Kernel loss does not clean external resources. Claim session cleanup
only after `driver.quit()` succeeds; otherwise retain identity and report `failed` or `unknown`.

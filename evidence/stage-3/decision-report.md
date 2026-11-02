# Stage 3 Mobile/Appium Graduation Decision

## Decision

Advance to Stage 4 cross-client validation.

The retained Android and iOS reference runs and the complete lifecycle failure matrix satisfy every Stage 3 graduation criterion. Keep the result experimental and unsupported: this evidence does not establish a supported mobile automation surface.

No AMKernel core change is recommended. No mobile-specific AMKernel interface is recommended. Appium Server and device lifecycle supervision remain external to AMKernel.

## Evidence index

[`index.json`](index.json) is the portable, machine-checkable decision record. It pins:

- Android and iOS evidence paths, sizes, and SHA-256 digests;
- the complete lifecycle aggregate path, size, and SHA-256 digest;
- the AMKernel revision and wheel identity;
- the scenario, measurement protocol, official Appium skill, and fixture identities;
- all ten graduation criteria with exact evidence and review links;
- all twelve measurements with complete Android and iOS values, run outcomes, and cleanup outcomes;
- all nineteen failure rows with the exact 33 Both/Shared occurrences, state, cleanup, and transcript hashes;
- the six canonical independent-review dispositions and their source records.

The index validates against [`tests/fixtures/mobile_appium/graduation-index.schema.json`](../../tests/fixtures/mobile_appium/graduation-index.schema.json). Its generator also revalidates both reference records and the lifecycle aggregate against [`evidence.schema.json`](../../tests/fixtures/mobile_appium/evidence.schema.json), reruns lifecycle semantic and artifact-hash checks, reconstructs the index from those sources, and rejects schema-valid records that differ from them.

## Independent review

The [canonical final disposition](https://github.com/FSQ-lab/amkernel/issues/69#issuecomment-6518659573) records 0 Blocker, 0 Major, and 0 Minor findings. The review's initial completeness and platform-reference-linkage findings were fixed before this decision: the index now maps every required row and rejects a lifecycle aggregate tied to different platform evidence.

## Graduation criteria

| Criterion | Result | Retained proof |
| --- | --- | --- |
| Retain the third-party Appium Python driver in one persistent kernel | Pass | Both reference runs execute the frozen scenario through one AMKernel session. |
| Control one Android emulator and one iOS simulator | Pass | [`references/android-evidence.json`](references/android-evidence.json) and [`references/ios-evidence.json`](references/ios-evidence.json). |
| Inspect state and perform representative interaction | Pass | Both reference runs complete the frozen inspect, navigate, type, and verify sequence. |
| Deliver screenshots without conversational bulk transfer | Pass | Screenshot artifacts are retained and hash-linked by both reference runs. |
| Reduce page source locally | Pass | Minimum observed reductions: Android 92.88%; iOS 97.66%, against the 80% floor. |
| Continue after ordinary automation errors | Pass | Both references verify continuation; the lifecycle matrix distinguishes recoverable failures. |
| Distinguish kernel-preserving from kernel-losing failures | Pass | [`lifecycle.json`](lifecycle.json) covers every frozen lifecycle case with explicit kernel, session, device, and server state. |
| Execute project-local automation code | Pass | Both reference runs execute the frozen project scenario and measurement protocol. |
| Retain bounded diagnostic artifacts | Pass | All 33 lifecycle occurrences hash-link bounded transcripts. |
| Clean managed resources without overclaiming external cleanup | Pass | Both references and all lifecycle occurrences record completed cleanup with no remaining external resources. |

## Measured results

All protocol ceilings passed.

| Measure | Android | iOS |
| --- | ---: | ---: |
| Kernel startup, median | 379.40 ms | 369.65 ms |
| Appium session startup, median | 2,046.78 ms | 1,377.30 ms |
| Per-cell derived overhead, median | 0.00 ms | 0.00 ms |
| Output delivery latency, median | 5.89 ms | 7.80 ms |
| Timeout-to-interrupt, median | 14.89 ms | 13.33 ms |
| Largest page source | 13,605 bytes | 38,377 bytes |
| Largest decoded screenshot | 70,689 bytes | 257,981 bytes |
| Minimum local page-source reduction | 92.88% | 97.66% |

Lifecycle evidence contains 33 platform-tagged occurrences: 14 frozen `Both` cases on Android and iOS plus 5 frozen `Shared` cases on Android. Every occurrence records observed cleanup; none retains an external resource.

## Rationale

The successful verticals required no production `src/amkernel/` changes. Existing Stage 2 output, artifact, timeout, interrupt, reset, and kernel-lifecycle semantics were sufficient. Mobile-specific supervision in core would broaden the interface without evidence of repeated cross-vertical need.

Stage 4 should therefore test the same kernel and output contracts across another client or vertical rather than hardening Appium-specific behavior into AMKernel.

## Scope limits

- One reference Coding Agent host.
- One local Android emulator and one local iOS simulator.
- Pinned fixture applications and one pinned official Appium skill revision.
- Local simulator/emulator behavior only; no physical-device or remote-grid claim.
- Appium Server and device lifecycle remain externally supervised.
- Experimental evidence only; no support commitment.

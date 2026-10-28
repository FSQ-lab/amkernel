# Architecture Decision Records

This directory contains durable decisions that affect AMKernel across modules, public contracts, lifecycle behavior, security boundaries, supported platforms, or project-wide tooling.

Product invariants remain in [`../architecture.md`](../architecture.md). ADRs refine implementation choices and may not silently override the architecture. A decision that changes an architectural invariant must update the architecture in the same accepted change.

## Status values

- `Proposed`: under review; implementation may not depend on it.
- `Accepted`: approved and binding for new work.
- `Rejected`: considered and deliberately not selected.
- `Superseded`: replaced by a later ADR, which must be linked.
- `Deprecated`: retained for history but no longer recommended; removal work must be tracked.

## When an ADR is required

Create an ADR before implementation when a choice:

- changes MCP inputs, results, errors, or content mapping;
- changes runner frames, versioning, correlation, or lifecycle state transitions;
- selects or replaces a language, official SDK, build system, storage format, or transport;
- changes interpreter resolution, process ownership, environment exposure, or security posture;
- changes supported Python or operating-system policy;
- moves behavior between delivery stages;
- affects multiple conceptual modules or is expensive to reverse.

Routine implementation details contained within one frozen module contract do not need an ADR.

## Naming

Use a monotonically increasing four-digit number and a stable kebab-case title:

```text
0001-stage-1-implementation-stack.md
0002-runner-protocol.md
```

Numbers are never reused, including for rejected decisions.

## Required structure

```markdown
# ADR-NNNN: Title

- Status: Proposed | Accepted | Rejected | Superseded | Deprecated
- Date: YYYY-MM-DD
- Deciders: role names
- Supersedes: ADR-NNNN, or None
- Related: GitHub Issue/risk/architecture references

## Context

Facts, constraints, and the decision pressure.

## Decision

The exact choice and its scope.

## Consequences

Positive and negative operational consequences.

## Alternatives considered

Serious alternatives and evidence-based rejection reasons.

## Verification

How implementation will prove the decision works.
```

## Change policy

- An `Accepted` ADR is immutable in meaning.
- Editorial fixes and updated source links are allowed when they do not change the decision.
- A changed decision gets a new ADR that marks the old one `Superseded` and identifies migration work.
- The Integration Lead updates this index and the linked GitHub work/risk Issues and Project fields in the same change.
- Implementation cannot use a `Proposed` ADR as if it were accepted.

## Index

| ADR | Status | Decision |
| --- | --- | --- |
| [ADR-0001](0001-stage-1-implementation-stack.md) | Accepted | Use a single Python implementation with the official MCP Python SDK and a uv-managed packaged toolchain |
| [ADR-0002](0002-github-project-management.md) | Accepted | Use GitHub Issues, Milestones, and organization Project #2 as the sole project-status system |

# AMKernel Project Management

Status: required project-management baseline.

AMKernel uses stage gates, contract-first planning, behavior-sized work items, and evidence-based completion. This is a lightweight Kanban model, not a sprint or ceremony framework.

Development mechanics and quality gates remain in [`development.md`](development.md). Product scope and delivery stages remain in [`architecture.md`](architecture.md).

## 1. Sources of truth

- [`architecture.md`](architecture.md): product invariants, conceptual modules, and delivery stages.
- [`development.md`](development.md): agent roles, ownership, implementation workflow, quality gates, and definition of done.
- [GitHub Project #2](https://github.com/orgs/FSQ-lab/projects/2): canonical status, stage, work type, priority, and queue order.
- [GitHub Issues](https://github.com/FSQ-lab/amkernel/issues): work-item contracts, dependencies, blockers, owners, risks, and verification evidence.
- [GitHub Milestones](https://github.com/FSQ-lab/amkernel/milestones): delivery grouping and exit tracking.
- [`decisions/`](decisions/): accepted architecture and implementation decisions.
- Experiment documents: platform-specific plans and measurements within their stage only.

When these artifacts disagree, implementation stops. Product behavior follows the architecture; accepted ADRs may refine but not silently override it. The Integration Lead resolves drift before work resumes.

## 2. Management model

Work moves through four delivery stages defined by the architecture:

1. execution correctness;
2. Agent-quality output;
3. Mobile/Appium experiment;
4. cross-client evidence.

Only one stage is the active delivery target. Later-stage research may occur, but later-stage production behavior does not enter the active milestone without an explicit architecture change.

Each stage has one or more milestones. A milestone contains behavior-sized work items and explicit entry and exit criteria. Progress is measured by accepted behavior and verification evidence, never by estimated percentage complete.

## 3. Work-item types

- **Decision**: freezes a cross-module or externally visible choice in an ADR.
- **Implementation slice**: delivers one observable behavior through the real surface.
- **Verification**: supplies independent behavior, lifecycle, platform, or packaging evidence.
- **Risk reduction**: closes or reduces an entry in the risk register.
- **Experiment**: collects evidence without silently changing the core contract.
- **Governance**: changes project process, CI, repository policy, or release controls.

A module-sized task is acceptable only when its output is a frozen internal contract required by a behavior slice.

## 4. Kanban states

| State | Meaning | Entry condition | Exit condition |
| --- | --- | --- | --- |
| `Backlog` | Valid work, not ready to start | Goal is recorded | Dependencies and planning owner identified |
| `Planning` | Contract, risks, and ownership are being resolved | Planning owner assigned | Task contract is complete |
| `Ready` | Safe to implement | Dependencies accepted; paths and sole writer known | Owner starts work |
| `In Progress` | Production or verification work is active | Sole writer/owner assigned | Focused checks pass and handoff is complete |
| `Review` | Independent architecture/correctness/security review | Implementation handoff exists | No blocking review finding remains |
| `Verification` | Integrated gates and real-surface scenarios run | Review passed; consumers migrated | Required evidence passes |
| `Done` | Complete, accepted, and documented | Definition of done satisfied | Immutable except correction or superseding work |
| `Blocked` | External decision, dependency, or environment prevents progress | `Blocked from`, blocker, and blocker owner recorded | Blocker removed; item returns to the recorded prior state |
| `Dropped` | Deliberately abandoned | Reason and replacement, if any, recorded | Final state |

A task cannot move directly from `Backlog` to `In Progress`. `Ready` means the contract is sufficiently frozen to prevent downstream agents from inventing behavior.

## 5. Work-in-progress and ownership

- One active delivery milestone at a time.
- One integrated change may modify a shared contract at a time.
- One writer per file and one owner per state machine.
- Multiple implementation items may be `In Progress` only when their contracts are frozen, file ownership is disjoint, and neither depends on the other's unfinished output.
- Shared schemas, build configuration, canonical documents, and integration entry points remain under the Integration Lead.
- A reviewer does not approve its own load-bearing production implementation.
- Blocked work does not retain file ownership unless the Integration Lead records why that is necessary.

## 6. Task contract template

Every item entering `Ready` uses this contract:

```text
ID and title:
Type:
Delivery stage and milestone:
Status:
Owner:
Independent reviewer:
Blocked from:
Blocker:
Blocker owner:


Goal:
Observable contract:
Non-goals:
Architecture and ADR constraints:
Dependencies:
Risks affected:

Write ownership:
Read-only consumers:
Contract changes:

Acceptance scenarios:
Focused verification:
Integrated verification:
Required evidence:

Handoff notes:
```

Rules:

- The goal describes user- or system-visible behavior, not files to create.
- Non-goals prevent stage creep.
- Acceptance scenarios must distinguish the intended behavior from plausible bugs.
- Exact paths are assigned before `Ready`; conceptual module names are used while layout is still undecided.
- A contract change names every consumer and uses a clean cutover.
- A task with unresolved state semantics, protocol fields, or process ownership remains in `Planning`.

## 7. Milestones

A milestone record contains:

- delivery stage and outcome;
- entry criteria;
- ordered work items and dependency edges;
- required ADRs and risks;
- exit scenarios and quality gates;
- platform and support claims allowed after completion;
- explicitly deferred work.

A milestone exits only when every required item is `Done`, every blocking risk has acceptable evidence, and the real public surface passes its exit scenarios. Incomplete work moves to a later milestone; it is never hidden inside a completion claim.

## 8. Decision management

Create an ADR before implementation when a decision:

- changes a public MCP input, result, or error contract;
- changes the private runner protocol or lifecycle state machine;
- selects or replaces a language, SDK, build system, persistence mechanism, or transport;
- changes security, process ownership, environment exposure, or supported platforms;
- moves behavior between delivery stages;
- affects more than one conceptual module or is expensive to reverse.

Accepted ADRs are not rewritten to conceal a changed decision. A later ADR supersedes them and identifies every affected consumer. Editorial corrections that do not change the decision are allowed and must remain visibly editorial.

## 9. Risk management

Every `Planning` item checks the open [`type:risk` Issues](https://github.com/FSQ-lab/amkernel/issues?q=is%3Aissue+state%3Aopen+label%3Atype%3Arisk). A task links the risks it reduces, increases, or creates. New correctness, security, lifecycle, protocol, dependency, or platform risks are registered as Issues before the task becomes `Ready`.

A high-impact risk requires:

- a named owner role;
- a concrete mitigation;
- a trigger or failure signal;
- evidence required to reduce or close it;
- independent review before acceptance.

A risk is not closed because code exists. It closes only when its stated evidence has been observed.

## 10. Reporting and handoff

Status reports contain facts only:

- work item and state transition;
- accepted contract or ADR;
- files and ownership;
- checks executed and observed output;
- open review findings;
- kernel, process, and artifact survival state after failures;
- changed risks and next unblocked item.

The linked Issue and GitHub Project fields are updated in the same change that moves an item to `Done`, `Blocked`, or `Dropped`. Local Markdown is never maintained as a synchronized status copy.

## 11. Repository governance rollout

Repository controls are activated when their prerequisites exist:

1. **Active now**: public repository, organization Project, Stage 1 milestone, work/risk Issue forms, labels, pull-request template, and ADRs.
2. **Toolchain bootstrap**: `pyproject.toml`, lockfile, canonical format/lint/type/test/build commands, and CI workflow definitions.
3. **After CI jobs pass with stable names**: require those checks and independent review through branch protection.
4. **After additional recurring issue categories exist**: add specialized Issue forms beyond the generic work and risk forms.
5. **After real GitHub users or teams own stable paths**: add `CODEOWNERS`; dynamic Agent ownership remains task-scoped and cannot be represented by CODEOWNERS.
6. **After an installable package and end-to-end evidence exist**: define detailed versioning, changelog, and release procedure.

No empty CI, fictitious CODEOWNERS entry, or release promise is created merely to make the repository look mature.
